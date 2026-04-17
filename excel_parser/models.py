"""Pydantic models for parsed Excel workbook structures."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Column(BaseModel):
    """Structured representation of a logical table column."""

    name: str
    original_name: str
    index: int
    excel_letter: str
    sample_values: list[Any] = Field(default_factory=list)


class Formula(BaseModel):
    """Represents a formula-bearing cell within a logical table."""

    cell: str
    row_index: int
    column_name: str
    formula: str
    cached_value: Any = None
    references: list[str] = Field(default_factory=list)


class Table(BaseModel):
    """Logical table extracted from a worksheet block."""

    name: str
    sheet_name: str
    header_row_index: int
    start_row: int
    end_row: int
    start_column: int
    end_column: int
    columns: list[Column] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    formulas: list[Formula] = Field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)


class WorkbookTables(BaseModel):
    """Workbook-level output from the Excel parsing layer."""

    file_name: str
    workbook_title: str
    sheet_names: list[str] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

