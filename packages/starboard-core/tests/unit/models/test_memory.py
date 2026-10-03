# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for memory domain models.

Tests cover:
- Episode creation and serialization
- Fact creation and serialization
- UserProfile Pydantic model
- SemanticQuery model
"""

from datetime import UTC, datetime

from starboard_core.models.memory import (
    Episode,
    Fact,
    SemanticQuery,
    UserProfile,
)


class TestEpisode:
    """Tests for Episode dataclass."""

    def test_create_episode(self):
        """Test creating an episode."""
        now = datetime.now(UTC)
        episode = Episode(
            id="ep_123",
            user_id="user_456",
            conversation_id="conv_789",
            summary="Discussed query optimization",
            key_points=["Added index", "Rewrote query"],
            embedding=[0.1, 0.2, 0.3],
            created_at=now,
        )

        assert episode.id == "ep_123"
        assert episode.user_id == "user_456"
        assert episode.conversation_id == "conv_789"
        assert episode.summary == "Discussed query optimization"
        assert len(episode.key_points) == 2
        assert len(episode.embedding) == 3

    def test_episode_to_dict(self):
        """Test episode serialization."""
        now = datetime.now(UTC)
        episode = Episode(
            id="ep_123",
            user_id="user_456",
            conversation_id=None,
            summary="Test summary",
            key_points=["point1"],
            embedding=None,
            created_at=now,
            metadata={"source": "chat"},
        )

        result = episode.to_dict()

        assert result["id"] == "ep_123"
        assert result["conversation_id"] is None
        assert result["embedding"] is None
        assert result["metadata"]["source"] == "chat"

    def test_episode_from_dict(self):
        """Test episode deserialization."""
        data = {
            "id": "ep_123",
            "user_id": "user_456",
            "conversation_id": "conv_789",
            "summary": "Summary",
            "key_points": ["p1", "p2"],
            "embedding": [0.1, 0.2],
            "created_at": "2024-01-01T12:00:00",
            "metadata": {"key": "value"},
        }

        episode = Episode.from_dict(data)

        assert episode.id == "ep_123"
        assert episode.conversation_id == "conv_789"
        assert len(episode.key_points) == 2
        assert episode.metadata["key"] == "value"


class TestFact:
    """Tests for Fact dataclass."""

    def test_create_fact(self):
        """Test creating a fact."""
        now = datetime.now(UTC)
        fact = Fact(
            id="fact_123",
            user_id="user_456",
            statement="User prefers Python",
            category="technical_skill",
            confidence=0.95,
            source="conversation:abc",
            verified=True,
            created_at=now,
            updated_at=now,
        )

        assert fact.id == "fact_123"
        assert fact.statement == "User prefers Python"
        assert fact.category == "technical_skill"
        assert fact.confidence == 0.95
        assert fact.verified is True

    def test_fact_to_dict(self):
        """Test fact serialization."""
        now = datetime.now(UTC)
        fact = Fact(
            id="fact_123",
            user_id="user_456",
            statement="Test statement",
            category="test",
            confidence=0.8,
            source=None,
            verified=False,
            created_at=now,
            updated_at=now,
        )

        result = fact.to_dict()

        assert result["id"] == "fact_123"
        assert result["statement"] == "Test statement"
        assert result["confidence"] == 0.8
        assert result["source"] is None

    def test_fact_from_dict(self):
        """Test fact deserialization."""
        data = {
            "id": "fact_123",
            "user_id": "user_456",
            "statement": "Statement",
            "category": "job_preference",
            "confidence": 0.9,
            "source": "conv:123",
            "verified": True,
            "created_at": "2024-01-01T12:00:00",
            "updated_at": "2024-01-01T13:00:00",
        }

        fact = Fact.from_dict(data)

        assert fact.id == "fact_123"
        assert fact.confidence == 0.9
        assert fact.verified is True

    def test_fact_from_dict_defaults(self):
        """Test fact deserialization with default values."""
        data = {
            "id": "fact_123",
            "user_id": "user_456",
            "statement": "Statement",
            "category": "test",
            "created_at": "2024-01-01T12:00:00",
            "updated_at": "2024-01-01T12:00:00",
        }

        fact = Fact.from_dict(data)

        assert fact.confidence == 1.0  # Default
        assert fact.source is None
        assert fact.verified is False  # Default
        assert fact.metadata == {}


class TestUserProfile:
    """Tests for UserProfile Pydantic model."""

    def test_create_user_profile(self):
        """Test creating a user profile."""
        profile = UserProfile(
            user_id="user_123",
            job_preferences={"roles": ["engineer"], "locations": ["remote"]},
            technical_context={"cloud_provider": "AWS"},
        )

        assert profile.user_id == "user_123"
        assert profile.job_preferences["roles"] == ["engineer"]
        assert profile.technical_context["cloud_provider"] == "AWS"

    def test_user_profile_defaults(self):
        """Test UserProfile default values."""
        profile = UserProfile(user_id="user_123")

        assert profile.user_id == "user_123"
        assert profile.job_preferences == {}
        assert profile.technical_context == {}
        assert profile.communication_preferences == {}
        assert profile.custom_fields == {}
        assert isinstance(profile.created_at, datetime)
        assert isinstance(profile.updated_at, datetime)


class TestSemanticQuery:
    """Tests for SemanticQuery Pydantic model."""

    def test_create_semantic_query(self):
        """Test creating a semantic query."""
        query = SemanticQuery(
            text="What languages does the user know?",
            categories=["technical_skill"],
            min_confidence=0.7,
            limit=5,
            include_unverified=True,
        )

        assert query.text == "What languages does the user know?"
        assert query.categories == ["technical_skill"]
        assert query.min_confidence == 0.7
        assert query.limit == 5
        assert query.include_unverified is True

    def test_semantic_query_defaults(self):
        """Test SemanticQuery default values."""
        query = SemanticQuery(text="Test query")

        assert query.text == "Test query"
        assert query.categories is None
        assert query.min_confidence == 0.0
        assert query.limit == 10
        assert query.include_unverified is False
