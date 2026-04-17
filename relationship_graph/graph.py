"""Infer relationships between logical tables."""

from __future__ import annotations

from collections import defaultdict

from relationship_graph.models import Relationship, RelationshipGraphModel
from schema_builder.models import TableSchema


class RelationshipGraphBuilder:
    """Infer joinable relationships using schema heuristics."""

    def build(self, tables: list[TableSchema]) -> RelationshipGraphModel:
        relationships: list[Relationship] = []
        adjacency: dict[str, list[str]] = defaultdict(list)

        for left_index, left_table in enumerate(tables):
            for right_table in tables[left_index + 1 :]:
                relationship = self._infer_pair(left_table, right_table)
                if not relationship:
                    continue

                relationships.append(relationship)
                adjacency[relationship.left_table].append(relationship.right_table)
                adjacency[relationship.right_table].append(relationship.left_table)

        summaries = [
            f"{item.left_table} joins to {item.right_table} on {item.left_column}/{item.right_column}."
            for item in relationships
        ]

        return RelationshipGraphModel(
            relationships=relationships,
            adjacency={key: sorted(set(value)) for key, value in adjacency.items()},
            summaries=summaries,
        )

    def _infer_pair(self, left_table: TableSchema, right_table: TableSchema) -> Relationship | None:
        best_relationship: Relationship | None = None
        best_score = 0.0

        for left_column in left_table.columns:
            for right_column in right_table.columns:
                score = self._column_match_score(left_column.name, right_column.name)
                if score <= best_score:
                    continue
                if score < 0.75:
                    continue

                reason = "Matched on shared business key names."
                if "id" in left_column.name.lower() and "id" in right_column.name.lower():
                    reason = "Matched on identifier-style columns."

                best_score = score
                best_relationship = Relationship(
                    left_table=left_table.table_name,
                    right_table=right_table.table_name,
                    join_key=self._join_key_name(left_column.name, right_column.name),
                    left_column=left_column.name,
                    right_column=right_column.name,
                    confidence=round(score, 3),
                    reason=reason,
                )

        return best_relationship

    def _column_match_score(self, left: str, right: str) -> float:
        left_norm = self._normalize(left)
        right_norm = self._normalize(right)

        if left_norm == right_norm:
            return 1.0

        left_tokens = set(left_norm.split("_"))
        right_tokens = set(right_norm.split("_"))
        overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)

        bonus = 0.0
        if "dealer" in left_tokens and "dealer" in right_tokens:
            bonus += 0.35
        if "id" in left_tokens and "id" in right_tokens:
            bonus += 0.35

        return overlap + bonus

    def _normalize(self, name: str) -> str:
        return name.lower().replace(" ", "_")

    def _join_key_name(self, left: str, right: str) -> str:
        if left == right:
            return left
        return f"{left}|{right}"
