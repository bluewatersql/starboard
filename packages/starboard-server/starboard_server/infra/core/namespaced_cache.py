"""Namespaced cache wrapper for key isolation.

This module provides a wrapper around CacheStore that prefixes all keys
with a namespace, preventing key collisions when multiple components
share the same underlying cache store.

Design:
    - Wraps any CacheStore implementation (InMemory, Redis)
    - All keys automatically prefixed: "namespace:key"
    - Tracks per-namespace metrics (hits/misses)
    - Implements CacheStore protocol for seamless substitution

Examples:
    >>> store = InMemoryCacheStore()
    >>> catalog_cache = NamespacedCache(store, namespace="catalog")
    >>> await catalog_cache.set("entries", data)
    >>> # Actual key in store: "catalog:entries"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from starboard_core.ports.cache_store import CacheMetrics

if TYPE_CHECKING:
    from starboard_core.ports.cache_store import CacheStore


@dataclass
class NamespacedCache:
    """Cache wrapper that prefixes all keys with a namespace.

    Prevents key collisions when multiple components share the same
    underlying cache store. Each namespace tracks its own metrics.

    Attributes:
        store: Underlying cache store implementation
        namespace: Prefix for all keys (e.g., "catalog", "sql", "data")
        separator: Character between namespace and key (default: ":")

    Examples:
        >>> store = InMemoryCacheStore()
        >>> cache = NamespacedCache(store, namespace="catalog")
        >>> await cache.set("entries", [...])  # Key: "catalog:entries"
        >>> data = await cache.get("entries")
        >>> metrics = cache.get_metrics()
        >>> metrics.hit_rate
        0.5
    """

    store: CacheStore
    namespace: str
    separator: str = ":"
    _hits: int = field(default=0, repr=False)
    _misses: int = field(default=0, repr=False)

    def _make_key(self, key: str) -> str:
        """Create namespaced key.

        Args:
            key: Original key

        Returns:
            Namespaced key in format "namespace:key"

        Examples:
            >>> cache._make_key("entries")
            'catalog:entries'
        """
        return f"{self.namespace}{self.separator}{key}"

    async def get(self, key: str, reset_ttl: bool = False) -> Any | None:
        """Retrieve value with namespaced key.

        Tracks hits and misses for metrics.

        Args:
            key: Cache key (will be prefixed with namespace)
            reset_ttl: If True, reset TTL on access (default: False).
                       Passed through to underlying store.

        Returns:
            Cached value if found, None otherwise

        Examples:
            >>> value = await cache.get("entries")
            >>> # With TTL reset for hot data
            >>> value = await cache.get("entries", reset_ttl=True)
        """
        result = await self.store.get(self._make_key(key), reset_ttl=reset_ttl)
        if result is None:
            self._misses += 1
        else:
            self._hits += 1
        return result

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Store value with namespaced key.

        Args:
            key: Cache key (will be prefixed with namespace)
            value: Value to cache
            ttl: Time-to-live in seconds (None = no expiration)

        Examples:
            >>> await cache.set("entries", data, ttl=300)
        """
        await self.store.set(self._make_key(key), value, ttl)

    async def delete(self, key: str) -> bool:
        """Delete value with namespaced key.

        Args:
            key: Cache key (will be prefixed with namespace)

        Returns:
            True if key existed and was deleted

        Examples:
            >>> deleted = await cache.delete("entries")
        """
        return await self.store.delete(self._make_key(key))

    async def exists(self, key: str) -> bool:
        """Check if namespaced key exists.

        Args:
            key: Cache key (will be prefixed with namespace)

        Returns:
            True if key exists and is not expired

        Examples:
            >>> exists = await cache.exists("entries")
        """
        return await self.store.exists(self._make_key(key))

    async def clear(self) -> None:
        """Clear all values in the underlying store.

        Warning:
            This clears the ENTIRE store, not just this namespace.
            For namespace-only clear, a pattern-based delete would be
            needed (Redis SCAN + DEL). Currently not implemented.

        Examples:
            >>> await cache.clear()
        """
        await self.store.clear()
        # Reset metrics on clear
        self._hits = 0
        self._misses = 0

    def get_metrics(self) -> CacheMetrics:
        """Get cache metrics for this namespace.

        Returns:
            CacheMetrics with hits, misses, hit_rate for this namespace.
            Size is 0 (not tracked at namespace level).

        Examples:
            >>> metrics = cache.get_metrics()
            >>> metrics.hit_rate
            0.85
        """
        return CacheMetrics.from_counts(
            hits=self._hits,
            misses=self._misses,
            size=0,  # Size not tracked at namespace level
        )

    def reset_metrics(self) -> None:
        """Reset hit/miss counters.

        Useful for testing or periodic metric snapshots.

        Examples:
            >>> cache.reset_metrics()
            >>> cache.get_metrics().hits
            0
        """
        self._hits = 0
        self._misses = 0
