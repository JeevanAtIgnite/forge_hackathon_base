"""Explainable insight outputs for agentic reasoning."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InsightFinding(BaseModel):
    """A single explainable insight backed by computed values."""

    title: str
    detail: str
    severity: str = "info"
    supporting_values: dict[str, Any] = Field(default_factory=dict)


class InsightReport(BaseModel):
    """Structured insight report surfaced to the API and UI."""

    summary: str
    findings: list[InsightFinding] = Field(default_factory=list)
    benchmark_rows: list[dict[str, Any]] = Field(default_factory=list)
    focus_entity: str | None = None
    metric: str | None = None
