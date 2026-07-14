# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""SessionManager for multi-turn CLI conversations."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiosqlite
from starboard_core.repositories.conversation import ConversationRepository
from starboard.bootstrap import SQLiteStateStore, get_logger

logger = get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class SessionInfo:
    """Metadata for a CLI session."""

    session_name: str
    conversation_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    turn_count: int
    last_message_preview: str | None


_CLI_SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS cli_sessions (
    session_name TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL DEFAULT 'cli_user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    turn_count INTEGER NOT NULL DEFAULT 0,
    last_message_preview TEXT
);
CREATE INDEX IF NOT EXISTS idx_cli_sessions_updated ON cli_sessions(updated_at DESC);
"""


class SessionManager:
    """
    Manages named CLI sessions mapping human-friendly names to conversation_ids.

    Wraps SQLiteStateStore and ConversationRepository, using a separate
    cli_sessions table for name→conversation_id mapping and metadata.
    Shares the same SQLite database file as the state store.

    Note:
        For db_path=":memory:", the SessionManager uses a separate in-memory
        database for cli_sessions (SQLite limitation). Use a file path for
        shared persistence.

    Example:
        >>> manager = SessionManager("~/.starboard/sessions.db")
        >>> await manager.connect()
        >>> info = await manager.get_or_create("my-session")
        >>> await manager.update_session_activity("my-session", "User asked about jobs")
        >>> await manager.close()
    """

    def __init__(self, db_path: str = "~/.starboard/sessions.db") -> None:
        """
        Initialize SessionManager.

        Args:
            db_path: Path to SQLite database file. Expanded via Path.expanduser().
                Does not connect yet.
        """
        self._db_path = str(Path(db_path).expanduser())
        self._state_store = SQLiteStateStore(self._db_path)
        self._conversation_repo = ConversationRepository(self._state_store)
        self._cli_conn: aiosqlite.Connection | None = None

    @property
    def state_store(self) -> SQLiteStateStore:
        """Return the underlying SQLiteStateStore."""
        return self._state_store

    @property
    def conversation_repo(self) -> ConversationRepository:
        """Return a ConversationRepository wrapping the state_store."""
        return self._conversation_repo

    def _get_cli_conn(self) -> aiosqlite.Connection:
        """Get the cli_sessions connection, raising if not connected."""
        if self._cli_conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._cli_conn

    async def connect(self) -> None:
        """
        Connect to SQLite, initialize state store, and create cli_sessions table.

        Raises:
            RuntimeError: If connection fails.
        """
        await self._state_store.connect()

        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._cli_conn = await aiosqlite.connect(self._db_path, timeout=30.0)
        await self._cli_conn.execute("PRAGMA journal_mode=WAL")
        await self._cli_conn.execute("PRAGMA foreign_keys=ON")
        await self._cli_conn.executescript(_CLI_SESSIONS_SCHEMA)
        await self._cli_conn.commit()

        logger.debug("session_manager_connected", db_path=self._db_path)

    async def close(self) -> None:
        """Close state store and cli_sessions connection."""
        if self._cli_conn:
            await self._cli_conn.close()
            self._cli_conn = None
        await self._state_store.close()
        logger.debug("session_manager_closed", db_path=self._db_path)

    async def get_or_create(
        self,
        session_name: str | None = None,
        user_id: str = "cli_user",
    ) -> SessionInfo:
        """
        Get existing session or create a new one.

        Args:
            session_name: Human-friendly name. If None, generates one like
                "session-{uuid4().hex[:8]}".
            user_id: User identifier (default "cli_user").

        Returns:
            SessionInfo for the session.

        Example:
            >>> info = await manager.get_or_create("my-session")
            >>> info = await manager.get_or_create()  # Auto-generated name
        """
        conn = self._get_cli_conn()

        if session_name is None:
            session_name = f"session-{uuid4().hex[:8]}"

        async with conn.execute(
            """
            SELECT session_name, conversation_id, user_id, created_at, updated_at,
                   turn_count, last_message_preview
            FROM cli_sessions
            WHERE session_name = ?
            """,
            (session_name,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is not None:
            return SessionInfo(
                session_name=str(row[0]),
                conversation_id=str(row[1]),
                user_id=str(row[2]),
                created_at=datetime.fromisoformat(str(row[3])),
                updated_at=datetime.fromisoformat(str(row[4])),
                turn_count=int(row[5]),
                last_message_preview=str(row[6]) if row[6] else None,
            )

        conversation_id = f"cli_session_{uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()

        await conn.execute(
            """
            INSERT INTO cli_sessions
                (session_name, conversation_id, user_id, created_at, updated_at,
                 turn_count, last_message_preview)
            VALUES (?, ?, ?, ?, ?, 0, NULL)
            """,
            (session_name, conversation_id, user_id, now, now),
        )
        await conn.commit()

        await self._conversation_repo.get_or_create(conversation_id, user_id)

        logger.debug(
            "session_created",
            session_name=session_name,
            conversation_id=conversation_id,
        )

        return SessionInfo(
            session_name=session_name,
            conversation_id=conversation_id,
            user_id=user_id,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
            turn_count=0,
            last_message_preview=None,
        )

    async def list_sessions(self) -> list[SessionInfo]:
        """
        List all sessions ordered by updated_at DESC.

        Returns:
            List of SessionInfo for all sessions.
        """
        conn = self._get_cli_conn()

        async with conn.execute(
            """
            SELECT session_name, conversation_id, user_id, created_at, updated_at,
                   turn_count, last_message_preview
            FROM cli_sessions
            ORDER BY updated_at DESC
            """
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            SessionInfo(
                session_name=str(r[0]),
                conversation_id=str(r[1]),
                user_id=str(r[2]),
                created_at=datetime.fromisoformat(str(r[3])),
                updated_at=datetime.fromisoformat(str(r[4])),
                turn_count=int(r[5]),
                last_message_preview=str(r[6]) if r[6] else None,
            )
            for r in rows
        ]

    async def delete_session(self, session_name: str) -> bool:
        """
        Delete session and its conversation data.

        Args:
            session_name: Name of the session to delete.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_cli_conn()

        async with conn.execute(
            "SELECT conversation_id FROM cli_sessions WHERE session_name = ?",
            (session_name,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return False

        conversation_id = str(row[0])
        await self._conversation_repo.delete(conversation_id)
        await conn.execute(
            "DELETE FROM cli_sessions WHERE session_name = ?", (session_name,)
        )
        await conn.commit()

        logger.debug("session_deleted", session_name=session_name)
        return True

    async def update_session_activity(
        self,
        session_name: str,
        last_message: str,
    ) -> None:
        """
        Update session activity: updated_at, turn_count, last_message_preview.

        Args:
            session_name: Name of the session.
            last_message: Last message content; truncated to 100 chars for preview.

        Raises:
            ValueError: If session not found.
        """
        conn = self._get_cli_conn()
        preview = last_message[:100]
        now = datetime.now(UTC).isoformat()

        cursor = await conn.execute(
            """
            UPDATE cli_sessions
            SET updated_at = ?, turn_count = turn_count + 1, last_message_preview = ?
            WHERE session_name = ?
            """,
            (now, preview, session_name),
        )
        await conn.commit()

        if cursor.rowcount == 0:
            raise ValueError(f"Session '{session_name}' not found")
