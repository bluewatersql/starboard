"""
Foundation data models for shared infrastructure.

This module defines immutable data classes used across the foundation layer:
- Vector search results and records
- Reflexion learnings
- Cache entries
- RAG context models
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class VectorSearchResult:
    """Result from vector similarity search.

    Attributes:
        id: Unique identifier for the vector
        score: Similarity score (0.0 to 1.0, higher is more similar)
        metadata: Additional metadata stored with the vector
        content: Original text content

    Example:
        >>> result = VectorSearchResult(
        ...     id="vec_123",
        ...     score=0.95,
        ...     metadata={"source": "documentation"},
        ...     content="How to optimize Databricks clusters"
        ... )
    """

    id: str
    score: float
    metadata: dict[str, Any]
    content: str


@dataclass(frozen=True)
class VectorRecord:
    """Vector embedding with metadata for storage.

    Attributes:
        id: Unique identifier
        embedding: Dense vector representation (typically 1536 dims for OpenAI)
        metadata: Additional metadata (tags, source, timestamps, etc.)
        content: Original text content

    Example:
        >>> record = VectorRecord(
        ...     id="vec_123",
        ...     embedding=[0.1, 0.2, ...],  # 1536 dimensions
        ...     metadata={"source": "docs", "type": "guide"},
        ...     content="Cluster optimization guide"
        ... )
    """

    id: str
    embedding: list[float]
    metadata: dict[str, Any]
    content: str


@dataclass(frozen=True)
class ReflexionLearning:
    """A learning captured through reflexion.

    Reflexion is a self-improvement technique where agents:
    1. Evaluate their own responses
    2. Identify failures or suboptimal approaches
    3. Extract learnings for future use

    Attributes:
        id: Unique identifier
        problem: Description of the problem encountered
        solution: How it was solved or should be solved
        feedback: Agent's self-evaluation feedback
        success_score: Quality score (0.0 to 1.0)
        created_at: When the learning was captured
        tags: Categorization tags
        agent_domain: Which agent domain this applies to
        metadata: Additional context

    Example:
        >>> learning = ReflexionLearning(
        ...     id="learn_123",
        ...     problem="Query optimization for large tables",
        ...     solution="Use partitioning and limit scans",
        ...     feedback="Initial approach caused timeout",
        ...     success_score=0.85,
        ...     created_at=datetime.now(),
        ...     tags=["query", "optimization", "performance"],
        ...     agent_domain="query",
        ...     metadata={"table_size_gb": 1000}
        ... )
    """

    id: str
    problem: str
    solution: str
    feedback: str
    success_score: float
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = field(default_factory=list)
    agent_domain: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate reflexion learning."""
        if not 0.0 <= self.success_score <= 1.0:
            raise ValueError(
                f"success_score must be between 0 and 1, got {self.success_score}"
            )
        if not self.problem:
            raise ValueError("problem cannot be empty")
        if not self.solution:
            raise ValueError("solution cannot be empty")


@dataclass(frozen=True)
class CacheEntry:
    """Entry in semantic cache.

    Attributes:
        id: Unique cache key
        query: Original query text
        query_embedding: Embedding of the query
        response: Cached response
        created_at: Cache creation time
        ttl: Time-to-live in seconds
        metadata: Additional context (model, parameters, etc.)

    Example:
        >>> entry = CacheEntry(
        ...     id="cache_123",
        ...     query="Show me top 10 expensive jobs",
        ...     query_embedding=[0.1, 0.2, ...],
        ...     response={"jobs": [...]},
        ...     created_at=datetime.now(),
        ...     ttl=300,
        ...     metadata={"model": "gpt-4", "temperature": 0.4}
        ... )
    """

    id: str
    query: str
    query_embedding: list[float]
    response: Any
    created_at: datetime
    ttl: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        age_seconds = (datetime.now(UTC) - self.created_at).total_seconds()
        return age_seconds > self.ttl
