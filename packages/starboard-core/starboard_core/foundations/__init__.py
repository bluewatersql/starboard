# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Foundation layer for shared infrastructure.

Immutable data models shared across the kernel — reflexion learnings — used by
the reference-file RAG context models. (The orphaned VectorStore/ReflexionStore/
SemanticCache protocols, the CacheEntry model, and the VectorRecord/
VectorSearchResult models were removed: the vector/embedding/semantic-cache
stack was deleted in the native-first simplification and nothing implemented or
consumed them.)

Usage:
    >>> from starboard_core.foundations import ReflexionLearning
"""

from starboard_core.foundations.models import ReflexionLearning

__all__ = [
    "ReflexionLearning",
]
