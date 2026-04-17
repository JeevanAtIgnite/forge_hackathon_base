"""Schemas for the stable Excel-first agentic data intelligence API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProcessDataSourceRequest(BaseModel):
    """Request to process or reprocess a workbook."""

    force_reprocess: bool = False


class ProcessDataSourceResponse(BaseModel):
    """High-level workbook processing status."""

    schema_id: str
    data_source_id: str
    processing_status: str
    is_ready_for_queries: bool
    workbook_title: str | None = None
    workbook_purpose: str | None = None
    domain: str | None = None
    context_header_for_qa: str | None = None
    table_count: int = 0
    relationship_count: int = 0
    formula_column_count: int = 0
    queryable_questions: list[str] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)
    processing_error: str | None = None
    processed_at: datetime | None = None


class ExcelSchemaResponse(BaseModel):
    """Full schema payload used by the UI workbook inspector."""

    id: str
    data_source_id: str
    processing_status: str
    is_ready_for_queries: bool
    workbook_title: str | None = None
    workbook_purpose: str | None = None
    domain: str | None = None
    context_header_for_qa: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)
    semantic_schema: dict[str, Any] = Field(default_factory=dict)
    enrichment: dict[str, Any] = Field(default_factory=dict)
    query_routing: dict[str, Any] = Field(default_factory=dict)
    queryable_questions: list[str] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)
    processing_error: str | None = None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None = None


class SchemaInfoResponse(BaseModel):
    """Compact workbook status summary."""

    data_source_id: str
    processing_status: str
    is_ready_for_queries: bool
    workbook_title: str | None = None
    workbook_purpose: str | None = None
    domain: str | None = None
    context_header_for_qa: str | None = None
    table_count: int = 0
    relationship_count: int = 0
    formula_column_count: int = 0
    queryable_questions_count: int = 0
    has_data_quality_notes: bool = False
    has_enrichment: bool = False


class ManifestSummaryResponse(BaseModel):
    """Workbook manifest summary."""

    sheet_count: int = 0
    sheet_names: list[str] = Field(default_factory=list)
    table_count: int = 0
    relationship_count: int = 0
    formula_column_count: int = 0
    tables: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EnrichmentResponse(BaseModel):
    """Optional workbook enrichment returned for inspection only."""

    semantic_model: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    kpi_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    table_overview: list[dict[str, Any]] = Field(default_factory=list)
    demo_scenarios: list[str] = Field(default_factory=list)
    relationship_graph: dict[str, Any] = Field(default_factory=dict)
    formula_catalog: dict[str, Any] = Field(default_factory=dict)
    metadata_index: dict[str, Any] = Field(default_factory=dict)


class AskQuestionRequest(BaseModel):
    """Natural-language workbook question."""

    question: str
    conversation_id: str | None = None


class AgentLogResponse(BaseModel):
    """One visible agent action in the orchestrator pipeline."""

    agent: str
    message: str


class QueryLogicResponse(BaseModel):
    """Transparent execution representation."""

    pandas: str = ""
    sql_like: str = ""


class InsightCardResponse(BaseModel):
    """Short explainable insight surfaced by the UI."""

    title: str
    message: str


class SimulationResponse(BaseModel):
    """Scenario before/after comparison."""

    before_rows: list[dict[str, Any]] = Field(default_factory=list)
    after_rows: list[dict[str, Any]] = Field(default_factory=list)
    summary: str


class NarrativeStep(BaseModel):
    """A single plain-English step in the reasoning narrative."""

    title: str
    body: str


class ReasoningResponse(BaseModel):
    """Structured reasoning payload explaining how the answer was derived."""

    intent: str | None = None
    metric_column: str | None = None
    dimension_column: str | None = None
    aggregation_op: str | None = None
    target_entity: str | None = None
    selected_tables: list[str] = Field(default_factory=list)
    row_count: int = 0
    narrative: list[NarrativeStep] = Field(default_factory=list)


class AskQuestionResponse(BaseModel):
    """Stable orchestrator response for the demo UI."""

    success: bool
    answer: str
    answer_text: str | None = None
    answer_title: str | None = None
    agent_logs: list[AgentLogResponse] = Field(default_factory=list)
    query_logic: QueryLogicResponse = Field(default_factory=QueryLogicResponse)
    supporting_data: list[dict[str, Any]] = Field(default_factory=list)
    insight_card: InsightCardResponse | None = None
    simulation: SimulationResponse | None = None
    reasoning: ReasoningResponse | None = None
    warnings: list[str] = Field(default_factory=list)
    selected_tables: list[str] = Field(default_factory=list)
    execution_time_ms: int = 0
    query_id: str
    conversation_id: str | None = None


class SuggestedQuestionsResponse(BaseModel):
    """Suggested workbook questions."""

    questions: list[str] = Field(default_factory=list)
    data_source_id: str


class QueryHistoryItem(BaseModel):
    """Stored query history item."""

    id: str
    question: str
    answer: Any = None
    code_used: str | None = None
    success: bool
    error_message: str | None = None
    execution_time_ms: int | None = None
    iterations_used: int = 0
    created_at: datetime


class QueryHistoryResponse(BaseModel):
    """Query history list."""

    items: list[QueryHistoryItem] = Field(default_factory=list)
    total: int


class ConversationMessageResponse(BaseModel):
    """Conversation message entry."""

    id: str
    role: str
    content: str
    code_used: str | None = None
    execution_time_ms: int | None = None
    is_error: bool
    error_message: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime


class ConversationResponse(BaseModel):
    """Full conversation payload."""

    id: str
    data_source_id: str
    title: str
    is_active: bool
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    messages: list[ConversationMessageResponse] = Field(default_factory=list)


class ConversationListItem(BaseModel):
    """Conversation row for list views."""

    id: str
    data_source_id: str
    title: str
    total_cost_usd: float
    message_count: int
    created_at: datetime
    last_message_at: datetime | None = None


class ConversationListResponse(BaseModel):
    """Conversation listing payload."""

    items: list[ConversationListItem] = Field(default_factory=list)
    total: int


class UsageSummaryResponse(BaseModel):
    """Usage summary payload."""

    period_days: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    total_calls: int
    by_call_type: dict[str, dict[str, float | int]] = Field(default_factory=dict)
