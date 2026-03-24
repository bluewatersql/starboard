"""Integration tests for Postgres memory store (requires running Postgres with pgvector)."""

import os
from datetime import UTC, datetime

import pytest
from starboard_core.models.memory import Episode, Fact, SemanticQuery
from starboard_server.adapters.state.postgres import PostgresMemoryStore


@pytest.fixture(scope="module")
async def memory_store():
    """
    Create Postgres memory store for testing.

    Requires:
        TEST_DATABASE_URL environment variable
        PostgreSQL with pgvector extension enabled
    """
    db_url = os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("TEST_DATABASE_URL not set")

    store = PostgresMemoryStore(db_url)
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
async def cleanup_episodes(memory_store):
    """Clean up test episodes after each test."""
    test_episode_ids = []

    def register_episode(episode_id: str):
        test_episode_ids.append(episode_id)

    yield register_episode

    # Cleanup would go here if needed


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_and_retrieve_episode(memory_store, cleanup_episodes):
    """Should store and retrieve episode."""
    episode_id = f"ep_test_{datetime.now(UTC).timestamp()}"
    cleanup_episodes(episode_id)

    episode = Episode(
        id=episode_id,
        user_id="test-user-1",
        conversation_id="conv-1",
        summary="Test conversation summary",
        key_points=["Point 1", "Point 2"],
        embedding=None,  # No embedding for basic test
        created_at=datetime.now(UTC),
    )

    stored_id = await memory_store.store_episode(episode)
    assert stored_id == episode_id

    # Retrieve episodes
    episodes = await memory_store.get_recent_episodes("test-user-1", limit=10)
    assert any(ep.id == episode_id for ep in episodes)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_episode_with_embedding(memory_store, cleanup_episodes):
    """Should store episode with vector embedding."""
    episode_id = f"ep_test_{datetime.now(UTC).timestamp()}"
    cleanup_episodes(episode_id)

    # Create fake embedding (1536 dimensions for OpenAI ada-002)
    fake_embedding = [0.1] * 1536

    episode = Episode(
        id=episode_id,
        user_id="test-user-1",
        conversation_id="conv-1",
        summary="Test with embedding",
        key_points=["Point 1"],
        embedding=fake_embedding,
        created_at=datetime.now(UTC),
    )

    await memory_store.store_episode(episode)

    # Retrieve and verify embedding is preserved
    episodes = await memory_store.get_recent_episodes("test-user-1", limit=10)
    found_episode = next((ep for ep in episodes if ep.id == episode_id), None)
    assert found_episode is not None
    assert found_episode.embedding is not None
    assert len(found_episode.embedding) == 1536


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_and_query_fact(memory_store):
    """Should store and query facts."""
    fact_id = f"fact_test_{datetime.now(UTC).timestamp()}"

    fact = Fact(
        id=fact_id,
        user_id="test-user-1",
        statement="User prefers Python",
        category="technical_preference",
        confidence=0.9,
        source="conversation:test",
        verified=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    await memory_store.store_fact(fact)

    # Query facts
    query = SemanticQuery(text="preferences", categories=["technical_preference"])
    facts = await memory_store.query_facts("test-user-1", query)
    assert any(f.id == fact_id for f in facts)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_fact(memory_store):
    """Should update existing fact."""
    fact_id = f"fact_test_{datetime.now(UTC).timestamp()}"

    fact = Fact(
        id=fact_id,
        user_id="test-user-1",
        statement="Initial statement",
        category="test",
        confidence=0.5,
        source=None,
        verified=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    await memory_store.store_fact(fact)

    # Update fact
    await memory_store.update_fact(fact_id, {"confidence": 0.95, "verified": True})

    # Verify update
    query = SemanticQuery(text="test", categories=["test"])
    facts = await memory_store.query_facts("test-user-1", query)
    updated_fact = next((f for f in facts if f.id == fact_id), None)
    assert updated_fact is not None
    assert updated_fact.confidence == 0.95
    assert updated_fact.verified is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_and_update_profile(memory_store):
    """Should get and update user profile."""
    user_id = f"test-user-{datetime.now(UTC).timestamp()}"

    # Get profile (creates empty one if doesn't exist)
    profile = await memory_store.get_profile(user_id)
    assert profile is not None
    assert profile.user_id == user_id

    # Update profile
    await memory_store.update_profile(
        user_id, {"job_preferences": {"roles": ["engineer"]}}
    )

    # Verify update
    updated_profile = await memory_store.get_profile(user_id)
    assert updated_profile.job_preferences == {"roles": ["engineer"]}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_user_data(memory_store):
    """Should delete all user data (GDPR compliance)."""
    user_id = f"test-user-{datetime.now(UTC).timestamp()}"

    # Create data for user
    episode = Episode(
        id=f"ep_{user_id}",
        user_id=user_id,
        conversation_id="conv-1",
        summary="Test",
        key_points=[],
        embedding=None,
        created_at=datetime.now(UTC),
    )
    await memory_store.store_episode(episode)

    fact = Fact(
        id=f"fact_{user_id}",
        user_id=user_id,
        statement="Test fact",
        category="test",
        confidence=1.0,
        source=None,
        verified=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await memory_store.store_fact(fact)

    # Delete all user data
    await memory_store.delete_user_data(user_id)

    # Verify deletion
    episodes = await memory_store.get_recent_episodes(user_id, limit=10)
    assert len(episodes) == 0

    query = SemanticQuery(text="test")
    facts = await memory_store.query_facts(user_id, query)
    assert len(facts) == 0
