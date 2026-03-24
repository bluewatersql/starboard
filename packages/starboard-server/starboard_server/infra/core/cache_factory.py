"""Cache factory for creating namespaced cache instances.

This module provides a factory pattern for creating cache instances with
isolated namespaces from a shared underlying store. This enables:

- Single cache store (Redis/InMemory) shared across components
- Namespace isolation prevents key collisions
- Unified metrics aggregation across all caches
- Easy swapping between InMemory (dev) and Redis (prod)

Design:
    CacheFactory wraps a base CacheStore and creates NamespacedCache
    instances on demand. Each namespace can only be created once to
    prevent accidental key collisions.

Examples:
    >>> store = InMemoryCacheStore()
    >>> factory = CacheFactory(store)
    >>> catalog_cache = factory.create("catalog", default_ttl=300)
    >>> sql_cache = factory.create("sql", default_ttl=60)
    >>> factory.list_namespaces()
    ['catalog', 'sql']
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from starboard_core.ports.cache_store import CacheMetrics

from starboard_server.infra.core.namespaced_cache import NamespacedCache

if TYPE_CHECKING:
    from starboard_core.ports.cache_store import CacheStore


@dataclass
class CacheFactory:
    """Factory for creating namespaced cache instances.

    Ensures all caches share the same underlying store but have
    isolated namespaces to prevent key collisions. Tracks all
    created namespaces for metrics aggregation.

    Attributes:
        _base_store: Underlying cache store (InMemory or Redis)
        _namespaces: Registry of created namespaces
        _caches: Map of namespace to cache instance (for metrics)

    Examples:
        >>> factory = CacheFactory(InMemoryCacheStore())
        >>> catalog_cache = factory.create("catalog", default_ttl=300)
        >>> sql_cache = factory.create("sql", default_ttl=60)
        >>> factory.list_namespaces()
        ['catalog', 'sql']
    """

    _base_store: CacheStore
    _namespaces: set[str] = field(default_factory=set, repr=False)
    _caches: dict[str, NamespacedCache] = field(default_factory=dict, repr=False)

    def create(
        self,
        namespace: str,
        default_ttl: int | None = None,  # noqa: ARG002 - reserved for future use
    ) -> NamespacedCache:
        """Create a namespaced cache instance.

        Each namespace can only be created once. Attempting to create
        a duplicate namespace raises ValueError.

        Args:
            namespace: Unique namespace prefix for keys (e.g., "catalog", "sql")
            default_ttl: Reserved for future use (TTL not enforced at wrapper level)

        Returns:
            NamespacedCache instance wrapping the base store

        Raises:
            ValueError: If namespace already exists

        Examples:
            >>> cache = factory.create("catalog")
            >>> cache.namespace
            'catalog'
            >>> factory.create("catalog")  # Raises ValueError
        """
        if namespace in self._namespaces:
            raise ValueError(
                f"Namespace '{namespace}' already exists. "
                "Use get_cache() to retrieve existing cache."
            )

        self._namespaces.add(namespace)
        cache = NamespacedCache(
            store=self._base_store,
            namespace=namespace,
        )
        self._caches[namespace] = cache

        return cache

    def get_cache(self, namespace: str) -> NamespacedCache | None:
        """Retrieve an existing namespaced cache.

        Args:
            namespace: Namespace to retrieve

        Returns:
            NamespacedCache if exists, None otherwise

        Examples:
            >>> factory.create("catalog")
            >>> cache = factory.get_cache("catalog")
            >>> cache.namespace
            'catalog'
        """
        return self._caches.get(namespace)

    def get_or_create(
        self,
        namespace: str,
        default_ttl: int | None = None,
    ) -> NamespacedCache:
        """Get existing cache or create new one.

        Convenience method that avoids ValueError for existing namespaces.

        Args:
            namespace: Namespace to get or create
            default_ttl: Reserved for future use

        Returns:
            NamespacedCache instance (existing or new)

        Examples:
            >>> cache1 = factory.get_or_create("catalog")
            >>> cache2 = factory.get_or_create("catalog")
            >>> cache1 is cache2
            True
        """
        existing = self.get_cache(namespace)
        if existing is not None:
            return existing
        return self.create(namespace, default_ttl)

    def list_namespaces(self) -> list[str]:
        """List all created namespaces.

        Returns:
            Sorted list of namespace names

        Examples:
            >>> factory.create("sql")
            >>> factory.create("catalog")
            >>> factory.list_namespaces()
            ['catalog', 'sql']
        """
        return sorted(self._namespaces)

    def get_all_metrics(self) -> dict[str, CacheMetrics]:
        """Get metrics from all registered caches.

        Returns:
            Dictionary mapping namespace to its CacheMetrics

        Examples:
            >>> metrics = factory.get_all_metrics()
            >>> metrics["catalog"].hit_rate
            0.85
        """
        return {ns: cache.get_metrics() for ns, cache in self._caches.items()}

    def get_aggregate_metrics(self) -> CacheMetrics:
        """Get aggregated metrics across all caches.

        Combines hits, misses, and sizes from all namespaces
        into a single CacheMetrics instance.

        Returns:
            Aggregated CacheMetrics across all namespaces

        Examples:
            >>> metrics = factory.get_aggregate_metrics()
            >>> metrics.hit_rate  # Overall hit rate
            0.82
        """
        all_metrics = list(self.get_all_metrics().values())

        if not all_metrics:
            return CacheMetrics.empty()

        total_hits = sum(m.hits for m in all_metrics)
        total_misses = sum(m.misses for m in all_metrics)
        total_size = sum(m.size for m in all_metrics)

        return CacheMetrics.from_counts(
            hits=total_hits,
            misses=total_misses,
            size=total_size,
        )

    async def clear_all(self) -> None:
        """Clear the entire cache store.

        Warning:
            This clears ALL data in the underlying store,
            not just namespaced data.

        Examples:
            >>> await factory.clear_all()
        """
        await self._base_store.clear()

        # Reset all metrics
        for cache in self._caches.values():
            cache.reset_metrics()
