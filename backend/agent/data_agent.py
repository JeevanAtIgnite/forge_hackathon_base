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
        dimension_column = self._dimension_column(working_df, plan.get("query"), plan.get("target_entity"))
        metric_column = self._metric_column(working_df, plan.get("metric_hint"), synthesized_metric, plan.get("query"))

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
            op = plan.get("aggregation_op") or "sum"
            numeric_series = pd.to_numeric(working_df[metric_column], errors="coerce").dropna()
            table_label = (plan.get("selected_tables") or ["this table"])[0]
            row_count = len(numeric_series)
            metric_label = self._readable_metric(metric_column)
            where_clause = f" in {table_label}" if table_label else ""
            if op == "mean":
                value = float(numeric_series.mean())
                answer = f"Average {metric_label}{where_clause} is {self._format_metric(metric_column, value)} (across {row_count:,} records)."
                pandas_logic = f"pd.to_numeric(df['{metric_column}'], errors='coerce').mean()"
                sql_like = f"SELECT AVG({metric_column}) FROM workbook_table;"
            elif op == "median":
                value = float(numeric_series.median())
                answer = f"Median {metric_label}{where_clause} is {self._format_metric(metric_column, value)}."
                pandas_logic = f"pd.to_numeric(df['{metric_column}'], errors='coerce').median()"
                sql_like = f"SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {metric_column}) FROM workbook_table;"
            elif op == "count":
                value = float(numeric_series.count())
                answer = f"{int(value):,} records have {metric_label}{where_clause}."
                pandas_logic = f"df['{metric_column}'].count()"
                sql_like = f"SELECT COUNT({metric_column}) FROM workbook_table;"
            else:
                value = float(numeric_series.sum())
                answer = f"Total {metric_label}{where_clause} is {self._format_metric(metric_column, value)} across {row_count:,} records."
                pandas_logic = f"pd.to_numeric(df['{metric_column}'], errors='coerce').sum()"
                sql_like = f"SELECT SUM({metric_column}) FROM workbook_table;"
            result_df = pd.DataFrame([{metric_column: value}])
            return {
                "status": "success",
                "answer": answer,
                "dataframe": result_df,
                "metric_column": metric_column,
                "dimension_column": dimension_column,
                "warnings": [],
                "pandas_logic": pandas_logic,
                "sql_like": sql_like,
            }

        if plan["intent"] == "ranking":
            direction = plan.get("ranking_direction") or "desc"
            result_df = self._ranking(working_df, dimension_column, metric_column, direction=direction)
            top_rows = result_df.head(2).to_dict(orient="records")
            table_label = (plan.get("selected_tables") or [""])[0]
            metric_label = self._readable_metric(metric_column)
            if top_rows and dimension_column:
                top_name = top_rows[0].get(dimension_column, "The top item")
                top_value = top_rows[0].get(metric_column)
                total_series = pd.to_numeric(result_df[metric_column], errors="coerce").dropna()
                total = float(total_series.sum()) if len(total_series) > 0 else 0.0
                share = (float(top_value) / total * 100.0) if total and top_value is not None else None
                runner_up = None
                if len(top_rows) > 1:
                    runner_up = f"{top_rows[1].get(dimension_column, '')} is next at {self._format_metric(metric_column, top_rows[1].get(metric_column))}"
                if share is not None:
                    noun = "overall" if metric_column.lower() == "total" or metric_label.lower().endswith("total") else metric_label
                    share_clause = f" — {share:.1f}% of {noun}"
                else:
                    share_clause = ""
                where_clause = f" in {table_label}" if table_label else ""
                verb = "ranks lowest" if direction == "asc" else "leads"
                answer = f"{top_name} {verb}{where_clause} with {metric_label} = {self._format_metric(metric_column, top_value)}{share_clause}."
                if runner_up:
                    answer += f" {runner_up}."
            else:
                qualifier = "lowest" if direction == "asc" else "highest"
                answer = f"The {qualifier} {metric_label} is {self._format_metric(metric_column, top_rows[0].get(metric_column) if top_rows else None)}."
            return {
                "status": "success",
                "answer": answer,
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
                "raw_dataframe": working_df,
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

        # Generic lookup fallback — if a dimension and metric exist, surface a ranking instead of a flat preview
        table_label = (plan.get("selected_tables") or [""])[0]
        metric_label = self._readable_metric(metric_column)
        if dimension_column:
            ranked = self._ranking(working_df, dimension_column, metric_column, target_entity=None, direction="desc")
            top_rows = ranked.head(2).to_dict(orient="records")
            if top_rows:
                top_name = top_rows[0].get(dimension_column)
                top_value = top_rows[0].get(metric_column)
                runner = ""
                if len(top_rows) > 1:
                    runner = f" {top_rows[1].get(dimension_column)} is next at {self._format_metric(metric_column, top_rows[1].get(metric_column))}."
                where_clause = f" in {table_label}" if table_label else ""
                answer = f"{top_name} leads{where_clause} on {metric_label} with {self._format_metric(metric_column, top_value)}.{runner}"
                return {
                    "status": "success",
                    "answer": answer,
                    "dataframe": ranked,
                    "metric_column": metric_column,
                    "dimension_column": dimension_column,
                    "warnings": [],
                    "pandas_logic": f"df.groupby('{dimension_column}')['{metric_column}'].sum().sort_values(ascending=False).head(10)",
                    "sql_like": f"SELECT {dimension_column}, SUM({metric_column}) AS total FROM workbook_table GROUP BY {dimension_column} ORDER BY total DESC LIMIT 10;",
                }

        # Last resort — describe the table
        numeric_series = pd.to_numeric(working_df[metric_column], errors="coerce").dropna()
        total_value = float(numeric_series.sum()) if not numeric_series.empty else 0.0
        row_count = len(working_df)
        where_clause = f" in {table_label}" if table_label else ""
        return {
            "status": "success",
            "answer": f"{metric_label}{where_clause} totals {self._format_metric(metric_column, total_value)} across {row_count:,} records.",
            "dataframe": working_df.head(10),
            "metric_column": metric_column,
            "dimension_column": dimension_column,
            "warnings": [],
            "pandas_logic": f"pd.to_numeric(df['{metric_column}'], errors='coerce').sum()",
            "sql_like": f"SELECT SUM({metric_column}) FROM workbook_table;",
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

    def _dimension_column(
        self,
        df: pd.DataFrame,
        query: str | None = None,
        target_entity: str | None = None,
    ) -> str | None:
        preferred_tokens = ("type", "category", "name", "group", "class", "kind", "status", "segment", "source", "item", "line")
        object_columns = [str(column) for column in df.columns if not pd.api.types.is_numeric_dtype(df[column])]

        if target_entity:
            target_lower = target_entity.strip().lower()
            for column in object_columns:
                values = df[column].dropna().astype(str).str.strip().str.lower().tolist()
                if target_lower in values:
                    return column

        if query:
            query_tokens = {token for token in re.findall(r"[a-z]+", query.lower()) if len(token) >= 3}
            best_column, best_score = None, 0
            for column in object_columns:
                column_tokens = set(re.findall(r"[a-z]+", column.lower()))
                overlap = len(column_tokens & query_tokens)
                if overlap > best_score:
                    best_score = overlap
                    best_column = column
            if best_column and best_score >= 1:
                return best_column

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

    def _metric_column(
        self,
        df: pd.DataFrame,
        metric_hint: str | None,
        synthesized_metric: str | None = None,
        query: str | None = None,
    ) -> str | None:
        numeric_columns = [str(column) for column in df.columns if self._is_business_numeric(df, str(column))]
        if not numeric_columns:
            return None

        if query:
            query_tokens = [token for token in re.findall(r"[a-z]+", query.lower()) if len(token) >= 3]
            stopwords = {"the", "for", "and", "from", "what", "which", "how", "show", "give", "most", "least", "top", "sum", "avg", "total", "average", "mean", "count"}
            meaningful = [token for token in query_tokens if token not in stopwords]
            best_column, best_score = None, 0
            for column in numeric_columns:
                column_tokens = re.findall(r"[a-z]+", column.lower())
                score = 0
                for column_token in column_tokens:
                    for query_token in meaningful:
                        if column_token == query_token:
                            score += 4
                        elif column_token.startswith(query_token) or query_token.startswith(column_token):
                            if min(len(column_token), len(query_token)) >= 4:
                                score += 2
                if score > best_score:
                    best_score = score
                    best_column = column
            if best_column and best_score >= 2:
                return best_column

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

    def _ranking(
        self,
        df: pd.DataFrame,
        dimension_column: str | None,
        metric_column: str,
        target_entity: str | None = None,
        direction: str = "desc",
    ) -> pd.DataFrame:
        ascending = direction == "asc"
        working = df.copy()
        working[metric_column] = pd.to_numeric(working[metric_column], errors="coerce")
        working = working.dropna(subset=[metric_column])
        if target_entity and dimension_column and target_entity in working[dimension_column].astype(str).tolist():
            return working[[dimension_column, metric_column]].sort_values(metric_column, ascending=True)
        if dimension_column:
            unique_count = working[dimension_column].nunique(dropna=True)
            if unique_count > 0 and unique_count < len(working):
                grouped = (
                    working.groupby(dimension_column, dropna=False)[metric_column]
                    .sum()
                    .reset_index()
                    .sort_values(metric_column, ascending=ascending)
                    .head(10)
                )
                return grouped
            return working[[dimension_column, metric_column]].sort_values(metric_column, ascending=ascending).head(10)
        return working[[metric_column]].sort_values(metric_column, ascending=ascending).head(10)

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

    def _readable_metric(self, column: str) -> str:
        label = str(column).strip()
        label = re.sub(r"\s*\(\$\)\s*$", "", label)
        label = re.sub(r"\s*\(%\)\s*$", "", label)
        return label.replace("_", " ")

    def _format_metric(self, column: str, value: Any) -> str:
        if value is None:
            return "—"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        lowered = str(column).lower()
        is_currency = "$" in str(column) or any(token in lowered for token in ("revenue", "cost", "price", "sales", "income", "gross", "budget", "ytd"))
        is_percent = "%" in str(column) or any(token in lowered for token in ("rate", "margin", "penetration", "share"))
        if is_currency:
            return self._format_currency(number)
        if is_percent and abs(number) <= 1.5:
            return f"{number * 100:.1f}%"
        if number.is_integer() and abs(number) >= 1000:
            return f"{int(number):,}"
        return f"{number:,.2f}"

    @staticmethod
    def _format_currency(value: float) -> str:
        if abs(value) >= 1_000_000:
            return f"${value / 1_000_000:,.2f}M"
        if abs(value) >= 10_000:
            return f"${value:,.0f}"
        return f"${value:,.2f}"

    def _is_business_numeric(self, df: pd.DataFrame, column: str) -> bool:
        series = df[column]
        lowered = column.lower()
        if pd.api.types.is_datetime64_any_dtype(series):
            return False
        if any(token in lowered for token in ("date", "year", "quarter")):
            return False
        if "#" in lowered or lowered.endswith("id") or lowered.endswith("uuid") or lowered.endswith("guid") or lowered.endswith("ref"):
            return False
        return pd.to_numeric(series, errors="coerce").notna().mean() > 0.2
