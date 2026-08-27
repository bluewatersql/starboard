# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unity Catalog native memory store (Phase 2 C2, D-2.6).

``UCMemoryStore`` satisfies :class:`starboard_core.ports.memory_store.MemoryStore`
over the UC Delta tables. It is **recency-only**: episodes and facts are queried
chronologically with no embedding/vector round-trip. Semantic recall
(``recall_episodes`` with true ANN) stays behind ``starboard[vectorsearch]`` — by
default ``recall_episodes`` transparently falls back to recency ordering, so the
store is fully functional with no vector dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from starboard_core.models.memory import Episode, Fact, SemanticQuery, UserProfile

from starboard.adapters.state.uc import _serde
from starboard.adapters.state.uc.tables import (
    MEMORY_EPISODES,
    MEMORY_FACTS,
    USER_PROFILES,
)
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.infra.storage.uc_adapter import UCStorageAdapter

logger = get_logger(__name__)


def _episode_to_row(ep: Episode) -> dict[str, Any]:
    """Serialize an :class:`Episode` (dropping any embedding — recency-only)."""
    return {
        "id": ep.id,
        "user_id": ep.user_id,
        "conversation_id": ep.conversation_id,
        "summary": ep.summary,
        "key_points": _serde.dumps(ep.key_points),
        "created_at": ep.created_at,
        "metadata": _serde.dumps(ep.metadata),
    }


def _row_to_episode(row: dict[str, Any]) -> Episode:
    return Episode(
        id=row["id"],
        user_id=row["user_id"],
        conversation_id=row.get("conversation_id"),
        summary=row["summary"],
        key_points=_serde.loads(row.get("key_points"), []),
        embedding=None,  # recency-only store: no vectors persisted
        created_at=_serde.parse_dt(row["created_at"]),
        metadata=_serde.loads(row.get("metadata"), {}),
    )


def _fact_to_row(fact: Fact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "user_id": fact.user_id,
        "statement": fact.statement,
        "category": fact.category,
        "confidence": fact.confidence,
        "source": fact.source,
        "verified": fact.verified,
        "created_at": fact.created_at,
        "updated_at": fact.updated_at,
        "metadata": _serde.dumps(fact.metadata),
    }


def _row_to_fact(row: dict[str, Any]) -> Fact:
    return Fact(
        id=row["id"],
        user_id=row["user_id"],
        statement=row["statement"],
        category=row["category"],
        confidence=_serde.parse_float(row.get("confidence"), 1.0),
        source=row.get("source"),
        verified=_serde.parse_bool(row.get("verified")),
        created_at=_serde.parse_dt(row["created_at"]),
        updated_at=_serde.parse_dt(row["updated_at"]),
        metadata=_serde.loads(row.get("metadata"), {}),
    )


class UCMemoryStore:
    """Recency-only long-term memory persisted to Unity Catalog Delta tables.

    Args:
        adapter: A configured :class:`UCStorageAdapter`.
    """

    def __init__(self, adapter: UCStorageAdapter) -> None:
        self._adapter = adapter

    # -- lifecycle ---------------------------------------------------------
    async def connect(self) -> None:
        """Ensure catalog/schema/tables exist."""
        await self._adapter.initialize()

    async def close(self) -> None:
        """Release resources (no-op)."""

    # -- generic KV (Protocol compliance) ----------------------------------
    async def get(self, _key: str) -> Any | None:
        return None

    async def set(self, _key: str, _value: Any) -> None:
        return None

    async def delete(self, _key: str) -> bool:
        return False

    # -- episodic memory (recency-only) ------------------------------------
    async def store_episode(self, episode: Episode) -> str:
        """Store an episode (upsert on ``id``)."""
        await self._adapter.upsert(MEMORY_EPISODES, _episode_to_row(episode))
        return episode.id

    async def recall_episodes(
        self,
        user_id: str,
        query: str,  # noqa: ARG002 — recency-only: no embedding of the query
        limit: int = 10,
    ) -> list[Episode]:
        """Recall episodes.

        Recency-only (D-2.6): there is **no** embedding/vector call. This falls
        back to the most-recent episodes; true semantic ANN recall is an opt-in
        ``starboard[vectorsearch]`` escape hatch, not part of the native path.
        """
        return await self.get_recent_episodes(user_id, limit)

    async def get_recent_episodes(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[Episode]:
        """Get a user's most recent episodes (chronological)."""
        rows = await self._adapter.read(
            MEMORY_EPISODES,
            filters={"user_id": user_id},
            order_by="created_at DESC",
            limit=limit,
        )
        return [_row_to_episode(r) for r in rows]

    # -- semantic memory (facts) -------------------------------------------
    async def store_fact(self, fact: Fact) -> str:
        """Store a fact (upsert on ``id``)."""
        await self._adapter.upsert(MEMORY_FACTS, _fact_to_row(fact))
        return fact.id

    async def query_facts(
        self,
        user_id: str,
        query: SemanticQuery,
    ) -> list[Fact]:
        """Query a user's facts with recency + Python-side filters (no vectors)."""
        rows = await self._adapter.read(
            MEMORY_FACTS,
            filters={"user_id": user_id},
            order_by="updated_at DESC",
        )
        facts = [_row_to_fact(r) for r in rows]
        if query.categories:
            facts = [f for f in facts if f.category in query.categories]
        facts = [f for f in facts if f.confidence >= query.min_confidence]
        if not query.include_unverified:
            facts = [f for f in facts if f.verified]
        facts.sort(key=lambda f: f.confidence, reverse=True)
        return facts[: query.limit]

    async def update_fact(
        self,
        fact_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update an existing fact."""
        row = await self._adapter.read_one(MEMORY_FACTS, {"id": fact_id})
        if row is None:
            raise ValueError(f"Fact {fact_id} not found")
        fact = _row_to_fact(row)
        fact_dict = fact.to_dict()
        fact_dict.update(updates)
        fact_dict["updated_at"] = datetime.now(UTC).isoformat()
        await self.store_fact(Fact.from_dict(fact_dict))

    # -- profile memory ----------------------------------------------------
    async def get_profile(self, user_id: str) -> UserProfile:
        """Get a user's profile, creating an empty one if absent."""
        row = await self._adapter.read_one(USER_PROFILES, {"user_id": user_id})
        if row is None:
            now = datetime.now(UTC)
            return UserProfile(user_id=user_id, created_at=now, updated_at=now)
        return UserProfile(
            user_id=row["user_id"],
            job_preferences=_serde.loads(row.get("job_preferences"), {}),
            technical_context=_serde.loads(row.get("technical_context"), {}),
            communication_preferences=_serde.loads(
                row.get("communication_preferences"), {}
            ),
            custom_fields=_serde.loads(row.get("custom_fields"), {}),
            created_at=_serde.parse_dt(row["created_at"]),
            updated_at=_serde.parse_dt(row["updated_at"]),
        )

    async def update_profile(
        self,
        user_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update profile fields and persist."""
        profile = await self.get_profile(user_id)
        for key, value in updates.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        profile.updated_at = datetime.now(UTC)
        await self._adapter.upsert(
            USER_PROFILES,
            {
                "user_id": profile.user_id,
                "job_preferences": _serde.dumps(profile.job_preferences),
                "technical_context": _serde.dumps(profile.technical_context),
                "communication_preferences": _serde.dumps(
                    profile.communication_preferences
                ),
                "custom_fields": _serde.dumps(profile.custom_fields),
                "created_at": profile.created_at,
                "updated_at": profile.updated_at,
            },
        )

    async def delete_user_data(self, user_id: str) -> None:
        """Delete all of a user's memory rows (GDPR)."""
        await self._adapter.delete(MEMORY_EPISODES, {"user_id": user_id})
        await self._adapter.delete(MEMORY_FACTS, {"user_id": user_id})
        await self._adapter.delete(USER_PROFILES, {"user_id": user_id})
