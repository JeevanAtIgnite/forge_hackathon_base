"""Structured execution tools backed by pandas."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import pandas as pd

from relationship_graph.models import RelationshipGraphModel
from schema_builder.models import WorkbookSchema


@dataclass
class ToolExecutionResult:
    """Result of executing a workbook plan."""

    dataframe: pd.DataFrame
    trace: list[str]
    metrics: dict[str, Any]


class WorkbookToolExecutor:
    """Expose workbook operations as structured tools."""

    def __init__(
        self,
        dataframes: dict[str, pd.DataFrame],
        schema: WorkbookSchema,
        relationships: RelationshipGraphModel,
    ) -> None:
        self.dataframes = dataframes
        self.schema = schema
        self.relationships = relationships

    def get_tables(self) -> list[str]:
        return sorted(self.dataframes)

    def get_schema(self, table_name: str) -> dict[str, Any]:
        table = next((item for item in self.schema.tables if item.table_name == table_name), None)
        if not table:
            raise KeyError(f"Unknown table: {table_name}")
        return table.model_dump(mode="json")

    def query_table(self, table_name: str, filters: dict[str, Any] | None = None) -> pd.DataFrame:
        if table_name not in self.dataframes:
            raise KeyError(f"Unknown table: {table_name}")

        df = self.dataframes[table_name].copy()
        for column_name, expected in (filters or {}).items():
            if column_name not in df.columns:
                raise KeyError(f"Unknown column '{column_name}' on table '{table_name}'")
            df = df[df[column_name].astype(str).str.lower() == str(expected).lower()]
        return df

    def join_tables(self, left_table: str, right_table: str, key: str | None = None) -> pd.DataFrame:
        left_df = self.query_table(left_table)
        right_df = self.query_table(right_table)

        relationship = next(
            (
                item
                for item in self.relationships.relationships
                if {item.left_table, item.right_table} == {left_table, right_table}
                and (key is None or key in {item.left_column, item.right_column, item.join_key})
            ),
            None,
        )
        if not relationship:
            raise KeyError(f"No valid relationship between {left_table} and {right_table}")

        return left_df.merge(
            right_df,
            left_on=relationship.left_column if relationship.left_table == left_table else relationship.right_column,
            right_on=relationship.right_column if relationship.right_table == right_table else relationship.left_column,
            how="inner",
            suffixes=(f"_{left_table}", f"_{right_table}"),
        )

    def compute_metric(self, df: pd.DataFrame, expression: str, output_column: str) -> pd.DataFrame:
        safe_df = df.copy()
        alias_map: dict[str, str] = {}

        for column in safe_df.columns:
            alias = self._alias(column)
            alias_map[alias] = column
            safe_df[alias] = pd.to_numeric(safe_df[column], errors="coerce")

        safe_expression = expression
        for alias, column in alias_map.items():
            safe_expression = re.sub(rf"\b{re.escape(column)}\b", alias, safe_expression)

        safe_df[output_column] = pd.eval(safe_expression, local_dict=safe_df.to_dict("series"), engine="python")
        return safe_df

    def build_working_dataframe(self, selected_tables: list[str]) -> tuple[pd.DataFrame, list[str]]:
        trace: list[str] = []
        if not selected_tables:
            raise ValueError("Planner did not select any tables.")

        if len(selected_tables) == 1:
            working_df = self.query_table(selected_tables[0])
            trace.append(f"Identified relevant table: {selected_tables[0]}.")
            return working_df, trace

        working_df = self.join_tables(selected_tables[0], selected_tables[1])
        trace.append(f"Identified relevant tables: {', '.join(selected_tables[:2])}.")
        trace.append(f"Joined {selected_tables[0]} and {selected_tables[1]} using the inferred relationship graph.")
        return working_df, trace

    def resolve_query_context(self, query: str, df: pd.DataFrame) -> dict[str, Any]:
        metric_column, grouping_column = self._resolve_columns(query, df)
        return {
            "metric_column": metric_column,
            "grouping_column": grouping_column,
            "category_column": self._resolve_category_column(query, df),
        }

    def execute_plan(self, query: str, selected_tables: list[str]) -> ToolExecutionResult:
        working_df, trace = self.build_working_dataframe(selected_tables)

        metric_column, grouping_column = self._resolve_columns(query, working_df)
        normalized_query = query.lower()
        metrics: dict[str, Any] = {
            "metric_column": metric_column,
            "grouping_column": grouping_column,
        }

        if len(selected_tables) > 1 and "staff" in normalized_query and metric_column and grouping_column:
            staffing_column = self._best_matching_column(working_df, ["staff", "staffing", "headcount", "employee", "fte"])
            if staffing_column:
                impact_df = working_df[[grouping_column, metric_column, staffing_column]].copy()
                impact_df[metric_column] = pd.to_numeric(impact_df[metric_column], errors="coerce")
                impact_df[staffing_column] = pd.to_numeric(impact_df[staffing_column], errors="coerce")
                impact_df = impact_df.dropna(subset=[metric_column, staffing_column])
                if not impact_df.empty:
                    impact_df["staffing_impact_score"] = impact_df[metric_column] * impact_df[staffing_column]
                    impact_df = impact_df.sort_values("staffing_impact_score", ascending=False).head(5)
                    trace.append(
                        f"Computed staffing impact as {metric_column} multiplied by {staffing_column} after joining the tables."
                    )
                    return ToolExecutionResult(
                        dataframe=impact_df,
                        trace=trace,
                        metrics={
                            **metrics,
                            "operation": "ranking",
                            "metric_column": "staffing_impact_score",
                            "base_metric": metric_column,
                            "staffing_column": staffing_column,
                            "ascending": False,
                        },
                    )

        if metric_column and any(token in normalized_query for token in ("average", "avg")):
            aggregated = working_df[metric_column].pipe(pd.to_numeric, errors="coerce").dropna()
            value = float(aggregated.mean()) if not aggregated.empty else 0.0
            trace.append(f"Computed the average of {metric_column}.")
            return ToolExecutionResult(
                dataframe=pd.DataFrame([{metric_column: value}]),
                trace=trace,
                metrics={**metrics, "operation": "average", "value": value},
            )

        if metric_column and grouping_column and any(token in normalized_query for token in ("highest", "top", "best", "lowest", "worst")):
            grouped = (
                working_df[[grouping_column, metric_column]]
                .assign(**{metric_column: pd.to_numeric(working_df[metric_column], errors="coerce")})
                .dropna(subset=[metric_column])
            )
            ascending = any(token in normalized_query for token in ("lowest", "worst"))
            result_df = grouped.sort_values(metric_column, ascending=ascending).head(5)
            trace.append(f"Ranked {grouping_column} by {metric_column}.")
            return ToolExecutionResult(
                dataframe=result_df,
                trace=trace,
                metrics={**metrics, "operation": "ranking", "ascending": ascending},
            )

        if any(token in normalized_query for token in ("high", "low", "categorized", "category")):
            category_column = self._resolve_category_column(query, working_df)
            if category_column:
                expected_label = None
                if "high" in normalized_query:
                    expected_label = "high"
                elif "low" in normalized_query:
                    expected_label = "low"

                label_series = working_df[category_column].astype(str).str.lower()
                if expected_label:
                    filtered = working_df[label_series == expected_label]
                    trace.append(f"Filtered rows where {category_column} equals {expected_label.title()}.")
                else:
                    filtered = working_df[label_series.str.contains("high|low", na=False)]
                    trace.append(f"Filtered rows using formula-derived category column {category_column}.")
                return ToolExecutionResult(
                    dataframe=filtered.head(10),
                    trace=trace,
                    metrics={**metrics, "operation": "classification", "category_column": category_column},
                )

        preview = working_df.head(10)
        trace.append("Returned supporting rows directly because the query maps to a lookup pattern.")
        return ToolExecutionResult(
            dataframe=preview,
            trace=trace,
            metrics={**metrics, "operation": "lookup"},
        )

    def _resolve_columns(self, query: str, df: pd.DataFrame) -> tuple[str | None, str | None]:
        metric_column = None
        grouping_column = None
        lowered_query = query.lower()

        if "conversion" in lowered_query:
            metric_column = self._best_matching_column(df, ["conversion_rate", "conversion", "appointment_rate"])
        if metric_column is None:
            metric_column = self._best_matching_column(df, re.findall(r"[a-z0-9_]+", lowered_query))
        if metric_column is None and any(token in lowered_query for token in ("underperform", "why", "performance", "insight", "anomaly")):
            metric_column = self._best_matching_column(df, ["conversion", "rate", "revenue", "sales", "leads", "appointments"])
        if metric_column is None:
            metric_column = self._first_numeric_metric(df)

        if any(token in lowered_query for token in ("dealer", "dealership", "store", "location")):
            grouping_column = self._best_matching_column(df, ["dealer", "dealership", "store", "location", "name"])
        if grouping_column is None:
            grouping_column = self._first_dimension_like_column(df)

        return metric_column, grouping_column

    def _resolve_category_column(self, query: str, df: pd.DataFrame) -> str | None:
        lowered_query = query.lower()
        keywords = ["category", "status", "segment", "band", "class"]
        if "high" in lowered_query or "low" in lowered_query:
            keywords.extend(["high", "low"])
        return self._best_matching_column(df, keywords)

    def _best_matching_column(self, df: pd.DataFrame, keywords: list[str]) -> str | None:
        scored_columns: list[tuple[str, int]] = []
        for column in df.columns:
            if not isinstance(df[column], pd.Series):
                continue
            lowered = column.lower()
            score = sum(3 for keyword in keywords if keyword in lowered)
            if score == 0:
                continue
            if pd.to_numeric(df[column], errors="coerce").notna().mean() > 0.6:
                score += 2
            scored_columns.append((column, score))

        if not scored_columns:
            return None
        scored_columns.sort(key=lambda item: item[1], reverse=True)
        return scored_columns[0][0]

    def _first_dimension_like_column(self, df: pd.DataFrame) -> str | None:
        for column in df.columns:
            if pd.api.types.is_numeric_dtype(df[column]):
                continue
            lowered = column.lower()
            if any(token in lowered for token in ("dealer", "name", "region", "store", "location", "team")):
                return column
        for column in df.columns:
            if not pd.api.types.is_numeric_dtype(df[column]):
                return column
        return None

    def _first_numeric_metric(self, df: pd.DataFrame) -> str | None:
        preferred = ["conversion", "rate", "revenue", "sales", "lead", "appoint", "staff", "cost"]
        for token in preferred:
            for column in df.columns:
                if token in column.lower() and pd.to_numeric(df[column], errors="coerce").notna().mean() > 0.6:
                    return column
        for column in df.columns:
            if pd.to_numeric(df[column], errors="coerce").notna().mean() > 0.6:
                return column
        return None

    def _alias(self, name: str) -> str:
        alias = re.sub(r"[^a-zA-Z0-9_]+", "_", name)
        alias = alias.strip("_").lower()
        return alias or "column"
