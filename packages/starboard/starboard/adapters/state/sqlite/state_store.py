# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""SQLite state store implementation."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from starboard_core.models.conversation import Conversation, ConversationMetadata

from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


class SQLiteStateStore:
    """
    SQLite-backed conversation state store for development and testing.

    Provides persistent storage of conversation state with full async support.
    Suitable for local development and single-instance deployments.

    Features:
    - File-based persistence (or :memory: for tests)
    - WAL mode for better concurrency
    - Automatic schema initialization
    - PostgreSQL-compatible schema for easy migration
    - JSON support for flexible metadata

    Args:
        db_path: Path to SQLite database file or ":memory:" for in-memory

    Example:
        ```python
        # Development with persistence
        store = SQLiteStateStore("./dev_data/starboard.db")
        await store.connect()

        # Testing with isolation
        store = SQLiteStateStore(":memory:")
        await store.connect()

        # Use like any other state store
        await store.save_conversation(conversation)
        conv = await store.get_conversation(conv_id)
        ```
    """

    def __init__(self, db_path: str = ":memory:"):
        """
        Initialize SQLite state store.

        Args:
            db_path: Path to database file or ":memory:" for in-memory database
        """
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        logger.debug(
            "sqlite_state_store_initialized",
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
        """
        Initialize database connection and schema.

        Creates database file (if not :memory:) and applies schema migrations.
        """
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

        # Enable foreign keys
        await self.conn.execute("PRAGMA foreign_keys=ON")

        # Initialize schema
        await self._init_schema()

        logger.debug(
            "sqlite_state_store_connected",
            db_path=self.db_path,
        )

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self.conn.close()
            logger.debug("sqlite_state_store_closed", db_path=self.db_path)

    async def _init_schema(self) -> None:
        """Initialize database schema (includes 006_user_authentication)."""
        await self.conn.executescript(
            """
            -- ========================================================================
            -- Migration 006: User Authentication Tables
            -- ========================================================================

            -- Users table
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                external_id TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'databricks',
                username TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT,
                login_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                metadata TEXT  -- JSON string
            );

            -- Unique indexes for users
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_provider_external
                ON users(provider, external_id);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
                ON users(username);

            CREATE INDEX IF NOT EXISTS idx_users_status
                ON users(status);

            CREATE INDEX IF NOT EXISTS idx_users_last_login
                ON users(last_login DESC);

            -- User sessions table
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                last_activity TEXT NOT NULL,
                source TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,  -- Boolean as integer
                context TEXT,  -- JSON string
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            -- Indexes for user sessions
            CREATE INDEX IF NOT EXISTS idx_sessions_user_active
                ON user_sessions(user_id, is_active);

            CREATE INDEX IF NOT EXISTS idx_sessions_last_activity
                ON user_sessions(last_activity);

            CREATE INDEX IF NOT EXISTS idx_sessions_source
                ON user_sessions(source);

            -- ========================================================================
            -- Existing Tables: Conversations and Feedback
            -- ========================================================================

            -- Conversations table
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                data TEXT NOT NULL,  -- JSON string containing messages and metadata
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                title TEXT,
                tags TEXT,  -- JSON array as string
                archived INTEGER DEFAULT 0  -- Boolean as integer (0/1)
            );

            -- Indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_conversations_user_id
                ON conversations(user_id);

            CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
                ON conversations(updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
                ON conversations(user_id, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_conversations_archived
                ON conversations(archived, user_id, updated_at DESC);

            -- User feedback table (Pattern 4: Feedback Collection)
            CREATE TABLE IF NOT EXISTS user_feedback (
                feedback_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                rating TEXT NOT NULL CHECK (rating IN ('positive', 'negative')),
                categories TEXT,  -- JSON array as string
                comment TEXT,
                context_snapshot TEXT NOT NULL DEFAULT '{}',  -- JSON string
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            -- Indexes for user feedback
            CREATE INDEX IF NOT EXISTS idx_feedback_conversation
                ON user_feedback(conversation_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_feedback_message
                ON user_feedback(message_id);

            CREATE INDEX IF NOT EXISTS idx_feedback_agent
                ON user_feedback(agent_name, rating, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_feedback_user
                ON user_feedback(user_id, created_at DESC);

            -- Partial index for negative feedback (for analysis)
            CREATE INDEX IF NOT EXISTS idx_feedback_negative
                ON user_feedback(agent_name, created_at DESC)
                WHERE rating = 'negative';
        """
        )
        await self.conn.commit()

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """
        Retrieve conversation by ID.

        Args:
            conversation_id: Unique conversation identifier

        Returns:
            Conversation object or None if not found
        """
        async with self.conn.execute(
            """
            SELECT id, user_id, data, created_at, updated_at, title, tags, archived
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        return self._row_to_conversation(tuple(row))

    async def save_conversation(self, conversation: Conversation) -> None:
        """
        Persist conversation (create or update).

        Args:
            conversation: Conversation object to save
        """
        # Serialize conversation data
        data_json = json.dumps(conversation.to_dict())
        tags_json = json.dumps(conversation.tags) if conversation.tags else None

        await self.conn.execute(
            """
            INSERT INTO conversations
                (id, user_id, data, created_at, updated_at, title, tags, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                user_id = excluded.user_id,
                data = excluded.data,
                updated_at = excluded.updated_at,
                title = excluded.title,
                tags = excluded.tags,
                archived = excluded.archived
            """,
            (
                conversation.id,
                conversation.user_id,
                data_json,
                conversation.created_at.isoformat(),
                conversation.updated_at.isoformat(),
                conversation.title,
                tags_json,
                1 if conversation.archived else 0,
            ),
        )
        await self.conn.commit()

        logger.debug(
            "conversation_saved",
            conversation_id=conversation.id,
            user_id=conversation.user_id,
        )

    async def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete conversation.

        Args:
            conversation_id: Unique conversation identifier

        Returns:
            True if deleted, False if not found
        """
        cursor = await self.conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        await self.conn.commit()

        deleted = cursor.rowcount > 0

        if deleted:
            logger.debug("conversation_deleted", conversation_id=conversation_id)

        return deleted

    async def delete_all_conversations(self, user_id: str) -> int:
        """
        Delete all conversations for a user (batch operation).

        Much more efficient than deleting one-by-one.
        Used by "Clear All Conversations" feature.

        Args:
            user_id: User identifier

        Returns:
            Number of conversations deleted

        Example:
            >>> count = await store.delete_all_conversations("user123")
            >>> print(f"Deleted {count} conversations")
            Deleted 42 conversations
        """
        cursor = await self.conn.execute(
            "DELETE FROM conversations WHERE user_id = ?",
            (user_id,),
        )
        await self.conn.commit()

        count = cursor.rowcount

        logger.debug(
            "all_conversations_deleted_db",
            user_id=user_id,
            count=count,
        )

        return count

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationMetadata]:
        """
        List conversations for a user (paginated).

        Args:
            user_id: User identifier
            limit: Maximum number of results (default 50)
            offset: Number of results to skip (default 0)

        Returns:
            List of conversation metadata objects
        """
        async with self.conn.execute(
            """
            SELECT id, user_id, data, created_at, updated_at, title, tags, archived
            FROM conversations
            WHERE user_id = ? AND archived = 0
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()

        conversations = [self._row_to_conversation(tuple(row)) for row in rows]
        return [ConversationMetadata.from_conversation(c) for c in conversations]

    async def update_metadata(
        self,
        conversation_id: str,
        updates: dict[str, Any],
    ) -> None:
        """
        Update conversation metadata (title, tags, etc.).

        Args:
            conversation_id: Unique conversation identifier
            updates: Dictionary of fields to update

        Raises:
            ValueError: If conversation not found
        """
        # Get existing conversation
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Apply updates
        for key, value in updates.items():
            if hasattr(conversation, key):
                setattr(conversation, key, value)

        # Update timestamp
        conversation.updated_at = datetime.now(UTC)

        # Save updated conversation
        await self.save_conversation(conversation)

        logger.debug(
            "conversation_metadata_updated",
            conversation_id=conversation_id,
            updated_fields=list(updates.keys()),
        )

    def _row_to_conversation(self, row: tuple) -> Conversation:
        """
        Convert database row to Conversation object.

        Args:
            row: Database row tuple

        Returns:
            Conversation object
        """
        (
            conv_id,
            user_id,
            data_json,
            created_at_str,
            updated_at_str,
            title,
            tags_json,
            archived_int,
        ) = row

        # Parse JSON data
        data = json.loads(data_json)

        # Reconstruct conversation from stored data
        conversation = Conversation.from_dict(data)

        # Override with metadata fields (these may have been updated separately)
        conversation.title = title
        conversation.tags = json.loads(tags_json) if tags_json else []
        conversation.archived = bool(archived_int)

        return conversation

    async def delete(self, _key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, _key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, _key: str, _value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
