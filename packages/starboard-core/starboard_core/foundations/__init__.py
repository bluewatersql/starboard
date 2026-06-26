# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Foundation layer for shared infrastructure.

This package provides protocols and models for:
- Vector similarity search (RAG)
- Reflexion-based learning
- Semantic caching

Usage:
    >>> from starboard_core.foundations import VectorStore, VectorRecord
    >>> from starboard_core.foundations import ReflexionLearning, SemanticCache
"""

from starboard_core.foundations.models import (
    CacheEntry,
    ReflexionLearning,
    VectorRecord,
    VectorSearchResult,
)
from starboard_core.foundations.protocols import (
    ReflexionStore,
    SemanticCache,
    VectorStore,
)

__all__ = [
    # Models
    "VectorSearchResult",
    "VectorRecord",
    "ReflexionLearning",
    "CacheEntry",
    # Protocols
    "VectorStore",
    "ReflexionStore",
    "SemanticCache",
]
