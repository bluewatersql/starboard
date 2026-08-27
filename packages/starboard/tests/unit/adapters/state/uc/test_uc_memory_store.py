# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for UCMemoryStore (Phase 2 C2, D-2.6 recency-only)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starboard.adapters.state.uc import UCMemoryStore
from starboard_core.models.memory import Episode, Fact, SemanticQuery
from starboard_core.ports.memory_store import MemoryStore

pytestmark = pytest.mark.asyncio

_MEMORY_METHODS = (
    "connect",
    "close",
    "get",
    "set",
    "delete",
    "store_episode",
    "recall_episodes",
    "get_recent_episodes",
    "store_fact",
    "query_facts",
    "update_fact",
    "get_profile",
    "update_profile",
    "delete_user_data",
)


def _episode(eid: str, uid: str, when: datetime) -> Episode:
    return Episode(
        id=eid,
        user_id=uid,
        conversation_id="c1",
        summary=f"summary-{eid}",
        key_points=["a", "b"],
        embedding=[0.1, 0.2, 0.3],  # must NOT be persisted (recency-only)
        created_at=when,
    )


def _fake_store():
    from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

    return UCMemoryStore(FakeUCAdapter()), None


class TestProtocolCompliance:
    def test_satisfies_memory_store_protocol(self) -> None:
        store, _ = _fake_store()
        for method in _MEMORY_METHODS:
            assert callable(getattr(store, method)), f"missing {method}"
        typed: MemoryStore = store
        assert typed is store


class TestRecencyOnly:
    async def test_recall_episodes_is_recency_only_no_vector_call(
        self, monkeypatch
    ) -> None:
        store, _ = _fake_store()
        # Guard: recall must NOT touch any embedding/vector machinery. If it
        # did, it would need an embedder — assert it works with none present and
        # simply mirrors recency ordering.
        recalled_via_recency = {"hit": False}
        original = store.get_recent_episodes

        async def _spy(user_id, limit=10):
            recalled_via_recency["hit"] = True
            return await original(user_id, limit)

        monkeypatch.setattr(store, "get_recent_episodes", _spy)

        await store.store_episode(_episode("e1", "u1", datetime(2026, 1, 1, tzinfo=UTC)))
        await store.store_episode(_episode("e2", "u1", datetime(2026, 3, 1, tzinfo=UTC)))
        result = await store.recall_episodes("u1", query="anything", limit=10)

        assert recalled_via_recency["hit"], "recall_episodes must use recency path"
        assert [e.id for e in result] == ["e2", "e1"]  # DESC by created_at

    async def test_stored_episode_drops_embedding(self) -> None:
        store, _ = _fake_store()
        await store.store_episode(
            _episode("e1", "u1", datetime(2026, 1, 1, tzinfo=UTC))
        )
        episodes = await store.get_recent_episodes("u1")
        assert len(episodes) == 1
        assert episodes[0].embedding is None  # no vectors persisted

    async def test_get_recent_episodes_orders_desc(self) -> None:
        store, _ = _fake_store()
        await store.store_episode(_episode("e1", "u1", datetime(2026, 1, 1, tzinfo=UTC)))
        await store.store_episode(_episode("e2", "u1", datetime(2026, 2, 1, tzinfo=UTC)))
        await store.store_episode(_episode("e3", "u2", datetime(2026, 5, 1, tzinfo=UTC)))
        episodes = await store.get_recent_episodes("u1", limit=10)
        assert [e.id for e in episodes] == ["e2", "e1"]  # user-scoped + recency


class TestFacts:
    async def test_store_and_query_facts(self) -> None:
        store, _ = _fake_store()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        fact = Fact(
            id="f1",
            user_id="u1",
            statement="likes spark",
            category="pref",
            confidence=0.9,
            source="conversation:c1",
            verified=True,
            created_at=now,
            updated_at=now,
        )
        await store.store_fact(fact)
        results = await store.query_facts(
            "u1", SemanticQuery(text="", min_confidence=0.5)
        )
        assert len(results) == 1
        assert results[0].statement == "likes spark"
