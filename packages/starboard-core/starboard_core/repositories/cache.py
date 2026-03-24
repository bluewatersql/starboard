"""Cache manager with utility functions."""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from starboard_core.ports.cache_store import CacheStore


class CacheManager:
    """High-level interface for caching operations."""

    def __init__(self, store: CacheStore, default_ttl: int = 300):
        """
        Initialize cache manager.

        Args:
            store: CacheStore implementation
            default_ttl: Default TTL in seconds (default: 5 minutes)
        """
        self._store = store
        self._default_ttl = default_ttl

    def generate_key(self, prefix: str, **kwargs: Any) -> str:
        """
        Generate deterministic cache key from parameters.

        Args:
            prefix: Key prefix (e.g., "tool:search")
            **kwargs: Parameters to include in key

        Returns:
            Cache key (e.g., "tool:search:a1b2c3...")
        """
        # Sort keys for deterministic hashing
        stable_repr = json.dumps(kwargs, sort_keys=True)
        key_hash = hashlib.sha256(stable_repr.encode()).hexdigest()[:16]
        return f"{prefix}:{key_hash}"

    async def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        ttl: int | None = None,
    ) -> Any:
        """
        Get value from cache or compute and store.

        Args:
            key: Cache key
            compute_fn: Function to compute value on cache miss
            ttl: Time-to-live in seconds (None = use default)

        Returns:
            Cached or computed value
        """
        value = await self._store.get(key)
        if value is not None:
            return value

        value = await compute_fn()
        ttl_seconds = ttl if ttl is not None else self._default_ttl
        await self._store.set(key, value, ttl_seconds)
        return value

    async def invalidate(self, key: str) -> bool:
        """
        Invalidate cached value.

        Args:
            key: Cache key

        Returns:
            True if key existed and was deleted
        """
        return await self._store.delete(key)

    async def clear_all(self) -> None:
        """Clear all cached values (use with caution!)."""
        await self._store.clear()
