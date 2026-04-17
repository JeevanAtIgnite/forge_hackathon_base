"""Simple deterministic planner for the demo pipeline."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


class Planner:
    """Plan intent and table selection without relying on LLM computation."""

    def plan(self, query: str, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
        normalized = query.lower()
        intent = self._intent(normalized)
        requires_join = any(token in normalized for token in ("compare", "vs", "staff", "combine", "join"))
        table_scores: list[tuple[str, int]] = []
        query_tokens = set(re.findall(r"[a-z0-9]+", normalized))

        stopwords = {"new", "used", "old", "top", "total", "sum", "the", "a", "an", "yes", "no"}
        query_terms = [term for term in query_tokens if len(term) >= 4 and term not in stopwords]

        for table_name, df in tables.items():
            score = 0
            table_tokens = set(re.findall(r"[a-z0-9]+", table_name.lower()))
            score += len(table_tokens & query_tokens) * 6
            for column in df.columns:
                lowered = str(column).lower()
                column_tokens = set(re.findall(r"[a-z0-9]+", lowered))
                if column_tokens & query_tokens:
                    score += 3
                if not pd.api.types.is_numeric_dtype(df[column]):
                    sample_values = [str(value).strip().lower() for value in df[column].dropna().head(100).tolist()]
                    for value in sample_values:
                        if not value or len(value) < 3:
                            continue
                        if value in stopwords:
                            continue
                        if value in normalized and any(term in value or value in term for term in query_terms):
                            score += 10
                            break
            if len([column for column in df.columns if not pd.api.types.is_numeric_dtype(df[column])]) == 1:
                score += 3
            table_scores.append((table_name, score))

        table_scores.sort(key=lambda item: item[1], reverse=True)
        if requires_join:
            selected_tables = [item[0] for item in table_scores[:2] if item[1] > 0] or list(tables.keys())[:1]
        else:
            selected_tables = [table_scores[0][0]] if table_scores else list(tables.keys())[:1]

        return {
            "query": query,
            "intent": intent,
            "selected_tables": selected_tables,
            "requires_join": len(selected_tables) > 1 and requires_join,
            "target_entity": self._target_entity(query, tables, selected_tables),
            "metric_hint": self._metric_hint(normalized),
            "aggregation_op": self._aggregation_op(normalized) if intent == "aggregation" else None,
        }

    def _intent(self, normalized: str) -> str:
        if "what if" in normalized:
            return "simulation"
        if "why" in normalized or "underperform" in normalized:
            return "insight"
        if any(token in normalized for token in ("average", "avg", "mean", "median")):
            return "aggregation"
        if any(token in normalized for token in ("total", "sum", "overall", "combined", "aggregate", "altogether")):
            return "aggregation"
        if any(token in normalized for token in ("count", "how many")):
            return "aggregation"
        if any(token in normalized for token in ("top", "most", "highest", "largest", "biggest", "leading")):
            return "ranking"
        if any(token in normalized for token in ("least", "lowest", "smallest", "worst", "bottom")):
            return "ranking"
        return "lookup"

    def _aggregation_op(self, normalized: str) -> str:
        if any(token in normalized for token in ("average", "avg", "mean")):
            return "mean"
        if "median" in normalized:
            return "median"
        if any(token in normalized for token in ("count", "how many")):
            return "count"
        return "sum"

    def _metric_hint(self, normalized: str) -> str | None:
        for token in ("revenue", "sales", "profit", "margin", "gross", "net", "cost", "price", "amount", "value", "income", "total"):
            if re.search(r"\b" + re.escape(token) + r"s?\b", normalized):
                return token
        return None

    def _target_entity(self, query: str, tables: dict[str, pd.DataFrame], selected_tables: list[str]) -> str | None:
        normalized = query.lower()
        best_value: str | None = None
        best_length = 0
        for table_name in selected_tables:
            df = tables.get(table_name)
            if df is None:
                continue
            for column in df.columns:
                if pd.api.types.is_numeric_dtype(df[column]):
                    continue
                values = {str(value).strip() for value in df[column].dropna().head(200).tolist()}
                for value in values:
                    if not value or len(value) < 4:
                        continue
                    pattern = r"\b" + re.escape(value.lower()) + r"\b"
                    if re.search(pattern, normalized) and len(value) > best_length:
                        best_value = value
                        best_length = len(value)
        return best_value
