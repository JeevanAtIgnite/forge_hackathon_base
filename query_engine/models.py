"""Transparent query translation models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryTranslation(BaseModel):
    """Human-readable translation of a natural language query."""

    query: str
    intent: str
    operations: list[str] = Field(default_factory=list)
    selected_tables: list[str] = Field(default_factory=list)
    pandas_logic: str = ""
    sql_like: str = ""
    notes: list[str] = Field(default_factory=list)
    simulation: dict[str, Any] = Field(default_factory=dict)
