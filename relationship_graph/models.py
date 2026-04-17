"""Relationship graph models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Relationship(BaseModel):
    """Potential join relationship between two logical tables."""

    left_table: str
    right_table: str
    join_key: str
    left_column: str
    right_column: str
    confidence: float
    reason: str


class RelationshipGraphModel(BaseModel):
    """Serialized graph representation for API and UI use."""

    relationships: list[Relationship] = Field(default_factory=list)
    adjacency: dict[str, list[str]] = Field(default_factory=dict)
    summaries: list[str] = Field(default_factory=list)

