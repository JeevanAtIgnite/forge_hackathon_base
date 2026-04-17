"""Shared models for the planner, executor, verifier, and responder."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from data_quality.models import DataQualityReport
from excel_parser.models import WorkbookTables
from formula_engine.models import FormulaCatalog
from insight_engine.models import InsightReport
from kpi_engine.models import KPIRecommendation
from query_engine.models import QueryTranslation
from relationship_graph.models import RelationshipGraphModel
from schema_builder.models import WorkbookSchema
from semantic_model.models import SemanticModel
from simulation_engine.models import SimulationResult


class ExecutionStep(BaseModel):
    """Single planner or executor step."""

    step_id: int
    action: str
    reasoning: str
    params: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    """Planner output for a user query."""

    query: str
    intent: str = "lookup"
    selected_tables: list[str] = Field(default_factory=list)
    steps: list[ExecutionStep] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    output_mode: str = "table"


class VerificationReport(BaseModel):
    """Verifier output to prevent unsupported claims."""

    valid: bool
    checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AgentAnswer(BaseModel):
    """Final user-facing answer plus trace and supporting data."""

    answer_text: str
    answer_title: str
    execution_trace: list[str] = Field(default_factory=list)
    reasoning_trace: list[str] = Field(default_factory=list)
    supporting_data: list[dict[str, Any]] = Field(default_factory=list)
    selected_tables: list[str] = Field(default_factory=list)
    verification: VerificationReport
    plan: ExecutionPlan
    metrics: dict[str, Any] = Field(default_factory=dict)
    query_translation: QueryTranslation
    insight_report: InsightReport | None = None
    simulation_result: SimulationResult | None = None
    data_quality_report: DataQualityReport | None = None
    kpi_recommendations: list[KPIRecommendation] = Field(default_factory=list)


class WorkbookKnowledgeBundle(BaseModel):
    """Combined workbook intelligence used by the agent and UI."""

    parsed_tables: WorkbookTables
    schema: WorkbookSchema
    formulas: FormulaCatalog
    relationships: RelationshipGraphModel
    metadata_index: dict[str, Any] = Field(default_factory=dict)
    semantic_model: SemanticModel
    data_quality_report: DataQualityReport
    kpi_recommendations: list[KPIRecommendation] = Field(default_factory=list)
