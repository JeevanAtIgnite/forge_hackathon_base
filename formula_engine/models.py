"""Models for semantic formula interpretation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DerivedColumnLogic(BaseModel):
    """Semantic description of a derived column backed by Excel formulas."""

    table_name: str
    column_name: str
    formula_type: str
    logic: str
    depends_on: list[str] = Field(default_factory=list)
    excel_formula_examples: list[str] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)


class FormulaCatalog(BaseModel):
    """Workbook-level list of interpreted formula semantics."""

    derived_columns: list[DerivedColumnLogic] = Field(default_factory=list)

