# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Cache infrastructure.

This package provides caching implementations:
- TTLSemanticCache: TTL-only exact-key LLM response caching (default, no vector deps)
- SemanticCache: Similarity-based LLM response caching (opt-in, requires a vector store)
"""

from starboard.infra.cache.semantic_cache import SemanticCache
from starboard.infra.cache.ttl_semantic_cache import TTLSemanticCache

__all__ = [
    "SemanticCache",
    "TTLSemanticCache",
]
