# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""SessionManager for multi-turn CLI conversations.

Phase 2 C3 (decision D-2.8): the thin CLI no longer needs a database driver.
Sessions persist as JSON files — a session index plus one transcript file per
conversation — with atomic writes. No ``aiosqlite`` / ``SQLiteStateStore`` on
the CLI hot path.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from starboard_core.ports.state_store import StateStore
from starboard_core.repositories.conversation import ConversationRepository

from starboard import get_logger
from starboard.cli.sessions.json_store import (
    INDEX_VERSION,
    JsonStateStore,
    atomic_write_json,
)

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


class SessionManager:
    """
    Manages named CLI sessions mapping human-friendly names to conversation_ids.

    Persistence is plain JSON on disk (decision D-2.8):

    * a session **index** at ``<sessions_dir>/index.json``::

        {"version": 1, "sessions": [
            {"session_name", "conversation_id", "user_id", "created_at",
             "updated_at", "turn_count", "last_message_preview"}, ...]}

    * a per-conversation **transcript** at ``<sessions_dir>/<conversation_id>.json``
      (owned by the ``ConversationRepository``/:class:`JsonStateStore`).

    The ``db_path`` constructor argument is kept for API compatibility: its
    ``.db`` suffix is dropped to derive the sessions directory, so the historical
    default ``~/.starboard/sessions.db`` maps to ``~/.starboard/sessions/``.
    ``":memory:"`` keeps everything in memory (no files written).

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
            db_path: Historical SQLite path; retained for API compatibility. The
                sessions directory is derived by stripping the ``.db`` suffix and
                expanding ``~``. ``":memory:"`` selects an in-memory store.
                Does not touch the filesystem yet.
        """
        self._db_path = db_path
        if db_path == ":memory:":
            self._base_dir: Path | None = None
        else:
            # "~/.starboard/sessions.db" -> "~/.starboard/sessions/"
            self._base_dir = Path(db_path).expanduser().with_suffix("")

        self._state_store = JsonStateStore(self._base_dir)
        self._conversation_repo = ConversationRepository(self._state_store)
        # In-memory session index keyed by session_name (mirrors index.json).
        self._sessions: dict[str, dict[str, Any]] = {}

    @property
    def state_store(self) -> StateStore:
        """Return the underlying StateStore (JSON-file backed)."""
        return self._state_store

    @property
    def conversation_repo(self) -> ConversationRepository:
        """Return a ConversationRepository wrapping the state_store."""
        return self._conversation_repo

    @property
    def _index_path(self) -> Path:
        assert self._base_dir is not None
        return self._base_dir / "index.json"

    async def connect(self) -> None:
        """
        Prepare the sessions directory and load the existing index (if any).
        """
        await self._state_store.connect()

        if self._base_dir is not None:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            self._load_index()

        logger.debug("session_manager_connected", db_path=self._db_path)

    async def close(self) -> None:
        """Release the underlying store (JSON store holds no open handles)."""
        await self._state_store.close()
        logger.debug("session_manager_closed", db_path=self._db_path)

    def _load_index(self) -> None:
        """Load the session index from disk into memory."""
        self._sessions = {}
        if self._base_dir is None or not self._index_path.exists():
            return
        try:
            doc = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("session_index_unreadable", path=str(self._index_path))
            return
        for entry in doc.get("sessions", []):
            self._sessions[entry["session_name"]] = dict(entry)

    def _write_index(self) -> None:
        """Persist the in-memory index atomically (no-op for in-memory mode)."""
        if self._base_dir is None:
            return
        atomic_write_json(
            self._index_path,
            {"version": INDEX_VERSION, "sessions": list(self._sessions.values())},
        )

    @staticmethod
    def _to_info(entry: dict[str, Any]) -> SessionInfo:
        return SessionInfo(
            session_name=str(entry["session_name"]),
            conversation_id=str(entry["conversation_id"]),
            user_id=str(entry["user_id"]),
            created_at=datetime.fromisoformat(entry["created_at"]),
            updated_at=datetime.fromisoformat(entry["updated_at"]),
            turn_count=int(entry["turn_count"]),
            last_message_preview=entry["last_message_preview"],
        )

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
        if session_name is None:
            session_name = f"session-{uuid4().hex[:8]}"

        existing = self._sessions.get(session_name)
        if existing is not None:
            return self._to_info(existing)

        conversation_id = f"cli_session_{uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()
        entry = {
            "session_name": session_name,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "created_at": now,
            "updated_at": now,
            "turn_count": 0,
            "last_message_preview": None,
        }

        # Register + persist the index first; roll back in-memory on failure so a
        # failed atomic write never leaves the index inconsistent with disk.
        self._sessions[session_name] = entry
        try:
            self._write_index()
        except Exception:
            del self._sessions[session_name]
            raise

        # Create the (empty) transcript for this conversation.
        await self._conversation_repo.get_or_create(conversation_id, user_id)

        logger.debug(
            "session_created",
            session_name=session_name,
            conversation_id=conversation_id,
        )
        return self._to_info(entry)

    async def list_sessions(self) -> list[SessionInfo]:
        """
        List all sessions ordered by updated_at DESC.

        Returns:
            List of SessionInfo for all sessions.
        """
        entries = sorted(
            self._sessions.values(),
            key=lambda e: e["updated_at"],
            reverse=True,
        )
        return [self._to_info(e) for e in entries]

    async def delete_session(self, session_name: str) -> bool:
        """
        Delete session and its conversation data.

        Args:
            session_name: Name of the session to delete.

        Returns:
            True if deleted, False if not found.
        """
        entry = self._sessions.get(session_name)
        if entry is None:
            return False

        await self._conversation_repo.delete(str(entry["conversation_id"]))
        del self._sessions[session_name]
        self._write_index()

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
        entry = self._sessions.get(session_name)
        if entry is None:
            raise ValueError(f"Session '{session_name}' not found")

        entry["updated_at"] = datetime.now(UTC).isoformat()
        entry["turn_count"] = int(entry["turn_count"]) + 1
        entry["last_message_preview"] = last_message[:100]
        self._write_index()
