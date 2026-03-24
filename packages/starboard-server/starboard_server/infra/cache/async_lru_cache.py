"""
Async LRU cache decorator with per-key locking (single-flight pattern).

This module provides:
- AsyncLRUCache: An async-safe LRU cache with TTL support
- Per-key locking to prevent duplicate concurrent requests (stampede prevention)
- Metrics tracking for hit rate analysis
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TypeVar

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class CacheEntry:
    """Cache entry with value, expiration, and metadata."""

    value: Any
    expires_at: float | None
    ttl: int | None
    created_at: float = field(default_factory=time.time)


class AsyncLRUCache:
    """
    Async LRU cache with per-key locking to prevent stampede.

    Features:
    - LRU eviction when max_size is reached
    - TTL expiration with optional reset on hit (opt-in, disabled by default)
    - Per-key locking to prevent duplicate concurrent requests (single-flight)
    - Async-safe for use with asyncio

    Example:
        >>> cache = AsyncLRUCache(max_size=100, default_ttl=300)
        >>>
        >>> @cache.cached(key_prefix="job")
        >>> async def get_job(job_id: int) -> dict:
        ...     return await fetch_job_from_api(job_id)
        >>>
        >>> # First call fetches from API
        >>> job = await get_job(123)
        >>>
        >>> # Second call returns cached value
        >>> job = await get_job(123)  # Cache hit!

        >>> # Opt-in to TTL reset for frequently accessed data
        >>> cache_warm = AsyncLRUCache(max_size=100, default_ttl=300, reset_ttl_on_hit=True)
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 300,  # 5 minutes
        reset_ttl_on_hit: bool = False,
    ):
        """Initialize async LRU cache.

        Args:
            max_size: Maximum number of entries before LRU eviction
            default_ttl: Default TTL in seconds (None for no expiration)
            reset_ttl_on_hit: Whether to reset TTL when cache is hit (default: False).
                             Set to True for data that should stay warm with frequent access.
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._reset_ttl_on_hit = reset_ttl_on_hit

        # Metrics
        self._hits = 0
        self._misses = 0

        logger.debug(
            "async_lru_cache_initialized",
            max_size=max_size,
            default_ttl=default_ttl,
            reset_ttl_on_hit=reset_ttl_on_hit,
        )

    async def _get_lock(self, key: str) -> asyncio.Lock:
        """Get or create a lock for a specific key."""
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    async def get(self, key: str) -> tuple[Any, bool]:
        """Get cached value.

        Returns:
            Tuple of (value, found) where found is True if cache hit
        """
        entry = self._cache.get(key)
        if entry is None:
            return None, False

        # Check expiration
        if entry.expires_at is not None and time.time() > entry.expires_at:
            del self._cache[key]
            return None, False

        # Move to end (most recently used)
        self._cache.move_to_end(key)

        # Reset TTL on hit if enabled
        if self._reset_ttl_on_hit and entry.expires_at is not None and entry.ttl:
            entry.expires_at = time.time() + entry.ttl

        self._hits += 1
        return entry.value, True

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set cached value with optional TTL override."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + effective_ttl if effective_ttl else None

        # Evict LRU entries if at capacity
        while len(self._cache) >= self._max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            logger.debug("lru_cache_eviction", evicted_key=oldest_key)

        self._cache[key] = CacheEntry(
            value=value,
            expires_at=expires_at,
            ttl=effective_ttl,
            created_at=time.time(),
        )
        self._cache.move_to_end(key)
        self._misses += 1

    def cached(
        self,
        key_prefix: str = "",
        ttl: int | None = None,
        key_builder: Callable[..., str] | None = None,
    ) -> Callable[[F], F]:
        """Decorator for caching async function results.

        Args:
            key_prefix: Prefix for cache keys (default: function name)
            ttl: TTL override for this function (None uses default)
            key_builder: Custom function to build cache key from args/kwargs

        Example:
            >>> @cache.cached(key_prefix="job", ttl=600)
            >>> async def get_job(job_id: int) -> dict:
            ...     return await api.jobs.get(job_id)
        """

        def decorator(func: F) -> F:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Build cache key
                if key_builder:
                    key = key_builder(*args, **kwargs)
                else:
                    key = self._build_key(key_prefix or func.__name__, args, kwargs)

                # Fast path: check cache without lock
                value, found = await self.get(key)
                if found:
                    logger.debug(
                        "async_lru_cache_hit",
                        key=key,
                        hit_rate=self.hit_rate,
                    )
                    return value

                # Slow path: acquire per-key lock to prevent stampede
                lock = await self._get_lock(key)
                async with lock:
                    # Double-check after acquiring lock
                    value, found = await self.get(key)
                    if found:
                        return value

                    # Execute function
                    logger.debug(
                        "async_lru_cache_miss",
                        key=key,
                        hit_rate=self.hit_rate,
                    )
                    result = await func(*args, **kwargs)

                    # Cache result
                    await self.set(key, result, ttl)

                    return result

            return wrapper  # type: ignore[return-value]

        return decorator

    def _build_key(
        self, prefix: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> str:
        """Build cache key from function arguments.

        Note: This includes ALL args in the key. When used with instance methods,
        the cache decorator should be called on plain functions or the caller
        should use key_builder for custom key generation.
        """
        # Serialize args/kwargs to JSON for stable hashing
        key_data = json.dumps(
            {"args": args, "kwargs": kwargs}, sort_keys=True, default=str
        )
        key_hash = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        return f"{prefix}:{key_hash}"

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def get_metrics(self) -> dict[str, Any]:
        """Get cache metrics."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self.hit_rate,
            "size": len(self._cache),
            "max_size": self._max_size,
        }

    async def clear(self) -> None:
        """Clear all cached entries."""
        async with self._global_lock:
            self._cache.clear()
            self._locks.clear()
        logger.debug("async_lru_cache_cleared")

    async def invalidate(self, key: str) -> bool:
        """Invalidate a specific cache entry.

        Returns:
            True if entry was found and removed, False otherwise
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    async def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all cache entries with a specific prefix.

        Args:
            prefix: The key prefix to match (e.g., "job:" to clear all job entries)

        Returns:
            Number of entries invalidated
        """
        keys_to_remove = [key for key in self._cache if key.startswith(prefix)]
        for key in keys_to_remove:
            del self._cache[key]
        return len(keys_to_remove)
