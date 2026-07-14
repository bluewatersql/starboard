# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""RAG domain layer - Pure logic, protocols, and models (NO I/O)."""

from starboard.infra.rag.domain.protocols import (
    CollectionType,
    EmbeddingProvider,
    MultiCollectionStore,
    VectorQuery,
    VectorQueryResult,
)

__all__ = [
    "CollectionType",
    "EmbeddingProvider",
    "MultiCollectionStore",
    "VectorQuery",
    "VectorQueryResult",
]
