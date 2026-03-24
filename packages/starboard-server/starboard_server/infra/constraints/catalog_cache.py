"""Caching layer for service catalog lookups.

Provides TTL-based caching to reduce repeated catalog queries.
Uses the CacheStore protocol for swappable backends (InMemory, Redis).

Part of Phase 9: Service Catalog & Next-Step Suggestions
Migrated to async in Phase 3 of caching abstraction.

Examples:
    >>> cache = CatalogCache(store=cache_store, ttl_seconds=300)
    >>> await cache.set("key", data)
    >>> result = await cache.get("key")
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from starboard_core.ports.cache_store import CacheMetrics

from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_core.ports.cache_store import CacheStore

logger = get_logger(__name__)

# Namespace prefix for catalog cache keys
CATALOG_NAMESPACE = "catalog"


class CatalogCache:
    """TTL-based cache for catalog entries using CacheStore protocol.

    Wraps a CacheStore implementation with catalog-specific functionality:
    - Automatic key namespacing (prefix: "catalog:")
    - Key generation from filter parameters
    - Metrics tracking

    For multi-process deployments, use Redis CacheStore. For development,
    InMemory CacheStore works well.

    Attributes:
        ttl_seconds: Time-to-live for cache entries in seconds
        _store: Underlying CacheStore implementation

    Examples:
        >>> from starboard_server.adapters.state.inmemory.cache_store import InMemoryCacheStore
        >>> store = InMemoryCacheStore()
        >>> cache = CatalogCache(store=store, ttl_seconds=300)
        >>> await cache.set("domain:performance", entries)
        >>> result = await cache.get("domain:performance")
    """

    def __init__(
        self,
        store: CacheStore,
        ttl_seconds: int = 300,
        namespace: str = CATALOG_NAMESPACE,
    ) -> None:
        """Initialize cache with specified store and TTL.

        Args:
            store: CacheStore implementation (InMemory or Redis)
            ttl_seconds: Time-to-live for cache entries (default 300s = 5min)
            namespace: Key prefix for namespace isolation (default: "catalog")

        Examples:
            >>> cache = CatalogCache(store=cache_store, ttl_seconds=300)
        """
        self._store = store
        self._ttl_seconds = ttl_seconds
        self._namespace = namespace
        self._hits = 0
        self._misses = 0

        logger.debug(
            "catalog_cache_initialized",
            ttl_seconds=ttl_seconds,
            namespace=namespace,
            store_type=type(store).__name__,
        )

    @property
    def ttl_seconds(self) -> int:
        """Get the TTL in seconds."""
        return self._ttl_seconds

    def _make_key(self, key: str) -> str:
        """Create namespaced key.

        Args:
            key: Original key

        Returns:
            Namespaced key in format "namespace:key"
        """
        return f"{self._namespace}:{key}"

    async def get(self, key: str) -> Any | None:
        """Retrieve value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value if present and not expired, None otherwise

        Examples:
            >>> result = await cache.get("domain:performance")
            >>> if result is None:
            ...     # Cache miss
        """
        namespaced_key = self._make_key(key)
        result = await self._store.get(namespaced_key)

        if result is None:
            self._misses += 1
            logger.debug("catalog_cache_miss", key=key)
            return None

        self._hits += 1
        logger.debug("catalog_cache_hit", key=key)
        return result

    async def set(self, key: str, value: Any) -> None:
        """Set value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache

        Examples:
            >>> await cache.set("domain:performance", entries)
        """
        namespaced_key = self._make_key(key)
        await self._store.set(namespaced_key, value, ttl=self._ttl_seconds)
        logger.debug("catalog_cache_set", key=key)

    async def clear(self) -> None:
        """Clear all cache entries.

        Warning:
            This clears the ENTIRE underlying store, not just catalog entries.
            In a shared store scenario, this affects all namespaces.

        Examples:
            >>> await cache.clear()
        """
        await self._store.clear()
        self._hits = 0
        self._misses = 0
        logger.debug("catalog_cache_cleared")

    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache.

        Args:
            key: Cache key to check

        Returns:
            True if key exists and is not expired

        Examples:
            >>> if await cache.exists("domain:performance"):
            ...     data = await cache.get("domain:performance")
        """
        namespaced_key = self._make_key(key)
        return await self._store.exists(namespaced_key)

    async def delete(self, key: str) -> bool:
        """Delete a specific cache entry.

        Args:
            key: Cache key to delete

        Returns:
            True if key existed and was deleted

        Examples:
            >>> await cache.delete("domain:performance")
        """
        namespaced_key = self._make_key(key)
        return await self._store.delete(namespaced_key)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with hits, misses, hit_rate

        Examples:
            >>> stats = cache.get_stats()
            >>> stats["hit_rate"]
            0.85
        """
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }

    def get_metrics(self) -> CacheMetrics:
        """Get cache metrics as CacheMetrics dataclass.

        Returns:
            CacheMetrics instance with hits, misses, hit_rate

        Examples:
            >>> metrics = cache.get_metrics()
            >>> metrics.hit_rate
            0.85
        """
        return CacheMetrics.from_counts(
            hits=self._hits,
            misses=self._misses,
            size=0,  # Size not tracked at this level
        )

    def reset_stats(self) -> None:
        """Reset hit/miss counters.

        Useful for testing or periodic metric snapshots.

        Examples:
            >>> cache.reset_stats()
            >>> cache.get_stats()["hits"]
            0
        """
        self._hits = 0
        self._misses = 0

    def generate_key(self, **filters: Any) -> str:
        """Generate cache key from filter parameters.

        Creates consistent hash-based key from filter parameters.
        Order-independent: same parameters always produce same key.

        Args:
            **filters: Filter parameters (domain, service_type, status)

        Returns:
            Cache key string (MD5 hash of sorted JSON)

        Examples:
            >>> key = cache.generate_key(domain="performance", service_type="agent")
            >>> key
            'a1b2c3d4...'
        """
        # Sort filters for consistent key generation (order-independent)
        filter_str = json.dumps(filters, sort_keys=True)
        key_hash = hashlib.md5(filter_str.encode()).hexdigest()

        logger.debug("catalog_cache_key_generated", filters=filters, key=key_hash[:8])
        return key_hash
