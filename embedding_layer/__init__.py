"""Metadata embedding layer.

The index intentionally embeds only table descriptions, column metadata, and
relationship summaries. Raw workbook rows are excluded.
"""

from embedding_layer.index import MetadataDocument, MetadataEmbeddingIndex, MetadataEmbeddingMatch

__all__ = [
    "MetadataDocument",
    "MetadataEmbeddingMatch",
    "MetadataEmbeddingIndex",
]
