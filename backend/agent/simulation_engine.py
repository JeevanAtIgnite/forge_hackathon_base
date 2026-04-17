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

        applied_uniformly = False
        if target_entity and dimension_column:
            mask = after[dimension_column].astype(str).str.lower() == target_entity.lower()
            if mask.any():
                after.loc[mask, metric_column] = pd.to_numeric(after.loc[mask, metric_column], errors="coerce") * (1 + percent)
            else:
                after[metric_column] = pd.to_numeric(after[metric_column], errors="coerce") * (1 + percent)
                applied_uniformly = True
                target_entity = None
        else:
            after[metric_column] = pd.to_numeric(after[metric_column], errors="coerce") * (1 + percent)
            applied_uniformly = True

        before_total = float(pd.to_numeric(before[metric_column], errors="coerce").sum())
        after_total = float(pd.to_numeric(after[metric_column], errors="coerce").sum())
        delta = after_total - before_total
        metric_label = self._metric_label(metric_column)
        direction = "rises" if percent >= 0 else "falls"
        before_fmt = self._format(before_total, metric_column)
        after_fmt = self._format(after_total, metric_column)
        delta_fmt = self._format(abs(delta), metric_column)
        delta_sign = "+" if delta >= 0 else "−"
        if target_entity:
            entity_label = target_entity
            summary = (
                f"If {entity_label} {direction} by {abs(percent) * 100:.0f}%, total {metric_label} "
                f"moves from {before_fmt} to {after_fmt} ({delta_sign}{delta_fmt})."
            )
        else:
            scope = "the whole table" if applied_uniformly else metric_label
            summary = (
                f"If {metric_label} {direction} {abs(percent) * 100:.0f}% across {scope}, "
                f"the total moves from {before_fmt} to {after_fmt} ({delta_sign}{delta_fmt})."
            )
        execution["simulation"] = {
            "before_rows": before.head(6).replace({pd.NA: None}).to_dict(orient="records"),
            "after_rows": after.head(6).replace({pd.NA: None}).to_dict(orient="records"),
            "summary": summary,
        }
        execution["answer"] = summary
        return execution

    @staticmethod
    def _metric_label(column: str) -> str:
        label = str(column).strip()
        label = re.sub(r"\s*\(\$\)\s*$", "", label)
        label = re.sub(r"\s*\(%\)\s*$", "", label)
        if label.lower() == "total":
            return "the overall total"
        return label

    @staticmethod
    def _format(value: float, column: str) -> str:
        lowered = str(column).lower()
        is_currency = "$" in str(column) or any(token in lowered for token in ("revenue", "cost", "price", "sales", "income", "gross", "budget", "ytd", "total"))
        if is_currency:
            if abs(value) >= 1_000_000:
                return f"${value / 1_000_000:,.2f}M"
            if abs(value) >= 10_000:
                return f"${value:,.0f}"
            return f"${value:,.2f}"
        if float(value).is_integer() and abs(value) >= 1000:
            return f"{int(value):,}"
        return f"{value:,.2f}"

    def _percent_change(self, query: str) -> float | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", query.lower())
        if not match:
            return None
        return float(match.group(1)) / 100.0
