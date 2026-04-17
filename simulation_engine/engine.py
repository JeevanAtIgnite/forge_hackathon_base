"""Apply simple what-if transformations and recompute projected metrics."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from simulation_engine.models import SimulationResult, SimulationScenario


class SimulationEngine:
    """Run deterministic simulations over selected workbook data."""

    def simulate(
        self,
        query: str,
        df: pd.DataFrame,
        grouping_column: str | None,
    ) -> SimulationResult:
        scenario = self._parse_scenario(query, df)
        if scenario is None:
            return SimulationResult(summary="The query did not specify a supported simulation scenario.")

        before_df = df.copy()
        after_df = df.copy()
        after_df[scenario.column_name] = pd.to_numeric(after_df[scenario.column_name], errors="coerce") * scenario.multiplier

        impacted_metrics = self._derive_impacted_metrics(before_df, after_df)
        preview_columns = [column for column in [grouping_column, scenario.column_name, *impacted_metrics.keys()] if column and column in after_df.columns]
        if not preview_columns:
            preview_columns = [scenario.column_name]

        before_rows = before_df[preview_columns].head(5).replace({pd.NA: None}).to_dict(orient="records")
        after_materialized = after_df.copy()
        for metric_name, values in impacted_metrics.items():
            after_materialized[metric_name] = values
        after_rows = after_materialized[preview_columns + [name for name in impacted_metrics if name not in preview_columns]].head(5)
        after_rows_data = after_rows.replace({pd.NA: None}).to_dict(orient="records")

        avg_before = pd.to_numeric(before_df[scenario.column_name], errors="coerce").mean()
        avg_after = pd.to_numeric(after_df[scenario.column_name], errors="coerce").mean()
        summary = (
            f"Simulated a {scenario.direction} of {scenario.percent_change:.0f}% on {scenario.column_name}. "
            f"The average value moves from {avg_before:.2f} to {avg_after:.2f}."
        )

        impacted_summary: dict[str, Any] = {}
        for metric_name, values in impacted_metrics.items():
            impacted_summary[metric_name] = {
                "before_average": float(pd.to_numeric(self._derive_impacted_metrics(before_df, before_df)[metric_name], errors="coerce").mean()),
                "after_average": float(pd.to_numeric(values, errors="coerce").mean()),
            }

        return SimulationResult(
            summary=summary,
            scenario=scenario,
            before_rows=before_rows,
            after_rows=after_rows_data,
            impacted_metrics=impacted_summary,
            changed_columns=[scenario.column_name, *impacted_metrics.keys()],
        )

    def _parse_scenario(self, query: str, df: pd.DataFrame) -> SimulationScenario | None:
        lowered = query.lower()
        match = re.search(r"(increase|increases|decrease|decreases|up|down).+?(\d+(?:\.\d+)?)\s*%", lowered)
        if not match:
            return None

        direction = "increase" if match.group(1) in {"increase", "increases", "up"} else "decrease"
        percent = float(match.group(2))
        multiplier = 1 + (percent / 100.0)
        if direction == "decrease":
            multiplier = 1 - (percent / 100.0)

        query_tokens = re.findall(r"[a-z]+", lowered)
        stems = set(query_tokens)
        if any(token.startswith("staff") for token in query_tokens):
            stems.add("staff")
        if any(token.startswith("lead") for token in query_tokens):
            stems.add("lead")
        if any(token.startswith("revenue") or token.startswith("sale") for token in query_tokens):
            stems.update({"revenue", "sales"})
        if any(token.startswith("appoint") for token in query_tokens):
            stems.add("appoint")

        candidates = [column for column in df.columns if any(token in column.lower() for token in stems)]
        numeric_candidates = [column for column in candidates if pd.to_numeric(df[column], errors="coerce").notna().mean() > 0.6]
        if not numeric_candidates:
            numeric_candidates = [
                column
                for column in df.columns
                if pd.to_numeric(df[column], errors="coerce").notna().mean() > 0.6
                and any(token in column.lower() for token in ("staff", "lead", "revenue", "cost", "appointment"))
            ]

        if not numeric_candidates:
            return None

        numeric_candidates.sort(key=self._scenario_score, reverse=True)

        return SimulationScenario(
            column_name=numeric_candidates[0],
            percent_change=percent,
            multiplier=multiplier,
            direction=direction,
        )

    def _derive_impacted_metrics(self, before_df: pd.DataFrame, after_df: pd.DataFrame) -> dict[str, Any]:
        impacted: dict[str, Any] = {}
        normalized_columns = {column.lower().replace("_", ""): column for column in after_df.columns}
        leads = self._find(normalized_columns, ["leads", "leadcount"])
        staff = self._find(normalized_columns, ["staffcount", "staffing", "headcount", "employeecount"])
        appointments = self._find(normalized_columns, ["appointments", "appts", "appointmentcount"])

        if leads and staff:
            impacted["leads_per_staff"] = pd.to_numeric(after_df[leads], errors="coerce") / pd.to_numeric(after_df[staff], errors="coerce")
        if appointments and leads:
            impacted["conversion_rate_projection"] = pd.to_numeric(after_df[appointments], errors="coerce") / pd.to_numeric(
                after_df[leads], errors="coerce"
            )
        return impacted

    def _find(self, columns: dict[str, str], candidates: list[str]) -> str | None:
        for candidate in candidates:
            if candidate in columns:
                return columns[candidate]
        return None

    def _scenario_score(self, column_name: str) -> int:
        lowered = column_name.lower()
        score = 0
        if "staffcount" in lowered or "staff_count" in lowered or "headcount" in lowered:
            score += 6
        if "staff" in lowered:
            score += 4
        if "count" in lowered:
            score += 3
        if "cost" in lowered:
            score -= 2
        return score
