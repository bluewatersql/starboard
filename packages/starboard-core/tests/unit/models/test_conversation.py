"""Tests for conversation domain models.

Tests cover:
- Message creation and serialization
- Conversation entity management
- ConversationMetadata extraction
- Timestamp handling
"""

from datetime import UTC, datetime

from starboard_core.models.conversation import (
    Conversation,
    ConversationMetadata,
    Message,
)


class TestMessage:
    """Tests for Message dataclass."""

    def test_create_message(self):
        """Test creating a message."""
        msg = Message(role="user", content="Hello world")

        assert msg.role == "user"
        assert msg.content == "Hello world"
        assert msg.tool_calls == []
        assert msg.metadata == {}
        assert isinstance(msg.timestamp, datetime)

    def test_message_with_tool_calls(self):
        """Test message with tool calls."""
        tool_calls = [{"name": "query_tool", "args": {}}]
        msg = Message(role="assistant", content="Result", tool_calls=tool_calls)

        assert msg.role == "assistant"
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "query_tool"

    def test_message_to_dict(self):
        """Test message serialization."""
        msg = Message(
            role="system",
            content="System message",
            metadata={"priority": "high"},
        )

        result = msg.to_dict()

        assert result["role"] == "system"
        assert result["content"] == "System message"
        assert "timestamp" in result
        assert result["metadata"]["priority"] == "high"

    def test_message_from_dict(self):
        """Test message deserialization."""
        data = {
            "role": "user",
            "content": "Test content",
            "timestamp": "2024-01-01T12:00:00+00:00",
            "tool_calls": [],
            "metadata": {"key": "value"},
        }

        msg = Message.from_dict(data)

        assert msg.role == "user"
        assert msg.content == "Test content"
        assert msg.metadata["key"] == "value"

    def test_message_from_dict_missing_timestamp(self):
        """Test deserialization with missing timestamp."""
        data = {"role": "user", "content": "Test"}

        msg = Message.from_dict(data)

        assert msg.role == "user"
        assert isinstance(msg.timestamp, datetime)

    def test_message_from_dict_missing_optional_fields(self):
        """Test deserialization with missing optional fields."""
        data = {"role": "user", "content": "Test", "timestamp": "2024-01-01T12:00:00"}

        msg = Message.from_dict(data)

        assert msg.tool_calls == []
        assert msg.metadata == {}


class TestConversation:
    """Tests for Conversation dataclass."""

    def test_create_conversation(self):
        """Test creating a conversation."""
        now = datetime.now(UTC)
        messages = [Message(role="user", content="Hello")]

        conv = Conversation(
            id="conv_123",
            user_id="user_456",
            messages=messages,
            created_at=now,
            updated_at=now,
        )

        assert conv.id == "conv_123"
        assert conv.user_id == "user_456"
        assert len(conv.messages) == 1
        assert conv.title is None
        assert conv.tags == []
        assert conv.archived is False

    def test_conversation_with_title_and_tags(self):
        """Test conversation with optional fields."""
        now = datetime.now(UTC)

        conv = Conversation(
            id="conv_123",
            user_id="user_456",
            messages=[],
            created_at=now,
            updated_at=now,
            title="Test conversation",
            tags=["important", "urgent"],
            archived=True,
        )

        assert conv.title == "Test conversation"
        assert conv.tags == ["important", "urgent"]
        assert conv.archived is True

    def test_conversation_to_dict(self):
        """Test conversation serialization."""
        now = datetime.now(UTC)
        messages = [Message(role="user", content="Test")]

        conv = Conversation(
            id="conv_123",
            user_id="user_456",
            messages=messages,
            created_at=now,
            updated_at=now,
            title="Test",
        )

        result = conv.to_dict()

        assert result["id"] == "conv_123"
        assert result["user_id"] == "user_456"
        assert len(result["messages"]) == 1
        assert result["title"] == "Test"

    def test_conversation_from_dict(self):
        """Test conversation deserialization."""
        data = {
            "id": "conv_123",
            "user_id": "user_456",
            "messages": [
                {"role": "user", "content": "Hello", "timestamp": "2024-01-01T12:00:00"}
            ],
            "created_at": "2024-01-01T12:00:00",
            "updated_at": "2024-01-01T12:30:00",
            "title": "Test conversation",
            "tags": ["test"],
            "archived": False,
        }

        conv = Conversation.from_dict(data)

        assert conv.id == "conv_123"
        assert conv.user_id == "user_456"
        assert len(conv.messages) == 1
        assert conv.title == "Test conversation"


class TestConversationMetadata:
    """Tests for ConversationMetadata model."""

    def test_from_conversation(self):
        """Test creating metadata from conversation."""
        now = datetime.now(UTC)
        messages = [
            Message(role="user", content="First message"),
            Message(role="assistant", content="Second message with a long response"),
        ]

        conv = Conversation(
            id="conv_123",
            user_id="user_456",
            messages=messages,
            created_at=now,
            updated_at=now,
            title="Test chat",
            tags=["important"],
        )

        metadata = ConversationMetadata.from_conversation(conv)

        assert metadata.id == "conv_123"
        assert metadata.user_id == "user_456"
        assert metadata.title == "Test chat"
        assert metadata.message_count == 2
        assert metadata.last_message_preview == "Second message with a long response"
        assert metadata.tags == ["important"]

    def test_from_conversation_empty_messages(self):
        """Test metadata from conversation with no messages."""
        now = datetime.now(UTC)

        conv = Conversation(
            id="conv_123",
            user_id="user_456",
            messages=[],
            created_at=now,
            updated_at=now,
        )

        metadata = ConversationMetadata.from_conversation(conv)

        assert metadata.message_count == 0
        assert metadata.last_message_preview is None

    def test_from_conversation_long_preview_truncated(self):
        """Test that long message previews are truncated to 100 chars."""
        now = datetime.now(UTC)
        long_content = "A" * 200  # 200 character message

        conv = Conversation(
            id="conv_123",
            user_id="user_456",
            messages=[Message(role="user", content=long_content)],
            created_at=now,
            updated_at=now,
        )

        metadata = ConversationMetadata.from_conversation(conv)

        assert len(metadata.last_message_preview) == 100
        assert metadata.last_message_preview == "A" * 100
