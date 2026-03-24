"""
Cache infrastructure.

This package provides caching implementations:
- SemanticCache: Similarity-based LLM response caching
"""

from starboard_server.infra.cache.semantic_cache import SemanticCache

__all__ = [
    "SemanticCache",
]
