"""Pandas execution agent."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


class DataAgent:
    """Execute plans using pandas only."""

    def execute(self, plan: dict[str, Any], tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
        selected_tables = plan.get("selected_tables", [])
        working_df = self._working_dataframe(selected_tables, tables)
        working_df, synthesized_metric = self._prepare_dataframe(working_df)
        dimension_column = self._dimension_column(working_df)
        metric_column = self._metric_column(working_df, plan.get("metric_hint"), synthesized_metric)

        if metric_column is None:
            return {
                "status": "warning",
                "answer": "I could not find a numeric metric to calculate from this workbook.",
                "dataframe": pd.DataFrame(),
                "metric_column": None,
                "dimension_column": dimension_column,
                "warnings": ["No numeric metric column was detected for this question."],
                "pandas_logic": "working_df = selected_table",
                "sql_like": "SELECT * FROM workbook_table LIMIT 10;",
            }

        if plan["intent"] == "aggregation":
            average_value = float(pd.to_numeric(working_df[metric_column], errors="coerce").dropna().mean())
            result_df = pd.DataFrame([{metric_column: average_value}])
            return {
                "status": "success",
                "answer": f"The average {metric_column} is {average_value:.2f}.",
                "dataframe": result_df,
                "metric_column": metric_column,
                "dimension_column": dimension_column,
                "warnings": [],
                "pandas_logic": f"pd.to_numeric(df['{metric_column}'], errors='coerce').mean()",
                "sql_like": f"SELECT AVG({metric_column}) FROM workbook_table;",
            }

        if plan["intent"] == "ranking":
            result_df = self._ranking(working_df, dimension_column, metric_column, plan.get("target_entity"))
            top_row = result_df.head(1).to_dict(orient="records")
            top_name = top_row[0].get(dimension_column) if top_row and dimension_column else "The top item"
            top_value = top_row[0].get(metric_column) if top_row else None
            return {
                "status": "success",
                "answer": f"{top_name} contributes the most with {metric_column} = {top_value}.",
                "dataframe": result_df,
                "metric_column": metric_column,
                "dimension_column": dimension_column,
                "warnings": [],
                "pandas_logic": f"df.sort_values('{metric_column}', ascending=False).head(10)",
                "sql_like": f"SELECT {dimension_column}, {metric_column} FROM workbook_table ORDER BY {metric_column} DESC LIMIT 10;",
            }

        if plan["intent"] == "insight":
            result_df = self._ranking(working_df, dimension_column, metric_column, plan.get("target_entity"))
            return {
                "status": "success",
                "answer": "",
                "dataframe": result_df,
                "metric_column": metric_column,
                "dimension_column": dimension_column,
                "target_entity": plan.get("target_entity"),
                "warnings": [],
                "pandas_logic": f"df[['{dimension_column}', '{metric_column}']].sort_values('{metric_column}')",
                "sql_like": f"SELECT {dimension_column}, {metric_column} FROM workbook_table ORDER BY {metric_column};",
            }

        if plan["intent"] == "simulation":
            result_df = self._simulation_base(working_df, dimension_column, metric_column, plan.get("target_entity"), plan["query"])
            return {
                "status": "success",
                "answer": "",
                "dataframe": result_df,
                "metric_column": metric_column,
                "dimension_column": dimension_column,
                "target_entity": plan.get("target_entity"),
                "warnings": [],
                "pandas_logic": f"df.loc[target_row, '{metric_column}'] *= scenario_multiplier",
                "sql_like": f"UPDATE workbook_table SET {metric_column} = {metric_column} * scenario_multiplier WHERE {dimension_column} = target_entity;",
            }

        preview = working_df.head(10)
        return {
            "status": "success",
            "answer": "I loaded the relevant workbook data and returned the first matching records.",
            "dataframe": preview,
            "metric_column": metric_column,
            "dimension_column": dimension_column,
            "warnings": [],
            "pandas_logic": "df.head(10)",
            "sql_like": "SELECT * FROM workbook_table LIMIT 10;",
        }

    def _working_dataframe(self, selected_tables: list[str], tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
        if not selected_tables:
            return next(iter(tables.values())).copy()
        if len(selected_tables) == 1:
            return tables[selected_tables[0]].copy()

        left = tables[selected_tables[0]].copy()
        right = tables[selected_tables[1]].copy()
        common = [column for column in left.columns if column in right.columns]
        if common:
            return left.merge(right, on=common[0], how="left", suffixes=("", "_joined"))
        return left

    def _prepare_dataframe(self, df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
        working = df.copy()
        numeric_columns = [str(column) for column in working.columns if self._is_business_numeric(working, str(column))]
        object_columns = [str(column) for column in working.columns if not pd.api.types.is_numeric_dtype(working[column])]

        if len(object_columns) == 1 and len(numeric_columns) >= 3:
            working["Total"] = sum(pd.to_numeric(working[column], errors="coerce").fillna(0) for column in numeric_columns)
            return working, "Total"

        return working, None

    def _dimension_column(self, df: pd.DataFrame) -> str | None:
        preferred_tokens = ("item", "type", "oem", "source", "month", "line", "dealer", "region", "stream", "category", "product")
        object_columns = [str(column) for column in df.columns if not pd.api.types.is_numeric_dtype(df[column])]

        for token in preferred_tokens:
            for column in object_columns:
                if token in column.lower():
                    return column

        for column in object_columns:
            uniqueness_ratio = df[column].nunique(dropna=True) / max(len(df[column].dropna()), 1)
            if uniqueness_ratio < 0.8:
                return column

        for column in object_columns:
            return column
        return None

    def _metric_column(self, df: pd.DataFrame, metric_hint: str | None, synthesized_metric: str | None = None) -> str | None:
        numeric_columns = [str(column) for column in df.columns if self._is_business_numeric(df, str(column))]
        if not numeric_columns:
            return None
        if synthesized_metric and synthesized_metric in numeric_columns:
            return synthesized_metric
        if metric_hint:
            for column in numeric_columns:
                if any(token in column.lower() for token in re.findall(r"[a-z0-9]+", metric_hint.lower()) if len(token) > 2):
                    return column
        for preferred in ("revenue", "sales", "profit", "margin", "gross", "net", "total", "price"):
            for column in numeric_columns:
                if preferred in column.lower():
                    return column
        return numeric_columns[0]

    def _ranking(self, df: pd.DataFrame, dimension_column: str | None, metric_column: str, target_entity: str | None) -> pd.DataFrame:
        working = df.copy()
        working[metric_column] = pd.to_numeric(working[metric_column], errors="coerce")
        working = working.dropna(subset=[metric_column])
        if target_entity and dimension_column and target_entity in working[dimension_column].astype(str).tolist():
            return working[[dimension_column, metric_column]].sort_values(metric_column, ascending=True)
        if dimension_column:
            return working[[dimension_column, metric_column]].sort_values(metric_column, ascending=False).head(10)
        return working[[metric_column]].sort_values(metric_column, ascending=False).head(10)

    def _simulation_base(
        self,
        df: pd.DataFrame,
        dimension_column: str | None,
        metric_column: str,
        target_entity: str | None,
        query: str,
    ) -> pd.DataFrame:
        working = df.copy()
        working[metric_column] = pd.to_numeric(working[metric_column], errors="coerce")
        percent = self._percent_change(query)
        if percent is None:
            return working

        if target_entity and dimension_column:
            mask = working[dimension_column].astype(str).str.lower() == target_entity.lower()
            working.loc[mask, metric_column] = working.loc[mask, metric_column] * (1 + percent)
        else:
            working[metric_column] = working[metric_column] * (1 + percent)
        return working

    def _percent_change(self, query: str) -> float | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", query.lower())
        if not match:
            return None
        return float(match.group(1)) / 100.0

    def _is_business_numeric(self, df: pd.DataFrame, column: str) -> bool:
        series = df[column]
        lowered = column.lower()
        if pd.api.types.is_datetime64_any_dtype(series):
            return False
        if any(token in lowered for token in ("date", "year", "quarter")):
            return False
        if "#" in lowered or lowered.endswith("id") or "vin" in lowered:
            return False
        return pd.to_numeric(series, errors="coerce").notna().mean() > 0.2
