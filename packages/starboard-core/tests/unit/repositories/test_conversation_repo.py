"""Tests for ConversationRepository.

Tests cover:
- Get or create conversation
- Get conversation by ID
- Add message to conversation
- Get recent messages
- List conversations for user
- Set conversation title
- Delete conversation
- Save/load agent context
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.models.conversation import (
    Conversation,
    ConversationMetadata,
    Message,
)
from starboard_core.repositories.conversation import ConversationRepository


@pytest.fixture
def mock_store():
    """Create a mock StateStore."""
    store = AsyncMock()
    return store


@pytest.fixture
def conversation_repo(mock_store):
    """Create a ConversationRepository with mock store."""
    return ConversationRepository(mock_store)


@pytest.fixture
def sample_conversation():
    """Create a sample conversation."""
    now = datetime.now(UTC)
    return Conversation(
        id="conv_123",
        user_id="user_456",
        messages=[
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ],
        created_at=now,
        updated_at=now,
        title="Test conversation",
    )


class TestGetOrCreate:
    """Tests for get_or_create method."""

    @pytest.mark.asyncio
    async def test_returns_existing_conversation(
        self, conversation_repo, mock_store, sample_conversation
    ):
        """Test that existing conversation is returned."""
        mock_store.get_conversation.return_value = sample_conversation

        result = await conversation_repo.get_or_create("conv_123", "user_456")

        assert result == sample_conversation
        mock_store.get_conversation.assert_called_once_with("conv_123")
        mock_store.save_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_conversation_when_not_found(
        self, conversation_repo, mock_store
    ):
        """Test that new conversation is created if not found."""
        mock_store.get_conversation.return_value = None

        result = await conversation_repo.get_or_create("new_conv", "user_789")

        assert result.id == "new_conv"
        assert result.user_id == "user_789"
        assert result.messages == []
        mock_store.save_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_conversation_has_timestamps(self, conversation_repo, mock_store):
        """Test that new conversation has created_at and updated_at."""
        mock_store.get_conversation.return_value = None

        result = await conversation_repo.get_or_create("conv_id", "user_id")

        assert result.created_at is not None
        assert result.updated_at is not None
        assert isinstance(result.created_at, datetime)
        assert isinstance(result.updated_at, datetime)


class TestGet:
    """Tests for get method."""

    @pytest.mark.asyncio
    async def test_returns_conversation_when_found(
        self, conversation_repo, mock_store, sample_conversation
    ):
        """Test that conversation is returned when found."""
        mock_store.get_conversation.return_value = sample_conversation

        result = await conversation_repo.get("conv_123")

        assert result == sample_conversation
        mock_store.get_conversation.assert_called_once_with("conv_123")

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, conversation_repo, mock_store):
        """Test that None is returned when conversation not found."""
        mock_store.get_conversation.return_value = None

        result = await conversation_repo.get("nonexistent")

        assert result is None


class TestAddMessage:
    """Tests for add_message method."""

    @pytest.mark.asyncio
    async def test_adds_message_to_conversation(
        self, conversation_repo, mock_store, sample_conversation
    ):
        """Test that message is added to conversation."""
        mock_store.get_conversation.return_value = sample_conversation
        new_message = Message(role="user", content="New message")

        await conversation_repo.add_message("conv_123", new_message)

        assert len(sample_conversation.messages) == 3
        assert sample_conversation.messages[-1] == new_message
        mock_store.save_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_conversation_timestamp(
        self, conversation_repo, mock_store, sample_conversation
    ):
        """Test that updated_at is updated when adding message."""
        original_updated_at = sample_conversation.updated_at
        mock_store.get_conversation.return_value = sample_conversation
        new_message = Message(role="user", content="New message")

        await conversation_repo.add_message("conv_123", new_message)

        assert sample_conversation.updated_at >= original_updated_at

    @pytest.mark.asyncio
    async def test_raises_error_when_conversation_not_found(
        self, conversation_repo, mock_store
    ):
        """Test that ValueError is raised when conversation not found."""
        mock_store.get_conversation.return_value = None
        new_message = Message(role="user", content="New message")

        with pytest.raises(ValueError, match="Conversation nonexistent not found"):
            await conversation_repo.add_message("nonexistent", new_message)


class TestGetRecentMessages:
    """Tests for get_recent_messages method."""

    @pytest.mark.asyncio
    async def test_returns_recent_messages(
        self, conversation_repo, mock_store, sample_conversation
    ):
        """Test that recent messages are returned."""
        mock_store.get_conversation.return_value = sample_conversation

        result = await conversation_repo.get_recent_messages("conv_123")

        assert len(result) == 2
        assert result[0].content == "Hello"
        assert result[1].content == "Hi there!"

    @pytest.mark.asyncio
    async def test_respects_limit(self, conversation_repo, mock_store):
        """Test that limit parameter is respected."""
        now = datetime.now(UTC)
        conv = Conversation(
            id="conv_123",
            user_id="user_456",
            messages=[Message(role="user", content=f"Message {i}") for i in range(30)],
            created_at=now,
            updated_at=now,
        )
        mock_store.get_conversation.return_value = conv

        result = await conversation_repo.get_recent_messages("conv_123", limit=5)

        assert len(result) == 5
        # Should return the last 5 messages
        assert result[0].content == "Message 25"
        assert result[-1].content == "Message 29"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_not_found(
        self, conversation_repo, mock_store
    ):
        """Test that empty list is returned when conversation not found."""
        mock_store.get_conversation.return_value = None

        result = await conversation_repo.get_recent_messages("nonexistent")

        assert result == []


class TestListForUser:
    """Tests for list_for_user method."""

    @pytest.mark.asyncio
    async def test_returns_conversation_list(self, conversation_repo, mock_store):
        """Test that conversation list is returned."""
        metadata_list = [
            ConversationMetadata(
                id="conv_1",
                user_id="user_456",
                title="First conversation",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                message_count=5,
                last_message_preview="Last message preview",
            ),
            ConversationMetadata(
                id="conv_2",
                user_id="user_456",
                title="Second conversation",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                message_count=10,
                last_message_preview="Another preview",
            ),
        ]
        mock_store.list_conversations.return_value = metadata_list

        result = await conversation_repo.list_for_user("user_456")

        assert len(result) == 2
        mock_store.list_conversations.assert_called_once_with("user_456", 50, 0)

    @pytest.mark.asyncio
    async def test_passes_pagination_params(self, conversation_repo, mock_store):
        """Test that limit and offset are passed to store."""
        mock_store.list_conversations.return_value = []

        await conversation_repo.list_for_user("user_456", limit=10, offset=20)

        mock_store.list_conversations.assert_called_once_with("user_456", 10, 20)


class TestSetTitle:
    """Tests for set_title method."""

    @pytest.mark.asyncio
    async def test_updates_title(self, conversation_repo, mock_store):
        """Test that title is updated via metadata."""
        await conversation_repo.set_title("conv_123", "New Title")

        mock_store.update_metadata.assert_called_once_with(
            "conv_123", {"title": "New Title"}
        )


class TestDelete:
    """Tests for delete method."""

    @pytest.mark.asyncio
    async def test_delete_existing_conversation(self, conversation_repo, mock_store):
        """Test deleting an existing conversation."""
        mock_store.delete_conversation.return_value = True

        result = await conversation_repo.delete("conv_123")

        assert result is True
        mock_store.delete_conversation.assert_called_once_with("conv_123")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_conversation(self, conversation_repo, mock_store):
        """Test deleting a non-existent conversation."""
        mock_store.delete_conversation.return_value = False

        result = await conversation_repo.delete("nonexistent")

        assert result is False


class TestSaveContext:
    """Tests for save_context method (multi-agent orchestration)."""

    @pytest.mark.asyncio
    async def test_saves_context_to_existing_conversation(
        self, conversation_repo, mock_store, sample_conversation
    ):
        """Test saving context to existing conversation."""
        mock_store.get_conversation.return_value = sample_conversation

        # Create a mock context object
        context = MagicMock()
        context.conversation_id = "conv_123"
        context.user_id = "user_456"
        context.conversation_history = [Message(role="user", content="Test")]
        context.working_memory = MagicMock()
        context.working_memory.to_dict.return_value = {"key": "value"}
        context.agent_transitions = []
        context.metadata = {"some": "data"}

        await conversation_repo.save_context(context)

        mock_store.save_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_conversation_when_saving_context_if_not_exists(
        self, conversation_repo, mock_store
    ):
        """Test that conversation is created if not found when saving context."""
        mock_store.get_conversation.return_value = None

        context = MagicMock()
        context.conversation_id = "new_conv"
        context.user_id = "user_789"
        context.conversation_history = []
        context.working_memory = MagicMock()
        context.working_memory.to_dict.return_value = {}
        context.agent_transitions = []
        context.metadata = {}

        await conversation_repo.save_context(context)

        mock_store.save_conversation.assert_called_once()
        saved_conv = mock_store.save_conversation.call_args[0][0]
        assert saved_conv.id == "new_conv"
        assert saved_conv.user_id == "user_789"


class TestLoadContext:
    """Tests for load_context method (multi-agent orchestration)."""

    @pytest.mark.asyncio
    async def test_loads_context_from_conversation(
        self, conversation_repo, mock_store, sample_conversation
    ):
        """Test loading context from conversation."""
        sample_conversation.metadata["working_memory"] = {"tool_results": []}
        sample_conversation.metadata["agent_transitions"] = [{"from": "A", "to": "B"}]
        sample_conversation.metadata["context_metadata"] = {"source": "test"}
        mock_store.get_conversation.return_value = sample_conversation

        result = await conversation_repo.load_context("conv_123")

        assert result["conversation_id"] == "conv_123"
        assert result["user_id"] == "user_456"
        assert len(result["conversation_history"]) == 2
        assert result["working_memory"] == {"tool_results": []}
        assert result["agent_transitions"] == [{"from": "A", "to": "B"}]
        assert result["metadata"] == {"source": "test"}

    @pytest.mark.asyncio
    async def test_returns_none_when_conversation_not_found(
        self, conversation_repo, mock_store
    ):
        """Test that None is returned when conversation not found."""
        mock_store.get_conversation.return_value = None

        result = await conversation_repo.load_context("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_missing_metadata_fields(
        self, conversation_repo, mock_store, sample_conversation
    ):
        """Test that missing metadata fields default to empty."""
        # metadata dict is empty by default
        sample_conversation.metadata = {}
        mock_store.get_conversation.return_value = sample_conversation

        result = await conversation_repo.load_context("conv_123")

        assert result["working_memory"] == {}
        assert result["agent_transitions"] == []
        assert result["metadata"] == {}
