"""Lightweight metadata-only embedding index."""

from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any

from pydantic import BaseModel, Field

from relationship_graph.models import RelationshipGraphModel
from schema_builder.models import WorkbookSchema


class MetadataDocument(BaseModel):
    """Metadata-only embedding document."""

    doc_id: str
    kind: str
    table_name: str | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetadataEmbeddingMatch(BaseModel):
    """Search result from the metadata embedding index."""

    doc_id: str
    kind: str
    table_name: str | None = None
    score: float
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetadataEmbeddingIndex:
    """Token-vector search over workbook metadata.

    This is deliberately metadata-only. It exists to help the planner select
    relevant tables and relationships without embedding raw rows.
    """

    def __init__(self, documents: list[MetadataDocument]):
        self.documents = documents
        self._vectors = {document.doc_id: self._vectorize(document.content) for document in documents}

    @classmethod
    def build(cls, schema: WorkbookSchema, relationships: RelationshipGraphModel) -> "MetadataEmbeddingIndex":
        documents: list[MetadataDocument] = []

        for table in schema.tables:
            documents.append(
                MetadataDocument(
                    doc_id=f"table:{table.table_name}",
                    kind="table",
                    table_name=table.table_name,
                    content=(
                        f"{table.description} Columns: "
                        + ", ".join(f"{column.name} ({column.data_type}, {column.semantic_role})" for column in table.columns)
                    ),
                    metadata={
                        "sheet_name": table.sheet_name,
                        "row_count": table.row_count,
                        "primary_key": table.primary_key,
                    },
                )
            )

        for relationship in relationships.relationships:
            documents.append(
                MetadataDocument(
                    doc_id=f"relationship:{relationship.left_table}:{relationship.right_table}",
                    kind="relationship",
                    content=(
                        f"{relationship.left_table} joins {relationship.right_table} "
                        f"using {relationship.left_column} and {relationship.right_column}. "
                        f"{relationship.reason}"
                    ),
                    metadata=relationship.model_dump(),
                )
            )

        return cls(documents=documents)

    def search(self, query: str, top_k: int = 5) -> list[MetadataEmbeddingMatch]:
        query_vector = self._vectorize(query)
        matches: list[MetadataEmbeddingMatch] = []

        for document in self.documents:
            score = self._cosine_similarity(query_vector, self._vectors[document.doc_id])
            if score <= 0:
                continue

            matches.append(
                MetadataEmbeddingMatch(
                    doc_id=document.doc_id,
                    kind=document.kind,
                    table_name=document.table_name,
                    score=round(score, 4),
                    content=document.content,
                    metadata=document.metadata,
                )
            )

        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:top_k]

    def relevant_tables(self, query: str, top_k: int = 3) -> list[str]:
        tables: list[str] = []
        for match in self.search(query, top_k=top_k * 2):
            if match.table_name and match.table_name not in tables:
                tables.append(match.table_name)
            if len(tables) == top_k:
                break
        return tables

    def snapshot(self) -> dict[str, Any]:
        return {
            "documents": [document.model_dump(mode="json") for document in self.documents],
        }

    def _vectorize(self, text: str) -> Counter[str]:
        tokens = re.findall(r"[a-z0-9_]+", text.lower())
        return Counter(tokens)

    def _cosine_similarity(self, left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0.0
        common = set(left) & set(right)
        numerator = sum(left[token] * right[token] for token in common)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        denominator = left_norm * right_norm
        if denominator == 0:
            return 0.0
        return numerator / denominator
