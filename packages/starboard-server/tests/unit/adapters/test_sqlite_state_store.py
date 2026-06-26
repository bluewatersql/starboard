# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for SQLite state store."""

from datetime import UTC, datetime

import pytest
from starboard_core.models.conversation import (
    Conversation,
    ConversationMetadata,
    Message,
)
from starboard_server.adapters.state.sqlite.state_store import SQLiteStateStore


@pytest.fixture
async def state_store():
    """Create in-memory SQLite state store for testing."""
    store = SQLiteStateStore(":memory:")
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
def sample_conversation():
    """Create a sample conversation for testing."""
    return Conversation(
        id="conv_123",
        user_id="user_456",
        messages=[
            Message(
                role="user",
                content="Hello",
                timestamp=datetime.now(UTC),
            ),
            Message(
                role="assistant",
                content="Hi there!",
                timestamp=datetime.now(UTC),
            ),
        ],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        title="Test Conversation",
        tags=["test", "example"],
        archived=False,
    )


class TestSQLiteStateStore:
    """Test suite for SQLiteStateStore."""

    @pytest.mark.unit
    async def test_init_creates_tables(self):
        """Test that connect() initializes schema."""
        store = SQLiteStateStore(":memory:")
        await store.connect()

        # Verify table exists by querying it
        async with store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'"
        ) as cursor:
            result = await cursor.fetchone()

        assert result is not None
        assert result[0] == "conversations"

        await store.close()

    @pytest.mark.unit
    async def test_save_and_get_conversation(self, state_store, sample_conversation):
        """Test saving and retrieving a conversation."""
        # Save conversation
        await state_store.save_conversation(sample_conversation)

        # Retrieve conversation
        retrieved = await state_store.get_conversation(sample_conversation.id)

        assert retrieved is not None
        assert retrieved.id == sample_conversation.id
        assert retrieved.user_id == sample_conversation.user_id
        assert retrieved.title == sample_conversation.title
        assert retrieved.tags == sample_conversation.tags
        assert len(retrieved.messages) == len(sample_conversation.messages)

    @pytest.mark.unit
    async def test_get_nonexistent_conversation(self, state_store):
        """Test getting a conversation that doesn't exist."""
        result = await state_store.get_conversation("nonexistent_id")
        assert result is None

    @pytest.mark.unit
    async def test_update_conversation(self, state_store, sample_conversation):
        """Test updating an existing conversation."""
        # Save initial conversation
        await state_store.save_conversation(sample_conversation)

        # Update conversation
        updated = Conversation(
            id=sample_conversation.id,
            user_id=sample_conversation.user_id,
            messages=sample_conversation.messages
            + [
                Message(
                    role="user",
                    content="Another message",
                    timestamp=datetime.now(UTC),
                )
            ],
            created_at=sample_conversation.created_at,
            updated_at=datetime.now(UTC),
            title="Updated Title",
            tags=["updated"],
            archived=False,
        )

        await state_store.save_conversation(updated)

        # Retrieve and verify
        retrieved = await state_store.get_conversation(sample_conversation.id)
        assert retrieved is not None
        assert retrieved.title == "Updated Title"
        assert retrieved.tags == ["updated"]
        assert len(retrieved.messages) == 3

    @pytest.mark.unit
    async def test_delete_conversation(self, state_store, sample_conversation):
        """Test deleting a conversation."""
        # Save conversation
        await state_store.save_conversation(sample_conversation)

        # Delete conversation
        result = await state_store.delete_conversation(sample_conversation.id)
        assert result is True

        # Verify deletion
        retrieved = await state_store.get_conversation(sample_conversation.id)
        assert retrieved is None

    @pytest.mark.unit
    async def test_delete_nonexistent_conversation(self, state_store):
        """Test deleting a conversation that doesn't exist."""
        result = await state_store.delete_conversation("nonexistent_id")
        assert result is False

    @pytest.mark.unit
    async def test_list_conversations(self, state_store):
        """Test listing conversations for a user."""
        user_id = "user_123"

        # Create multiple conversations
        conversations = [
            Conversation(
                id=f"conv_{i}",
                user_id=user_id,
                messages=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                title=f"Conversation {i}",
                tags=[],
                archived=False,
            )
            for i in range(5)
        ]

        # Save all conversations
        for conv in conversations:
            await state_store.save_conversation(conv)

        # List conversations
        result = await state_store.list_conversations(user_id, limit=10)

        assert len(result) == 5
        assert all(isinstance(item, ConversationMetadata) for item in result)
        assert all(item.user_id == user_id for item in result)

    @pytest.mark.unit
    async def test_list_conversations_pagination(self, state_store):
        """Test pagination in list_conversations."""
        user_id = "user_123"

        # Create 10 conversations
        for i in range(10):
            conv = Conversation(
                id=f"conv_{i}",
                user_id=user_id,
                messages=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                title=f"Conversation {i}",
                tags=[],
                archived=False,
            )
            await state_store.save_conversation(conv)

        # Get first page
        page1 = await state_store.list_conversations(user_id, limit=5, offset=0)
        assert len(page1) == 5

        # Get second page
        page2 = await state_store.list_conversations(user_id, limit=5, offset=5)
        assert len(page2) == 5

        # Verify no overlap
        page1_ids = {item.id for item in page1}
        page2_ids = {item.id for item in page2}
        assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.unit
    async def test_list_conversations_filters_archived(self, state_store):
        """Test that archived conversations are filtered out."""
        user_id = "user_123"

        # Create active conversation
        active_conv = Conversation(
            id="conv_active",
            user_id=user_id,
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            title="Active",
            tags=[],
            archived=False,
        )
        await state_store.save_conversation(active_conv)

        # Create archived conversation
        archived_conv = Conversation(
            id="conv_archived",
            user_id=user_id,
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            title="Archived",
            tags=[],
            archived=True,
        )
        await state_store.save_conversation(archived_conv)

        # List conversations
        result = await state_store.list_conversations(user_id)

        # Only active conversation should be returned
        assert len(result) == 1
        assert result[0].id == "conv_active"

    @pytest.mark.unit
    async def test_update_metadata(self, state_store, sample_conversation):
        """Test updating conversation metadata."""
        # Save conversation
        await state_store.save_conversation(sample_conversation)

        # Update metadata
        await state_store.update_metadata(
            sample_conversation.id,
            {"title": "New Title", "tags": ["updated", "metadata"]},
        )

        # Verify update
        retrieved = await state_store.get_conversation(sample_conversation.id)
        assert retrieved is not None
        assert retrieved.title == "New Title"
        assert retrieved.tags == ["updated", "metadata"]

    @pytest.mark.unit
    async def test_update_metadata_nonexistent_conversation(self, state_store):
        """Test updating metadata for non-existent conversation."""
        with pytest.raises(ValueError, match="not found"):
            await state_store.update_metadata(
                "nonexistent_id",
                {"title": "New Title"},
            )

    @pytest.mark.unit
    async def test_concurrent_operations(self, state_store):
        """Test concurrent save operations."""
        import asyncio

        conversations = [
            Conversation(
                id=f"conv_{i}",
                user_id="user_123",
                messages=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                title=f"Conversation {i}",
                tags=[],
                archived=False,
            )
            for i in range(10)
        ]

        # Save all concurrently
        await asyncio.gather(
            *[state_store.save_conversation(conv) for conv in conversations]
        )

        # Verify all were saved
        result = await state_store.list_conversations("user_123", limit=20)
        assert len(result) == 10

    @pytest.mark.unit
    async def test_file_based_persistence(self, tmp_path):
        """Test file-based SQLite with persistence across connections."""
        db_path = str(tmp_path / "test.db")

        # Create store and save conversation
        store1 = SQLiteStateStore(db_path)
        await store1.connect()

        conv = Conversation(
            id="conv_123",
            user_id="user_456",
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            title="Test",
            tags=[],
            archived=False,
        )
        await store1.save_conversation(conv)
        await store1.close()

        # Open new store and verify conversation persisted
        store2 = SQLiteStateStore(db_path)
        await store2.connect()
        retrieved = await store2.get_conversation("conv_123")
        await store2.close()

        assert retrieved is not None
        assert retrieved.id == "conv_123"
        assert retrieved.title == "Test"

    @pytest.mark.unit
    async def test_special_characters_in_content(self, state_store):
        """Test handling of special characters in conversation content."""
        conv = Conversation(
            id="conv_special",
            user_id="user_123",
            messages=[
                Message(
                    role="user",
                    content="Test with 'quotes' and \"double quotes\" and special chars: {}[]<>",
                    timestamp=datetime.now(UTC),
                )
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            title="Test with 'special' chars",
            tags=["test's", 'another"tag'],
            archived=False,
        )

        await state_store.save_conversation(conv)
        retrieved = await state_store.get_conversation("conv_special")

        assert retrieved is not None
        assert retrieved.title == conv.title
        assert retrieved.tags == conv.tags
        assert retrieved.messages[0].content == conv.messages[0].content

    @pytest.mark.unit
    async def test_empty_messages_list(self, state_store):
        """Test conversation with empty messages list."""
        conv = Conversation(
            id="conv_empty",
            user_id="user_123",
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            title="Empty",
            tags=[],
            archived=False,
        )

        await state_store.save_conversation(conv)
        retrieved = await state_store.get_conversation("conv_empty")

        assert retrieved is not None
        assert len(retrieved.messages) == 0

    @pytest.mark.unit
    async def test_large_conversation(self, state_store):
        """Test conversation with many messages."""
        # Create conversation with 100 messages
        messages = [
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
                timestamp=datetime.now(UTC),
            )
            for i in range(100)
        ]

        conv = Conversation(
            id="conv_large",
            user_id="user_123",
            messages=messages,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            title="Large Conversation",
            tags=[],
            archived=False,
        )

        await state_store.save_conversation(conv)
        retrieved = await state_store.get_conversation("conv_large")

        assert retrieved is not None
        assert len(retrieved.messages) == 100
