# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Cache infrastructure.

This package provides caching implementations:
- SemanticCache: Similarity-based LLM response caching
"""

from starboard.infra.cache.semantic_cache import SemanticCache

__all__ = [
    "SemanticCache",
]
