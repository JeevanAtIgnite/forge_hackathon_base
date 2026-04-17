"""Deterministic insight generation over executed workbook results."""

from __future__ import annotations

from typing import Any

import pandas as pd

from insight_engine.models import InsightFinding, InsightReport


class InsightEngine:
    """Generate comparisons, rankings, and root-cause style findings."""

    def analyze(
        self,
        query: str,
        df: pd.DataFrame,
        grouping_column: str | None,
        metric_column: str | None,
    ) -> InsightReport:
        if df.empty or not grouping_column or not metric_column or grouping_column not in df.columns or metric_column not in df.columns:
            return InsightReport(summary="Not enough structured data was available to generate deeper insights.")

        working_df = df.copy()
        working_df[metric_column] = pd.to_numeric(working_df[metric_column], errors="coerce")
        working_df = working_df.dropna(subset=[metric_column])
        if working_df.empty:
            return InsightReport(summary="The selected metric could not be converted into numeric values for insight generation.")

        focus_entity = self._match_entity(query, working_df, grouping_column)
        if any(token in query.lower() for token in ("underperform", "why", "behind")) and focus_entity:
            return self._underperformance_report(working_df, grouping_column, metric_column, focus_entity)

        ranked = working_df.sort_values(metric_column, ascending=False)
        top_row = ranked.iloc[0]
        average_value = float(working_df[metric_column].mean())
        summary = (
            f"{top_row[grouping_column]} leads on {self._label(metric_column)} with {top_row[metric_column]:.4f}, "
            f"compared with an average of {average_value:.4f}."
        )
        findings = [
            InsightFinding(
                title="Top performer",
                detail=f"{top_row[grouping_column]} is the strongest entity on {self._label(metric_column)}.",
                severity="info",
                supporting_values={
                    "entity": top_row[grouping_column],
                    "metric_value": float(top_row[metric_column]),
                    "average": average_value,
                },
            )
        ]
        return InsightReport(
            summary=summary,
            findings=findings,
            benchmark_rows=ranked.head(5).replace({pd.NA: None}).to_dict(orient="records"),
            metric=metric_column,
        )

    def _underperformance_report(
        self,
        df: pd.DataFrame,
        grouping_column: str,
        metric_column: str,
        focus_entity: str,
    ) -> InsightReport:
        row = df[df[grouping_column].astype(str).str.lower() == focus_entity.lower()].head(1)
        if row.empty:
            return InsightReport(summary=f"{focus_entity} was not found in the selected result set.")

        row_data = row.iloc[0]
        average_value = float(df[metric_column].mean())
        best_value = float(df[metric_column].max())
        entity_value = float(row_data[metric_column])
        rank = int(df[metric_column].rank(method="min", ascending=False)[row.index[0]])
        findings: list[InsightFinding] = [
            InsightFinding(
                title="Below peer average",
                detail=(
                    f"{focus_entity} is at {entity_value:.4f} on {self._label(metric_column)}, "
                    f"versus a peer average of {average_value:.4f}."
                ),
                severity="high" if entity_value < average_value else "info",
                supporting_values={
                    "entity_value": entity_value,
                    "peer_average": average_value,
                    "gap_to_average": entity_value - average_value,
                },
            ),
            InsightFinding(
                title="Peer ranking",
                detail=f"{focus_entity} ranks #{rank} on {self._label(metric_column)} out of {len(df)} entities.",
                severity="medium",
                supporting_values={"rank": rank, "population": len(df), "best_value": best_value},
            ),
        ]

        numeric_columns = [
            column
            for column in df.columns
            if column != metric_column and pd.to_numeric(df[column], errors="coerce").notna().mean() > 0.8
        ]
        for column in numeric_columns[:2]:
            average_secondary = pd.to_numeric(df[column], errors="coerce").mean()
            entity_secondary = pd.to_numeric(row[column], errors="coerce").iloc[0]
            findings.append(
                InsightFinding(
                    title=f"{self._label(column).title()} comparison",
                    detail=(
                        f"{focus_entity} has {entity_secondary:.4f} for {self._label(column)}, "
                        f"compared with {average_secondary:.4f} for peers."
                    ),
                    severity="info",
                    supporting_values={
                        "entity_value": float(entity_secondary),
                        "peer_average": float(average_secondary),
                    },
                )
            )

        summary = (
            f"{focus_entity} underperforms on {self._label(metric_column)} relative to peers, "
            f"with a gap of {entity_value - average_value:.4f} versus the peer average."
        )
        benchmark_rows = df.sort_values(metric_column, ascending=False).head(5)
        return InsightReport(
            summary=summary,
            findings=findings,
            benchmark_rows=benchmark_rows.replace({pd.NA: None}).to_dict(orient="records"),
            focus_entity=focus_entity,
            metric=metric_column,
        )

    def _match_entity(self, query: str, df: pd.DataFrame, grouping_column: str) -> str | None:
        lowered = query.lower()
        candidates = sorted({str(value) for value in df[grouping_column].dropna().unique()}, key=len, reverse=True)
        for candidate in candidates:
            if candidate.lower() in lowered:
                return candidate
        return None

    def _label(self, value: str) -> str:
        return value.replace("_", " ").strip().lower()
