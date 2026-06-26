# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Analytics SQL - Cache Adapter.

Wraps semantic cache for analytics query results.
Provides high-level interface for cache lookup and storage.
"""

from __future__ import annotations

from typing import Any

from starboard_server.infra.cache.semantic_cache import SemanticCache


class AnalyticsCacheAdapter:
    """Adapter for semantic caching of analytics query results.

    This adapter provides a high-level interface for caching analytics
    query results using semantic similarity. It wraps the low-level
    SemanticCache implementation.

    Features:
    - Cache lookup by semantic similarity
    - Automatic metadata extraction
    - TTL management
    - Cache metrics

    Example:
        >>> adapter = AnalyticsCacheAdapter(
        ...     semantic_cache=semantic_cache,
        ...     similarity_threshold=0.93,
        ...     ttl=300
        ... )
        >>>
        >>> # Try cache lookup
        >>> cached = await adapter.lookup("Show warehouse costs")
        >>> if cached:
        ...     return cached["results"]
        >>>
        >>> # Cache miss - execute query
        >>> result = await execute_query(...)
        >>> await adapter.store("Show warehouse costs", result)
    """

    def __init__(
        self,
        semantic_cache: SemanticCache,
        similarity_threshold: float = 0.93,
        ttl: int = 300,
    ):
        """Initialize cache adapter.

        Args:
            semantic_cache: Underlying semantic cache
            similarity_threshold: Minimum similarity for cache hit (0.0-1.0)
            ttl: Default time-to-live in seconds

        Example:
            >>> adapter = AnalyticsCacheAdapter(
            ...     semantic_cache=cache,
            ...     similarity_threshold=0.93,
            ...     ttl=300
            ... )
        """
        self.semantic_cache = semantic_cache
        self.similarity_threshold = similarity_threshold
        self.default_ttl = ttl

    async def lookup(
        self,
        query: str,
        similarity_threshold: float | None = None,
    ) -> dict[str, Any] | None:
        """Lookup cached result for query.

        Args:
            query: Natural language query
            similarity_threshold: Override default threshold

        Returns:
            Cached result dict or None if cache miss

        Raises:
            ValueError: If query is empty

        Example:
            >>> result = await adapter.lookup("Show warehouse costs")
            >>> if result:
            ...     print(f"Cache hit! SQL: {result['sql']}")
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        threshold = similarity_threshold or self.similarity_threshold

        # Lookup in semantic cache
        cache_entry = await self.semantic_cache.get(
            query=query,
            similarity_threshold=threshold,
        )

        if cache_entry is None:
            return None

        # Enrich response with cache metadata
        response = (
            cache_entry.response.copy()
            if isinstance(cache_entry.response, dict)
            else cache_entry.response
        )
        if isinstance(response, dict):
            response["cache_hit"] = True
            response["cache_query"] = cache_entry.query
            response["cache_metadata"] = cache_entry.metadata

        return response

    async def store(
        self,
        query: str,
        result_data: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """Store query result in cache.

        Args:
            query: Natural language query
            result_data: Query result to cache (must include sql, results)
            ttl: Time-to-live in seconds (None = use default)

        Raises:
            ValueError: If query is empty

        Example:
            >>> result = {
            ...     "sql": "SELECT ...",
            ...     "results": [...],
            ...     "intent": "cost_analysis",
            ...     "confidence": 0.85
            ... }
            >>> await adapter.store("Show warehouse costs", result)
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        ttl = ttl if ttl is not None else self.default_ttl

        # Extract metadata from result
        metadata = self._extract_metadata(result_data)

        # Store in semantic cache
        await self.semantic_cache.set(
            query=query,
            response=result_data,
            ttl=ttl,
            metadata=metadata,
        )

    async def invalidate(
        self,
        pattern: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Invalidate cache entries.

        Args:
            pattern: Text pattern to match
            tags: Tags to filter by

        Returns:
            Number of entries invalidated

        Example:
            >>> # Invalidate all warehouse-related caches
            >>> count = await adapter.invalidate(pattern="warehouse")
        """
        return await self.semantic_cache.invalidate(
            pattern=pattern,
            tags=tags,
        )

    def get_metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Returns:
            Dict with hits, misses, hit_rate, etc.

        Example:
            >>> metrics = adapter.get_metrics()
            >>> print(f"Hit rate: {metrics['hit_rate']:.1%}")
        """
        return self.semantic_cache.get_metrics()

    def _extract_metadata(self, result_data: dict[str, Any]) -> dict[str, Any]:
        """Extract relevant metadata from result data.

        Args:
            result_data: Query result

        Returns:
            Metadata dict for caching

        Note:
            Extracts: intent, domain, confidence, tables_used
        """
        metadata = {}

        # Extract common fields
        for key in ["intent", "domain", "confidence", "tables_used"]:
            if key in result_data:
                metadata[key] = result_data[key]

        return metadata
