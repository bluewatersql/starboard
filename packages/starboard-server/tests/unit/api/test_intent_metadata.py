# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for intent classification metadata in API models.

Phase 2 Component 5: API & Streaming

Verifies that intent classification data can be serialized and deserialized
through the existing API metadata infrastructure.
"""

from datetime import UTC, datetime

from starboard_server.api.models import (
    ChatEvent,
    EventType,
    Message,
    MessageRole,
    MessageStatus,
)
from starboard_server.api.models.events import StreamingChatEvent
from starboard_server.domain.models.conversation_patterns import (
    IntentClassification,
    UserIntentType,
)


class TestIntentMetadataInMessage:
    """Tests for intent classification in Message metadata."""

    def test_message_with_intent_metadata(self):
        """Message can include intent classification in metadata."""
        intent = IntentClassification(
            intent_type=UserIntentType.EXTENSION,
            confidence=0.92,
            reasoning="User added temporal constraint",
            extracted_entities={"timeframe": "morning", "metric": "slowness"},
        )

        message = Message(
            id="msg_001",
            conversation_id="conv_123",
            role=MessageRole.USER,
            content="Only show results for the morning",
            timestamp=datetime.now(UTC),
            status=MessageStatus.COMPLETED,
            metadata={
                "intent_classification": intent.to_dict(),
                "token_count": 8,
            },
        )

        # Verify message serializes correctly
        assert message.id == "msg_001"
        assert message.metadata["intent_classification"]["intent_type"] == "extension"
        assert message.metadata["intent_classification"]["confidence"] == 0.92
        assert (
            message.metadata["intent_classification"]["extracted_entities"]["timeframe"]
            == "morning"
        )
        assert message.metadata["token_count"] == 8

    def test_message_metadata_roundtrip(self):
        """Intent classification survives JSON serialization roundtrip."""
        intent = IntentClassification(
            intent_type=UserIntentType.REFINEMENT,
            confidence=0.88,
            reasoning="User corrected previous statement",
            extracted_entities={"original": "100ms", "corrected": "1000ms"},
        )

        message = Message(
            id="msg_002",
            conversation_id="conv_123",
            role=MessageRole.USER,
            content="I meant 1000ms, not 100ms",
            timestamp=datetime.now(UTC),
            status=MessageStatus.COMPLETED,
            metadata={"intent_classification": intent.to_dict()},
        )

        # Serialize to JSON
        json_data = message.model_dump()

        # Deserialize back
        restored_message = Message.model_validate(json_data)

        # Verify intent classification is intact
        assert (
            restored_message.metadata["intent_classification"]["intent_type"]
            == "refinement"
        )
        assert restored_message.metadata["intent_classification"]["confidence"] == 0.88
        assert (
            restored_message.metadata["intent_classification"]["reasoning"]
            == "User corrected previous statement"
        )

        # Can reconstruct IntentClassification from metadata
        restored_intent = IntentClassification.from_dict(
            restored_message.metadata["intent_classification"]
        )
        assert restored_intent.intent_type == UserIntentType.REFINEMENT
        assert restored_intent.confidence == 0.88

    def test_message_without_intent_metadata(self):
        """Message works fine without intent classification (backward compat)."""
        message = Message(
            id="msg_003",
            conversation_id="conv_123",
            role=MessageRole.ASSISTANT,
            content="Here's the query analysis.",
            timestamp=datetime.now(UTC),
            status=MessageStatus.COMPLETED,
            metadata={"token_count": 120, "latency_ms": 1500},
        )

        # No intent classification - still valid
        assert "intent_classification" not in message.metadata
        assert message.metadata["token_count"] == 120


class TestIntentMetadataInChatEvents:
    """Tests for intent classification in SSE event payloads."""

    def test_chat_event_with_intent_data(self):
        """ChatEvent can include intent classification in data payload."""
        intent_data = {
            "intent_type": "extension",
            "confidence": 0.95,
            "reasoning": "User added constraint",
            "extracted_entities": {"constraint": "last_week"},
        }

        event = ChatEvent(
            event_id="evt_001",
            type=EventType.MESSAGE_END,
            data={
                "message_id": "msg_001",
                "intent_classification": intent_data,
                "processing_time_ms": 250,
            },
            timestamp=datetime.now(UTC),
        )

        # Verify event includes intent data
        assert event.data["intent_classification"]["intent_type"] == "extension"
        assert event.data["intent_classification"]["confidence"] == 0.95
        assert event.data["processing_time_ms"] == 250

    def test_streaming_chat_event_with_intent_data(self):
        """StreamingChatEvent can include intent classification."""
        intent_data = {
            "intent_type": "clarification",
            "confidence": 0.91,
            "reasoning": "User answered agent's question",
            "extracted_entities": {"answer": "last 7 days"},
        }

        event = StreamingChatEvent(
            event_id="evt_002",
            conversation_id="conv_123",
            event_type="message.complete",
            data={
                "message_id": "msg_002",
                "intent_classification": intent_data,
            },
            timestamp=datetime.now(UTC),
        )

        # Verify event serializes correctly
        assert event.conversation_id == "conv_123"
        assert event.data["intent_classification"]["intent_type"] == "clarification"
        assert (
            event.data["intent_classification"]["extracted_entities"]["answer"]
            == "last 7 days"
        )

    def test_event_without_intent_data(self):
        """Events work fine without intent classification (backward compat)."""
        event = ChatEvent(
            event_id="evt_003",
            type=EventType.TOOL_CALL_START,
            data={
                "tool_name": "analyze_query",
                "parameters": {"query_id": "123"},
            },
            timestamp=datetime.now(UTC),
        )

        # No intent classification - still valid
        assert "intent_classification" not in event.data
        assert event.data["tool_name"] == "analyze_query"


class TestIntentClassificationCompatibility:
    """Tests for IntentClassification compatibility with API models."""

    def test_intent_classification_to_dict_for_api(self):
        """IntentClassification.to_dict() produces API-compatible format."""
        intent = IntentClassification(
            intent_type=UserIntentType.NEW_QUERY,
            confidence=0.99,
            reasoning="Completely different topic",
            extracted_entities={"topic": "cost_analysis"},
        )

        # Convert to dict (API-ready format)
        intent_dict = intent.to_dict()

        # Verify format is JSON-serializable
        assert isinstance(intent_dict, dict)
        assert intent_dict["intent_type"] == "new_query"
        assert isinstance(intent_dict["confidence"], float)
        assert isinstance(intent_dict["reasoning"], str)
        assert isinstance(intent_dict["extracted_entities"], dict)

    def test_intent_classification_from_dict_from_api(self):
        """IntentClassification.from_dict() can parse API metadata."""
        # Simulate receiving this from API
        api_metadata = {
            "intent_type": "feedback",
            "confidence": 0.87,
            "reasoning": "User expressed satisfaction",
            "extracted_entities": {"sentiment": "positive"},
        }

        # Should reconstruct successfully
        intent = IntentClassification.from_dict(api_metadata)

        assert intent.intent_type == UserIntentType.FEEDBACK
        assert intent.confidence == 0.87
        assert intent.reasoning == "User expressed satisfaction"
        assert intent.extracted_entities["sentiment"] == "positive"

    def test_all_intent_types_serialize(self):
        """All UserIntentType values can be serialized through API."""
        for intent_type in UserIntentType:
            intent = IntentClassification(
                intent_type=intent_type,
                confidence=0.9,
                reasoning=f"Test {intent_type.value}",
                extracted_entities={},
            )

            # Create message with this intent
            message = Message(
                id="msg_test",
                conversation_id="conv_test",
                role=MessageRole.USER,
                content="Test message",
                timestamp=datetime.now(UTC),
                status=MessageStatus.COMPLETED,
                metadata={"intent_classification": intent.to_dict()},
            )

            # Verify it serializes and deserializes
            json_data = message.model_dump()
            restored = Message.model_validate(json_data)
            restored_intent = IntentClassification.from_dict(
                restored.metadata["intent_classification"]
            )

            assert restored_intent.intent_type == intent_type
            assert restored_intent.confidence == 0.9
