"""Postgres state store implementation."""

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg
from starboard_core.models.conversation import (
    Conversation,
    ConversationMetadata,
    Message,
)


class PostgresStateStore:
    """Postgres-backed conversation state store."""

    def __init__(self, connection_string: str):
        """
        Initialize Postgres state store.

        Args:
            connection_string: Postgres connection string (postgres://user:pass@host:port/db)
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

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Retrieve conversation by ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, data, created_at, updated_at, title, tags, archived
                FROM conversations
                WHERE id = $1
                """,
                conversation_id,
            )

            if row is None:
                return None

            # Deserialize messages from JSONB
            data = row["data"]
            messages = [Message.from_dict(m) for m in data.get("messages", [])]

            return Conversation(
                id=row["id"],
                user_id=row["user_id"],
                messages=messages,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                title=row["title"],
                tags=list(row["tags"]) if row["tags"] else [],
                archived=row["archived"],
                metadata=data.get("metadata", {}),
            )

    async def save_conversation(self, conversation: Conversation) -> None:
        """Persist conversation (create or update)."""
        async with self.pool.acquire() as conn:
            # Serialize messages to JSONB
            data = {
                "messages": [m.to_dict() for m in conversation.messages],
                "metadata": conversation.metadata,
            }

            await conn.execute(
                """
                INSERT INTO conversations
                    (id, user_id, data, created_at, updated_at, title, tags, archived)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE
                SET
                    data = $3,
                    updated_at = $5,
                    title = $6,
                    tags = $7,
                    archived = $8
                """,
                conversation.id,
                conversation.user_id,
                json.dumps(data),  # asyncpg wants string for jsonb
                conversation.created_at,
                conversation.updated_at,
                conversation.title,
                conversation.tags,
                conversation.archived,
            )

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete conversation."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM conversations WHERE id = $1",
                conversation_id,
            )
            # Result format: "DELETE N" where N is number of rows deleted
            deleted_count = int(result.split()[-1])
            return deleted_count > 0

    async def delete_all_conversations(self, user_id: str) -> int:
        """
        Delete all conversations for a user (batch operation).

        Much more efficient than deleting one-by-one.
        Used by "Clear All Conversations" feature.

        Args:
            user_id: User identifier

        Returns:
            Number of conversations deleted
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM conversations WHERE user_id = $1",
                user_id,
            )
            # Result format: "DELETE N" where N is number of rows deleted
            deleted_count = int(result.split()[-1])
            return deleted_count

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationMetadata]:
        """List conversations for a user (paginated)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, user_id, title, created_at, updated_at, tags, archived,
                    jsonb_array_length(data->'messages') as message_count,
                    data->'messages'->-1->>'content' as last_message_content
                FROM conversations
                WHERE user_id = $1 AND archived = false
                ORDER BY updated_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_id,
                limit,
                offset,
            )

            return [
                ConversationMetadata(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    message_count=row["message_count"],
                    last_message_preview=(
                        row["last_message_content"][:100]
                        if row["last_message_content"]
                        else None
                    ),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    tags=list(row["tags"]) if row["tags"] else [],
                    archived=row["archived"],
                )
                for row in rows
            ]

    async def update_metadata(
        self,
        conversation_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update conversation metadata (title, tags, etc.)."""
        # Build dynamic SET clause
        set_clauses: list[str] = []
        params: list[Any] = [conversation_id]
        param_idx = 2

        for key, value in updates.items():
            if key in ("title", "tags", "archived"):
                set_clauses.append(f"{key} = ${param_idx}")
                params.append(value)
                param_idx += 1

        if not set_clauses:
            return

        # Always update updated_at
        set_clauses.append(f"updated_at = ${param_idx}")
        params.append(datetime.now(UTC))

        query = f"""
            UPDATE conversations
            SET {", ".join(set_clauses)}
            WHERE id = $1
        """

        async with self.pool.acquire() as conn:
            await conn.execute(query, *params)
