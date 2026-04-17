"""Simple deterministic insight engine."""

from __future__ import annotations

from typing import Any

import pandas as pd


class InsightEngine:
    """Generate short explanations from result differences."""

    def analyze(self, execution: dict[str, Any]) -> dict[str, Any]:
        df: pd.DataFrame = execution["dataframe"]
        metric_column = execution.get("metric_column")
        dimension_column = execution.get("dimension_column")
        target_entity = execution.get("target_entity")
        query = str(execution.get("query", "")).lower()

        if df.empty or metric_column is None:
            execution["insight_card"] = {
                "title": "No insight available",
                "message": "I could not find enough structured numeric data to explain the result.",
            }
            execution["answer"] = execution.get("answer") or "I could not produce a reliable insight from this workbook."
            return execution

        working = df.copy()
        working[metric_column] = pd.to_numeric(working[metric_column], errors="coerce")
        working = working.dropna(subset=[metric_column])
        average_value = float(working[metric_column].mean())

        if target_entity and dimension_column and target_entity in working[dimension_column].astype(str).tolist():
            row = working[working[dimension_column].astype(str).str.lower() == target_entity.lower()].head(1)
            if not row.empty:
                entity_value = float(row.iloc[0][metric_column])
                gap_pct = ((entity_value - average_value) / average_value * 100.0) if average_value else 0.0
                direction = "below" if gap_pct < 0 else "above"
                metric_label = "overall performance" if metric_column == "Total" else metric_column
                if "underperform" in query and gap_pct >= 0:
                    message = f"{target_entity} is not underperforming in this workbook. It is {abs(gap_pct):.0f}% above average on {metric_label}."
                else:
                    message = (
                        f"{target_entity} is {abs(gap_pct):.0f}% {direction} average on {metric_label}, "
                        f"which is driving the performance difference."
                    )
                execution["insight_card"] = {"title": "Performance driver", "message": message}
                execution["answer"] = message
                return execution

        top_row = working.sort_values(metric_column, ascending=False).head(1).to_dict(orient="records")
        if top_row and dimension_column:
            execution["insight_card"] = {
                "title": "Top performer",
                "message": f"{top_row[0][dimension_column]} is leading on {metric_column} compared with the rest of the table.",
            }
            execution["answer"] = execution["insight_card"]["message"]
        return execution
