# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
SQLite-based reflexion store for agent learnings.

Reflexion enables agents to improve by:
1. Evaluating their own responses
2. Extracting learnings from failures
3. Retrieving relevant past learnings

Example:
    >>> from starboard_server.infra.reflexion import SQLiteReflexionStore
    >>> from starboard_core.foundations.models import ReflexionLearning
    >>>
    >>> store = SQLiteReflexionStore("learnings.db", vector_store)
    >>> await store.initialize()
    >>>
    >>> # Save a learning
    >>> learning = ReflexionLearning(
    ...     id="learn_1",
    ...     problem="Query timeout on large table",
    ...     solution="Use partition pruning",
    ...     feedback="Initial approach scanned full table",
    ...     success_score=0.85,
    ...     tags=["query", "performance"]
    ... )
    >>> await store.save_learning(learning)
    >>>
    >>> # Search for relevant learnings
    >>> results = await store.search_learnings(
    ...     "optimize slow query",
    ...     top_k=5
    ... )
"""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime

import aiosqlite
from starboard_core.foundations.models import ReflexionLearning, VectorRecord
from starboard_core.foundations.protocols import VectorStore


class SQLiteReflexionStore:
    """SQLite-based store for agent reflexion learnings.

    This store combines:
    - SQLite for structured learning metadata
    - Vector store for semantic search

    Attributes:
        db_path: Path to SQLite database
        vector_store: Vector store for semantic search
        embedding_fn: Function to generate embeddings
    """

    def __init__(
        self,
        db_path: str,
        vector_store: VectorStore,
        embedding_fn: Callable[[str], Awaitable[list[float]]],
    ):
        """Initialize reflexion store.

        Args:
            db_path: Path to SQLite database
            vector_store: Vector store for semantic search
            embedding_fn: Async function to generate embeddings
        """
        self.db_path = db_path
        self.vector_store = vector_store
        self.embedding_fn = embedding_fn
        self._initialized = False

    async def initialize(self) -> None:
        """Create tables and initialize vector store.

        Raises:
            RuntimeError: If initialization fails
        """
        # Create learnings table
        async with aiosqlite.connect(
            self.db_path,
            timeout=30.0,  # 30 second timeout
        ) as db:
            # Enable WAL mode for better concurrent access
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=30000")  # 30s busy timeout

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS learnings (
                    id TEXT PRIMARY KEY,
                    problem TEXT NOT NULL,
                    solution TEXT NOT NULL,
                    feedback TEXT NOT NULL,
                    success_score REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    CHECK (success_score >= 0.0 AND success_score <= 1.0)
                )
            """
            )

            # Create indices for common queries
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learnings_success_score
                ON learnings(success_score)
            """
            )

            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learnings_created_at
                ON learnings(created_at)
            """
            )

            await db.commit()

        # Initialize vector store
        await self.vector_store.initialize()

        self._initialized = True

    async def save_learning(self, learning: ReflexionLearning) -> None:
        """Save a learning from agent reflexion.

        Args:
            learning: The reflexion learning to save

        Raises:
            RuntimeError: If store not initialized
            ValueError: If learning data is invalid

        Example:
            >>> learning = ReflexionLearning(
            ...     id="learn_123",
            ...     problem="Query timeout on large table",
            ...     solution="Use partition pruning",
            ...     feedback="Initial approach scanned full table",
            ...     success_score=0.85,
            ...     tags=["query", "performance"]
            ... )
            >>> await store.save_learning(learning)
        """
        if not self._initialized:
            await self.initialize()

        # Store in SQLite
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO learnings
                (id, problem, solution, feedback, success_score, created_at, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    learning.id,
                    learning.problem,
                    learning.solution,
                    learning.feedback,
                    learning.success_score,
                    learning.created_at.isoformat(),
                    json.dumps(learning.tags),
                ),
            )
            await db.commit()

        # Generate embedding for semantic search
        # Combine problem + solution for better search
        search_text = f"{learning.problem} {learning.solution}"
        embedding = await self._get_embedding(search_text)

        # Store in vector store
        vector = VectorRecord(
            id=learning.id,
            embedding=embedding,
            metadata={
                "problem": learning.problem,
                "solution": learning.solution,
                "success_score": learning.success_score,
                "tags": learning.tags,
                "created_at": learning.created_at.isoformat(),
            },
            content=search_text,
        )

        await self.vector_store.upsert([vector])

    async def search_learnings(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[ReflexionLearning]:
        """Search for relevant learnings using semantic similarity.

        Args:
            query: Problem description to search for
            top_k: Maximum number of results
            min_score: Minimum success score threshold

        Returns:
            List of relevant learnings ordered by relevance

        Example:
            >>> learnings = await store.search_learnings(
            ...     "optimize slow queries",
            ...     top_k=3,
            ...     min_score=0.7
            ... )
        """
        if not self._initialized:
            await self.initialize()

        # Generate query embedding
        query_embedding = await self._get_embedding(query)

        # Search vector store
        results = await self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k * 2,  # Get more, then filter
            filters=None,
        )

        # Fetch full learning data from SQLite
        learnings = []
        async with aiosqlite.connect(self.db_path) as db:
            for result in results:
                cursor = await db.execute(
                    """
                    SELECT id, problem, solution, feedback, success_score,
                           created_at, tags
                    FROM learnings
                    WHERE id = ? AND success_score >= ?
                """,
                    (result.id, min_score),
                )

                row = await cursor.fetchone()
                if row:
                    learning = ReflexionLearning(
                        id=row[0],
                        problem=row[1],
                        solution=row[2],
                        feedback=row[3],
                        success_score=row[4],
                        created_at=datetime.fromisoformat(row[5]),
                        tags=json.loads(row[6]),
                    )
                    learnings.append(learning)

                    if len(learnings) >= top_k:
                        break

        return learnings

    async def get_by_tags(
        self,
        tags: list[str],
    ) -> list[ReflexionLearning]:
        """Get learnings by tags.

        Args:
            tags: List of tags to filter by (AND logic)

        Returns:
            List of learnings matching all tags

        Example:
            >>> learnings = await store.get_by_tags(
            ...     ["performance", "query"]
            ... )
        """
        if not self._initialized:
            await self.initialize()

        if not tags:
            return []

        learnings = []
        async with aiosqlite.connect(self.db_path) as db:
            # Fetch all learnings and filter by tags in Python
            # (SQLite JSON support is limited without extensions)
            cursor = await db.execute(
                """
                SELECT id, problem, solution, feedback, success_score,
                       created_at, tags
                FROM learnings
            """
            )

            rows = await cursor.fetchall()
            for row in rows:
                learning_tags = set(json.loads(row[6]))
                if all(tag in learning_tags for tag in tags):
                    learning = ReflexionLearning(
                        id=row[0],
                        problem=row[1],
                        solution=row[2],
                        feedback=row[3],
                        success_score=row[4],
                        created_at=datetime.fromisoformat(row[5]),
                        tags=list(learning_tags),
                    )
                    learnings.append(learning)

        return learnings

    async def count(self) -> int:
        """Get count of stored learnings.

        Returns:
            Total learning count

        Raises:
            RuntimeError: If store not initialized
        """
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM learnings")
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def clear(self) -> None:
        """Clear all learnings from the store.

        Warning: This deletes all learning data!
        """
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM learnings")
            await db.commit()

        # Clear vector store
        if hasattr(self.vector_store, "clear"):
            await self.vector_store.clear()

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding for text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        return await self.embedding_fn(text)

    async def close(self) -> None:
        """Release resources (no-op for this store)."""

    async def connect(self) -> None:
        """Initialize connection (no-op for this store)."""

    async def delete(self, _key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, _key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, _key: str, _value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
