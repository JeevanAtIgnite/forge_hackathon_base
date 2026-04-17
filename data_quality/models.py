"""Structured data-quality reporting models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DataQualityIssue(BaseModel):
    """Single data quality issue detected in a workbook."""

    table_name: str
    column_name: str
    issue_type: str
    severity: str
    message: str


class TableQualityReport(BaseModel):
    """Table-level quality summary."""

    table_name: str
    row_count: int
    issues: list[DataQualityIssue] = Field(default_factory=list)


class DataQualityReport(BaseModel):
    """Workbook-level quality report."""

    summary: str
    warnings: list[str] = Field(default_factory=list)
    issues: list[DataQualityIssue] = Field(default_factory=list)
    table_reports: list[TableQualityReport] = Field(default_factory=list)
