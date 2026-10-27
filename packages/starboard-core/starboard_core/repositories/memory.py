# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Memory repository."""

import uuid
from datetime import UTC, datetime
from typing import Any

from starboard_core.models.memory import Episode, Fact, SemanticQuery, UserProfile
from starboard_core.ports.memory_store import MemoryStore


class MemoryRepository:
    """High-level interface for long-term memory operations."""

    def __init__(self, store: MemoryStore):
        """
        Initialize memory repository.

        Args:
            store: MemoryStore implementation for persistence
        """
        self._store = store

    async def remember_conversation(
        self,
        user_id: str,
        conversation_id: str,
        conversation_summary: str,
        key_points: list[str],
        embedding: list[float] | None = None,
    ) -> str:
        """
        Store conversation as episodic memory.

        Args:
            user_id: User identifier
            conversation_id: Conversation identifier
            conversation_summary: Summary of conversation
            key_points: Key takeaways from conversation
            embedding: Optional embedding vector for semantic search

        Returns:
            Episode ID
        """
        episode = Episode(
            id=f"ep_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            conversation_id=conversation_id,
            summary=conversation_summary,
            key_points=key_points,
            embedding=embedding,
            created_at=datetime.now(UTC),
        )
        return await self._store.store_episode(episode)

    async def learn_fact(
        self,
        user_id: str,
        statement: str,
        category: str,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> str:
        """
        Store learned fact.

        Args:
            user_id: User identifier
            statement: Fact statement
            category: Fact category (e.g., "job_preference", "technical_skill")
            confidence: Confidence score (0.0 to 1.0)
            source: Optional source reference

        Returns:
            Fact ID
        """
        fact = Fact(
            id=f"fact_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            statement=statement,
            category=category,
            confidence=confidence,
            source=source,
            verified=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        return await self._store.store_fact(fact)

    async def get_relevant_context(
        self,
        user_id: str,
        query: str,
        max_episodes: int = 5,
        max_facts: int = 10,
    ) -> dict[str, Any]:
        """
        Retrieve relevant memories for a query.

        Args:
            user_id: User identifier
            query: Search query
            max_episodes: Maximum number of episodes to retrieve
            max_facts: Maximum number of facts to retrieve

        Returns:
            Dictionary with episodes, facts, and profile
        """
        episodes = await self._store.recall_episodes(user_id, query, max_episodes)
        facts = await self._store.query_facts(
            user_id, SemanticQuery(text=query, limit=max_facts)
        )
        profile = await self._store.get_profile(user_id)

        return {
            "episodes": episodes,
            "facts": facts,
            "profile": profile,
        }

    async def get_profile(self, user_id: str) -> UserProfile:
        """
        Get user profile.

        Args:
            user_id: User identifier

        Returns:
            User profile
        """
        return await self._store.get_profile(user_id)

    async def update_profile(self, user_id: str, updates: dict[str, Any]) -> None:
        """
        Update user profile.

        Args:
            user_id: User identifier
            updates: Fields to update
        """
        await self._store.update_profile(user_id, updates)
