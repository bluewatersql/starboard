"""Tests for in-memory state store."""

from datetime import UTC, datetime

import pytest
from starboard_core.models.conversation import Conversation, Message
from starboard_server.adapters.state.inmemory import InMemoryStateStore


@pytest.fixture
def store():
    """Create a fresh in-memory store for each test."""
    return InMemoryStateStore()


@pytest.fixture
def sample_conversation():
    """Create a sample conversation for testing."""
    return Conversation(
        id="conv-1",
        user_id="user-1",
        messages=[
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_get_conversation_not_found(store):
    """Should return None for non-existent conversation."""
    result = await store.get_conversation("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_save_and_get_conversation(store, sample_conversation):
    """Should save and retrieve conversation."""
    await store.save_conversation(sample_conversation)

    retrieved = await store.get_conversation("conv-1")
    assert retrieved is not None
    assert retrieved.id == "conv-1"
    assert retrieved.user_id == "user-1"
    assert len(retrieved.messages) == 2


@pytest.mark.asyncio
async def test_update_existing_conversation(store, sample_conversation):
    """Should update existing conversation on save."""
    await store.save_conversation(sample_conversation)

    # Update conversation
    sample_conversation.messages.append(Message(role="user", content="Another message"))
    await store.save_conversation(sample_conversation)

    retrieved = await store.get_conversation("conv-1")
    assert retrieved is not None
    assert len(retrieved.messages) == 3


@pytest.mark.asyncio
async def test_delete_conversation(store, sample_conversation):
    """Should delete conversation."""
    await store.save_conversation(sample_conversation)

    deleted = await store.delete_conversation("conv-1")
    assert deleted is True

    retrieved = await store.get_conversation("conv-1")
    assert retrieved is None


@pytest.mark.asyncio
async def test_delete_nonexistent_conversation(store):
    """Should return False when deleting non-existent conversation."""
    deleted = await store.delete_conversation("nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_list_conversations_empty(store):
    """Should return empty list for user with no conversations."""
    result = await store.list_conversations("user-1", limit=10)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_list_conversations(store):
    """Should list conversations for user."""
    # Create multiple conversations
    for i in range(3):
        conv = Conversation(
            id=f"conv-{i}",
            user_id="user-1",
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await store.save_conversation(conv)

    # List conversations
    result = await store.list_conversations("user-1", limit=10)
    assert len(result) == 3
    assert all(m.user_id == "user-1" for m in result)


@pytest.mark.asyncio
async def test_list_conversations_filters_by_user(store):
    """Should only list conversations for specified user."""
    # Create conversations for different users
    conv1 = Conversation(
        id="conv-1",
        user_id="user-1",
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    conv2 = Conversation(
        id="conv-2",
        user_id="user-2",
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await store.save_conversation(conv1)
    await store.save_conversation(conv2)

    # List for user-1
    result = await store.list_conversations("user-1")
    assert len(result) == 1
    assert result[0].user_id == "user-1"


@pytest.mark.asyncio
async def test_list_conversations_excludes_archived(store):
    """Should exclude archived conversations."""
    # Create active and archived conversations
    active = Conversation(
        id="conv-active",
        user_id="user-1",
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        archived=False,
    )
    archived = Conversation(
        id="conv-archived",
        user_id="user-1",
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        archived=True,
    )
    await store.save_conversation(active)
    await store.save_conversation(archived)

    # List conversations (should exclude archived)
    result = await store.list_conversations("user-1")
    assert len(result) == 1
    assert result[0].id == "conv-active"


@pytest.mark.asyncio
async def test_list_conversations_pagination(store):
    """Should paginate conversation list."""
    # Create 10 conversations
    for i in range(10):
        conv = Conversation(
            id=f"conv-{i}",
            user_id="user-1",
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await store.save_conversation(conv)

    # Get first page
    page1 = await store.list_conversations("user-1", limit=3, offset=0)
    assert len(page1) == 3

    # Get second page
    page2 = await store.list_conversations("user-1", limit=3, offset=3)
    assert len(page2) == 3

    # Pages should be different
    page1_ids = {m.id for m in page1}
    page2_ids = {m.id for m in page2}
    assert page1_ids.isdisjoint(page2_ids)


@pytest.mark.asyncio
async def test_update_metadata(store, sample_conversation):
    """Should update conversation metadata."""
    await store.save_conversation(sample_conversation)

    # Update title
    await store.update_metadata("conv-1", {"title": "New Title"})

    retrieved = await store.get_conversation("conv-1")
    assert retrieved is not None
    assert retrieved.title == "New Title"


@pytest.mark.asyncio
async def test_update_metadata_nonexistent(store):
    """Should raise error when updating non-existent conversation."""
    with pytest.raises(ValueError, match="Conversation .* not found"):
        await store.update_metadata("nonexistent", {"title": "Test"})


@pytest.mark.asyncio
async def test_update_metadata_updates_timestamp(store, sample_conversation):
    """Should update updated_at timestamp when updating metadata."""
    await store.save_conversation(sample_conversation)

    original_updated_at = sample_conversation.updated_at

    # Small delay to ensure timestamp changes
    import asyncio

    await asyncio.sleep(0.01)

    await store.update_metadata("conv-1", {"title": "New Title"})

    retrieved = await store.get_conversation("conv-1")
    assert retrieved is not None
    assert retrieved.updated_at > original_updated_at
