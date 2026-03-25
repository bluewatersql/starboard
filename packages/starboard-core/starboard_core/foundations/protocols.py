"""
Foundation protocols for shared infrastructure.

This module defines Protocol interfaces that must be implemented by concrete classes:
- VectorStore: Vector similarity search
- ReflexionStore: Learning storage and retrieval
- SemanticCache: Semantic caching layer

All protocols use async methods for non-blocking I/O operations.
"""

from typing import Any, Protocol

from starboard_core.foundations.models import (
    CacheEntry,
    ReflexionLearning,
    VectorRecord,
    VectorSearchResult,
)


class VectorStore(Protocol):
    """Protocol for vector similarity search backends.

    Implementations:
    - SQLiteVectorStore: Uses sqlite-vec extension
    - PostgresVectorStore: Uses pgvector extension

    Usage:
        >>> store = SQLiteVectorStore("vectors.db")
        >>> await store.initialize()
        >>> results = await store.search(query_embedding, top_k=5)
    """

    async def connect(self) -> None:
        """Initialize connection to the backing store."""
        ...

    async def close(self) -> None:
        """Release resources and close connections."""
        ...

    async def get(self, key: str) -> Any | None:
        """Generic key-value get (for Protocol compliance)."""
        ...

    async def set(self, key: str, value: Any) -> None:
        """Generic key-value set (for Protocol compliance)."""
        ...

    async def initialize(self) -> None:
        """Initialize the vector store (create tables, load extensions, etc.).

        Raises:
            RuntimeError: If initialization fails
        """
        ...

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors using cosine similarity.

        Args:
            query_embedding: Dense vector to search for
            top_k: Maximum number of results to return
            filters: Optional metadata filters (e.g., {"source": "docs"})

        Returns:
            List of search results ordered by similarity (highest first)

        Example:
            >>> results = await store.search(
            ...     query_embedding=[0.1, 0.2, ...],
            ...     top_k=10,
            ...     filters={"type": "documentation"}
            ... )
        """
        ...

    async def upsert(self, vectors: list[VectorRecord]) -> None:
        """Insert or update vectors in batch.

        Args:
            vectors: List of vector records to upsert

        Raises:
            ValueError: If vectors list is empty or invalid

        Example:
            >>> vectors = [
            ...     VectorRecord(
            ...         id="vec_1",
            ...         embedding=[...],
            ...         metadata={"source": "docs"},
            ...         content="How to use feature X"
            ...     )
            ... ]
            >>> await store.upsert(vectors)
        """
        ...

    async def delete(self, ids: list[str]) -> None:
        """Delete vectors by ID.

        Args:
            ids: List of vector IDs to delete

        Example:
            >>> await store.delete(["vec_1", "vec_2"])
        """
        ...

    async def count(self) -> int:
        """Get total number of vectors in store.

        Returns:
            Total vector count
        """
        ...


class ReflexionStore(Protocol):
    """Protocol for storing and retrieving agent learnings.

    Reflexion enables agents to improve by:
    1. Evaluating their own responses
    2. Extracting learnings from failures
    3. Retrieving relevant past learnings

    Usage:
        >>> store = SQLiteReflexionStore("learnings.db")
        >>> await store.initialize()
        >>> await store.save_learning(learning)
        >>> relevant = await store.search_learnings("how to optimize queries", top_k=5)
    """

    async def connect(self) -> None:
        """Initialize connection to the backing store."""
        ...

    async def close(self) -> None:
        """Release resources and close connections."""
        ...

    async def get(self, key: str) -> Any | None:
        """Generic key-value get (for Protocol compliance)."""
        ...

    async def set(self, key: str, value: Any) -> None:
        """Generic key-value set (for Protocol compliance)."""
        ...

    async def delete(self, key: str) -> bool:
        """Generic key-value delete (for Protocol compliance)."""
        ...

    async def initialize(self) -> None:
        """Initialize the reflexion store (create tables, indexes, etc.).

        Raises:
            RuntimeError: If initialization fails
        """
        ...

    async def save_learning(self, learning: ReflexionLearning) -> None:
        """Save a learning from agent reflexion.

        Args:
            learning: The reflexion learning to save

        Example:
            >>> learning = ReflexionLearning(
            ...     id="learn_123",
            ...     problem="Query timeout on large table",
            ...     solution="Use partition pruning",
            ...     feedback="Initial approach scanned full table",
            ...     success_score=0.85,
            ...     created_at=datetime.now(),
            ...     tags=["query", "performance"],
            ...     agent_domain="query"
            ... )
            >>> await store.save_learning(learning)
        """
        ...

    async def search_learnings(
        self,
        query: str,
        top_k: int = 5,
        agent_domain: str | None = None,
        min_score: float = 0.0,
    ) -> list[ReflexionLearning]:
        """Search for relevant learnings using semantic similarity.

        Args:
            query: Problem description to search for
            top_k: Maximum number of results
            agent_domain: Optional domain filter ("query", "job", etc.)
            min_score: Minimum success score threshold

        Returns:
            List of relevant learnings ordered by relevance

        Example:
            >>> learnings = await store.search_learnings(
            ...     "optimize slow queries",
            ...     top_k=3,
            ...     agent_domain="query",
            ...     min_score=0.7
            ... )
        """
        ...

    async def get_by_tags(
        self,
        tags: list[str],
        agent_domain: str | None = None,
    ) -> list[ReflexionLearning]:
        """Get learnings by tags.

        Args:
            tags: List of tags to filter by (AND logic)
            agent_domain: Optional domain filter

        Returns:
            List of learnings matching all tags

        Example:
            >>> learnings = await store.get_by_tags(
            ...     ["performance", "query"],
            ...     agent_domain="query"
            ... )
        """
        ...

    async def count(self, agent_domain: str | None = None) -> int:
        """Get count of stored learnings.

        Args:
            agent_domain: Optional domain filter

        Returns:
            Total learning count
        """
        ...


class SemanticCache(Protocol):
    """Protocol for semantic LLM response caching.

    Unlike traditional caching (exact key match), semantic caching:
    1. Embeds the query
    2. Searches for similar cached queries
    3. Returns cached response if similarity > threshold

    This dramatically reduces LLM costs for similar queries.

    Usage:
        >>> cache = SemanticCache(vector_store, embedding_client, ttl=300)
        >>> # Try to get from cache
        >>> cached = await cache.get("Show top 10 expensive jobs")
        >>> if cached is None:
        ...     response = await llm.generate(...)
        ...     await cache.set("Show top 10 expensive jobs", response)
    """

    async def get(
        self,
        query: str,
        similarity_threshold: float = 0.95,
    ) -> CacheEntry | None:
        """Get cached response for semantically similar query.

        Args:
            query: Query to look up
            similarity_threshold: Minimum similarity score (0.0 to 1.0)

        Returns:
            CacheEntry if similar cached query found, None otherwise

        Example:
            >>> entry = await cache.get("top 10 expensive jobs")
            >>> if entry and not entry.is_expired:
            ...     return entry.response
        """
        ...

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
        ...

    async def invalidate(
        self,
        pattern: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Invalidate cache entries.

        Args:
            pattern: Optional text pattern to match
            tags: Optional tags to filter by

        Returns:
            Number of entries invalidated

        Example:
            >>> # Invalidate all job-related caches
            >>> count = await cache.invalidate(tags=["job"])
        """
        ...

    async def cleanup_expired(self) -> int:
        """Remove expired cache entries.

        Returns:
            Number of entries removed
        """
        ...

    async def count(self) -> int:
        """Get total number of cache entries.

        Returns:
            Total cache entry count
        """
        ...
