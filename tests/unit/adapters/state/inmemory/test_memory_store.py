# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for in-memory memory store."""

from datetime import UTC, datetime

import pytest
from starboard_core.models.memory import Episode, Fact, SemanticQuery
from starboard_server.adapters.state.inmemory import InMemoryMemoryStore


@pytest.fixture
def memory_store():
    """Create a fresh in-memory memory store for each test."""
    return InMemoryMemoryStore()


@pytest.fixture
def sample_episode():
    """Create a sample episode for testing."""
    return Episode(
        id="ep_test123",
        user_id="user-1",
        conversation_id="conv-1",
        summary="User asked about Python best practices",
        key_points=["Use type hints", "Follow PEP 8"],
        embedding=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_fact():
    """Create a sample fact for testing."""
    return Fact(
        id="fact_test123",
        user_id="user-1",
        statement="User prefers Python over Java",
        category="technical_preference",
        confidence=0.9,
        source="conversation:conv-1",
        verified=True,  # Must be verified to be returned by default query
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# Episodic Memory Tests


@pytest.mark.asyncio
async def test_store_episode(memory_store, sample_episode):
    """Should store episode and return ID."""
    episode_id = await memory_store.store_episode(sample_episode)
    assert episode_id == sample_episode.id


@pytest.mark.asyncio
async def test_recall_episodes(memory_store, sample_episode):
    """Should recall episodes for user."""
    await memory_store.store_episode(sample_episode)

    episodes = await memory_store.recall_episodes("user-1", "query", limit=10)
    assert len(episodes) == 1
    assert episodes[0].id == sample_episode.id


@pytest.mark.asyncio
async def test_recall_episodes_returns_most_recent(memory_store):
    """Should return most recent episodes first."""
    # Create episodes with different timestamps
    for i in range(3):
        episode = Episode(
            id=f"ep_{i}",
            user_id="user-1",
            conversation_id=f"conv-{i}",
            summary=f"Summary {i}",
            key_points=[],
            embedding=None,
            created_at=datetime.now(UTC),
        )
        await memory_store.store_episode(episode)
        import asyncio

        await asyncio.sleep(0.01)  # Ensure different timestamps

    episodes = await memory_store.recall_episodes("user-1", "query", limit=10)
    # Most recent should be first
    assert episodes[0].id == "ep_2"
    assert episodes[1].id == "ep_1"
    assert episodes[2].id == "ep_0"


@pytest.mark.asyncio
async def test_recall_episodes_filters_by_user(memory_store):
    """Should only recall episodes for specified user."""
    ep1 = Episode(
        id="ep_1",
        user_id="user-1",
        conversation_id="conv-1",
        summary="Summary 1",
        key_points=[],
        embedding=None,
        created_at=datetime.now(UTC),
    )
    ep2 = Episode(
        id="ep_2",
        user_id="user-2",
        conversation_id="conv-2",
        summary="Summary 2",
        key_points=[],
        embedding=None,
        created_at=datetime.now(UTC),
    )
    await memory_store.store_episode(ep1)
    await memory_store.store_episode(ep2)

    episodes = await memory_store.recall_episodes("user-1", "query")
    assert len(episodes) == 1
    assert episodes[0].user_id == "user-1"


@pytest.mark.asyncio
async def test_get_recent_episodes(memory_store, sample_episode):
    """Should get recent episodes chronologically."""
    await memory_store.store_episode(sample_episode)

    episodes = await memory_store.get_recent_episodes("user-1", limit=10)
    assert len(episodes) == 1
    assert episodes[0].id == sample_episode.id


# Semantic Memory (Facts) Tests


@pytest.mark.asyncio
async def test_store_fact(memory_store, sample_fact):
    """Should store fact and return ID."""
    fact_id = await memory_store.store_fact(sample_fact)
    assert fact_id == sample_fact.id


@pytest.mark.asyncio
async def test_query_facts_basic(memory_store, sample_fact):
    """Should query facts for user."""
    await memory_store.store_fact(sample_fact)

    query = SemanticQuery(text="preferences")
    facts = await memory_store.query_facts("user-1", query)
    assert len(facts) == 1
    assert facts[0].id == sample_fact.id


@pytest.mark.asyncio
async def test_query_facts_filters_by_category(memory_store):
    """Should filter facts by category."""
    fact1 = Fact(
        id="fact_1",
        user_id="user-1",
        statement="Likes Python",
        category="technical_preference",
        confidence=1.0,
        source=None,
        verified=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    fact2 = Fact(
        id="fact_2",
        user_id="user-1",
        statement="Lives in NYC",
        category="location",
        confidence=1.0,
        source=None,
        verified=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await memory_store.store_fact(fact1)
    await memory_store.store_fact(fact2)

    query = SemanticQuery(text="test", categories=["technical_preference"])
    facts = await memory_store.query_facts("user-1", query)
    assert len(facts) == 1
    assert facts[0].category == "technical_preference"


@pytest.mark.asyncio
async def test_query_facts_filters_by_confidence(memory_store):
    """Should filter facts by minimum confidence."""
    fact1 = Fact(
        id="fact_1",
        user_id="user-1",
        statement="High confidence",
        category="test",
        confidence=0.9,
        source=None,
        verified=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    fact2 = Fact(
        id="fact_2",
        user_id="user-1",
        statement="Low confidence",
        category="test",
        confidence=0.3,
        source=None,
        verified=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await memory_store.store_fact(fact1)
    await memory_store.store_fact(fact2)

    query = SemanticQuery(text="test", min_confidence=0.5)
    facts = await memory_store.query_facts("user-1", query)
    assert len(facts) == 1
    assert facts[0].confidence >= 0.5


@pytest.mark.asyncio
async def test_query_facts_excludes_unverified(memory_store):
    """Should exclude unverified facts by default."""
    fact1 = Fact(
        id="fact_1",
        user_id="user-1",
        statement="Verified",
        category="test",
        confidence=1.0,
        source=None,
        verified=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    fact2 = Fact(
        id="fact_2",
        user_id="user-1",
        statement="Unverified",
        category="test",
        confidence=1.0,
        source=None,
        verified=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await memory_store.store_fact(fact1)
    await memory_store.store_fact(fact2)

    query = SemanticQuery(text="test", include_unverified=False)
    facts = await memory_store.query_facts("user-1", query)
    assert len(facts) == 1
    assert facts[0].verified is True


@pytest.mark.asyncio
async def test_update_fact(memory_store, sample_fact):
    """Should update existing fact."""
    await memory_store.store_fact(sample_fact)

    await memory_store.update_fact(
        sample_fact.id, {"confidence": 0.95, "verified": True}
    )

    query = SemanticQuery(text="test")
    facts = await memory_store.query_facts("user-1", query)
    assert facts[0].confidence == 0.95
    assert facts[0].verified is True


# Profile Tests


@pytest.mark.asyncio
async def test_get_profile_creates_empty_for_new_user(memory_store):
    """Should create empty profile for new user."""
    profile = await memory_store.get_profile("new-user")
    assert profile is not None
    assert profile.user_id == "new-user"
    assert profile.job_preferences == {}


@pytest.mark.asyncio
async def test_update_profile(memory_store):
    """Should update user profile."""
    # Get profile (creates empty one)
    await memory_store.get_profile("user-1")

    # Update profile
    await memory_store.update_profile(
        "user-1",
        {
            "job_preferences": {"roles": ["engineer"]},
        },
    )

    # Retrieve and verify
    updated_profile = await memory_store.get_profile("user-1")
    assert updated_profile.job_preferences == {"roles": ["engineer"]}


@pytest.mark.asyncio
async def test_delete_user_data(memory_store, sample_episode, sample_fact):
    """Should delete all user data (GDPR compliance)."""
    # Store data for user
    await memory_store.store_episode(sample_episode)
    await memory_store.store_fact(sample_fact)
    await memory_store.get_profile("user-1")  # Creates profile

    # Delete all user data
    await memory_store.delete_user_data("user-1")

    # Verify all data is deleted
    episodes = await memory_store.recall_episodes("user-1", "test")
    assert len(episodes) == 0

    query = SemanticQuery(text="test")
    facts = await memory_store.query_facts("user-1", query)
    assert len(facts) == 0

    # Profile should be recreated as empty
    profile = await memory_store.get_profile("user-1")
    assert profile.job_preferences == {}
