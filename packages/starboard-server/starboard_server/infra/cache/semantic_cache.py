"""
Semantic cache for LLM responses.

Unlike traditional caching (exact key match), semantic caching:
1. Embeds the query
2. Searches for similar cached queries
3. Returns cached response if similarity > threshold

This dramatically reduces LLM costs for similar queries.

Example:
    >>> from starboard_server.infra.cache import SemanticCache
    >>> from starboard_server.infra.rag import SQLiteVectorStore
    >>>
    >>> store = SQLiteVectorStore("cache.db")
    >>> await store.initialize()
    >>>
    >>> cache = SemanticCache(
    ...     vector_store=store,
    ...     embedding_fn=get_embedding,
    ...     ttl=300,  # 5 minutes
    ...     similarity_threshold=0.95
    ... )
    >>>
    >>> # Try to get from cache
    >>> entry = await cache.get("Show top 10 expensive jobs")
    >>> if entry is None:
    ...     response = await llm.generate(...)
    ...     await cache.set("Show top 10 expensive jobs", response)
"""

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from starboard_core.foundations.models import (
    CacheEntry,
    VectorRecord,
)
from starboard_core.foundations.protocols import VectorStore


class SemanticCache:
    """Semantic cache using vector similarity for cache lookup.

    This cache uses embeddings to find semantically similar queries, allowing
    cache hits even when query text differs slightly.

    Attributes:
        vector_store: Vector store for similarity search
        embedding_fn: Function to generate embeddings from text
        ttl: Default time-to-live in seconds
        similarity_threshold: Minimum similarity for cache hit (0.0 to 1.0)

    Example:
        >>> cache = SemanticCache(
        ...     vector_store=store,
        ...     embedding_fn=get_embedding,
        ...     ttl=300,
        ...     similarity_threshold=0.95
        ... )
        >>>
        >>> # Cache miss - generate and store
        >>> entry = await cache.get("top 10 jobs")
        >>> if entry is None:
        ...     response = await expensive_llm_call(...)
        ...     await cache.set("top 10 jobs", response)
        >>>
        >>> # Cache hit - similar query
        >>> entry = await cache.get("show me top ten jobs")
        >>> if entry:
        ...     return entry.response  # No LLM call needed!
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_fn: Callable[[str], Awaitable[list[float]]],
        ttl: int = 300,
        similarity_threshold: float = 0.95,
    ):
        """Initialize semantic cache.

        Args:
            vector_store: Vector store for similarity search
            embedding_fn: Async function to generate embeddings
            ttl: Default time-to-live in seconds
            similarity_threshold: Minimum similarity for cache hit (0.0 to 1.0)

        Raises:
            ValueError: If threshold not in valid range
        """
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError(
                f"similarity_threshold must be between 0 and 1, got {similarity_threshold}"
            )

        self.vector_store = vector_store
        self.embedding_fn = embedding_fn
        self.default_ttl = ttl
        self.similarity_threshold = similarity_threshold

        # Metrics
        self._hits = 0
        self._misses = 0

    async def get(
        self,
        query: str,
        similarity_threshold: float | None = None,
    ) -> CacheEntry | None:
        """Get cached response for semantically similar query.

        Args:
            query: Query to look up
            similarity_threshold: Override default threshold

        Returns:
            CacheEntry if similar cached query found, None otherwise

        Example:
            >>> entry = await cache.get("top 10 expensive jobs")
            >>> if entry and not entry.is_expired:
            ...     return entry.response
        """
        threshold = similarity_threshold or self.similarity_threshold

        # Generate embedding for query
        query_embedding = await self._get_embedding(query)

        # Search for similar queries
        results = await self.vector_store.search(
            query_embedding=query_embedding,
            top_k=1,  # Only need most similar
            filters=None,
        )

        if not results:
            self._misses += 1
            return None

        best_match = results[0]

        # Check if similarity meets threshold
        if best_match.score < threshold:
            self._misses += 1
            return None

        # Parse cache entry from metadata
        try:
            cache_data = best_match.metadata
            entry = CacheEntry(
                id=best_match.id,
                query=cache_data["query"],
                query_embedding=query_embedding,
                response=cache_data["response"],
                created_at=datetime.fromisoformat(cache_data["created_at"]),
                ttl=cache_data["ttl"],
                metadata=cache_data.get("metadata", {}),
            )

            # Check if expired
            if entry.is_expired:
                # Clean up expired entry
                await self.vector_store.delete([entry.id])
                self._misses += 1
                return None

            self._hits += 1
            return entry

        except (KeyError, ValueError):
            # Invalid cache data
            await self.vector_store.delete([best_match.id])
            self._misses += 1
            return None

    async def set(
        self,
        query: str,
        response: Any,
        ttl: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Cache a response with semantic key.

        Args:
            query: Original query
            response: Response to cache
            ttl: Time-to-live in seconds (None = use default)
            metadata: Additional context

        Example:
            >>> await cache.set(
            ...     "Show top 10 expensive jobs",
            ...     {"jobs": [...]},
            ...     ttl=300,
            ...     metadata={"model": "gpt-4"}
            ... )
        """
        ttl = ttl if ttl is not None else self.default_ttl

        # Generate embedding
        query_embedding = await self._get_embedding(query)

        # Create unique ID from query hash
        cache_id = self._generate_cache_id(query)

        # Create cache entry
        entry = CacheEntry(
            id=cache_id,
            query=query,
            query_embedding=query_embedding,
            response=response,
            created_at=datetime.now(UTC),
            ttl=ttl,
            metadata=metadata or {},
        )

        # Store as vector record
        vector = VectorRecord(
            id=cache_id,
            embedding=query_embedding,
            metadata={
                "query": query,
                "response": response,
                "created_at": entry.created_at.isoformat(),
                "ttl": ttl,
                "metadata": metadata or {},
            },
            content=query,  # Store query text for reference
        )

        await self.vector_store.upsert([vector])

    async def invalidate(
        self,
        pattern: str | None = None,  # noqa: ARG002
        tags: list[str] | None = None,  # noqa: ARG002
    ) -> int:
        """Invalidate cache entries.

        Args:
            pattern: Optional text pattern to match
            tags: Optional tags to filter by

        Returns:
            Number of entries invalidated

        Note:
            Currently only supports full invalidation.
            Pattern and tag filtering to be implemented.

        Example:
            >>> # Invalidate all job-related caches
            >>> count = await cache.invalidate(tags=["job"])
        """
        # TODO(BACKLOG-002): Implement pattern and tag filtering for cache invalidation
        # For now, just count and return 0
        return 0

    async def cleanup_expired(self) -> int:
        """Remove expired cache entries.

        Returns:
            Number of entries removed

        Example:
            >>> # Run periodic cleanup
            >>> removed = await cache.cleanup_expired()
            >>> logger.info("Cleaned up {removed} expired entries")
        """
        # This would require scanning all entries
        # For now, we clean up expired entries lazily during get()
        return 0

    async def count(self) -> int:
        """Get total number of cache entries.

        Returns:
            Total cache entry count
        """
        return await self.vector_store.count()

    def get_metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Returns:
            Dictionary with hit rate, counts, etc.

        Example:
            >>> metrics = cache.get_metrics()
            >>> print(f"Hit rate: {metrics['hit_rate']:.1%}")
        """
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate": hit_rate,
            "similarity_threshold": self.similarity_threshold,
            "default_ttl": self.default_ttl,
        }

    def reset_metrics(self) -> None:
        """Reset hit/miss counters."""
        self._hits = 0
        self._misses = 0

    async def clear(self) -> None:
        """Clear all cache entries.

        Warning: This deletes all cached data!
        """
        # Get all IDs and delete
        # For now, rely on vector store's clear method
        if hasattr(self.vector_store, "clear"):
            await self.vector_store.clear()

    def _generate_cache_id(self, query: str) -> str:
        """Generate unique cache ID from query.

        Args:
            query: Query text

        Returns:
            Unique cache ID
        """
        # Use SHA256 hash of query
        hash_obj = hashlib.sha256(query.encode("utf-8"))
        return f"cache_{hash_obj.hexdigest()[:16]}"

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding for text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        return await self.embedding_fn(text)
