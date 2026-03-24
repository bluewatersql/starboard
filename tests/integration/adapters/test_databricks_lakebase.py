"""Integration tests for Databricks Lakebase adapters.

These tests require an actual Databricks Lakebase instance.

Setup:
    1. Create a Lakebase instance in your Databricks workspace
    2. Set environment variables:
       export LAKEBASE_INSTANCE_NAME=your-instance
       export LAKEBASE_DATABASE_NAME=test_db
       export DATABASE_BACKEND=databricks
    3. Run database setup script:
       python scripts/setup_databricks_lakebase.py
    4. Run tests:
       pytest tests/integration/adapters/test_databricks_lakebase.py -v

Note:
    Tests are skipped if environment variables are not set.
"""

import os
from datetime import UTC, datetime

import pytest
from starboard_core.models.conversation import Conversation, Message
from starboard_core.models.memory import Episode, Fact, SemanticQuery
from starboard_server.adapters.state.databricks import (
    DatabricksLakebaseConfig,
    DatabricksLakebaseMemoryStore,
    DatabricksLakebaseStateStore,
)

# Skip if Lakebase not configured
pytestmark = pytest.mark.skipif(
    not os.getenv("LAKEBASE_INSTANCE_NAME"),
    reason="LAKEBASE_INSTANCE_NAME not set - skipping Lakebase integration tests",
)


@pytest.fixture
async def lakebase_config():
    """Load Lakebase configuration from environment."""
    try:
        config = DatabricksLakebaseConfig.from_env()
        config.validate()
        return config
    except ValueError as e:
        pytest.skip(f"Lakebase configuration invalid: {e}")


@pytest.fixture
async def state_store(lakebase_config):
    """Create and connect Lakebase state store."""
    store = DatabricksLakebaseStateStore(lakebase_config)
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
async def memory_store(lakebase_config):
    """Create and connect Lakebase memory store."""
    store = DatabricksLakebaseMemoryStore(lakebase_config)
    await store.connect()
    yield store
    await store.close()


class TestDatabricksLakebaseStateStore:
    """Integration tests for DatabricksLakebaseStateStore."""

    @pytest.mark.asyncio
    async def test_connection(self, state_store):
        """Test that connection is established successfully."""
        assert state_store._pool is not None
        assert state_store._sdk_client is not None

    @pytest.mark.asyncio
    async def test_save_and_get_conversation(self, state_store):
        """Test saving and retrieving a conversation."""
        # Create test conversation
        conversation = Conversation(
            id="test-conv-001",
            user_id="test-user",
            messages=[
                Message(
                    role="user",
                    content="Hello",
                    created_at=datetime.now(UTC),
                ),
                Message(
                    role="assistant",
                    content="Hi there!",
                    created_at=datetime.now(UTC),
                ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            title="Test Conversation",
            tags=["test", "integration"],
            archived=False,
        )

        # Save conversation
        await state_store.save_conversation(conversation)

        # Retrieve conversation
        retrieved = await state_store.get_conversation("test-conv-001")

        assert retrieved is not None
        assert retrieved.id == "test-conv-001"
        assert retrieved.user_id == "test-user"
        assert len(retrieved.messages) == 2
        assert retrieved.title == "Test Conversation"
        assert "test" in retrieved.tags

    @pytest.mark.asyncio
    async def test_list_conversations(self, state_store):
        """Test listing conversations for a user."""
        # Create multiple test conversations
        for i in range(3):
            conversation = Conversation(
                id=f"test-list-{i}",
                user_id="test-list-user",
                messages=[
                    Message(
                        role="user",
                        content=f"Message {i}",
                        created_at=datetime.now(UTC),
                    )
                ],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                title=f"Conversation {i}",
                archived=False,
            )
            await state_store.save_conversation(conversation)

        # List conversations
        conversations = await state_store.list_conversations(
            user_id="test-list-user",
            limit=10,
            offset=0,
        )

        assert len(conversations) >= 3
        assert all(c.user_id == "test-list-user" for c in conversations)

    @pytest.mark.asyncio
    async def test_update_metadata(self, state_store):
        """Test updating conversation metadata."""
        # Create conversation
        conversation = Conversation(
            id="test-update-meta",
            user_id="test-user",
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            title="Original Title",
        )
        await state_store.save_conversation(conversation)

        # Update metadata
        await state_store.update_metadata(
            conversation_id="test-update-meta",
            updates={"title": "Updated Title", "tags": ["updated"]},
        )

        # Verify update
        retrieved = await state_store.get_conversation("test-update-meta")
        assert retrieved.title == "Updated Title"
        assert "updated" in retrieved.tags

    @pytest.mark.asyncio
    async def test_delete_conversation(self, state_store):
        """Test deleting a conversation."""
        # Create conversation
        conversation = Conversation(
            id="test-delete",
            user_id="test-user",
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await state_store.save_conversation(conversation)

        # Delete conversation
        deleted = await state_store.delete_conversation("test-delete")
        assert deleted is True

        # Verify deletion
        retrieved = await state_store.get_conversation("test-delete")
        assert retrieved is None


class TestDatabricksLakebaseMemoryStore:
    """Integration tests for DatabricksLakebaseMemoryStore."""

    @pytest.mark.asyncio
    async def test_connection(self, memory_store):
        """Test that connection is established successfully."""
        assert memory_store._pool is not None
        assert memory_store._sdk_client is not None

    @pytest.mark.asyncio
    async def test_store_and_recall_episode(self, memory_store):
        """Test storing and recalling an episode."""
        # Create test episode
        episode = Episode(
            id="test-episode-001",
            user_id="test-user",
            conversation_id="test-conv",
            summary="User discussed Databricks optimization",
            key_points=["performance", "databricks", "optimization"],
            embedding=None,  # No embedding for basic test
            created_at=datetime.now(UTC),
            metadata={"source": "test"},
        )

        # Store episode
        episode_id = await memory_store.store_episode(episode)
        assert episode_id == "test-episode-001"

        # Recall episodes
        episodes = await memory_store.get_recent_episodes(
            user_id="test-user",
            limit=10,
        )

        assert len(episodes) >= 1
        found = next((e for e in episodes if e.id == "test-episode-001"), None)
        assert found is not None
        assert found.summary == "User discussed Databricks optimization"
        assert "performance" in found.key_points

    @pytest.mark.asyncio
    async def test_store_and_query_fact(self, memory_store):
        """Test storing and querying facts."""
        # Create test fact
        fact = Fact(
            id="test-fact-001",
            user_id="test-user",
            statement="User prefers Python for data analysis",
            category="job_preference",
            confidence=0.9,
            source="conversation:test-conv",
            verified=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            metadata={"test": True},
        )

        # Store fact
        fact_id = await memory_store.store_fact(fact)
        assert fact_id == "test-fact-001"

        # Query facts
        query = SemanticQuery(
            categories=["job_preference"],
            min_confidence=0.8,
            include_unverified=False,
            limit=10,
        )
        facts = await memory_store.query_facts(user_id="test-user", query=query)

        assert len(facts) >= 1
        found = next((f for f in facts if f.id == "test-fact-001"), None)
        assert found is not None
        assert found.statement == "User prefers Python for data analysis"
        assert found.confidence == 0.9

    @pytest.mark.asyncio
    async def test_update_fact(self, memory_store):
        """Test updating a fact."""
        # Create fact
        fact = Fact(
            id="test-fact-update",
            user_id="test-user",
            statement="Original statement",
            category="test",
            confidence=0.7,
            source="test",
            verified=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await memory_store.store_fact(fact)

        # Update fact
        await memory_store.update_fact(
            fact_id="test-fact-update",
            updates={
                "statement": "Updated statement",
                "confidence": 0.95,
                "verified": True,
            },
        )

        # Verify update
        query = SemanticQuery(categories=["test"], min_confidence=0.5, limit=10)
        facts = await memory_store.query_facts(user_id="test-user", query=query)

        found = next((f for f in facts if f.id == "test-fact-update"), None)
        assert found is not None
        assert found.statement == "Updated statement"
        assert found.confidence == 0.95
        assert found.verified is True

    @pytest.mark.asyncio
    async def test_get_and_update_profile(self, memory_store):
        """Test getting and updating user profile."""
        # Get profile (creates if not exists)
        profile = await memory_store.get_profile("test-profile-user")
        assert profile.user_id == "test-profile-user"

        # Update profile
        await memory_store.update_profile(
            user_id="test-profile-user",
            updates={
                "job_preferences": {"role": "Data Engineer", "location": "Remote"},
                "technical_context": {"skills": ["Python", "Spark", "Databricks"]},
            },
        )

        # Retrieve updated profile
        updated_profile = await memory_store.get_profile("test-profile-user")
        assert updated_profile.job_preferences["role"] == "Data Engineer"
        assert "Python" in updated_profile.technical_context["skills"]

    @pytest.mark.asyncio
    async def test_delete_user_data(self, memory_store):
        """Test GDPR-compliant user data deletion."""
        user_id = "test-delete-user"

        # Create test data
        episode = Episode(
            id=f"episode-{user_id}",
            user_id=user_id,
            conversation_id="test",
            summary="Test episode",
            key_points=[],
            created_at=datetime.now(UTC),
        )
        await memory_store.store_episode(episode)

        fact = Fact(
            id=f"fact-{user_id}",
            user_id=user_id,
            statement="Test fact",
            category="test",
            confidence=0.8,
            source="test",
            verified=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await memory_store.store_fact(fact)

        # Delete all user data
        await memory_store.delete_user_data(user_id)

        # Verify deletion
        episodes = await memory_store.get_recent_episodes(user_id, limit=10)
        assert len([e for e in episodes if e.user_id == user_id]) == 0

        query = SemanticQuery(categories=["test"], min_confidence=0.5, limit=10)
        facts = await memory_store.query_facts(user_id, query)
        assert len([f for f in facts if f.user_id == user_id]) == 0


class TestDatabricksLakebaseTokenRefresh:
    """Integration tests for OAuth token refresh mechanism."""

    @pytest.mark.asyncio
    async def test_token_refresh_background_task(self, lakebase_config):
        """Test that background token refresh task starts."""
        store = DatabricksLakebaseStateStore(lakebase_config)
        await store.connect()

        try:
            # Verify task is running
            assert store._token_refresh_task is not None
            assert not store._token_refresh_task.done()

            # Verify initial token
            assert store._current_password is not None
            assert store._last_password_refresh > 0

        finally:
            await store.close()

            # Verify task is cancelled
            assert (
                store._token_refresh_task.cancelled()
                or store._token_refresh_task.done()
            )

    @pytest.mark.asyncio
    async def test_credentials_refresh(self, lakebase_config):
        """Test manual credential refresh."""
        store = DatabricksLakebaseStateStore(lakebase_config)
        await store.connect()

        try:
            # Get initial credentials
            initial_password = store._current_password
            initial_refresh_time = store._last_password_refresh

            # Trigger manual refresh
            await store._refresh_credentials()

            # Verify new credentials
            assert store._current_password is not None
            assert store._current_password != initial_password  # Should be different
            assert store._last_password_refresh > initial_refresh_time

        finally:
            await store.close()
