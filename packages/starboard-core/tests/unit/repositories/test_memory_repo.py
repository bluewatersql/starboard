# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for MemoryRepository.

Tests cover:
- Remembering conversations (episodic memory)
- Learning facts (semantic memory)
- Getting relevant context
- Profile management
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from starboard_core.models.memory import Episode, Fact, SemanticQuery, UserProfile
from starboard_core.repositories.memory import MemoryRepository


@pytest.fixture
def mock_store():
    """Create a mock MemoryStore."""
    store = AsyncMock()
    return store


@pytest.fixture
def memory_repo(mock_store):
    """Create a MemoryRepository with mock store."""
    return MemoryRepository(mock_store)


@pytest.fixture
def sample_episode():
    """Create a sample episode."""
    return Episode(
        id="ep_abc123",
        user_id="user_456",
        conversation_id="conv_789",
        summary="Discussion about job optimization",
        key_points=["Identified slow query", "Recommended index"],
        embedding=[0.1] * 1536,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_fact():
    """Create a sample fact."""
    return Fact(
        id="fact_abc123",
        user_id="user_456",
        statement="User prefers detailed explanations",
        category="preference",
        confidence=0.9,
        source="conv_789",
        verified=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_profile():
    """Create a sample user profile."""
    return UserProfile(
        user_id="user_456",
        preferences={"verbosity": "high", "format": "markdown"},
        context={"workspace": "prod"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestRememberConversation:
    """Tests for remember_conversation method."""

    @pytest.mark.asyncio
    async def test_stores_episode(self, memory_repo, mock_store):
        """Test that episode is stored correctly."""
        mock_store.store_episode.return_value = "ep_generated123"

        result = await memory_repo.remember_conversation(
            user_id="user_456",
            conversation_id="conv_789",
            conversation_summary="Discussed query optimization",
            key_points=["Found slow query", "Added index"],
        )

        assert result == "ep_generated123"
        mock_store.store_episode.assert_called_once()

        # Verify episode structure
        stored_episode = mock_store.store_episode.call_args[0][0]
        assert stored_episode.user_id == "user_456"
        assert stored_episode.conversation_id == "conv_789"
        assert stored_episode.summary == "Discussed query optimization"
        assert stored_episode.key_points == ["Found slow query", "Added index"]
        assert stored_episode.id.startswith("ep_")

    @pytest.mark.asyncio
    async def test_stores_episode_with_embedding(self, memory_repo, mock_store):
        """Test that episode stores optional embedding."""
        mock_store.store_episode.return_value = "ep_123"
        embedding = [0.1] * 1536

        await memory_repo.remember_conversation(
            user_id="user_456",
            conversation_id="conv_789",
            conversation_summary="Test",
            key_points=[],
            embedding=embedding,
        )

        stored_episode = mock_store.store_episode.call_args[0][0]
        assert stored_episode.embedding == embedding

    @pytest.mark.asyncio
    async def test_episode_has_timestamp(self, memory_repo, mock_store):
        """Test that episode has created_at timestamp."""
        mock_store.store_episode.return_value = "ep_123"

        await memory_repo.remember_conversation(
            user_id="user_456",
            conversation_id="conv_789",
            conversation_summary="Test",
            key_points=[],
        )

        stored_episode = mock_store.store_episode.call_args[0][0]
        assert stored_episode.created_at is not None
        assert isinstance(stored_episode.created_at, datetime)


class TestLearnFact:
    """Tests for learn_fact method."""

    @pytest.mark.asyncio
    async def test_stores_fact(self, memory_repo, mock_store):
        """Test that fact is stored correctly."""
        mock_store.store_fact.return_value = "fact_generated123"

        result = await memory_repo.learn_fact(
            user_id="user_456",
            statement="User prefers SQL over Python",
            category="preference",
        )

        assert result == "fact_generated123"
        mock_store.store_fact.assert_called_once()

        # Verify fact structure
        stored_fact = mock_store.store_fact.call_args[0][0]
        assert stored_fact.user_id == "user_456"
        assert stored_fact.statement == "User prefers SQL over Python"
        assert stored_fact.category == "preference"
        assert stored_fact.id.startswith("fact_")

    @pytest.mark.asyncio
    async def test_stores_fact_with_defaults(self, memory_repo, mock_store):
        """Test that fact has default confidence and verified=False."""
        mock_store.store_fact.return_value = "fact_123"

        await memory_repo.learn_fact(
            user_id="user_456",
            statement="Test fact",
            category="test",
        )

        stored_fact = mock_store.store_fact.call_args[0][0]
        assert stored_fact.confidence == 1.0
        assert stored_fact.verified is False
        assert stored_fact.source is None

    @pytest.mark.asyncio
    async def test_stores_fact_with_custom_params(self, memory_repo, mock_store):
        """Test that fact stores custom confidence and source."""
        mock_store.store_fact.return_value = "fact_123"

        await memory_repo.learn_fact(
            user_id="user_456",
            statement="Test fact",
            category="test",
            confidence=0.7,
            source="conv_abc",
        )

        stored_fact = mock_store.store_fact.call_args[0][0]
        assert stored_fact.confidence == 0.7
        assert stored_fact.source == "conv_abc"

    @pytest.mark.asyncio
    async def test_fact_has_timestamps(self, memory_repo, mock_store):
        """Test that fact has created_at and updated_at timestamps."""
        mock_store.store_fact.return_value = "fact_123"

        await memory_repo.learn_fact(
            user_id="user_456",
            statement="Test",
            category="test",
        )

        stored_fact = mock_store.store_fact.call_args[0][0]
        assert stored_fact.created_at is not None
        assert stored_fact.updated_at is not None


class TestGetRelevantContext:
    """Tests for get_relevant_context method."""

    @pytest.mark.asyncio
    async def test_returns_all_context_types(
        self, memory_repo, mock_store, sample_episode, sample_fact, sample_profile
    ):
        """Test that method returns episodes, facts, and profile."""
        mock_store.recall_episodes.return_value = [sample_episode]
        mock_store.query_facts.return_value = [sample_fact]
        mock_store.get_profile.return_value = sample_profile

        result = await memory_repo.get_relevant_context(
            user_id="user_456",
            query="job optimization",
        )

        assert "episodes" in result
        assert "facts" in result
        assert "profile" in result
        assert len(result["episodes"]) == 1
        assert len(result["facts"]) == 1
        assert result["profile"] == sample_profile

    @pytest.mark.asyncio
    async def test_passes_query_to_stores(
        self, memory_repo, mock_store, sample_profile
    ):
        """Test that query is passed to episode recall and fact query."""
        mock_store.recall_episodes.return_value = []
        mock_store.query_facts.return_value = []
        mock_store.get_profile.return_value = sample_profile

        await memory_repo.get_relevant_context(
            user_id="user_456",
            query="test query",
        )

        mock_store.recall_episodes.assert_called_once_with("user_456", "test query", 5)

        # Check SemanticQuery was created with correct params
        fact_query_call = mock_store.query_facts.call_args
        assert fact_query_call[0][0] == "user_456"
        semantic_query = fact_query_call[0][1]
        assert isinstance(semantic_query, SemanticQuery)
        assert semantic_query.text == "test query"
        assert semantic_query.limit == 10

    @pytest.mark.asyncio
    async def test_respects_max_limits(self, memory_repo, mock_store, sample_profile):
        """Test that custom max_episodes and max_facts are respected."""
        mock_store.recall_episodes.return_value = []
        mock_store.query_facts.return_value = []
        mock_store.get_profile.return_value = sample_profile

        await memory_repo.get_relevant_context(
            user_id="user_456",
            query="test",
            max_episodes=3,
            max_facts=5,
        )

        mock_store.recall_episodes.assert_called_once_with("user_456", "test", 3)

        semantic_query = mock_store.query_facts.call_args[0][1]
        assert semantic_query.limit == 5


class TestGetProfile:
    """Tests for get_profile method."""

    @pytest.mark.asyncio
    async def test_returns_profile(self, memory_repo, mock_store, sample_profile):
        """Test that profile is returned."""
        mock_store.get_profile.return_value = sample_profile

        result = await memory_repo.get_profile("user_456")

        assert result == sample_profile
        mock_store.get_profile.assert_called_once_with("user_456")


class TestUpdateProfile:
    """Tests for update_profile method."""

    @pytest.mark.asyncio
    async def test_updates_profile(self, memory_repo, mock_store):
        """Test that profile update is delegated to store."""
        updates = {"preferences": {"verbosity": "low"}}

        await memory_repo.update_profile("user_456", updates)

        mock_store.update_profile.assert_called_once_with("user_456", updates)

    @pytest.mark.asyncio
    async def test_updates_multiple_fields(self, memory_repo, mock_store):
        """Test updating multiple profile fields."""
        updates = {
            "preferences": {"format": "json"},
            "context": {"workspace": "dev"},
        }

        await memory_repo.update_profile("user_456", updates)

        mock_store.update_profile.assert_called_once_with("user_456", updates)
