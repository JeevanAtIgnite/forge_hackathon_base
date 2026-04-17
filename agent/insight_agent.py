"""Insight agent for explainable root-cause and benchmark analysis."""

from __future__ import annotations

import pandas as pd

from insight_engine.engine import InsightEngine
from insight_engine.models import InsightReport


class InsightAgent:
    """Generate insights from structured execution results."""

    def __init__(self) -> None:
        self.engine = InsightEngine()

    def analyze(self, query: str, dataframe: pd.DataFrame, grouping_column: str | None, metric_column: str | None) -> InsightReport:
        return self.engine.analyze(query, dataframe, grouping_column, metric_column)
