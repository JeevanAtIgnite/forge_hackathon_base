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

        for table_name, df in tables.items():
            score = 0
            table_tokens = set(re.findall(r"[a-z0-9]+", table_name.lower()))
            score += len(table_tokens & query_tokens) * 3
            for column in df.columns:
                lowered = str(column).lower()
                if any(token in lowered for token in query_tokens):
                    score += 2
                if not pd.api.types.is_numeric_dtype(df[column]):
                    sample_values = [str(value).strip().lower() for value in df[column].dropna().head(100).tolist()]
                    joined_values = " ".join(sample_values)
                    if joined_values and any(token in joined_values for token in query_tokens):
                        score += 2
                    for value in sample_values:
                        if value and value in normalized:
                            score += 20
            if "revenue stream" in normalized and any("line item" in str(column).lower() for column in df.columns):
                score += 12
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
        }

    def _intent(self, normalized: str) -> str:
        if "what if" in normalized:
            return "simulation"
        if "why" in normalized or "underperform" in normalized:
            return "insight"
        if "average" in normalized or "avg" in normalized:
            return "aggregation"
        if any(token in normalized for token in ("top", "most", "highest", "largest")):
            return "ranking"
        return "lookup"

    def _metric_hint(self, normalized: str) -> str | None:
        for token in ("revenue", "sales", "profit", "margin", "gross", "net", "used vehicle", "new vehicle"):
            if token in normalized:
                return token
        return None

    def _target_entity(self, query: str, tables: dict[str, pd.DataFrame], selected_tables: list[str]) -> str | None:
        normalized = query.lower()
        for table_name in selected_tables:
            df = tables.get(table_name)
            if df is None:
                continue
            for column in df.columns:
                if pd.api.types.is_numeric_dtype(df[column]):
                    continue
                values = {str(value).strip() for value in df[column].dropna().head(100).tolist()}
                for value in values:
                    if value and value.lower() in normalized:
                        return value
        return None
