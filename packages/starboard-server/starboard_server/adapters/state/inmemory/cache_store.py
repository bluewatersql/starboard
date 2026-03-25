"""In-memory cache store implementation with optional TTL reset-on-hit.

This module provides an in-memory cache with TTL support and the ability
to optionally reset TTL when a cache entry is accessed.

Features:
- TTL (time-to-live) expiration
- Optional TTL reset on cache hit (opt-in, disabled by default)
- Simple LRU eviction when max size is reached
- Async-compatible interface
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    """Cache entry with expiration and TTL tracking.

    Attributes:
        value: The cached value
        expires_at: Unix timestamp when entry expires (None for no expiration)
        ttl: Original TTL in seconds (used for reset-on-hit)

    Example:
        >>> entry = CacheEntry(value="data", expires_at=time.time() + 60, ttl=60)
        >>> entry.ttl
        60
    """

    value: Any
    expires_at: float | None  # Unix timestamp or None for no expiration
    ttl: int | None = field(default=None)  # Original TTL for reset-on-hit


class InMemoryCacheStore:
    """In-memory cache store with TTL support and optional reset-on-hit.

    This cache implementation provides:
    - TTL-based expiration for cache entries
    - Optional TTL reset when entries are accessed (reset_ttl parameter, opt-in)
    - Simple LRU eviction when max size is reached

    The reset-on-hit feature keeps frequently accessed data warm by
    resetting the expiration time each time the entry is accessed.
    This is disabled by default to avoid hard-to-debug cache behavior
    where entries never expire if accessed frequently.

    Example:
        >>> cache = InMemoryCacheStore(max_size=1000)
        >>> await cache.set("key", "value", ttl=300)  # 5 minute TTL
        >>>
        >>> # Standard access - TTL NOT reset (default behavior)
        >>> value = await cache.get("key")  # TTL unchanged, expires as expected
        >>>
        >>> # Opt-in to TTL reset for data that should stay warm
        >>> value = await cache.get("key", reset_ttl=True)  # TTL reset to 5 minutes
    """

    def __init__(self, max_size: int = 1000):
        """Initialize in-memory cache.

        Args:
            max_size: Maximum number of entries (simple LRU eviction)
        """
        self._cache: dict[str, CacheEntry] = {}
        self._max_size = max_size

    async def get(self, key: str, reset_ttl: bool = False) -> Any | None:
        """Retrieve cached value with optional TTL reset.

        By default, TTL is NOT reset on access. This ensures cache entries
        expire predictably based on their original TTL. Set reset_ttl=True
        explicitly for data that should stay warm with frequent access.

        Args:
            key: Cache key to retrieve
            reset_ttl: If True, reset TTL on cache hit (default: False).
                      Set to True for data that benefits from staying warm.

        Returns:
            Cached value if found and not expired, None otherwise

        Example:
            >>> # Standard access - TTL unchanged (default)
            >>> value = await cache.get("key")
            >>>
            >>> # Opt-in to keep data warm (for chart/table toggle scenarios)
            >>> value = await cache.get("key", reset_ttl=True)
        """
        entry = self._cache.get(key)
        if entry is None:
            return None

        # Check expiration
        if entry.expires_at is not None and time.time() > entry.expires_at:
            del self._cache[key]
            return None

        # Reset TTL on cache hit (keep frequently accessed data warm)
        if reset_ttl and entry.expires_at is not None and entry.ttl is not None:
            entry.expires_at = time.time() + entry.ttl

        return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Store value in cache with optional TTL (seconds).

        The TTL is stored in the cache entry to support reset-on-hit.
        When the entry is later accessed with get(), the TTL can be
        reset to keep the data warm.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (None for no expiration)

        Example:
            >>> # Cache for 1 hour
            >>> await cache.set("key", "value", ttl=3600)
            >>>
            >>> # Cache without expiration
            >>> await cache.set("key", "value")
        """
        # Enforce max size (simple LRU: remove oldest)
        if len(self._cache) >= self._max_size and key not in self._cache:
            # Remove first key (not true LRU, but simple)
            first_key = next(iter(self._cache))
            del self._cache[first_key]

        expires_at = None
        if ttl is not None:
            expires_at = time.time() + ttl

        self._cache[key] = CacheEntry(value=value, expires_at=expires_at, ttl=ttl)

    async def delete(self, key: str) -> bool:
        """Remove value from cache.

        Args:
            key: Cache key to delete

        Returns:
            True if key was found and deleted, False otherwise
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    async def exists(self, key: str) -> bool:
        """Check if key exists and is not expired.

        Note: This uses get() internally, which may reset TTL.
        Use get(key, reset_ttl=False) if you want to check
        without resetting TTL.

        Args:
            key: Cache key to check

        Returns:
            True if key exists and is not expired
        """
        value = await self.get(key, reset_ttl=False)
        return value is not None

    async def clear(self) -> None:
        """Clear all cached values."""

    async def close(self) -> None:
        """Release resources (no-op for this store)."""

    async def connect(self) -> None:
        """Initialize connection (no-op for this store)."""


        self._cache.clear()
