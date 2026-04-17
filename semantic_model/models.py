"""Business-oriented semantic abstractions over workbook schema."""

from __future__ import annotations

from pydantic import BaseModel, Field

from relationship_graph.models import Relationship


class SemanticEntity(BaseModel):
    """Business entity inferred from dimension-like columns."""

    name: str
    table_name: str
    columns: list[str] = Field(default_factory=list)
    description: str


class SemanticMetric(BaseModel):
    """Metric definition inferred from workbook columns or formulas."""

    name: str
    table_name: str
    source_columns: list[str] = Field(default_factory=list)
    description: str
    derived: bool = False


class SemanticModel(BaseModel):
    """Workbook-wide semantic model for routing, insights, and explanation."""

    tables: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    derived_metrics: list[str] = Field(default_factory=list)
    entity_details: list[SemanticEntity] = Field(default_factory=list)
    metric_details: list[SemanticMetric] = Field(default_factory=list)
    summary: str = ""
