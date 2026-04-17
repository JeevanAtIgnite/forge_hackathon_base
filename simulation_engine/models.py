"""Simulation scenario and result models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SimulationScenario(BaseModel):
    """Parsed what-if scenario extracted from a natural language query."""

    column_name: str
    percent_change: float
    multiplier: float
    direction: str


class SimulationResult(BaseModel):
    """Before-vs-after simulation output."""

    summary: str
    scenario: SimulationScenario | None = None
    before_rows: list[dict[str, Any]] = Field(default_factory=list)
    after_rows: list[dict[str, Any]] = Field(default_factory=list)
    impacted_metrics: dict[str, Any] = Field(default_factory=dict)
    changed_columns: list[str] = Field(default_factory=list)
