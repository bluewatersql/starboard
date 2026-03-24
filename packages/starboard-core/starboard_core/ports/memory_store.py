"""Memory store protocol (interface)."""

from typing import Any, Protocol

from starboard_core.models.memory import Episode, Fact, SemanticQuery, UserProfile


class MemoryStore(Protocol):
    """
    Abstract interface for long-term memory storage.

    Supports three types of memory:
    - Episodic: Past conversation summaries, events
    - Semantic: Extracted facts, entities, relationships
    - Profile: User preferences, context, settings
    """

    # Episodic Memory
    async def store_episode(
        self,
        episode: Episode,
    ) -> str:
        """
        Store a conversation episode.

        Args:
            episode: Episode to store (summary, key points, embedding)

        Returns:
            Episode ID
        """
        ...

    async def recall_episodes(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
    ) -> list[Episode]:
        """
        Retrieve relevant episodes via semantic search.

        Args:
            user_id: User identifier
            query: Search query (will be embedded)
            limit: Maximum number of results

        Returns:
            List of episodes ranked by relevance
        """
        ...

    async def get_recent_episodes(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[Episode]:
        """
        Get most recent episodes (chronological).

        Args:
            user_id: User identifier
            limit: Maximum number of results

        Returns:
            List of episodes ordered by recency
        """
        ...

    # Semantic Memory (Facts)
    async def store_fact(
        self,
        fact: Fact,
    ) -> str:
        """
        Store an extracted fact.

        Args:
            fact: Fact to store (statement, source, confidence)

        Returns:
            Fact ID
        """
        ...

    async def query_facts(
        self,
        user_id: str,
        query: SemanticQuery,
    ) -> list[Fact]:
        """
        Query facts with filters.

        Args:
            user_id: User identifier
            query: Semantic query with filters (category, confidence, etc.)

        Returns:
            List of matching facts
        """
        ...

    async def update_fact(
        self,
        fact_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update an existing fact (e.g., confidence, verification status)."""
        ...

    # Profile Memory (Preferences)
    async def get_profile(
        self,
        user_id: str,
    ) -> UserProfile:
        """
        Get user profile (preferences, context).

        Args:
            user_id: User identifier

        Returns:
            User profile (may be empty for new users)
        """
        ...

    async def update_profile(
        self,
        user_id: str,
        updates: dict[str, Any],
    ) -> None:
        """
        Update user profile fields.

        Args:
            user_id: User identifier
            updates: Key-value pairs to update
        """
        ...

    async def delete_user_data(
        self,
        user_id: str,
    ) -> None:
        """
        Delete all user data (GDPR compliance).

        Args:
            user_id: User identifier
        """
        ...
