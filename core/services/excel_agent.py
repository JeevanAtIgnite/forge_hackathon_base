"""Stable Excel-first service powered by a single pandas-based orchestrator."""

from __future__ import annotations

import json
import math
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.orchestrator import AgenticOrchestrator
from backend.agent.workbook import WorkbookLoader
from core.exceptions.base import BusinessLogicError, NotFoundError, ValidationError
from core.logging import get_logger
from core.models.conversation import Conversation, ConversationMessage
from core.models.data_source import DataSource
from core.models.excel_schema import ExcelSchema, ProcessingStatus, QueryHistory
from core.services.conversation import ConversationService

logger = get_logger(__name__)
WORKBOOK_LOADER = WorkbookLoader()
ORCHESTRATOR = AgenticOrchestrator()


def _json_safe(value: Any) -> Any:
    """Recursively replace NaN/inf and pandas missing values with JSON-serializable values."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None:
        return None
    try:
        import pandas as pd
        if value is pd.NaT or (hasattr(pd, "isna") and not isinstance(value, (str, bytes)) and pd.isna(value)):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    return value


class ExcelAgentService:
    """Minimal service wrapper for workbook processing and agent orchestration."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.workbook_loader = WORKBOOK_LOADER
        self.orchestrator = ORCHESTRATOR

    async def process_data_source(
        self,
        data_source_id: str,
        user_id: str,
        force_reprocess: bool = False,
    ) -> ExcelSchema:
        """Load workbook tables into a stable manifest and lightweight metadata."""
        data_source = await self._get_data_source(data_source_id, user_id)
        existing_schema = await self._get_existing_schema(data_source_id)

        if existing_schema and not force_reprocess and existing_schema.processing_status == ProcessingStatus.COMPLETED:
            return existing_schema

        if existing_schema is None:
            schema = ExcelSchema(data_source_id=data_source_id)
            self.session.add(schema)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                schema = await self._get_existing_schema(data_source_id)
                if schema is None:
                    raise
        else:
            schema = existing_schema

        workbook_path = Path(data_source.stored_file_path)
        if not workbook_path.exists():
            schema.mark_failed(f"File not found: {data_source.stored_file_path}")
            await self.session.flush()
            raise ValidationError(f"Stored file not found: {data_source.stored_file_path}", field="stored_file_path")

        try:
            schema.mark_extracting()
            await self.session.flush()

            workbook = self.workbook_loader.load(str(workbook_path))
            schema.mark_completed(
                manifest=workbook.manifest,
                semantic_schema=workbook.semantic_schema,
                workbook_purpose=workbook.workbook_purpose,
                detected_colors=[],
                total_sections=workbook.manifest.get("table_count", 0),
                total_merged_regions=0,
                queryable_questions=workbook.suggested_questions,
                data_quality_notes=[issue["message"] for issue in workbook.enrichment.get("data_quality", {}).get("issues", [])[:8]],
                enrichment=workbook.enrichment,
                workbook_title=workbook.semantic_schema.get("workbook_title"),
                domain="excel_first_demo",
                context_header_for_qa=(
                    "Excel is treated as structured pandas tables. "
                    "Queries are executed, not guessed, and agent logs describe each step."
                ),
                query_routing={
                    "engine": "backend.agent.orchestrator",
                    "table_names": list(workbook.tables.keys()),
                    "relationship_graph_required": False,
                    "embedding_required": False,
                },
            )
            await self.session.flush()
            await self.session.refresh(schema)
            return schema

        except Exception as exc:
            logger.error("Workbook processing failed", data_source_id=data_source_id, error=str(exc), exc_info=True)
            schema.mark_failed(str(exc))
            await self.session.flush()
            raise BusinessLogicError(message=f"Processing failed: {exc}", error_code="PROCESSING_ERROR")

    async def get_schema(self, data_source_id: str, user_id: str) -> ExcelSchema:
        await self._get_data_source(data_source_id, user_id)
        schema = await self._get_existing_schema(data_source_id)
        if schema is None:
            raise NotFoundError(
                message="Schema not found. Process the data source first.",
                resource_type="ExcelSchema",
                resource_id=data_source_id,
            )
        return schema

    async def ask_question(
        self,
        data_source_id: str,
        user_id: str,
        question: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a query through the single orchestrator and persist the result."""
        data_source = await self._get_data_source(data_source_id, user_id)
        schema = await self.get_schema(data_source_id, user_id)

        if not schema.is_ready_for_queries:
            raise BusinessLogicError(
                message=f"Data source not ready for queries. Status: {schema.processing_status}",
                error_code="NOT_READY",
            )

        conv_service = ConversationService(self.session)
        if conversation_id:
            conversation = await conv_service.get_conversation(conversation_id, user_id, include_messages=False)
        else:
            title = question[:100] + ("..." if len(question) > 100 else "")
            conversation = await conv_service.create_conversation(user_id=user_id, data_source_id=data_source_id, title=title)

        await conv_service.add_message(conversation_id=conversation.id, user_id=user_id, role="user", content=question)

        query_history = QueryHistory(excel_schema_id=schema.id, user_id=user_id, question=question)
        self.session.add(query_history)
        await self.session.flush()

        started_at = time.time()
        try:
            workbook = self.workbook_loader.load(data_source.stored_file_path)
            result = self.orchestrator.run_query(question, workbook.tables)
            execution_time_ms = int((time.time() - started_at) * 1000)
            warnings = result.get("warnings") or []
            first_warning = warnings[0] if warnings else None

            answer_payload = _json_safe({
                "text": result["answer"],
                "agent_logs": result["agent_logs"],
                "query_logic": result["query_logic"],
                "result_table": result["result_table"],
                "insight_card": result.get("insight_card"),
                "simulation": result.get("simulation"),
                "warnings": warnings,
            })

            query_history.success = result["status"] != "error"
            query_history.answer = answer_payload
            query_history.code_used = json.dumps(_json_safe(result["query_logic"]), indent=2)
            query_history.iterations_used = len(result["agent_logs"])
            query_history.execution_time_ms = execution_time_ms

            await conv_service.add_message(
                conversation_id=conversation.id,
                user_id=user_id,
                role="assistant",
                content=result["answer"],
                code_used=query_history.code_used,
                execution_time_ms=execution_time_ms,
                cost_usd=Decimal("0"),
                is_error=result["status"] == "error",
                error_message=first_warning,
            )
            await self.session.flush()

            return _json_safe({
                "success": result["status"] == "success",
                "answer": result["answer"],
                "answer_text": result["answer"],
                "answer_title": "Agentic Data Intelligence Answer",
                "agent_logs": result["agent_logs"],
                "query_logic": result["query_logic"],
                "supporting_data": result["result_table"],
                "insight_card": result.get("insight_card"),
                "simulation": result.get("simulation"),
                "reasoning": result.get("reasoning"),
                "warnings": warnings,
                "selected_tables": result.get("selected_tables", []),
                "execution_time_ms": execution_time_ms,
                "query_id": query_history.id,
                "conversation_id": conversation.id,
            })

        except Exception as exc:
            execution_time_ms = int((time.time() - started_at) * 1000)
            try:
                await self.session.rollback()
            except Exception:
                pass

            query_history = QueryHistory(
                excel_schema_id=schema.id,
                user_id=user_id,
                question=question,
                success=False,
                error_message=str(exc),
                execution_time_ms=execution_time_ms,
            )
            self.session.add(query_history)
            await self.session.flush()

            await conv_service.add_message(
                conversation_id=conversation.id,
                user_id=user_id,
                role="assistant",
                content=f"Failed to answer query: {exc}",
                execution_time_ms=execution_time_ms,
                is_error=True,
                error_message=str(exc),
                cost_usd=Decimal("0"),
            )
            await self.session.flush()

            return {
                "success": False,
                "answer": f"Failed to answer query: {exc}",
                "answer_text": f"Failed to answer query: {exc}",
                "answer_title": "Agentic Data Intelligence Answer",
                "agent_logs": [{"agent": "Validator", "message": "Execution failed, but the system returned a safe error response."}],
                "query_logic": {"pandas": "", "sql_like": ""},
                "supporting_data": [],
                "insight_card": None,
                "simulation": None,
                "warnings": [str(exc)],
                "selected_tables": [],
                "execution_time_ms": execution_time_ms,
                "query_id": query_history.id,
                "conversation_id": conversation.id,
            }

    async def get_query_history(self, data_source_id: str, user_id: str, limit: int = 50) -> list[QueryHistory]:
        await self._get_data_source(data_source_id, user_id)
        schema = await self._get_existing_schema(data_source_id)
        if schema is None:
            return []
        stmt = (
            select(QueryHistory)
            .where(QueryHistory.excel_schema_id == schema.id)
            .where(QueryHistory.user_id == user_id)
            .order_by(QueryHistory.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_suggested_questions(self, data_source_id: str, user_id: str) -> list[str]:
        data_source = await self._get_data_source(data_source_id, user_id)
        schema = await self.get_schema(data_source_id, user_id)
        try:
            workbook = self.workbook_loader.load(data_source.stored_file_path)
            live = workbook.suggested_questions
            if live:
                return live
        except Exception as exc:
            logger.warning("Live suggestion generation failed; falling back to cached", error=str(exc))
        return schema.queryable_questions or []

    async def get_conversations(
        self,
        user_id: str,
        data_source_id: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Conversation], int]:
        conv_service = ConversationService(self.session)
        return await conv_service.list_conversations(user_id=user_id, data_source_id=data_source_id, skip=skip, limit=limit)

    async def get_conversation(self, conversation_id: str, user_id: str) -> Conversation:
        conv_service = ConversationService(self.session)
        return await conv_service.get_conversation(conversation_id=conversation_id, user_id=user_id, include_messages=True)

    async def get_conversation_messages(self, conversation_id: str, user_id: str, limit: int = 100) -> list[ConversationMessage]:
        conv_service = ConversationService(self.session)
        return await conv_service.get_conversation_messages(conversation_id=conversation_id, user_id=user_id, limit=limit)

    async def delete_conversation(self, conversation_id: str, user_id: str) -> None:
        conv_service = ConversationService(self.session)
        await conv_service.delete_conversation(conversation_id, user_id)

    async def get_usage_summary(self, user_id: str, days: int = 30) -> dict:
        conv_service = ConversationService(self.session)
        return await conv_service.get_user_usage_summary(user_id, days)

    async def _get_data_source(self, data_source_id: str, user_id: str) -> DataSource:
        stmt = select(DataSource).where(DataSource.id == data_source_id, DataSource.user_id == user_id)
        result = await self.session.execute(stmt)
        data_source = result.scalar_one_or_none()
        if data_source is None:
            raise NotFoundError(message="Data source not found", resource_type="DataSource", resource_id=data_source_id)
        return data_source

    async def _get_existing_schema(self, data_source_id: str) -> ExcelSchema | None:
        stmt = select(ExcelSchema).where(ExcelSchema.data_source_id == data_source_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
