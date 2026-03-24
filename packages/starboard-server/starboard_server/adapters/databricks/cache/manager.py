"""Unified cache manager for Databricks client.

This module provides a unified caching layer with:
- LRU eviction when max size is reached
- TTL-based expiration
- Per-key locking for stampede prevention
- DataFrame serialization support
- Pattern-based invalidation

Design Principles:
- Single cache layer (replaces multiple overlapping caches)
- Async-native interface
- Clear invalidation semantics
- Comprehensive metrics tracking
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with value, expiration, and metadata.

    Attributes:
        value: The cached value
        expires_at: Unix timestamp when entry expires (None for no expiration)
        ttl: Original TTL in seconds (used for reference)
        created_at: Unix timestamp when entry was created
    """

    value: Any
    expires_at: float | None
    ttl: int | None = None
    created_at: float = field(default_factory=time.time)


class CacheManager:
    """Unified cache manager with LRU eviction and per-key locking.

    This cache provides:
    - LRU eviction when max_size is reached
    - TTL-based expiration for cache entries
    - Per-key locking to prevent cache stampede
    - DataFrame serialization for Polars DataFrames
    - Pattern-based invalidation for related entries
    - Comprehensive hit/miss metrics

    Example:
        >>> cache = CacheManager(max_size=500, default_ttl=300)
        >>>
        >>> # Basic usage
        >>> await cache.set("job:123", {"name": "ETL"})
        >>> job = await cache.get("job:123")  # Returns cached dict
        >>>
        >>> # With per-key locking (stampede prevention)
        >>> lock = await cache.get_lock("expensive:key")
        >>> async with lock:
        ...     if await cache.get("expensive:key") is None:
        ...         result = await expensive_operation()
        ...         await cache.set("expensive:key", result)
        >>>
        >>> # DataFrame caching
        >>> await cache.set_dataframe("sql:abc:wh1", df)
        >>> cached_df = await cache.get_dataframe("sql:abc:wh1")
        >>>
        >>> # Pattern invalidation
        >>> await cache.invalidate_pattern("job:123:*")  # Clear all job:123 entries
    """

    def __init__(
        self,
        max_size: int = 500,
        default_ttl: int | None = 300,
    ) -> None:
        """Initialize cache manager.

        Args:
            max_size: Maximum number of entries before LRU eviction
            default_ttl: Default TTL in seconds (None for no expiration)
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._max_size = max_size
        self._default_ttl = default_ttl

        # Metrics
        self._hits = 0
        self._misses = 0

        logger.debug(
            "cache_manager_initialized",
            extra={
                "max_size": max_size,
                "default_ttl": default_ttl,
            },
        )

    # =========================================================================
    # Core Cache Operations
    # =========================================================================

    async def get(self, key: str) -> Any | None:
        """Get cached value by key.

        Returns None if key doesn't exist or has expired.
        Updates LRU order on hit.

        Args:
            key: Cache key to retrieve

        Returns:
            Cached value or None if not found/expired
        """
        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            return None

        # Check expiration
        if entry.expires_at is not None and time.time() > entry.expires_at:
            del self._cache[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self._hits += 1

        return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Store value in cache with optional TTL override.

        If cache is at capacity, evicts the least recently used entry.

        Args:
            key: Cache key
            value: Value to cache (must be serializable)
            ttl: TTL in seconds (uses default_ttl if None)
        """
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + effective_ttl if effective_ttl else None

        # Check if key already exists (update case)
        if key in self._cache:
            self._cache[key] = CacheEntry(
                value=value,
                expires_at=expires_at,
                ttl=effective_ttl,
            )
            self._cache.move_to_end(key)
            return

        # Evict LRU entries if at capacity
        while len(self._cache) >= self._max_size:
            oldest_key, _ = self._cache.popitem(last=False)
            logger.debug("cache_lru_eviction", extra={"evicted_key": oldest_key})

        self._cache[key] = CacheEntry(
            value=value,
            expires_at=expires_at,
            ttl=effective_ttl,
        )

    # =========================================================================
    # Per-Key Locking (Stampede Prevention)
    # =========================================================================

    async def get_lock(self, key: str) -> asyncio.Lock:
        """Get or create a lock for a specific cache key.

        Use this for stampede prevention when multiple concurrent
        requests might try to populate the same cache entry.

        Args:
            key: Cache key to get lock for

        Returns:
            asyncio.Lock instance for this key

        Example:
            >>> lock = await cache.get_lock("expensive:operation")
            >>> async with lock:
            ...     cached = await cache.get("expensive:operation")
            ...     if cached is None:
            ...         result = await expensive_fetch()
            ...         await cache.set("expensive:operation", result)
            ...         return result
            ...     return cached
        """
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    # =========================================================================
    # DataFrame Support
    # =========================================================================

    async def get_dataframe(self, key: str) -> pl.DataFrame | None:
        """Get cached DataFrame by key.

        Deserializes the stored dict representation back to a DataFrame.

        Args:
            key: Cache key

        Returns:
            Polars DataFrame or None if not found/expired
        """
        data = await self.get(key)
        if data is None:
            return None
        return self._deserialize_dataframe(data)

    async def set_dataframe(
        self,
        key: str,
        df: pl.DataFrame,
        ttl: int | None = None,
    ) -> None:
        """Store DataFrame in cache (serialized to dict).

        DataFrames are serialized to dict format for storage,
        which allows for JSON-compatible caching and inspection.

        Args:
            key: Cache key
            df: Polars DataFrame to cache
            ttl: TTL in seconds (uses default_ttl if None)
        """
        await self.set(key, self._serialize_dataframe(df), ttl)

    def _serialize_dataframe(self, df: pl.DataFrame) -> dict[str, Any]:
        """Serialize DataFrame to dict for caching.

        Format:
            {
                "rows": [{"col1": val1, ...}, ...],
                "columns": ["col1", "col2", ...],
                "dtypes": {"col1": "Int64", ...}
            }
        """
        return {
            "rows": df.to_dicts(),
            "columns": df.columns,
            "dtypes": {col: str(dtype) for col, dtype in zip(df.columns, df.dtypes)},
        }

    def _deserialize_dataframe(self, data: dict[str, Any]) -> pl.DataFrame:
        """Reconstruct DataFrame from cached dict."""
        rows = data.get("rows", [])
        columns = data.get("columns", [])

        if not rows:
            # Empty DataFrame - return with schema if available
            if columns:
                return pl.DataFrame(schema=columns)
            return pl.DataFrame()

        df = pl.DataFrame(rows)
        # Ensure column order matches cached order
        if columns:
            df = df.select(columns)

        return df

    # =========================================================================
    # Cache Key Generation Utilities
    # =========================================================================

    @staticmethod
    def sql_key(query: str, warehouse_id: str) -> str:
        """Generate cache key for SQL query.

        Creates a deterministic key based on query content and warehouse.

        Args:
            query: SQL query text
            warehouse_id: Warehouse identifier

        Returns:
            Cache key in format: sql:{hash}:{warehouse_id}
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        return f"sql:{query_hash}:{warehouse_id}"

    # =========================================================================
    # Invalidation
    # =========================================================================

    async def invalidate(self, key: str) -> bool:
        """Invalidate a specific cache entry.

        Args:
            key: Cache key to invalidate

        Returns:
            True if entry was found and removed, False otherwise
        """
        if key in self._cache:
            del self._cache[key]
            logger.debug("cache_invalidated", extra={"key": key})
            return True
        return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all cache entries matching a pattern.

        Supports fnmatch-style wildcards:
        - * matches any sequence of characters
        - ? matches any single character

        Args:
            pattern: Pattern to match (e.g., "job:123:*")

        Returns:
            Number of entries invalidated

        Example:
            >>> await cache.invalidate_pattern("job:123:*")  # All job:123 entries
            >>> await cache.invalidate_pattern("cluster:*")   # All cluster entries
        """
        keys_to_remove = [k for k in self._cache if fnmatch.fnmatch(k, pattern)]
        for key in keys_to_remove:
            del self._cache[key]

        if keys_to_remove:
            logger.debug(
                "cache_pattern_invalidated",
                extra={"pattern": pattern, "count": len(keys_to_remove)},
            )

        return len(keys_to_remove)

    async def clear(self) -> None:
        """Clear all cache entries and locks."""
        async with self._global_lock:
            self._cache.clear()
            self._locks.clear()
        logger.debug("cache_cleared")

    # =========================================================================
    # Metrics
    # =========================================================================

    def get_metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Returns:
            Dictionary with:
            - hits: Number of cache hits
            - misses: Number of cache misses
            - hit_rate: Hit rate (0.0 to 1.0)
            - size: Current number of cached entries
            - max_size: Maximum cache size
        """
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
            "size": len(self._cache),
            "max_size": self._max_size,
        }

    def reset_metrics(self) -> None:
        """Reset hit/miss counters (useful for testing)."""
        self._hits = 0
        self._misses = 0
        logger.debug("cache_metrics_reset")
