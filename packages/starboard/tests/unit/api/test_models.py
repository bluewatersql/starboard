# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for chat API models.

Tests cover:
- Validation rules and constraints
- Edge cases (empty strings, max lengths, invalid values)
- JSON serialization/deserialization
- Model immutability where applicable
- Cross-field validation
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from starboard.api.models import (
    ChatEvent,
    ConversationConfig,
    ConversationHistory,
    ConversationMetadata,
    ConversationResponse,
    CreateConversationRequest,
    ErrorResponse,
    EventType,
    Message,
    MessageResponse,
    MessageRole,
    MessageStatus,
    SendMessageRequest,
    ToolCall,
)

# ============================================================================
# ConversationConfig Tests
# ============================================================================


class TestConversationConfig:
    """Tests for ConversationConfig model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ConversationConfig()
        assert config.temperature == 0.4
        assert config.max_tokens == 120000  # Updated to match new default
        assert config.safe_mode is False
        assert config.streaming is True
        assert (
            config.model == "databricks-claude-sonnet-4-5"
        )  # Updated to match new default

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ConversationConfig(
            temperature=0.7,
            max_tokens=150000,  # Updated to be within new valid range
            safe_mode=True,
            streaming=False,
            model="databricks-gpt-4-turbo",  # Updated model name
        )
        assert config.temperature == 0.7
        assert config.max_tokens == 150000
        assert config.safe_mode is True
        assert config.streaming is False
        assert config.model == "databricks-gpt-4-turbo"

    def test_temperature_bounds(self):
        """Test temperature validation."""
        # Valid boundaries
        ConversationConfig(temperature=0.1)
        ConversationConfig(temperature=1.0)

        # Invalid: below minimum
        with pytest.raises(ValidationError) as exc_info:
            ConversationConfig(temperature=0.09)
        assert "greater than or equal to 0.1" in str(exc_info.value)

        # Invalid: above maximum
        with pytest.raises(ValidationError) as exc_info:
            ConversationConfig(temperature=1.1)
        assert "less than or equal to 1" in str(exc_info.value)

    def test_max_tokens_bounds(self):
        """Test max_tokens validation."""
        # Valid boundaries
        ConversationConfig(max_tokens=10000)
        ConversationConfig(max_tokens=200000)

        # Invalid: below minimum
        with pytest.raises(ValidationError) as exc_info:
            ConversationConfig(max_tokens=9999)
        assert "greater than or equal to 10000" in str(exc_info.value)

        # Invalid: above maximum
        with pytest.raises(ValidationError) as exc_info:
            ConversationConfig(max_tokens=200001)
        assert "less than or equal to 200000" in str(exc_info.value)

    def test_model_length(self):
        """Test model name length validation."""
        # Valid
        ConversationConfig(model="a")
        ConversationConfig(model="a" * 100)

        # Invalid: empty
        with pytest.raises(ValidationError) as exc_info:
            ConversationConfig(model="")
        assert "at least 1 character" in str(exc_info.value)

        # Invalid: too long
        with pytest.raises(ValidationError) as exc_info:
            ConversationConfig(model="a" * 101)
        assert "at most 100 characters" in str(exc_info.value)

    def test_immutability(self):
        """Test that config is frozen after creation."""
        config = ConversationConfig()
        with pytest.raises(ValidationError):
            config.temperature = 0.9

    def test_json_serialization(self):
        """Test JSON serialization round-trip."""
        config = ConversationConfig(
            temperature=0.5, max_tokens=100000
        )  # Updated to valid range
        json_str = config.model_dump_json()
        config2 = ConversationConfig.model_validate_json(json_str)
        assert config == config2


# ============================================================================
# ToolCall Tests
# ============================================================================


class TestToolCall:
    """Tests for ToolCall model."""

    def test_minimal_tool_call(self):
        """Test minimal tool call with required fields only."""
        tool_call = ToolCall(
            tool_call_id="tc_123", tool_name="test_tool", status="running"
        )
        assert tool_call.tool_call_id == "tc_123"
        assert tool_call.tool_name == "test_tool"
        assert tool_call.status == "running"
        assert tool_call.friendly_name is None
        assert tool_call.arguments is None
        assert tool_call.output is None
        assert tool_call.error is None
        assert tool_call.duration_ms is None

    def test_complete_tool_call(self):
        """Test tool call with all fields."""
        tool_call = ToolCall(
            tool_call_id="tc_456",
            tool_name="get_job_status",
            friendly_name="Get Job Status",
            status="completed",
            arguments={"job_id": "12345"},
            output='{"status": "SUCCESS"}',
            duration_ms=150,
        )
        assert tool_call.tool_call_id == "tc_456"
        assert tool_call.tool_name == "get_job_status"
        assert tool_call.friendly_name == "Get Job Status"
        assert tool_call.arguments == {"job_id": "12345"}
        assert tool_call.output == '{"status": "SUCCESS"}'
        assert tool_call.status == "completed"
        assert tool_call.duration_ms == 150

    def test_failed_tool_call(self):
        """Test tool call with error."""
        tool_call = ToolCall(
            tool_call_id="tc_789",
            tool_name="test_tool",
            status="failed",
            error="Connection timeout",
        )
        assert tool_call.status == "failed"
        assert tool_call.error == "Connection timeout"


# ============================================================================
# Message Tests
# ============================================================================


class TestMessage:
    """Tests for Message model."""

    def test_minimal_message(self):
        """Test minimal message with required fields."""
        now = datetime.now(UTC)
        message = Message(
            id="msg_123",
            conversation_id="conv_abc",
            role=MessageRole.USER,
            content="Hello",
            timestamp=now,
            status=MessageStatus.COMPLETED,
        )
        assert message.id == "msg_123"
        assert message.conversation_id == "conv_abc"
        assert message.role == MessageRole.USER
        assert message.content == "Hello"
        assert message.timestamp == now
        assert message.status == MessageStatus.COMPLETED
        assert message.tool_calls == []
        assert message.metadata == {}

    def test_message_with_tool_calls(self):
        """Test message with tool calls."""
        now = datetime.now(UTC)
        tool_call = ToolCall(
            tool_call_id="tc_123", tool_name="test_tool", status="completed"
        )
        message = Message(
            id="msg_123",
            conversation_id="conv_abc",
            role=MessageRole.ASSISTANT,
            content="Result",
            timestamp=now,
            status=MessageStatus.COMPLETED,
            tool_calls=[tool_call],
        )
        assert len(message.tool_calls) == 1
        assert message.tool_calls[0].tool_name == "test_tool"

    def test_message_with_metadata(self):
        """Test message with metadata."""
        now = datetime.now(UTC)
        message = Message(
            id="msg_123",
            conversation_id="conv_abc",
            role=MessageRole.ASSISTANT,
            content="Result",
            timestamp=now,
            status=MessageStatus.COMPLETED,
            metadata={"tokens": 100, "cost": 0.001, "latency_ms": 1200},
        )
        assert message.metadata["tokens"] == 100
        assert message.metadata["cost"] == 0.001
        assert message.metadata["latency_ms"] == 1200

    def test_content_length_validation(self):
        """Test content length validation - no max length constraint."""
        now = datetime.now(UTC)

        # Valid: any length is allowed
        Message(
            id="msg_123",
            conversation_id="conv_abc",
            role=MessageRole.USER,
            content="a" * 10000,
            timestamp=now,
            status=MessageStatus.COMPLETED,
        )

        # Also valid: long content
        Message(
            id="msg_123",
            conversation_id="conv_abc",
            role=MessageRole.USER,
            content="a" * 60000,
            timestamp=now,
            status=MessageStatus.COMPLETED,
        )


# ============================================================================
# Request Models Tests
# ============================================================================


class TestCreateConversationRequest:
    """Tests for CreateConversationRequest model."""

    def test_minimal_request(self):
        """Test minimal request with no fields (all optional)."""
        request = CreateConversationRequest()
        assert request.context is None
        assert request.config is None
        assert request.initial_message is None
        assert request.metadata is None

    def test_with_context_only(self):
        """Test request with context only."""
        request = CreateConversationRequest(
            context={"workspace_id": "ws_abc"},
        )
        assert request.context == {"workspace_id": "ws_abc"}
        assert request.config is None
        assert request.initial_message is None

    def test_with_config_only(self):
        """Test request with config only."""
        config = ConversationConfig(temperature=0.5)
        request = CreateConversationRequest(config=config)
        assert request.config == config
        assert request.context is None
        assert request.initial_message is None

    def test_with_initial_message(self):
        """Test request with initial_message."""
        request = CreateConversationRequest(
            initial_message="Analyze job performance for job 12345",
        )
        assert request.initial_message == "Analyze job performance for job 12345"
        assert request.context is None
        assert request.config is None

    def test_with_metadata(self):
        """Test request with metadata."""
        metadata = {"tags": ["test", "automation"], "source": "homepage"}
        request = CreateConversationRequest(metadata=metadata)
        assert request.metadata == metadata
        assert request.context is None
        assert request.config is None

    def test_full_request(self):
        """Test request with all fields."""
        config = ConversationConfig(temperature=0.5)
        context = {"workspace_id": "ws_abc", "job_id": "12345"}
        metadata = {"tags": ["job-analysis"], "source": "ui"}
        request = CreateConversationRequest(
            context=context,
            config=config,
            initial_message="Analyze this job",
            metadata=metadata,
        )
        assert request.context == context
        assert request.config == config
        assert request.initial_message == "Analyze this job"
        assert request.metadata == metadata

    def test_initial_message_min_length(self):
        """Test initial_message minimum length validation."""
        # Empty string should fail
        with pytest.raises(ValidationError) as exc_info:
            CreateConversationRequest(initial_message="")
        assert "at least 1 character" in str(exc_info.value).lower()

    def test_initial_message_max_length(self):
        """Test initial_message maximum length validation."""
        # Message exceeding 10000 chars should fail
        long_message = "a" * 10001
        with pytest.raises(ValidationError) as exc_info:
            CreateConversationRequest(initial_message=long_message)
        assert "at most 10000 characters" in str(exc_info.value).lower()

    def test_initial_message_max_length_boundary(self):
        """Test initial_message at exactly max length."""
        # Message at exactly 10000 chars should pass
        max_message = "a" * 10000
        request = CreateConversationRequest(initial_message=max_message)
        assert len(request.initial_message) == 10000

    def test_initial_message_whitespace_preserved(self):
        """Test that whitespace in initial_message is preserved."""
        message_with_whitespace = "  Analyze job   12345  "
        request = CreateConversationRequest(initial_message=message_with_whitespace)
        # Should preserve whitespace (not strip)
        assert request.initial_message == message_with_whitespace

    def test_metadata_empty_dict(self):
        """Test metadata with empty dict."""
        request = CreateConversationRequest(metadata={})
        assert request.metadata == {}

    def test_metadata_nested_structure(self):
        """Test metadata with nested structure."""
        metadata = {
            "tags": ["test"],
            "source": "ui",
            "user_preferences": {
                "theme": "dark",
                "notifications": True,
            },
        }
        request = CreateConversationRequest(metadata=metadata)
        assert request.metadata == metadata
        assert request.metadata["user_preferences"]["theme"] == "dark"


class TestSendMessageRequest:
    """Tests for SendMessageRequest model."""

    def test_minimal_request(self):
        """Test minimal request with required fields only."""
        request = SendMessageRequest(content="Hello")
        assert request.content == "Hello"
        assert request.attachments is None
        assert request.metadata is None

    def test_full_request(self):
        """Test request with all fields."""
        attachment = {
            "type": "file",
            "url": "s3://bucket/file.txt",
            "name": "file.txt",
            "filename": "file.txt",
            "size": 1024,
        }
        request = SendMessageRequest(
            content="Hello",
            attachments=[attachment],
            metadata={"source": "ui"},
        )
        assert request.content == "Hello"
        assert len(request.attachments) == 1
        assert request.metadata == {"source": "ui"}

    def test_content_validation(self):
        """Test content validation."""
        # Invalid: empty
        with pytest.raises(ValidationError):
            SendMessageRequest(content="")


# ============================================================================
# Response Models Tests
# ============================================================================


class TestConversationResponse:
    """Tests for ConversationResponse model."""

    def test_response_creation(self):
        """Test response creation."""
        now = datetime.now(UTC)
        config = ConversationConfig()
        response = ConversationResponse(
            conversation_id="conv_abc123",
            created_at=now,
            config=config,
            friendly_name="Test Conversation",  # Added required field
        )
        assert response.conversation_id == "conv_abc123"
        assert response.created_at == now
        assert response.config == config


class TestMessageResponse:
    """Tests for MessageResponse model."""

    def test_response_creation(self):
        """Test response creation."""
        response = MessageResponse(
            message_id="msg_abc123",
            conversation_id="conv_xyz",
            status=MessageStatus.PENDING,
            trace_id="trace_001",
        )
        assert response.message_id == "msg_abc123"
        assert response.conversation_id == "conv_xyz"
        assert response.trace_id == "trace_001"
        assert response.status == MessageStatus.PENDING


# ============================================================================
# SSE Event Models Tests
# ============================================================================


class TestChatEvent:
    """Tests for ChatEvent model."""

    def test_event_creation(self):
        """Test event creation."""
        now = datetime.now(UTC)
        event = ChatEvent(
            event_id="evt_001",
            type=EventType.MESSAGE_DELTA,
            data={"message_id": "msg_abc", "delta": {"content": "Hello"}},
            timestamp=now,
        )
        assert event.event_id == "evt_001"
        assert event.type == EventType.MESSAGE_DELTA
        assert event.data["message_id"] == "msg_abc"
        assert event.timestamp == now


# ============================================================================
# Error Models Tests
# ============================================================================


class TestErrorResponse:
    """Tests for ErrorResponse model."""

    def test_minimal_error(self):
        """Test minimal error with required fields."""
        error = ErrorResponse(
            code="VALIDATION_ERROR",
            message="Invalid request",
        )
        assert error.code == "VALIDATION_ERROR"
        assert error.message == "Invalid request"
        assert error.details is None
        assert error.trace_id is None

    def test_full_error(self):
        """Test error with all fields."""
        error = ErrorResponse(
            code="VALIDATION_ERROR",
            message="Invalid request body",
            details={"field": "content", "issue": "empty"},
            trace_id="trace_001",
        )
        assert error.code == "VALIDATION_ERROR"
        assert error.message == "Invalid request body"
        assert error.details == {"field": "content", "issue": "empty"}
        assert error.trace_id == "trace_001"


# ============================================================================
# Integration Tests
# ============================================================================


class TestModelIntegration:
    """Integration tests for model interactions."""

    def test_conversation_history_with_messages(self):
        """Test complete conversation history."""
        now = datetime.now(UTC)

        message1 = Message(
            id="msg_1",
            conversation_id="conv_abc",
            role=MessageRole.USER,
            content="Hello",
            timestamp=now,
            status=MessageStatus.COMPLETED,
        )

        message2 = Message(
            id="msg_2",
            conversation_id="conv_abc",
            role=MessageRole.ASSISTANT,
            content="Hi there!",
            timestamp=now,
            status=MessageStatus.COMPLETED,
        )

        metadata = ConversationMetadata(
            total_messages=2,
            total_tokens=50,
            total_cost=0.0005,
            created_at=now,
            updated_at=now,
            friendly_name="Test Conversation",  # Added required field
        )

        history = ConversationHistory(
            conversation_id="conv_abc",
            messages=[message1, message2],
            metadata=metadata,
        )

        assert len(history.messages) == 2
        assert history.metadata.total_messages == 2
        assert history.metadata.total_tokens == 50

    def test_json_serialization_round_trip(self):
        """Test JSON serialization for complex nested structures."""
        now = datetime.now(UTC)

        tool_call = ToolCall(
            tool_call_id="tc_123",
            tool_name="get_job_status",
            friendly_name="Get Job Status",
            status="completed",
            arguments={"job_id": "12345"},
            output='{"status": "SUCCESS"}',
        )

        message = Message(
            id="msg_123",
            conversation_id="conv_abc",
            role=MessageRole.ASSISTANT,
            content="Job is running",
            timestamp=now,
            status=MessageStatus.COMPLETED,
            tool_calls=[tool_call],
            metadata={"tokens": 100},
        )

        # Serialize to JSON
        json_str = message.model_dump_json()

        # Deserialize back
        message2 = Message.model_validate_json(json_str)

        assert message2.id == message.id
        assert len(message2.tool_calls) == 1
        assert message2.tool_calls[0].tool_name == "get_job_status"
        assert message2.metadata["tokens"] == 100
