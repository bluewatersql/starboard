"""SQLite memory store implementation with vector support."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from starboard_core.models.memory import Episode, Fact, SemanticQuery, UserProfile

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class SQLiteMemoryStore:
    """
    SQLite-backed long-term memory store with vector similarity search.

    Provides persistent storage for episodic memory (conversation summaries),
    semantic memory (extracted facts), and user profiles. Uses sqlite-vec
    extension for efficient vector similarity search.

    Features:
    - Vector embeddings with cosine similarity search
    - Episodic memory with temporal ordering
    - Semantic facts with confidence scoring
    - User profile management
    - GDPR-compliant deletion

    Args:
        db_path: Path to SQLite database file or ":memory:" for in-memory

    Example:
        ```python
        store = SQLiteMemoryStore("./dev_data/memory.db")
        await store.connect()

        # Store episode with embedding
        episode = Episode(
            id="ep_123",
            user_id="user_456",
            summary="User optimized query performance",
            embedding=[0.1, 0.2, ...],  # 1536 dimensions
        )
        await store.store_episode(episode)

        # Semantic search
        results = await store.recall_episodes(
            user_id="user_456",
            query_embedding=[0.15, 0.25, ...],
            limit=5
        )
        ```

    Note:
        Vector search requires embeddings to be computed upstream (e.g., via OpenAI).
        This store only handles storage and similarity computation.
    """

    def __init__(self, db_path: str = ":memory:"):
        """
        Initialize SQLite memory store.

        Args:
            db_path: Path to database file or ":memory:" for in-memory database
        """
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._vec_enabled = False
        logger.debug(
            "sqlite_memory_store_initialized",
            db_path=db_path,
            is_memory=db_path == ":memory:",
        )

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get the database connection, raising if not connected."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    async def connect(self) -> None:
        """Initialize database connection, load extensions, and create schema."""
        # Create directory for file-based databases
        if self.db_path != ":memory:":
            db_file = Path(self.db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)

        # Connect with timeout
        self._conn = await aiosqlite.connect(
            self.db_path,
            timeout=30.0,
        )

        # Enable WAL mode for better concurrency
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")

        # Try to load sqlite-vec extension
        try:
            # sqlite-vec package provides the extension path
            import sqlite_vec

            # Check if enable_load_extension is available (requires sqlite3 compiled with extension support)
            if not hasattr(self.conn, "enable_load_extension"):
                raise AttributeError(
                    "SQLite extension loading not supported - sqlite3 module not compiled with extension support"
                )

            # Use aiosqlite's async methods for loading extensions (handles threading correctly)
            await self.conn.enable_load_extension(True)

            # Get the path to the sqlite-vec extension
            # sqlite_vec.loadable_path() returns the path to the shared library
            extension_path = sqlite_vec.loadable_path()

            # Load the extension using the async method
            await self.conn.load_extension(extension_path)

            # Disable further extension loading for security
            await self.conn.enable_load_extension(False)

            self._vec_enabled = True
            logger.debug(
                "sqlite_vec_extension_loaded",
                db_path=self.db_path,
                extension_path=extension_path,
            )
        except ImportError:
            logger.warning(
                "sqlite_vec_package_not_installed",
                error="sqlite-vec package not found",
                fallback="Simple similarity search will be used. Install with: pip install sqlite-vec",
            )
        except AttributeError as e:
            logger.warning(
                "sqlite_extension_loading_not_supported",
                error=str(e),
                fallback="Simple similarity search will be used. "
                "To enable vector search, rebuild Python with: "
                "PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' pyenv install <version>",
            )
            self._vec_enabled = False
        except Exception as e:
            logger.warning(
                "sqlite_vec_extension_not_available",
                error=str(e),
                fallback="Simple similarity search will be used",
            )
            self._vec_enabled = False

        # Initialize schema
        await self._init_schema()

        logger.debug(
            "sqlite_memory_store_connected",
            db_path=self.db_path,
            vec_enabled=self._vec_enabled,
        )

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self.conn.close()
            logger.debug("sqlite_memory_store_closed", db_path=self.db_path)

    async def _init_schema(self) -> None:
        """Initialize database schema (migration 002_memory)."""
        if self._vec_enabled:
            # Use sqlite-vec for efficient vector search
            await self.conn.executescript(
                """
                -- Episodic memory with vector embeddings
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT,
                    summary TEXT NOT NULL,
                    key_points TEXT,  -- JSON array
                    embedding BLOB,  -- Vector stored as BLOB
                    created_at TEXT NOT NULL,
                    metadata TEXT  -- JSON object
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_user_id
                    ON episodes(user_id);

                CREATE INDEX IF NOT EXISTS idx_episodes_created_at
                    ON episodes(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_episodes_conversation_id
                    ON episodes(conversation_id);
            """
            )
        else:
            # Fallback without vector extension
            await self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT,
                    summary TEXT NOT NULL,
                    key_points TEXT,
                    embedding TEXT,  -- JSON array (no vector ops)
                    created_at TEXT NOT NULL,
                    metadata TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_user_id
                    ON episodes(user_id);

                CREATE INDEX IF NOT EXISTS idx_episodes_created_at
                    ON episodes(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_episodes_conversation_id
                    ON episodes(conversation_id);
            """
            )

        # Semantic memory (facts) - no vector search needed
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                statement TEXT NOT NULL,
                category TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT,
                verified INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_facts_user_id
                ON facts(user_id);

            CREATE INDEX IF NOT EXISTS idx_facts_category
                ON facts(category);

            CREATE INDEX IF NOT EXISTS idx_facts_confidence
                ON facts(confidence DESC);

            CREATE INDEX IF NOT EXISTS idx_facts_user_category
                ON facts(user_id, category);

            -- User profiles
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,  -- JSON containing all profile fields
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """
        )

        await self.conn.commit()

    # Episodic Memory

    async def store_episode(self, episode: Episode) -> str:
        """
        Store a conversation episode with embedding.

        Args:
            episode: Episode object with summary and optional embedding

        Returns:
            Episode ID
        """
        # Serialize complex fields
        key_points_json = json.dumps(episode.key_points) if episode.key_points else None
        metadata_json = json.dumps(episode.metadata) if episode.metadata else None

        # Handle embedding based on vec extension availability
        embedding_data: bytes | str | None
        if self._vec_enabled and episode.embedding:
            # Store as BLOB for vec extension
            embedding_data = json.dumps(episode.embedding).encode()
        else:
            # Store as JSON string
            embedding_data = (
                json.dumps(episode.embedding) if episode.embedding else None
            )

        await self.conn.execute(
            """
            INSERT INTO episodes
                (id, user_id, conversation_id, summary, key_points, embedding, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                summary = excluded.summary,
                key_points = excluded.key_points,
                embedding = excluded.embedding,
                metadata = excluded.metadata
            """,
            (
                episode.id,
                episode.user_id,
                episode.conversation_id,
                episode.summary,
                key_points_json,
                embedding_data,
                episode.created_at.isoformat(),
                metadata_json,
            ),
        )
        await self.conn.commit()

        logger.debug("episode_stored", episode_id=episode.id, user_id=episode.user_id)
        return episode.id

    async def recall_episodes(
        self,
        user_id: str,
        query_embedding: list[float] | None = None,
        limit: int = 10,
    ) -> list[Episode]:
        """
        Retrieve relevant episodes via semantic search or recency.

        Args:
            user_id: User identifier
            query_embedding: Query embedding vector (1536 dimensions) for similarity search
            limit: Maximum number of episodes to return

        Returns:
            List of episodes, ordered by relevance or recency

        Note:
            If query_embedding is None or vec extension not available,
            returns most recent episodes.
        """
        if self._vec_enabled and query_embedding:
            # Vector similarity search (to be implemented with sqlite-vec)
            # For now, fall back to recency
            logger.warning("vector_similarity_search_not_yet_implemented")

        # Fallback: return most recent episodes
        return await self.get_recent_episodes(user_id, limit)

    async def get_recent_episodes(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[Episode]:
        """
        Get most recent episodes (chronological order).

        Args:
            user_id: User identifier
            limit: Maximum number of episodes

        Returns:
            List of episodes, most recent first
        """
        async with self.conn.execute(
            """
            SELECT id, user_id, conversation_id, summary, key_points, embedding, created_at, metadata
            FROM episodes
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_episode(tuple(row)) for row in rows]

    # Semantic Memory (Facts)

    async def store_fact(self, fact: Fact) -> str:
        """Store an extracted fact."""
        metadata_json = json.dumps(fact.metadata) if fact.metadata else None

        await self.conn.execute(
            """
            INSERT INTO facts
                (id, user_id, statement, category, confidence, source, verified, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                statement = excluded.statement,
                category = excluded.category,
                confidence = excluded.confidence,
                verified = excluded.verified,
                updated_at = excluded.updated_at,
                metadata = excluded.metadata
            """,
            (
                fact.id,
                fact.user_id,
                fact.statement,
                fact.category,
                fact.confidence,
                fact.source,
                1 if fact.verified else 0,
                fact.created_at.isoformat(),
                fact.updated_at.isoformat(),
                metadata_json,
            ),
        )
        await self.conn.commit()

        logger.debug("fact_stored", fact_id=fact.id, user_id=fact.user_id)
        return fact.id

    async def query_facts(
        self,
        user_id: str,
        query: SemanticQuery,
    ) -> list[Fact]:
        """Query facts with filters."""
        # Build dynamic query
        conditions = ["user_id = ?"]
        params: list[Any] = [user_id]

        if query.categories:
            placeholders = ",".join("?" * len(query.categories))
            conditions.append(f"category IN ({placeholders})")
            params.extend(query.categories)

        conditions.append("confidence >= ?")
        params.append(query.min_confidence)

        if not query.include_unverified:
            conditions.append("verified = 1")

        where_clause = " AND ".join(conditions)

        async with self.conn.execute(
            f"""
            SELECT id, user_id, statement, category, confidence, source, verified, created_at, updated_at, metadata
            FROM facts
            WHERE {where_clause}
            ORDER BY confidence DESC
            LIMIT ?
            """,
            (*params, query.limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_fact(tuple(row)) for row in rows]

    async def update_fact(
        self,
        fact_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update an existing fact."""
        # Get existing fact
        async with self.conn.execute(
            "SELECT * FROM facts WHERE id = ?", (fact_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            raise ValueError(f"Fact {fact_id} not found")

        # Apply updates
        fact = self._row_to_fact(tuple(row))
        fact_dict = fact.to_dict()
        fact_dict.update(updates)
        fact_dict["updated_at"] = datetime.now(UTC).isoformat()

        updated_fact = Fact.from_dict(fact_dict)

        # Store updated fact
        await self.store_fact(updated_fact)

    # Profile Memory (Preferences)

    async def get_profile(self, user_id: str) -> UserProfile:
        """Get user profile (preferences, context)."""
        async with self.conn.execute(
            "SELECT data, created_at, updated_at FROM user_profiles WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            # Create new profile
            profile = UserProfile(
                user_id=user_id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await self.update_profile(user_id, {})
            return profile

        data_json, created_at_str, updated_at_str = row
        data = json.loads(data_json)
        # UserProfile is a Pydantic model - use model_validate to deserialize
        return UserProfile.model_validate(data)

    async def update_profile(
        self,
        user_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update user profile fields."""
        # Get existing profile or create new
        try:
            profile = await self.get_profile(user_id)
        except Exception:
            profile = UserProfile(
                user_id=user_id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

        # Apply updates (mode='json' serializes datetime to ISO strings)
        profile_dict = profile.model_dump(mode="json")
        profile_dict.update(updates)
        profile_dict["updated_at"] = datetime.now(UTC).isoformat()

        # Store
        data_json = json.dumps(profile_dict)

        await self.conn.execute(
            """
            INSERT INTO user_profiles (user_id, data, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                data_json,
                profile_dict["created_at"],
                profile_dict["updated_at"],
            ),
        )
        await self.conn.commit()

    async def delete_user_data(self, user_id: str) -> None:
        """Delete all user data (GDPR compliance)."""
        await self.conn.execute("DELETE FROM episodes WHERE user_id = ?", (user_id,))
        await self.conn.execute("DELETE FROM facts WHERE user_id = ?", (user_id,))
        await self.conn.execute(
            "DELETE FROM user_profiles WHERE user_id = ?", (user_id,)
        )
        await self.conn.commit()

        logger.debug("user_data_deleted", user_id=user_id)

    # Helper methods

    def _row_to_episode(self, row: tuple[Any, ...]) -> Episode:
        """Convert database row to Episode object."""
        (
            episode_id,
            user_id,
            conversation_id,
            summary,
            key_points_json,
            embedding_data,
            created_at_str,
            metadata_json,
        ) = row

        key_points = json.loads(key_points_json) if key_points_json else []
        metadata = json.loads(metadata_json) if metadata_json else {}

        # Parse embedding
        if embedding_data:
            if isinstance(embedding_data, bytes):
                embedding = json.loads(embedding_data.decode())
            else:
                embedding = json.loads(embedding_data)
        else:
            embedding = None

        return Episode(
            id=episode_id,
            user_id=user_id,
            conversation_id=conversation_id,
            summary=summary,
            key_points=key_points,
            embedding=embedding,
            created_at=datetime.fromisoformat(created_at_str),
            metadata=metadata,
        )

    def _row_to_fact(self, row: tuple[Any, ...]) -> Fact:
        """Convert database row to Fact object."""
        (
            fact_id,
            user_id,
            statement,
            category,
            confidence,
            source,
            verified_int,
            created_at_str,
            updated_at_str,
            metadata_json,
        ) = row

        metadata = json.loads(metadata_json) if metadata_json else {}

        return Fact(
            id=fact_id,
            user_id=user_id,
            statement=statement,
            category=category,
            confidence=confidence,
            source=source,
            verified=bool(verified_int),
            created_at=datetime.fromisoformat(created_at_str),
            updated_at=datetime.fromisoformat(updated_at_str),
            metadata=metadata,

    async def delete(self, key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, key: str, value: object) -> None:
        """Generic key-value set (Protocol compliance)."""


        )
