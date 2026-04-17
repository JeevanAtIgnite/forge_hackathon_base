"""Simple scenario simulation engine."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


class SimulationEngine:
    """Apply scenario changes and summarize before-vs-after impact."""

    def simulate(self, execution: dict[str, Any], original_tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df: pd.DataFrame = execution["dataframe"]
        metric_column = execution.get("metric_column")
        dimension_column = execution.get("dimension_column")
        target_entity = execution.get("target_entity")
        query = execution.get("query", "")

        if df.empty or metric_column is None:
            execution["simulation"] = None
            execution["answer"] = "I could not run the scenario because no executable metric was found."
            return execution

        before = df.copy()
        after = df.copy()
        percent = self._percent_change(query)
        if percent is None:
            execution["simulation"] = None
            execution["answer"] = "I could not detect a percentage change in the scenario."
            return execution

        if target_entity and dimension_column:
            mask = after[dimension_column].astype(str).str.lower() == target_entity.lower()
            after.loc[mask, metric_column] = pd.to_numeric(after.loc[mask, metric_column], errors="coerce") * (1 + percent)
        else:
            after[metric_column] = pd.to_numeric(after[metric_column], errors="coerce") * (1 + percent)

        before_total = float(pd.to_numeric(before[metric_column], errors="coerce").sum())
        after_total = float(pd.to_numeric(after[metric_column], errors="coerce").sum())
        entity_label = target_entity or metric_column
        metric_label = "overall total" if metric_column == "Total" else metric_column
        execution["simulation"] = {
            "before_rows": before.head(6).replace({pd.NA: None}).to_dict(orient="records"),
            "after_rows": after.head(6).replace({pd.NA: None}).to_dict(orient="records"),
            "summary": f"If {entity_label} increases by {percent * 100:.0f}%, the {metric_label} moves from {before_total:.2f} to {after_total:.2f}.",
        }
        execution["answer"] = execution["simulation"]["summary"]
        return execution

    def _percent_change(self, query: str) -> float | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", query.lower())
        if not match:
            return None
        return float(match.group(1)) / 100.0
