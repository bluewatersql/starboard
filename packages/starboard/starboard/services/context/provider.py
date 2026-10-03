# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Shared context provider for optimization workflows.

This module provides a centralized, cacheable context management system
that is shared across all optimizer types. It separates concerns between
data fetching, transformation, and caching.

All operations are async for clean integration with async agents and tools.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from starboard.exceptions import AdapterError, DatabricksAPIError
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.adapters.databricks import AsyncDatabricksClient

logger = get_logger(__name__)

# Type alias for async fetcher functions
AsyncFetcher = Callable[..., Awaitable[Any]]


@dataclass
class ContextCache:
    """
    In-memory cache for context data.

    Attributes:
        data: Cached data dictionary
        hits: Cache hit counter
        misses: Cache miss counter
    """

    data: dict[str, Any] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, key: str) -> tuple[Any, bool]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Tuple of (value, found) where found indicates cache hit
        """
        if key in self.data:
            self.hits += 1
            return self.data[key], True
        self.misses += 1
        return None, False

    def put(self, key: str, value: Any) -> None:
        """
        Store value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        self.data[key] = value

    def clear(self) -> None:
        """Clear all cached data."""
        self.data.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict[str, int | float]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total": total,
            "hit_rate": round(hit_rate, 2),
            "size": len(self.data),
        }


class SharedContextProvider:
    """
    Centralized async context provider with caching and lazy loading.

    This provider manages all context data for optimization workflows,
    providing a clean async interface for fetching and caching data from
    Databricks. It supports:
    - Lazy loading: Data is only fetched when requested
    - Caching: Fetched data is cached for reuse
    - Batch operations: Multiple items can be fetched efficiently
    - Full async: All operations are async for clean agent integration

    Attributes:
        client: Async Databricks client
        cache: Context cache for storing fetched data
        fetchers: Registered async data fetching functions
    """

    def __init__(self, client: AsyncDatabricksClient) -> None:
        """
        Initialize shared context provider.

        Args:
            client: Async Databricks client
        """
        self.client = client
        self.cache = ContextCache()
        self.fetchers: dict[str, AsyncFetcher] = {}

        # Register default fetchers
        self._register_default_fetchers()

    def _register_default_fetchers(self) -> None:
        """Register default async data fetching functions."""
        from starboard.services.context.fetchers import (
            fetch_cluster_config,
            fetch_cluster_events,
            fetch_cluster_metrics,
            fetch_dbfs_file,
            fetch_delta_history,
            fetch_explain_plan,
            fetch_job_metadata,
            fetch_job_run_detail,
            fetch_jobs_by_name,
            fetch_jobs_list,
            fetch_notebook_source,
            fetch_query_history,
            fetch_table_lineage,
            fetch_table_metadata,
            fetch_warehouse_config,
            fetch_warehouse_metrics,
            fetch_warehouse_query_history,
        )

        self.fetchers = {
            "query_history": fetch_query_history,
            "table_metadata": fetch_table_metadata,
            "table_lineage": fetch_table_lineage,
            "delta_history": fetch_delta_history,
            "warehouse_config": fetch_warehouse_config,
            "warehouse_metrics": fetch_warehouse_metrics,
            "warehouse_query_history": fetch_warehouse_query_history,
            "explain_plan": fetch_explain_plan,
            "cluster_metrics": fetch_cluster_metrics,
            "cluster_config": fetch_cluster_config,
            "cluster_events": fetch_cluster_events,
            "jobs_list": fetch_jobs_list,
            "jobs_by_name": fetch_jobs_by_name,
            "job_metadata": fetch_job_metadata,
            "job_run_detail": fetch_job_run_detail,
            "notebook_source": fetch_notebook_source,
            "dbfs_file": fetch_dbfs_file,
        }

    async def get(self, resource_type: str, resource_id: str, **kwargs: Any) -> Any:
        """
        Get resource data with caching.

        Args:
            resource_type: Type of resource (e.g., 'table_metadata')
            resource_id: Resource identifier
            **kwargs: Additional parameters for the fetcher

        Returns:
            Resource data or None if not found
        """
        cache_key = self._build_cache_key(resource_type, resource_id, kwargs)

        # Check cache first
        cached, found = self.cache.get(cache_key)
        if found:
            logger.debug("cache_hit", cache_key=cache_key)
            return cached

        # Fetch data
        logger.debug("cache_miss", cache_key=cache_key)
        fetcher = self.fetchers.get(resource_type)
        if not fetcher:
            logger.warning("no_fetcher_registered", resource_type=resource_type)
            return None

        try:
            # All fetchers are async - await directly
            data = await fetcher(self.client, resource_id, **kwargs)
            if data is not None:
                self.cache.put(cache_key, data)
            return data
        except (DatabricksAPIError, AdapterError) as e:
            logger.error(
                "fetch_error",
                resource_type=resource_type,
                resource_id=resource_id,
                error=str(e),
            )
            return None

    async def get_many(
        self, resource_type: str, resource_ids: list[str], **kwargs: Any
    ) -> dict[str, Any]:
        """
        Get multiple resources of the same type.

        Args:
            resource_type: Type of resource
            resource_ids: List of resource identifiers
            **kwargs: Additional parameters for the fetcher

        Returns:
            Dictionary mapping resource IDs to their data
        """
        results = {}
        for resource_id in resource_ids:
            data = await self.get(resource_type, resource_id, **kwargs)
            if data is not None:
                results[resource_id] = data
        return results

    def put(
        self, resource_type: str, resource_id: str, data: Any, **kwargs: Any
    ) -> None:
        """
        Store data in cache (useful for preloaded data).

        Args:
            resource_type: Type of resource
            resource_id: Resource identifier
            data: Data to cache
            **kwargs: Additional parameters for cache key
        """
        cache_key = self._build_cache_key(resource_type, resource_id, kwargs)
        self.cache.put(cache_key, data)

    def register_fetcher(self, resource_type: str, fetcher: AsyncFetcher) -> None:
        """
        Register a custom async data fetcher.

        Args:
            resource_type: Type of resource this fetcher handles
            fetcher: Async fetching function that takes (client, resource_id, **kwargs)
        """
        self.fetchers[resource_type] = fetcher
        logger.debug("fetcher_registered", resource_type=resource_type)

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self.cache.clear()
        logger.debug("cache_cleared")

    def cache_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        return self.cache.stats()

    def _build_cache_key(
        self, resource_type: str, resource_id: str, params: dict[str, Any]
    ) -> str:
        """
        Build cache key from resource type, ID, and parameters.

        Args:
            resource_type: Type of resource
            resource_id: Resource identifier
            params: Additional parameters

        Returns:
            Cache key string
        """
        if not params:
            return f"{resource_type}::{resource_id}"

        # Sort params for consistent cache keys
        param_str = "::".join(
            f"{k}={v}" for k, v in sorted(params.items()) if v is not None
        )
        return f"{resource_type}::{resource_id}::{param_str}"
