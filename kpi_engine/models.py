"""Recommended KPIs inferred from workbook structure."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KPIRecommendation(BaseModel):
    """A suggested KPI based on detected metrics and business entities."""

    name: str
    formula: str
    rationale: str
    tables: list[str] = Field(default_factory=list)
    source_columns: list[str] = Field(default_factory=list)
    category: str = "efficiency"
