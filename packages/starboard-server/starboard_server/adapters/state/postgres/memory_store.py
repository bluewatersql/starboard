"""Postgres memory store implementation with pgvector support."""

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg
from starboard_core.models.memory import Episode, Fact, SemanticQuery, UserProfile


class PostgresMemoryStore:
    """Postgres-backed long-term memory store with vector search."""

    def __init__(self, connection_string: str):
        """
        Initialize Postgres memory store.

        Args:
            connection_string: Postgres connection string

        Note:
            Requires pgvector extension for vector similarity search
        """
        self._connection_string = connection_string
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        """Get the connection pool, raising if not connected."""
        if self._pool is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._pool

    async def connect(self) -> None:
        """Initialize connection pool."""
        self._pool = await asyncpg.create_pool(
            self._connection_string,
            min_size=5,
            max_size=20,
            command_timeout=60,
        )

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()

    # Episodic Memory

    async def store_episode(self, episode: Episode) -> str:
        """Store a conversation episode."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO episodes
                    (id, user_id, conversation_id, summary, key_points, embedding, created_at, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE
                SET
                    summary = $4,
                    key_points = $5,
                    embedding = $6,
                    metadata = $8
                """,
                episode.id,
                episode.user_id,
                episode.conversation_id,
                episode.summary,
                episode.key_points,
                episode.embedding,  # pgvector handles list[float] → vector conversion
                episode.created_at,
                json.dumps(episode.metadata),
            )
        return episode.id

    async def recall_episodes(
        self,
        user_id: str,
        query: str,  # noqa: ARG002 (query embedding happens upstream)
        limit: int = 10,
    ) -> list[Episode]:
        """
        Retrieve relevant episodes via semantic search.

        Note:
            For full semantic search, caller should provide query embedding.
            This implementation returns most recent episodes as fallback.
            Phase 3 will add embedding service integration.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, conversation_id, summary, key_points, embedding, created_at, metadata
                FROM episodes
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )

            return [self._row_to_episode(row) for row in rows]

    async def recall_episodes_by_embedding(
        self,
        user_id: str,
        query_embedding: list[float],
        limit: int = 10,
    ) -> list[Episode]:
        """
        Retrieve relevant episodes via vector similarity search.

        Args:
            user_id: User identifier
            query_embedding: Query vector (1536 dimensions for OpenAI ada-002)
            limit: Maximum number of results

        Returns:
            List of episodes ranked by cosine similarity
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, conversation_id, summary, key_points, embedding, created_at, metadata,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM episodes
                WHERE user_id = $2 AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                query_embedding,
                user_id,
                limit,
            )

            return [self._row_to_episode(row) for row in rows]

    async def get_recent_episodes(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[Episode]:
        """Get most recent episodes (chronological)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, conversation_id, summary, key_points, embedding, created_at, metadata
                FROM episodes
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )

            return [self._row_to_episode(row) for row in rows]

    def _row_to_episode(self, row: asyncpg.Record) -> Episode:
        """Convert database row to Episode."""
        return Episode(
            id=row["id"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            summary=row["summary"],
            key_points=list(row["key_points"]) if row["key_points"] else [],
            embedding=list(row["embedding"]) if row["embedding"] else None,
            created_at=row["created_at"],
            metadata=row["metadata"] if isinstance(row["metadata"], dict) else {},
        )

    # Semantic Memory (Facts)

    async def store_fact(self, fact: Fact) -> str:
        """Store an extracted fact."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO facts
                    (id, user_id, statement, category, confidence, source, verified, created_at, updated_at, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (id) DO UPDATE
                SET
                    statement = $3,
                    category = $4,
                    confidence = $5,
                    source = $6,
                    verified = $7,
                    updated_at = $9,
                    metadata = $10
                """,
                fact.id,
                fact.user_id,
                fact.statement,
                fact.category,
                fact.confidence,
                fact.source,
                fact.verified,
                fact.created_at,
                fact.updated_at,
                json.dumps(fact.metadata),
            )
        return fact.id

    async def query_facts(
        self,
        user_id: str,
        query: SemanticQuery,
    ) -> list[Fact]:
        """Query facts with filters."""
        # Build WHERE clause dynamically
        where_clauses = ["user_id = $1"]
        params: list[Any] = [user_id]
        param_idx = 2

        if query.categories:
            where_clauses.append(f"category = ANY(${param_idx})")
            params.append(query.categories)
            param_idx += 1

        where_clauses.append(f"confidence >= ${param_idx}")
        params.append(query.min_confidence)
        param_idx += 1

        if not query.include_unverified:
            where_clauses.append("verified = true")

        # Add limit
        params.append(query.limit)
        limit_param = f"${param_idx}"

        where_sql = " AND ".join(where_clauses)
        sql = f"""
            SELECT id, user_id, statement, category, confidence, source, verified, created_at, updated_at, metadata
            FROM facts
            WHERE {where_sql}
            ORDER BY confidence DESC
            LIMIT {limit_param}
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

            return [self._row_to_fact(row) for row in rows]

    def _row_to_fact(self, row: asyncpg.Record) -> Fact:
        """Convert database row to Fact."""
        return Fact(
            id=row["id"],
            user_id=row["user_id"],
            statement=row["statement"],
            category=row["category"],
            confidence=row["confidence"],
            source=row["source"],
            verified=row["verified"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=row["metadata"] if isinstance(row["metadata"], dict) else {},
        )

    async def update_fact(
        self,
        fact_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update an existing fact."""
        # Build dynamic SET clause
        set_clauses: list[str] = []
        params: list[Any] = [fact_id]
        param_idx = 2

        for key, value in updates.items():
            if key in ("statement", "category", "confidence", "source", "verified"):
                set_clauses.append(f"{key} = ${param_idx}")
                params.append(value)
                param_idx += 1

        if not set_clauses:
            return

        # Always update updated_at
        set_clauses.append(f"updated_at = ${param_idx}")
        params.append(datetime.now(UTC))

        query = f"""
            UPDATE facts
            SET {", ".join(set_clauses)}
            WHERE id = $1
        """

        async with self.pool.acquire() as conn:
            await conn.execute(query, *params)

    # Profile Memory (Preferences)

    async def get_profile(self, user_id: str) -> UserProfile:
        """Get user profile (preferences, context)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_id, data, created_at, updated_at
                FROM profiles
                WHERE user_id = $1
                """,
                user_id,
            )

            if row is None:
                # Create empty profile for new users
                now = datetime.now(UTC)
                profile = UserProfile(
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )

                # Store empty profile
                await conn.execute(
                    """
                    INSERT INTO profiles (user_id, data, created_at, updated_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    user_id,
                    json.dumps(
                        {
                            "job_preferences": {},
                            "technical_context": {},
                            "communication_preferences": {},
                            "custom_fields": {},
                        }
                    ),
                    now,
                    now,
                )

                return profile

            # Deserialize profile data
            data = row["data"]
            return UserProfile(
                user_id=row["user_id"],
                job_preferences=data.get("job_preferences", {}),
                technical_context=data.get("technical_context", {}),
                communication_preferences=data.get("communication_preferences", {}),
                custom_fields=data.get("custom_fields", {}),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def update_profile(
        self,
        user_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update user profile fields."""
        # Get current profile
        profile = await self.get_profile(user_id)

        # Merge updates
        data = {
            "job_preferences": profile.job_preferences,
            "technical_context": profile.technical_context,
            "communication_preferences": profile.communication_preferences,
            "custom_fields": profile.custom_fields,
        }

        for key, value in updates.items():
            if key in data:
                data[key] = value

        # Save updated profile
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE profiles
                SET data = $1, updated_at = $2
                WHERE user_id = $3
                """,
                json.dumps(data),
                datetime.now(UTC),
                user_id,
            )

    async def delete_user_data(self, user_id: str) -> None:
        """Delete all user data (GDPR compliance)."""
        async with (
            self.pool.acquire() as conn,
            conn.transaction(),
        ):
            await conn.execute("DELETE FROM episodes WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM facts WHERE user_id = $1", user_id)

            await conn.execute("DELETE FROM profiles WHERE user_id = $1", user_id)

    async def delete(self, key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, key: str, value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
