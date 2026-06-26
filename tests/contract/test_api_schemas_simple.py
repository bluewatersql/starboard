# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Backend API Contract Tests - Simplified.

Validates basic schema exports and structure.
Tests actual model behavior without making assumptions about fields.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

# Import actual API models
from starboard_server.api.models import (
    ChatEvent,
    CreateConversationRequest,
    EventType,
    MessageResponse,
    MessageStatus,
    SendMessageRequest,
)


class TestSchemaExports:
    """Test that schemas are properly exported."""

    @pytest.fixture
    def schema_dir(self) -> Path:
        """Get schema directory."""
        return Path(__file__).parent / "schemas"

    def test_schemas_directory_exists(self, schema_dir: Path):
        """Schema directory should exist."""
        assert schema_dir.exists(), (
            f"Schema directory not found: {schema_dir}. "
            "Run 'python scripts/export_api_schemas.py' first."
        )

    def test_required_schemas_exported(self, schema_dir: Path):
        """All required schemas should be exported."""
        required_schemas = [
            "CreateConversationRequest",
            "ConversationResponse",
            "SendMessageRequest",
            "MessageResponse",
            "SubmitFeedbackRequest",
            "ChatEvent",
        ]

        for schema_name in required_schemas:
            schema_file = schema_dir / f"{schema_name}.json"
            assert schema_file.exists(), f"Missing schema file: {schema_name}.json"

    def test_schema_has_valid_structure(self, schema_dir: Path):
        """Exported schemas should have valid JSON Schema structure."""
        schema_file = schema_dir / "SendMessageRequest.json"
        if not schema_file.exists():
            pytest.skip("Schema file not generated yet")

        with open(schema_file) as f:
            schema = json.load(f)

        # Check required JSON Schema fields
        assert "$schema" in schema
        assert "$id" in schema
        assert "type" in schema
        assert "properties" in schema


class TestCreateConversationRequest:
    """Test CreateConversationRequest actual model."""

    def test_valid_minimal_request(self):
        """Should validate minimal request (user_id comes from auth middleware)."""
        # CreateConversationRequest no longer has user_id field
        # user_id is extracted from authentication middleware
        request = CreateConversationRequest()
        assert request.context is None
        assert request.config is None

    def test_valid_request_with_context(self):
        """Should validate request with context and initial message."""
        data = {
            "context": {"job_id": "12345"},
            "initial_message": "Analyze job performance",
        }
        request = CreateConversationRequest(**data)
        assert request.context == {"job_id": "12345"}
        assert request.initial_message == "Analyze job performance"


class TestSendMessageRequest:
    """Test SendMessageRequest actual model."""

    def test_valid_message_request(self):
        """Should validate correct message request."""
        data = {"content": "Show me cost trends"}
        request = SendMessageRequest(**data)
        assert request.content == "Show me cost trends"

    def test_empty_content_rejected(self):
        """Should reject empty content."""
        with pytest.raises(ValidationError):
            SendMessageRequest(content="")  # min_length=1

    def test_optional_fields(self):
        """Should handle optional fields."""
        data = {
            "content": "Test message",
            "attachments": [
                {
                    "filename": "file.pdf",
                    "size": 1024,
                    "type": "file",
                    "url": "https://example.com/file.pdf",
                }
            ],
            "metadata": {"source": "web"},
        }
        request = SendMessageRequest(**data)
        assert request.attachments is not None
        assert request.metadata == {"source": "web"}


class TestMessageResponse:
    """Test MessageResponse actual model."""

    def test_valid_response(self):
        """Should validate correct response with all required fields."""
        data = {
            "message_id": "msg_123",
            "conversation_id": "conv_456",
            "status": MessageStatus.COMPLETED,
        }
        response = MessageResponse(**data)
        assert response.message_id == "msg_123"
        assert response.status == MessageStatus.COMPLETED

    def test_missing_required_status(self):
        """Should reject response without status."""
        with pytest.raises(ValidationError):
            MessageResponse(
                message_id="msg_123",
                conversation_id="conv_456",
            )

    def test_optional_trace_id(self):
        """Should allow optional trace_id."""
        data = {
            "message_id": "msg_123",
            "conversation_id": "conv_456",
            "status": MessageStatus.COMPLETED,
            "trace_id": "trace_789",
        }
        response = MessageResponse(**data)
        assert response.trace_id == "trace_789"


class TestChatEvent:
    """Test ChatEvent actual model."""

    def test_valid_chat_event(self):
        """Should validate correct chat event."""
        data = {
            "event_id": "evt_123",
            "type": EventType.THINKING,
            "data": {"content": "Processing your request..."},
            "timestamp": "2025-11-28T10:00:00Z",
        }
        event = ChatEvent(**data)
        assert event.type == EventType.THINKING

    def test_actual_event_types(self):
        """Should support actual event types from enum."""
        event_types = [
            EventType.THINKING,
            EventType.STEP_COMPLETE,
            EventType.ERROR,
            EventType.TOOL_START,
            EventType.TOOL_END,
            EventType.NEXT_STEPS,
            EventType.MESSAGE_START,
            EventType.MESSAGE_DELTA,
            EventType.MESSAGE_END,
        ]

        for event_type in event_types:
            data = {
                "event_id": "evt_test",
                "type": event_type,
                "data": {},
                "timestamp": "2025-11-28T10:00:00Z",
            }
            event = ChatEvent(**data)
            assert event.type == event_type


class TestBackwardCompatibility:
    """Test backward compatibility of API schemas."""

    def test_serialization_roundtrip(self):
        """Should serialize and deserialize without data loss."""
        original = MessageResponse(
            message_id="msg_123",
            conversation_id="conv_456",
            status=MessageStatus.COMPLETED,
            trace_id="trace_789",
        )

        # Serialize to JSON
        json_data = original.model_dump_json()

        # Deserialize back
        restored = MessageResponse.model_validate_json(json_data)

        assert restored.message_id == original.message_id
        assert restored.status == original.status
        assert restored.trace_id == original.trace_id


class TestRequestResponseIntegration:
    """Test actual request/response flow."""

    def test_conversation_creation_flow(self):
        """Test conversation creation matches response structure."""
        # Request - user_id is now from auth middleware, not request body
        request = CreateConversationRequest(
            initial_message="Show me cost trends",
            context={"workspace_id": "ws_123"},
        )

        # Verify request structure
        assert request.initial_message == "Show me cost trends"
        assert request.context == {"workspace_id": "ws_123"}

    def test_message_send_flow(self):
        """Test message send matches response structure."""
        # Request
        request = SendMessageRequest(content="Show me cost trends")

        # Response
        response = MessageResponse(
            message_id="msg_456",
            conversation_id="conv_789",
            status=MessageStatus.COMPLETED,
        )

        # Verify basic contract
        assert isinstance(request.content, str)
        assert isinstance(response.message_id, str)
        assert isinstance(response.status, MessageStatus)
