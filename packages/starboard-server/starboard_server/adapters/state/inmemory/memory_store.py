# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""In-memory memory store implementation."""

from datetime import UTC, datetime
from typing import Any

from starboard_core.models.memory import Episode, Fact, SemanticQuery, UserProfile


class InMemoryMemoryStore:
    """In-memory long-term memory store for development/testing."""

    def __init__(self):
        """Initialize in-memory memory store."""
        self._episodes: dict[str, Episode] = {}
        self._facts: dict[str, Fact] = {}
        self._profiles: dict[str, UserProfile] = {}

    # Episodic Memory
    async def store_episode(self, episode: Episode) -> str:
        """Store a conversation episode."""
        self._episodes[episode.id] = episode
        return episode.id

    async def recall_episodes(
        self,
        user_id: str,
        query: str,  # noqa: ARG002 (not used in simple in-memory implementation)
        limit: int = 10,
    ) -> list[Episode]:
        """
        Retrieve relevant episodes via semantic search.

        Note: In-memory implementation returns most recent episodes.
        Full semantic search requires vector database (Phase 2).
        """
        # Filter by user
        user_episodes = [ep for ep in self._episodes.values() if ep.user_id == user_id]

        # Sort by created_at (descending) - most recent first
        user_episodes.sort(key=lambda ep: ep.created_at, reverse=True)

        # Return most recent episodes (simplified version without semantic search)
        return user_episodes[:limit]

    async def get_recent_episodes(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[Episode]:
        """Get most recent episodes (chronological)."""
        # Filter by user
        user_episodes = [ep for ep in self._episodes.values() if ep.user_id == user_id]

        # Sort by created_at (descending)
        user_episodes.sort(key=lambda ep: ep.created_at, reverse=True)

        return user_episodes[:limit]

    # Semantic Memory (Facts)
    async def store_fact(self, fact: Fact) -> str:
        """Store an extracted fact."""
        self._facts[fact.id] = fact
        return fact.id

    async def query_facts(
        self,
        user_id: str,
        query: SemanticQuery,
    ) -> list[Fact]:
        """
        Query facts with filters.

        Note: In-memory implementation uses simple filtering.
        Full semantic search requires vector database (Phase 2).
        """
        # Filter by user
        user_facts = [f for f in self._facts.values() if f.user_id == user_id]

        # Apply category filter
        if query.categories:
            user_facts = [f for f in user_facts if f.category in query.categories]

        # Apply confidence filter
        user_facts = [f for f in user_facts if f.confidence >= query.min_confidence]

        # Apply verified filter
        if not query.include_unverified:
            user_facts = [f for f in user_facts if f.verified]

        # Sort by confidence (descending)
        user_facts.sort(key=lambda f: f.confidence, reverse=True)

        return user_facts[: query.limit]

    async def update_fact(
        self,
        fact_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update an existing fact."""
        fact = self._facts.get(fact_id)
        if fact is None:
            raise ValueError(f"Fact {fact_id} not found")

        # Create updated fact (facts are frozen dataclasses)
        fact_dict = fact.to_dict()
        fact_dict.update(updates)
        fact_dict["updated_at"] = datetime.now(UTC).isoformat()

        # Store updated fact
        self._facts[fact_id] = Fact.from_dict(fact_dict)

    # Profile Memory (Preferences)
    async def get_profile(self, user_id: str) -> UserProfile:
        """Get user profile (preferences, context)."""
        if user_id not in self._profiles:
            # Create empty profile for new users
            self._profiles[user_id] = UserProfile(
                user_id=user_id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        return self._profiles[user_id]

    async def update_profile(
        self,
        user_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update user profile fields."""
        profile = await self.get_profile(user_id)

        # Update fields
        for key, value in updates.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

        profile.updated_at = datetime.now(UTC)

    async def delete_user_data(self, user_id: str) -> None:
        """Delete all user data (GDPR compliance)."""
        # Delete episodes
        self._episodes = {
            k: v for k, v in self._episodes.items() if v.user_id != user_id
        }

        # Delete facts
        self._facts = {k: v for k, v in self._facts.items() if v.user_id != user_id}

        # Delete profile
        if user_id in self._profiles:
            del self._profiles[user_id]

    async def close(self) -> None:
        """Release resources (no-op for this store)."""

    async def connect(self) -> None:
        """Initialize connection (no-op for this store)."""

    async def delete(self, _key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, _key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, _key: str, _value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
