# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
RAG (Retrieval-Augmented Generation) infrastructure for Analytics Agent.

Reference-file retrieval only. Analytics context is built from on-disk curated
reference files (see ``starboard_core.rag``) plus the domain protocols and
keyword resolver in this package. The vector/embedding/ANN stack (SQLite /
in-memory / managed Vector Search stores, embedding providers, and the
index-build services) was removed in the native-first simplification; the host
agent grounds SQL generation from reference files rather than a vector index.

Public surface:
- ``domain/``: protocols and pure logic (no I/O)
- ``domain_keywords``: free-text → RAG resource-domain resolution
"""

from __future__ import annotations

from starboard.infra.rag.domain import (
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
