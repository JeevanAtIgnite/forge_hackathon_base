"""Structured schema models inferred from parsed workbook tables."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from formula_engine.models import DerivedColumnLogic


class ColumnSchema(BaseModel):
    """Inferred schema for a single column."""

    name: str
    data_type: str
    description: str
    semantic_role: str
    nullable: bool
    unique_ratio: float
    sample_values: list[Any] = Field(default_factory=list)
    is_primary_candidate: bool = False


class TableSchema(BaseModel):
    """Inferred schema for a logical table."""

    table_name: str
    description: str
    columns: list[ColumnSchema] = Field(default_factory=list)
    primary_key: str | None = None
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    sheet_name: str
    derived_columns: list[DerivedColumnLogic] = Field(default_factory=list)


class WorkbookSchema(BaseModel):
    """Workbook-level schema package used by the agent and UI."""

    workbook_title: str
    overview: str
    domain: str
    tables: list[TableSchema] = Field(default_factory=list)
    table_summaries: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)

