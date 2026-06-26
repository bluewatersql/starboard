# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for Postgres state store (requires running Postgres)."""

import os
from datetime import UTC, datetime

import pytest
from starboard_core.models.conversation import Conversation, Message
from starboard_server.adapters.state.postgres import PostgresStateStore


@pytest.fixture(scope="module")
async def postgres_store():
    """
    Create Postgres store for testing.

    Requires:
        TEST_DATABASE_URL environment variable with Postgres connection string
    """
    db_url = os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("TEST_DATABASE_URL not set")

    store = PostgresStateStore(db_url)
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
async def cleanup_conversations(postgres_store):
    """Clean up test conversations after each test."""
    test_conversation_ids = []

    def register_conversation(conversation_id: str):
        test_conversation_ids.append(conversation_id)

    yield register_conversation

    # Cleanup
    for conversation_id in test_conversation_ids:
        await postgres_store.delete_conversation(conversation_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_save_and_get_conversation(postgres_store, cleanup_conversations):
    """Should save and retrieve conversation."""
    conv_id = f"test-conv-{datetime.now(UTC).timestamp()}"
    cleanup_conversations(conv_id)

    conv = Conversation(
        id=conv_id,
        user_id="test-user-1",
        messages=[Message(role="user", content="Test message")],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    await postgres_store.save_conversation(conv)

    retrieved = await postgres_store.get_conversation(conv_id)
    assert retrieved is not None
    assert retrieved.id == conv_id
    assert len(retrieved.messages) == 1
    assert retrieved.messages[0].content == "Test message"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_conversation(postgres_store, cleanup_conversations):
    """Should update existing conversation."""
    conv_id = f"test-conv-{datetime.now(UTC).timestamp()}"
    cleanup_conversations(conv_id)

    # Create conversation
    conv = Conversation(
        id=conv_id,
        user_id="test-user-1",
        messages=[Message(role="user", content="First message")],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await postgres_store.save_conversation(conv)

    # Update conversation
    conv.messages.append(Message(role="assistant", content="Second message"))
    await postgres_store.save_conversation(conv)

    # Verify update
    retrieved = await postgres_store.get_conversation(conv_id)
    assert retrieved is not None
    assert len(retrieved.messages) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_conversation(postgres_store, cleanup_conversations):
    """Should delete conversation."""
    conv_id = f"test-conv-{datetime.now(UTC).timestamp()}"
    cleanup_conversations(conv_id)

    conv = Conversation(
        id=conv_id,
        user_id="test-user-1",
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await postgres_store.save_conversation(conv)

    # Delete
    deleted = await postgres_store.delete_conversation(conv_id)
    assert deleted is True

    # Verify deletion
    retrieved = await postgres_store.get_conversation(conv_id)
    assert retrieved is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_conversations(postgres_store, cleanup_conversations):
    """Should list conversations for user."""
    user_id = f"test-user-{datetime.now(UTC).timestamp()}"

    # Create multiple conversations
    conv_ids = []
    for i in range(3):
        conv_id = f"test-conv-{user_id}-{i}"
        conv_ids.append(conv_id)
        cleanup_conversations(conv_id)

        conv = Conversation(
            id=conv_id,
            user_id=user_id,
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await postgres_store.save_conversation(conv)

    # List conversations
    result = await postgres_store.list_conversations(user_id, limit=10)
    assert len(result) == 3
    assert all(m.user_id == user_id for m in result)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_metadata(postgres_store, cleanup_conversations):
    """Should update conversation metadata."""
    conv_id = f"test-conv-{datetime.now(UTC).timestamp()}"
    cleanup_conversations(conv_id)

    conv = Conversation(
        id=conv_id,
        user_id="test-user-1",
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await postgres_store.save_conversation(conv)

    # Update metadata
    await postgres_store.update_metadata(conv_id, {"title": "Test Title"})

    # Verify update
    retrieved = await postgres_store.get_conversation(conv_id)
    assert retrieved is not None
    assert retrieved.title == "Test Title"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_nonexistent_conversation(postgres_store):
    """Should return None for non-existent conversation."""
    result = await postgres_store.get_conversation("nonexistent-conv")
    assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conversation_with_metadata(postgres_store, cleanup_conversations):
    """Should preserve conversation metadata."""
    conv_id = f"test-conv-{datetime.now(UTC).timestamp()}"
    cleanup_conversations(conv_id)

    conv = Conversation(
        id=conv_id,
        user_id="test-user-1",
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        title="Test Conversation",
        tags=["test", "integration"],
        metadata={"custom_field": "custom_value"},
    )
    await postgres_store.save_conversation(conv)

    retrieved = await postgres_store.get_conversation(conv_id)
    assert retrieved is not None
    assert retrieved.title == "Test Conversation"
    assert retrieved.tags == ["test", "integration"]
    assert retrieved.metadata["custom_field"] == "custom_value"
