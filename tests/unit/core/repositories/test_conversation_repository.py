# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for conversation repository."""

import pytest
from starboard_core.models.conversation import Message
from starboard_core.repositories.conversation import ConversationRepository
from starboard_server.adapters.state.inmemory import InMemoryStateStore


@pytest.fixture
def state_store():
    """Create a fresh state store for each test."""
    return InMemoryStateStore()


@pytest.fixture
def conversation_repo(state_store):
    """Create conversation repository with in-memory store."""
    return ConversationRepository(state_store)


@pytest.mark.asyncio
async def test_get_or_create_new_conversation(conversation_repo):
    """Should create new conversation if doesn't exist."""
    conv = await conversation_repo.get_or_create("conv-1", "user-1")
    assert conv is not None
    assert conv.id == "conv-1"
    assert conv.user_id == "user-1"
    assert len(conv.messages) == 0


@pytest.mark.asyncio
async def test_get_or_create_existing_conversation(conversation_repo):
    """Should return existing conversation."""
    # Create conversation
    conv1 = await conversation_repo.get_or_create("conv-1", "user-1")

    # Get same conversation
    conv2 = await conversation_repo.get_or_create("conv-1", "user-1")

    assert conv1.id == conv2.id


@pytest.mark.asyncio
async def test_get_nonexistent_conversation(conversation_repo):
    """Should return None for non-existent conversation."""
    conv = await conversation_repo.get("nonexistent")
    assert conv is None


@pytest.mark.asyncio
async def test_add_message(conversation_repo):
    """Should add message to conversation."""
    # Create conversation
    await conversation_repo.get_or_create("conv-1", "user-1")

    # Add message
    message = Message(role="user", content="Hello")
    await conversation_repo.add_message("conv-1", message)

    # Verify message was added
    conv = await conversation_repo.get("conv-1")
    assert len(conv.messages) == 1
    assert conv.messages[0].content == "Hello"


@pytest.mark.asyncio
async def test_add_message_to_nonexistent_conversation(conversation_repo):
    """Should raise error when adding message to non-existent conversation."""
    message = Message(role="user", content="Hello")

    with pytest.raises(ValueError, match="Conversation .* not found"):
        await conversation_repo.add_message("nonexistent", message)


@pytest.mark.asyncio
async def test_get_recent_messages(conversation_repo):
    """Should get recent messages."""
    # Create conversation with messages
    await conversation_repo.get_or_create("conv-1", "user-1")

    for i in range(5):
        message = Message(role="user", content=f"Message {i}")
        await conversation_repo.add_message("conv-1", message)

    # Get recent messages (last 3)
    recent = await conversation_repo.get_recent_messages("conv-1", limit=3)
    assert len(recent) == 3
    assert recent[0].content == "Message 2"
    assert recent[2].content == "Message 4"


@pytest.mark.asyncio
async def test_get_recent_messages_empty_conversation(conversation_repo):
    """Should return empty list for conversation with no messages."""
    recent = await conversation_repo.get_recent_messages("nonexistent", limit=10)
    assert len(recent) == 0


@pytest.mark.asyncio
async def test_list_for_user(conversation_repo):
    """Should list conversations for user."""
    # Create multiple conversations
    await conversation_repo.get_or_create("conv-1", "user-1")
    await conversation_repo.get_or_create("conv-2", "user-1")
    await conversation_repo.get_or_create("conv-3", "user-2")

    # List for user-1
    result = await conversation_repo.list_for_user("user-1")
    assert len(result) == 2
    assert all(m.user_id == "user-1" for m in result)


@pytest.mark.asyncio
async def test_set_title(conversation_repo):
    """Should set conversation title."""
    await conversation_repo.get_or_create("conv-1", "user-1")

    await conversation_repo.set_title("conv-1", "My Conversation")

    conv = await conversation_repo.get("conv-1")
    assert conv.title == "My Conversation"


@pytest.mark.asyncio
async def test_delete_conversation(conversation_repo):
    """Should delete conversation."""
    await conversation_repo.get_or_create("conv-1", "user-1")

    deleted = await conversation_repo.delete("conv-1")
    assert deleted is True

    conv = await conversation_repo.get("conv-1")
    assert conv is None


@pytest.mark.asyncio
async def test_delete_nonexistent_conversation(conversation_repo):
    """Should return False when deleting non-existent conversation."""
    deleted = await conversation_repo.delete("nonexistent")
    assert deleted is False
