# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unity Catalog native state store (Phase 2 C2).

``UCStateStore`` satisfies :class:`starboard_core.ports.state_store.StateStore`
over the (previously orphaned) :class:`UCStorageAdapter` / ``UCRepository``
building blocks, persisting conversation snapshots as governed Delta rows.

Per D-2.6 this is scoped to **low-write, seconds-latency** durable state
(periodic conversation snapshots) — not high-concurrency per-turn chat, which
stays on Lakebase/Postgres.

The store also exposes ``get_user_store()`` / ``get_feedback_repo()`` capability
hooks so the container can obtain UC-native user/feedback stores without an
``isinstance`` ladder (native_simplification §1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_core.models.conversation import (
    Conversation,
    ConversationMetadata,
    Message,
)

from starboard.adapters.state.uc import _serde
from starboard.adapters.state.uc.tables import CONVERSATIONS
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.adapters.state.uc.feedback_repository import UCFeedbackRepository
    from starboard.adapters.state.uc.user_store import UCUserStore
    from starboard.infra.storage.uc_adapter import UCStorageAdapter

logger = get_logger(__name__)


def _conversation_to_row(conv: Conversation) -> dict[str, Any]:
    """Serialize a :class:`Conversation` into a UC ``conversations`` row."""
    return {
        "conversation_id": conv.id,
        "user_id": conv.user_id,
        "messages": _serde.dumps([m.to_dict() for m in conv.messages]),
        "metadata": _serde.dumps(conv.metadata),
        "title": conv.title,
        "tags": _serde.dumps(conv.tags),
        "archived": conv.archived,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
    }


def _row_to_conversation(row: dict[str, Any]) -> Conversation:
    """Deserialize a UC ``conversations`` row into a :class:`Conversation`."""
    messages = [Message.from_dict(m) for m in _serde.loads(row.get("messages"), [])]
    return Conversation(
        id=row["conversation_id"],
        user_id=row["user_id"],
        messages=messages,
        created_at=_serde.parse_dt(row["created_at"]),
        updated_at=_serde.parse_dt(row["updated_at"]),
        title=row.get("title"),
        tags=_serde.loads(row.get("tags"), []),
        archived=_serde.parse_bool(row.get("archived")),
        metadata=_serde.loads(row.get("metadata"), {}),
    )


class UCStateStore:
    """Conversation state persisted to a Unity Catalog Delta table.

    Args:
        adapter: A configured :class:`UCStorageAdapter` (built by the state
            factory over the auth resolver's ``WorkspaceClient``).
    """

    def __init__(self, adapter: UCStorageAdapter) -> None:
        self._adapter = adapter

    # -- lifecycle ---------------------------------------------------------
    async def connect(self) -> None:
        """Ensure catalog/schema/tables exist."""
        await self._adapter.initialize()

    async def close(self) -> None:
        """Release resources (SQL warehouse is stateless — no-op)."""

    # -- generic KV (Protocol compliance) ----------------------------------
    async def get(self, key: str) -> Any | None:
        """Generic get: resolves ``key`` as a conversation id."""
        return await self.get_conversation(key)

    async def set(self, key: str, value: Any) -> None:  # noqa: ARG002
        """Generic set is unsupported for UC state (use ``save_conversation``)."""
        logger.debug("uc_state_store_generic_set_ignored", key=key)

    async def delete(self, key: str) -> bool:
        """Generic delete: resolves ``key`` as a conversation id."""
        return await self.delete_conversation(key)

    # -- conversations -----------------------------------------------------
    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Retrieve a conversation by id."""
        row = await self._adapter.read_one(
            CONVERSATIONS, {"conversation_id": conversation_id}
        )
        if row is None:
            return None
        return _row_to_conversation(row)

    async def save_conversation(self, conversation: Conversation) -> None:
        """Persist a conversation (MERGE upsert on ``conversation_id``)."""
        await self._adapter.upsert(CONVERSATIONS, _conversation_to_row(conversation))

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation by id (always reports success — Delta has no count)."""
        await self._adapter.delete(CONVERSATIONS, {"conversation_id": conversation_id})
        return True

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationMetadata]:
        """List a user's non-archived conversations, most-recent first."""
        rows = await self._adapter.read(
            CONVERSATIONS,
            filters={"user_id": user_id},
            order_by="updated_at DESC",
            limit=limit + offset if limit else None,
        )
        convs = [_row_to_conversation(r) for r in rows]
        convs = [c for c in convs if not c.archived]
        page = convs[offset : offset + limit] if limit else convs[offset:]
        return [ConversationMetadata.from_conversation(c) for c in page]

    async def update_metadata(
        self,
        conversation_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update conversation metadata fields (title/tags/archived/metadata)."""
        conv = await self.get_conversation(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        for key, value in updates.items():
            if hasattr(conv, key):
                setattr(conv, key, value)
        await self.save_conversation(conv)

    # -- capability hooks (native_simplification §1) -----------------------
    def get_user_store(self) -> UCUserStore:
        """Return a UC-native user store sharing this store's adapter."""
        from starboard.adapters.state.uc.user_store import UCUserStore

        return UCUserStore(self._adapter)

    def get_feedback_repo(self) -> UCFeedbackRepository:
        """Return a UC-native feedback repository sharing this store's adapter."""
        from starboard.adapters.state.uc.feedback_repository import (
            UCFeedbackRepository,
        )

        return UCFeedbackRepository(self._adapter)
