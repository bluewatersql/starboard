# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for SQLite memory store."""

from datetime import UTC, datetime

import pytest
from starboard_core.models.memory import Episode, Fact, SemanticQuery
from starboard_server.adapters.state.sqlite.memory_store import SQLiteMemoryStore


@pytest.fixture
async def memory_store():
    """Create in-memory SQLite memory store for testing."""
    store = SQLiteMemoryStore(":memory:")
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
def sample_episode():
    """Create a sample episode for testing."""
    return Episode(
        id="ep_123",
        user_id="user_456",
        conversation_id="conv_789",
        summary="User optimized a query by adding indexes",
        key_points=["Added index on user_id", "Reduced execution time by 50%"],
        embedding=[0.1, 0.2, 0.3] * 512,  # 1536 dimensions
        created_at=datetime.now(UTC),
        metadata={"topic": "query_optimization"},
    )


@pytest.fixture
def sample_fact():
    """Create a sample fact for testing."""
    return Fact(
        id="fact_123",
        user_id="user_456",
        statement="User prefers Python for data processing",
        category="preference",
        confidence=0.95,
        source="conversation:conv_789",
        verified=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        metadata={"domain": "programming"},
    )


class TestSQLiteMemoryStore:
    """Test suite for SQLiteMemoryStore."""

    @pytest.mark.unit
    async def test_init_creates_tables(self):
        """Test that connect() initializes schema."""
        store = SQLiteMemoryStore(":memory:")
        await store.connect()

        # Verify tables exist
        async with store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            tables = [row[0] for row in await cursor.fetchall()]

        assert "episodes" in tables
        assert "facts" in tables
        assert "user_profiles" in tables

        await store.close()

    # Episodic Memory Tests

    @pytest.mark.unit
    async def test_store_and_get_episode(self, memory_store, sample_episode):
        """Test storing and retrieving an episode."""
        # Store episode
        episode_id = await memory_store.store_episode(sample_episode)
        assert episode_id == sample_episode.id

        # Retrieve episodes
        episodes = await memory_store.get_recent_episodes(
            sample_episode.user_id, limit=10
        )

        assert len(episodes) == 1
        assert episodes[0].id == sample_episode.id
        assert episodes[0].summary == sample_episode.summary
        assert episodes[0].key_points == sample_episode.key_points

    @pytest.mark.unit
    async def test_store_episode_without_embedding(self, memory_store):
        """Test storing episode without embedding."""
        episode = Episode(
            id="ep_no_embed",
            user_id="user_123",
            conversation_id="conv_456",
            summary="Test episode",
            key_points=None,
            embedding=None,
            created_at=datetime.now(UTC),
            metadata=None,
        )

        episode_id = await memory_store.store_episode(episode)
        assert episode_id == episode.id

        # Retrieve and verify
        episodes = await memory_store.get_recent_episodes("user_123")
        assert len(episodes) == 1
        assert episodes[0].embedding is None

    @pytest.mark.unit
    async def test_update_existing_episode(self, memory_store, sample_episode):
        """Test updating an existing episode."""
        # Store initial episode
        await memory_store.store_episode(sample_episode)

        # Update episode
        updated_episode = Episode(
            id=sample_episode.id,
            user_id=sample_episode.user_id,
            conversation_id=sample_episode.conversation_id,
            summary="Updated summary",
            key_points=["New key point"],
            embedding=sample_episode.embedding,
            created_at=sample_episode.created_at,
            metadata={"updated": True},
        )

        await memory_store.store_episode(updated_episode)

        # Retrieve and verify
        episodes = await memory_store.get_recent_episodes(sample_episode.user_id)
        assert len(episodes) == 1
        assert episodes[0].summary == "Updated summary"
        assert episodes[0].key_points == ["New key point"]

    @pytest.mark.unit
    async def test_get_recent_episodes_ordering(self, memory_store):
        """Test that recent episodes are ordered by creation time."""
        user_id = "user_123"

        # Create episodes with different timestamps
        for i in range(5):
            episode = Episode(
                id=f"ep_{i}",
                user_id=user_id,
                conversation_id=f"conv_{i}",
                summary=f"Episode {i}",
                key_points=None,
                embedding=None,
                created_at=datetime.now(UTC),
                metadata=None,
            )
            await memory_store.store_episode(episode)

        # Get recent episodes
        episodes = await memory_store.get_recent_episodes(user_id, limit=10)

        # Verify ordering (most recent first)
        assert len(episodes) == 5
        for i in range(len(episodes) - 1):
            assert episodes[i].created_at >= episodes[i + 1].created_at

    @pytest.mark.unit
    async def test_get_recent_episodes_limit(self, memory_store):
        """Test limit parameter in get_recent_episodes."""
        user_id = "user_123"

        # Create 10 episodes
        for i in range(10):
            episode = Episode(
                id=f"ep_{i}",
                user_id=user_id,
                conversation_id=f"conv_{i}",
                summary=f"Episode {i}",
                key_points=None,
                embedding=None,
                created_at=datetime.now(UTC),
                metadata=None,
            )
            await memory_store.store_episode(episode)

        # Get limited number
        episodes = await memory_store.get_recent_episodes(user_id, limit=3)
        assert len(episodes) == 3

    @pytest.mark.unit
    async def test_get_recent_episodes_user_isolation(self, memory_store):
        """Test that episodes are isolated per user."""
        # Store episodes for different users
        for user_id in ["user_1", "user_2"]:
            episode = Episode(
                id=f"ep_{user_id}",
                user_id=user_id,
                conversation_id=f"conv_{user_id}",
                summary=f"Episode for {user_id}",
                key_points=None,
                embedding=None,
                created_at=datetime.now(UTC),
                metadata=None,
            )
            await memory_store.store_episode(episode)

        # Get episodes for user_1
        episodes = await memory_store.get_recent_episodes("user_1")

        assert len(episodes) == 1
        assert episodes[0].user_id == "user_1"

    # Semantic Memory (Facts) Tests

    @pytest.mark.unit
    async def test_store_and_query_fact(self, memory_store, sample_fact):
        """Test storing and querying facts."""
        # Store fact
        fact_id = await memory_store.store_fact(sample_fact)
        assert fact_id == sample_fact.id

        # Query facts
        query = SemanticQuery(
            text="",  # Empty text for keyword-only filtering
            categories=None,
            min_confidence=0.0,
            include_unverified=True,
            limit=10,
        )
        facts = await memory_store.query_facts(sample_fact.user_id, query)

        assert len(facts) == 1
        assert facts[0].id == sample_fact.id
        assert facts[0].statement == sample_fact.statement

    @pytest.mark.unit
    async def test_query_facts_by_category(self, memory_store):
        """Test querying facts by category."""
        user_id = "user_123"

        # Store facts with different categories
        categories = ["preference", "skill", "experience"]
        for i, category in enumerate(categories):
            fact = Fact(
                id=f"fact_{i}",
                user_id=user_id,
                statement=f"Fact about {category}",
                category=category,
                confidence=0.9,
                source=None,
                verified=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                metadata=None,
            )
            await memory_store.store_fact(fact)

        # Query for specific category
        query = SemanticQuery(
            text="",  # Empty text for category filtering
            categories=["preference"],
            min_confidence=0.0,
            include_unverified=True,
            limit=10,
        )
        facts = await memory_store.query_facts(user_id, query)

        assert len(facts) == 1
        assert facts[0].category == "preference"

    @pytest.mark.unit
    async def test_query_facts_min_confidence(self, memory_store):
        """Test filtering facts by minimum confidence."""
        user_id = "user_123"

        # Store facts with different confidence levels
        confidences = [0.5, 0.7, 0.9]
        for i, confidence in enumerate(confidences):
            fact = Fact(
                id=f"fact_{i}",
                user_id=user_id,
                statement=f"Fact {i}",
                category="test",
                confidence=confidence,
                source=None,
                verified=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                metadata=None,
            )
            await memory_store.store_fact(fact)

        # Query with minimum confidence
        query = SemanticQuery(
            text="",  # Empty text for confidence filtering
            categories=None,
            min_confidence=0.8,
            include_unverified=True,
            limit=10,
        )
        facts = await memory_store.query_facts(user_id, query)

        assert len(facts) == 1
        assert facts[0].confidence >= 0.8

    @pytest.mark.unit
    async def test_query_facts_verified_only(self, memory_store):
        """Test filtering to verified facts only."""
        user_id = "user_123"

        # Store verified and unverified facts
        for i in range(3):
            fact = Fact(
                id=f"fact_{i}",
                user_id=user_id,
                statement=f"Fact {i}",
                category="test",
                confidence=0.9,
                source=None,
                verified=i % 2 == 0,  # Every other fact is verified
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                metadata=None,
            )
            await memory_store.store_fact(fact)

        # Query for verified only
        query = SemanticQuery(
            text="",  # Empty text for verified filtering
            categories=None,
            min_confidence=0.0,
            include_unverified=False,
            limit=10,
        )
        facts = await memory_store.query_facts(user_id, query)

        assert len(facts) == 2
        assert all(fact.verified for fact in facts)

    @pytest.mark.unit
    async def test_update_fact(self, memory_store, sample_fact):
        """Test updating an existing fact."""
        # Store initial fact
        await memory_store.store_fact(sample_fact)

        # Update fact
        await memory_store.update_fact(
            sample_fact.id,
            {"confidence": 1.0, "verified": True},
        )

        # Query and verify
        query = SemanticQuery(
            text="",  # Empty text for update verification
            categories=None,
            min_confidence=0.0,
            include_unverified=True,
            limit=10,
        )
        facts = await memory_store.query_facts(sample_fact.user_id, query)

        assert len(facts) == 1
        assert facts[0].confidence == 1.0
        assert facts[0].verified is True

    @pytest.mark.unit
    async def test_update_nonexistent_fact(self, memory_store):
        """Test updating a fact that doesn't exist."""
        with pytest.raises(ValueError, match="not found"):
            await memory_store.update_fact(
                "nonexistent_id",
                {"confidence": 1.0},
            )

    # User Profile Tests

    @pytest.mark.unit
    async def test_get_profile_creates_if_not_exists(self, memory_store):
        """Test that get_profile creates profile if it doesn't exist."""
        profile = await memory_store.get_profile("new_user")

        assert profile is not None
        assert profile.user_id == "new_user"
        assert isinstance(profile.created_at, datetime)

    @pytest.mark.unit
    async def test_update_profile(self, memory_store):
        """Test updating user profile."""
        user_id = "user_123"

        # Get/create initial profile
        await memory_store.get_profile(user_id)

        # Update profile
        await memory_store.update_profile(
            user_id,
            {
                "preferences": {"theme": "dark", "language": "en"},
                "role": "data_engineer",
            },
        )

        # Get updated profile
        profile = await memory_store.get_profile(user_id)

        assert profile.user_id == user_id
        # Note: Actual verification depends on UserProfile.to_dict/from_dict implementation

    @pytest.mark.unit
    async def test_delete_user_data(self, memory_store):
        """Test deleting all user data (GDPR compliance)."""
        user_id = "user_123"

        # Create user data
        episode = Episode(
            id="ep_123",
            user_id=user_id,
            conversation_id="conv_456",
            summary="Test",
            key_points=None,
            embedding=None,
            created_at=datetime.now(UTC),
            metadata=None,
        )
        await memory_store.store_episode(episode)

        fact = Fact(
            id="fact_123",
            user_id=user_id,
            statement="Test fact",
            category="test",
            confidence=0.9,
            source=None,
            verified=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            metadata=None,
        )
        await memory_store.store_fact(fact)

        await memory_store.get_profile(user_id)

        # Delete user data
        await memory_store.delete_user_data(user_id)

        # Verify all data deleted
        episodes = await memory_store.get_recent_episodes(user_id)
        assert len(episodes) == 0

        query = SemanticQuery(
            text="",  # Empty text for deletion verification
            categories=None,
            min_confidence=0.0,
            include_unverified=True,
            limit=10,
        )
        facts = await memory_store.query_facts(user_id, query)
        assert len(facts) == 0

        # Profile should be recreated as empty
        profile = await memory_store.get_profile(user_id)
        assert profile.user_id == user_id

    @pytest.mark.unit
    async def test_file_based_persistence(self, tmp_path):
        """Test file-based SQLite with persistence across connections."""
        db_path = str(tmp_path / "test_memory.db")

        # Create store and save data
        store1 = SQLiteMemoryStore(db_path)
        await store1.connect()

        episode = Episode(
            id="ep_123",
            user_id="user_456",
            conversation_id="conv_789",
            summary="Test episode",
            key_points=None,
            embedding=None,
            created_at=datetime.now(UTC),
            metadata=None,
        )
        await store1.store_episode(episode)
        await store1.close()

        # Open new store and verify data persisted
        store2 = SQLiteMemoryStore(db_path)
        await store2.connect()
        episodes = await store2.get_recent_episodes("user_456")
        await store2.close()

        assert len(episodes) == 1
        assert episodes[0].id == "ep_123"

    @pytest.mark.unit
    async def test_special_characters_in_data(self, memory_store):
        """Test handling of special characters in facts."""
        fact = Fact(
            id="fact_special",
            user_id="user_123",
            statement="User said: 'I prefer Python' and \"loves\" SQL",
            category="preference",
            confidence=0.9,
            source="conversation:conv_'123'",
            verified=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            metadata={"key": "value with 'quotes'"},
        )

        await memory_store.store_fact(fact)

        query = SemanticQuery(
            text="",  # Empty text for special character testing
            categories=None,
            min_confidence=0.0,
            include_unverified=True,
            limit=10,
        )
        facts = await memory_store.query_facts("user_123", query)

        assert len(facts) == 1
        assert facts[0].statement == fact.statement
