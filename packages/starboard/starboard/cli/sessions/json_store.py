# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""JSON-file persistence for CLI sessions (no external DB driver).

This module provides the storage primitives used by :class:`SessionManager`:

* :func:`atomic_write_json` — crash-safe write (temp file in the same directory
  followed by :func:`os.replace`); on any failure the temp file is removed and
  the destination is left untouched.
* :class:`JsonStateStore` — a :class:`starboard_core.ports.state_store.StateStore`
  implementation that persists each conversation transcript as
  ``<base_dir>/<conversation_id>.json``. Passing ``base_dir=None`` keeps
  everything in memory (used for the ``":memory:"`` CLI mode and tests).

No database-driver dependency — this keeps the thin CLI off any SQL hot path
(Phase 2 C3, decision D-2.8).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starboard_core.models.conversation import Conversation, ConversationMetadata

# Schema versions embedded in each JSON document so a future migration can
# detect the on-disk format without guessing.
INDEX_VERSION = 1
TRANSCRIPT_VERSION = 1


def atomic_write_json(path: Path, data: Any) -> None:
    """Atomically write ``data`` as JSON to ``path``.

    Writes to a uniquely named temp file in the destination directory, fsyncs
    it, then :func:`os.replace`s it into place (atomic on the same filesystem).
    If anything fails — including the replace — the temp file is cleaned up and
    the original ``path`` is left intact, so a crash mid-write never leaves a
    partial or truncated file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # Never leave a stray temp file behind (covers replace failures too).
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


class JsonStateStore:
    """File-backed conversation store satisfying the ``StateStore`` Protocol.

    Each conversation is a single JSON document::

        {"version": 1, "conversation": <Conversation.to_dict()>}

    stored at ``<base_dir>/<conversation_id>.json``. When ``base_dir`` is
    ``None`` the store is purely in-memory (the ``":memory:"`` CLI mode).
    """

    def __init__(self, base_dir: Path | None) -> None:
        """Initialize the store.

        Args:
            base_dir: Directory for transcript files, or ``None`` for in-memory.
        """
        self._base_dir = base_dir
        self._memory: dict[str, Conversation] = {}

    async def connect(self) -> None:
        """Create the backing directory (no-op for in-memory)."""
        if self._base_dir is not None:
            self._base_dir.mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        """Release resources (nothing to release for a file/memory store)."""

    def _transcript_path(self, conversation_id: str) -> Path:
        assert self._base_dir is not None
        return self._base_dir / f"{conversation_id}.json"

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Retrieve a conversation by ID, or ``None`` if not found."""
        if self._base_dir is None:
            return self._memory.get(conversation_id)
        path = self._transcript_path(conversation_id)
        if not path.exists():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
        return Conversation.from_dict(doc["conversation"])

    async def save_conversation(self, conversation: Conversation) -> None:
        """Persist a conversation (create or overwrite)."""
        if self._base_dir is None:
            self._memory[conversation.id] = conversation
            return
        atomic_write_json(
            self._transcript_path(conversation.id),
            {"version": TRANSCRIPT_VERSION, "conversation": conversation.to_dict()},
        )

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation transcript. Returns ``True`` if it existed."""
        if self._base_dir is None:
            return self._memory.pop(conversation_id, None) is not None
        path = self._transcript_path(conversation_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationMetadata]:
        """List a user's conversations (most-recent first, paginated)."""
        conversations: list[Conversation] = []
        if self._base_dir is None:
            conversations = [
                c
                for c in self._memory.values()
                if c.user_id == user_id and not c.archived
            ]
        else:
            for path in self._base_dir.glob("*.json"):
                if path.name == "index.json":
                    continue
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    conv = Conversation.from_dict(doc["conversation"])
                except (json.JSONDecodeError, KeyError, OSError):
                    continue
                if conv.user_id == user_id and not conv.archived:
                    conversations.append(conv)

        conversations.sort(key=lambda c: c.updated_at, reverse=True)
        page = conversations[offset : offset + limit]
        return [ConversationMetadata.from_conversation(c) for c in page]

    async def update_metadata(
        self,
        conversation_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Apply metadata updates (title, tags, ...) to a conversation."""
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        for key, value in updates.items():
            if hasattr(conversation, key):
                setattr(conversation, key, value)
        conversation.updated_at = datetime.now(UTC)
        await self.save_conversation(conversation)

    # -- generic key/value methods (Protocol compliance, unused by the CLI) --
    async def get(self, _key: str) -> Any | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, _key: str, _value: Any) -> None:
        """Generic key-value set (Protocol compliance)."""

    async def delete(self, _key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False
