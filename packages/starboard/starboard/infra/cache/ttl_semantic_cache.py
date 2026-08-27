# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""TTL-only exact-key response cache (the default, dependency-free cache).

This is the default "semantic cache" for Phase 2 C4 (decision D-2.9). Despite
the shared name, it performs **no** similarity search: it is a plain in-memory
key/value cache keyed by an exact hash of the query string, with per-entry TTL
expiry. It carries **no vector store, no embeddings, and no sqlite-vec
dependency** — so a no-extras / ``vector_backend="none"`` install never touches
an ANN driver.

The similarity-based :class:`~starboard.infra.cache.semantic_cache.SemanticCache`
remains available for opt-in use behind ``vector_backend`` /
``starboard[vectorsearch]``. Both expose the same duck-typed surface the
analytics cache adapter relies on (``get`` / ``set`` / ``invalidate`` /
``cleanup_expired`` / ``count`` / ``get_metrics``), so wiring is a drop-in swap.

Example:
    >>> cache = TTLSemanticCache(ttl=300)
    >>> await cache.set("Show top 10 expensive jobs", {"sql": "SELECT ..."})
    >>> entry = await cache.get("Show top 10 expensive jobs")  # exact-key hit
    >>> entry.response
    {'sql': 'SELECT ...'}
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from starboard_core.foundations.models import CacheEntry


class TTLSemanticCache:
    """Exact-key, TTL-only LLM response cache with no vector dependency.

    Attributes:
        default_ttl: Default time-to-live in seconds applied when ``set`` is
            called without an explicit ``ttl``.
        max_size: Maximum number of live entries; least-recently-used entries
            are evicted past this bound.
    """

    def __init__(self, ttl: int = 300, max_size: int = 1000):
        """Initialize the TTL cache.

        Args:
            ttl: Default time-to-live in seconds.
            max_size: Maximum number of entries before LRU eviction.
        """
        self.default_ttl = ttl
        self.max_size = max_size
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()

        # Metrics
        self._hits = 0
        self._misses = 0

    async def get(
        self,
        query: str,
        similarity_threshold: float | None = None,  # noqa: ARG002 - API compat only
    ) -> CacheEntry | None:
        """Return the cached entry for an *exact* query match, if live.

        Args:
            query: Query to look up. Only exact-key matches hit.
            similarity_threshold: Accepted for interface compatibility with the
                similarity-based cache; ignored here (there is no fuzzy path).

        Returns:
            The :class:`CacheEntry` when a non-expired exact match exists,
            otherwise ``None``.
        """
        key = self._key(query)
        entry = self._entries.get(key)

        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired:
            del self._entries[key]
            self._misses += 1
            return None

        # Mark as most-recently-used.
        self._entries.move_to_end(key)
        self._hits += 1
        return entry

    async def set(
        self,
        query: str,
        response: Any,
        ttl: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Cache ``response`` under the exact ``query`` key.

        Args:
            query: Original query (exact-match key).
            response: Response payload to cache.
            ttl: Time-to-live in seconds (``None`` uses ``default_ttl``).
            metadata: Optional additional context stored alongside the entry.
        """
        effective_ttl = ttl if ttl is not None else self.default_ttl
        key = self._key(query)

        # Evict LRU entries when at capacity (unless replacing an existing key).
        while key not in self._entries and len(self._entries) >= self.max_size:
            self._entries.popitem(last=False)

        self._entries[key] = CacheEntry(
            id=key,
            query=query,
            query_embedding=[],  # TTL-only cache stores no embeddings
            response=response,
            created_at=datetime.now(UTC),
            ttl=effective_ttl,
            metadata=metadata or {},
        )
        self._entries.move_to_end(key)

    async def invalidate(
        self,
        pattern: str | None = None,
        tags: list[str] | None = None,  # noqa: ARG002 - reserved for parity
    ) -> int:
        """Invalidate cache entries.

        Args:
            pattern: Optional case-insensitive substring; when given, only
                entries whose query contains it are removed. When ``None``, all
                entries are cleared.
            tags: Reserved for interface parity; not used by the TTL cache.

        Returns:
            The number of entries removed.
        """
        if pattern is None:
            count = len(self._entries)
            self._entries.clear()
            return count

        needle = pattern.lower()
        to_remove = [
            key
            for key, entry in self._entries.items()
            if needle in entry.query.lower()
        ]
        for key in to_remove:
            del self._entries[key]
        return len(to_remove)

    async def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            The number of entries removed.
        """
        to_remove = [key for key, entry in self._entries.items() if entry.is_expired]
        for key in to_remove:
            del self._entries[key]
        return len(to_remove)

    async def count(self) -> int:
        """Return the number of stored entries (including any not-yet-reaped)."""
        return len(self._entries)

    def get_metrics(self) -> dict[str, Any]:
        """Return cache performance metrics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate": hit_rate,
            "default_ttl": self.default_ttl,
            "cache_type": "ttl_exact_key",
        }

    def reset_metrics(self) -> None:
        """Reset hit/miss counters."""
        self._hits = 0
        self._misses = 0

    async def clear(self) -> None:
        """Clear all cache entries."""
        self._entries.clear()

    async def close(self) -> None:
        """Release resources (no-op; kept for lifecycle parity)."""

    @staticmethod
    def _key(query: str) -> str:
        """Generate a stable exact-match key from the query text."""
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
        return f"cache_{digest}"
