"""Cache store protocol (interface) and metrics.

This module defines the abstract interface for cache implementations
and standardized metrics for cache observability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class CacheMetrics:
    """Standardized cache performance metrics.

    Provides a consistent structure for cache hit/miss tracking
    across all cache implementations.

    Attributes:
        hits: Number of cache hits (successful retrievals)
        misses: Number of cache misses (key not found or expired)
        size: Current number of entries in cache
        hit_rate: Calculated hit rate (hits / total requests)

    Examples:
        >>> metrics = CacheMetrics(hits=80, misses=20, size=50, hit_rate=0.8)
        >>> metrics.hit_rate
        0.8
        >>> metrics.to_dict()
        {'hits': 80, 'misses': 20, 'size': 50, 'hit_rate': 0.8}
    """

    hits: int
    misses: int
    size: int
    hit_rate: float

    @classmethod
    def empty(cls) -> CacheMetrics:
        """Create empty metrics (zero state).

        Returns:
            CacheMetrics with all values at zero

        Examples:
            >>> CacheMetrics.empty()
            CacheMetrics(hits=0, misses=0, size=0, hit_rate=0.0)
        """
        return cls(hits=0, misses=0, size=0, hit_rate=0.0)

    @classmethod
    def from_counts(cls, hits: int, misses: int, size: int = 0) -> CacheMetrics:
        """Create metrics from hit/miss counts with auto-calculated hit_rate.

        Args:
            hits: Number of cache hits
            misses: Number of cache misses
            size: Current cache size (default: 0)

        Returns:
            CacheMetrics with calculated hit_rate

        Examples:
            >>> CacheMetrics.from_counts(80, 20, 50)
            CacheMetrics(hits=80, misses=20, size=50, hit_rate=0.8)
        """
        total = hits + misses
        hit_rate = hits / total if total > 0 else 0.0
        return cls(hits=hits, misses=misses, size=size, hit_rate=hit_rate)

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary for serialization.

        Returns:
            Dictionary with hits, misses, size, hit_rate

        Examples:
            >>> metrics = CacheMetrics(hits=10, misses=5, size=8, hit_rate=0.67)
            >>> metrics.to_dict()
            {'hits': 10, 'misses': 5, 'size': 8, 'hit_rate': 0.67}
        """
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": self.size,
            "hit_rate": self.hit_rate,
        }


@runtime_checkable
class CacheStore(Protocol):
    """Abstract interface for key-value caching with TTL support."""

    async def get(
        self,
        key: str,
        reset_ttl: bool = False,
    ) -> Any | None:
        """
        Retrieve cached value.

        Args:
            key: Cache key
            reset_ttl: If True, reset TTL on access (default: False).
                       Implementations may ignore this if not supported.

        Returns:
            Cached value if present and not expired, None otherwise
        """
        ...

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """
        Store value in cache.

        Args:
            key: Cache key
            value: Value to cache (must be serializable)
            ttl: Time-to-live in seconds (None = no expiration)
        """
        ...

    async def delete(
        self,
        key: str,
    ) -> bool:
        """
        Remove value from cache.

        Args:
            key: Cache key

        Returns:
            True if key existed, False otherwise
        """
        ...

    async def exists(
        self,
        key: str,
    ) -> bool:
        """
        Check if key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if key exists and not expired, False otherwise
        """
        ...

    async def clear(self) -> None:
        """Clear all cached values (use sparingly)."""
        ...
