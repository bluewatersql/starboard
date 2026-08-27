# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for UCStateStore (Phase 2 C2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starboard_core.models.conversation import Conversation, Message
from starboard_core.ports.state_store import StateStore

from starboard.adapters.state.uc import UCStateStore
from starboard.adapters.state.uc.tables import UC_STATE_REGISTRY
from starboard.infra.storage.uc_adapter import (
    InvalidColumnError,
    UCStorageAdapter,
    UCStorageConfig,
)

pytestmark = pytest.mark.asyncio

_STATE_METHODS = (
    "connect",
    "close",
    "get",
    "set",
    "delete",
    "get_conversation",
    "save_conversation",
    "delete_conversation",
    "list_conversations",
    "update_metadata",
)


def _conversation(cid: str = "c1", uid: str = "u1") -> Conversation:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    return Conversation(
        id=cid,
        user_id=uid,
        messages=[
            Message(role="user", content="hello", timestamp=now),
            Message(role="assistant", content="hi there", timestamp=now),
        ],
        created_at=now,
        updated_at=now,
        title="greeting",
        tags=["t1", "t2"],
        metadata={"k": "v"},
    )


class TestProtocolCompliance:
    def test_satisfies_state_store_protocol(self, monkeypatch) -> None:
        from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

        store = UCStateStore(FakeUCAdapter())
        for method in _STATE_METHODS:
            assert callable(getattr(store, method)), f"missing {method}"
        # Structural Protocol assignability (mypy-equivalent at runtime).
        typed: StateStore = store
        assert typed is store


class TestRoundTrip:
    async def test_save_then_get_roundtrip(self) -> None:
        from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

        adapter = FakeUCAdapter()
        store = UCStateStore(adapter)
        conv = _conversation()

        await store.save_conversation(conv)

        # Upsert goes through the MERGE path with a serialized row.
        assert adapter.upserts, "save_conversation must upsert (MERGE)"
        table_id, row = adapter.upserts[0]
        assert table_id == "conversations"
        assert row["conversation_id"] == "c1"
        assert isinstance(row["messages"], str)  # JSON-serialized blob

        fetched = await store.get_conversation("c1")
        assert fetched is not None
        assert fetched.id == "c1"
        assert fetched.user_id == "u1"
        assert fetched.title == "greeting"
        assert fetched.tags == ["t1", "t2"]
        assert fetched.metadata == {"k": "v"}
        assert [m.content for m in fetched.messages] == ["hello", "hi there"]
        assert fetched.created_at == conv.created_at

    async def test_get_missing_returns_none(self) -> None:
        from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

        store = UCStateStore(FakeUCAdapter())
        assert await store.get_conversation("nope") is None

    async def test_list_conversations_recency_and_archived_filter(self) -> None:
        from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

        store = UCStateStore(FakeUCAdapter())
        old = _conversation("c1")
        old.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
        new = _conversation("c2")
        new.updated_at = datetime(2026, 2, 1, tzinfo=UTC)
        archived = _conversation("c3")
        archived.archived = True
        for c in (old, new, archived):
            await store.save_conversation(c)

        listed = await store.list_conversations("u1")
        ids = [m.id for m in listed]
        assert ids == ["c2", "c1"]  # DESC by updated_at, archived excluded

    async def test_update_metadata_persists(self) -> None:
        from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

        store = UCStateStore(FakeUCAdapter())
        await store.save_conversation(_conversation())
        await store.update_metadata("c1", {"title": "renamed"})
        fetched = await store.get_conversation("c1")
        assert fetched is not None
        assert fetched.title == "renamed"

    async def test_update_metadata_missing_raises(self) -> None:
        from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

        store = UCStateStore(FakeUCAdapter())
        with pytest.raises(ValueError):
            await store.update_metadata("ghost", {"title": "x"})

    async def test_delete_conversation(self) -> None:
        from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

        adapter = FakeUCAdapter()
        store = UCStateStore(adapter)
        await store.save_conversation(_conversation())
        assert await store.delete_conversation("c1") is True
        assert await store.get_conversation("c1") is None


class TestCapabilityHooks:
    def test_exposes_user_and_feedback_stores(self) -> None:
        from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

        from starboard.adapters.state.uc import UCFeedbackRepository, UCUserStore

        store = UCStateStore(FakeUCAdapter())
        assert isinstance(store.get_user_store(), UCUserStore)
        assert isinstance(store.get_feedback_repo(), UCFeedbackRepository)


class TestSqlInjectionDefensesHold:
    def test_invalid_column_rejected_on_conversations(self) -> None:
        # Real adapter over the UC state registry: identifier allowlist still bites.
        adapter = UCStorageAdapter(
            workspace_client=object(),
            config=UCStorageConfig(warehouse_id="wh"),
            registry=UC_STATE_REGISTRY,
        )
        with pytest.raises(InvalidColumnError):
            adapter._build_read_query(
                "conversations", None, {"user_id; DROP TABLE x": "u"}, None, None
            )
