"""Integration tests for next steps streaming via SSE.

Tests that NextStepsEvent properly flows through the API layer
and is correctly formatted for SSE transmission to clients.

Part of Phase 1: Foundation - Component 7 (API Endpoints)
"""

from uuid import uuid4

import pytest
from starboard_server.agents.events import (
    NextStepsEvent,
)
from starboard_server.api.event_converter import convert_streaming_event_to_chat_event
from starboard_server.api.models import EventType as ChatEventType
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)


class TestNextStepsEventConversion:
    """Test that NextStepsEvent converts properly to ChatEvent."""

    def test_convert_next_steps_event_with_single_option(self):
        """Convert NextStepsEvent with one option."""
        # Arrange
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Continue analysis",
            description="Continue with deeper analysis",
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters=None,
        )

        streaming_event = NextStepsEvent(
            step=1,
            next_steps=(option,),
        )

        # Act
        chat_event = convert_streaming_event_to_chat_event(
            event=streaming_event,
            conversation_id="conv_123",
            message_id="msg_456",
        )

        # Assert
        assert chat_event.type == ChatEventType.NEXT_STEPS
        assert "next_steps" in chat_event.data
        assert len(chat_event.data["next_steps"]) == 1
        assert chat_event.data["next_steps"][0]["number"] == 1
        assert chat_event.data["next_steps"][0]["title"] == "Continue analysis"

    def test_convert_next_steps_event_with_multiple_options(self):
        """Convert NextStepsEvent with multiple options."""
        # Arrange
        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Optimize query",
                description="Rewrite for performance",
                action_type=ActionType.TOOL_CALL,
                target_agent=None,
                tool_name="optimize_query",
                parameters={"mode": "aggressive"},
            ),
            NextStepOption(
                id="opt2",
                number=2,
                title="Analyze costs",
                description=None,
                action_type=ActionType.ROUTE,
                target_agent="cost_analyzer",
                tool_name=None,
                parameters=None,
            ),
            NextStepOption(
                id="opt3",
                number=3,
                title="Continue",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        )

        streaming_event = NextStepsEvent(
            step=5,
            next_steps=options,
        )

        # Act
        chat_event = convert_streaming_event_to_chat_event(
            event=streaming_event,
            conversation_id="conv_789",
            message_id="msg_012",
        )

        # Assert
        assert chat_event.type == ChatEventType.NEXT_STEPS
        assert len(chat_event.data["next_steps"]) == 3

        # Check first option (tool call)
        opt1 = chat_event.data["next_steps"][0]
        assert opt1["number"] == 1
        assert opt1["action_type"] == "tool_call"
        assert opt1["tool_name"] == "optimize_query"
        assert opt1["parameters"] == {"mode": "aggressive"}

        # Check second option (route)
        opt2 = chat_event.data["next_steps"][1]
        assert opt2["number"] == 2
        assert opt2["action_type"] == "route"
        assert opt2["target_agent"] == "cost_analyzer"

        # Check third option (continue)
        opt3 = chat_event.data["next_steps"][2]
        assert opt3["number"] == 3
        assert opt3["action_type"] == "continue"

    def test_convert_preserves_event_metadata(self):
        """Verify that event metadata is preserved during conversion."""
        # Arrange
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Test",
            description=None,
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters=None,
        )

        streaming_event = NextStepsEvent(
            step=10,
            next_steps=(option,),
        )

        message_id = f"msg_{uuid4().hex[:12]}"

        # Act
        chat_event = convert_streaming_event_to_chat_event(
            event=streaming_event,
            conversation_id="conv_abc",
            message_id=message_id,
        )

        # Assert
        assert chat_event.data["message_id"] == message_id
        assert chat_event.event_id.startswith("evt_")
        assert chat_event.timestamp is not None

    def test_event_data_serialization(self):
        """Verify that NextStepsEvent.to_sse_data() produces correct structure."""
        # Arrange
        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Option 1",
                description="First option",
                action_type=ActionType.TOOL_CALL,
                target_agent=None,
                tool_name="tool_1",
                parameters={"key": "value"},
            ),
            NextStepOption(
                id="opt2",
                number=2,
                title="Option 2",
                description="Second option",
                action_type=ActionType.ROUTE,
                target_agent="agent_2",
                tool_name=None,
                parameters=None,
            ),
        )

        streaming_event = NextStepsEvent(
            step=3,
            next_steps=options,
        )

        # Act
        sse_data = streaming_event.to_sse_data(message_id="msg_test")

        # Assert
        assert "message_id" in sse_data
        assert "next_steps" in sse_data
        assert isinstance(sse_data["next_steps"], list)
        assert len(sse_data["next_steps"]) == 2

        # Verify each option is a dict (serialized)
        for opt in sse_data["next_steps"]:
            assert isinstance(opt, dict)
            assert "number" in opt
            assert "title" in opt
            assert "action_type" in opt


class TestEventTypeMapping:
    """Test that NextStepsEvent is correctly mapped in EVENT_TYPE_MAPPING."""

    def test_next_steps_event_in_mapping(self):
        """Verify NextStepsEvent is registered in event converter."""
        from starboard_server.api.event_converter import EVENT_TYPE_MAPPING

        assert NextStepsEvent in EVENT_TYPE_MAPPING
        assert EVENT_TYPE_MAPPING[NextStepsEvent] == ChatEventType.NEXT_STEPS

    def test_event_coverage_validation(self):
        """Verify that all streaming events are covered in mapping."""
        from starboard_server.api.event_converter import validate_event_coverage

        is_valid, missing = validate_event_coverage()

        assert is_valid, f"Missing event mappings: {missing}"
        assert len(missing) == 0


class TestSSEFormatting:
    """Test SSE message formatting for next steps events."""

    def test_sse_format_structure(self):
        """Verify SSE format matches specification."""
        # Arrange
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Test option",
            description=None,
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters=None,
        )

        streaming_event = NextStepsEvent(
            step=1,
            next_steps=(option,),
        )

        # Act
        chat_event = convert_streaming_event_to_chat_event(
            event=streaming_event,
            conversation_id="conv_test",
            message_id="msg_test",
        )

        # Assert - Verify structure is JSON-serializable
        import json

        try:
            json.dumps(chat_event.data)
        except TypeError as e:
            pytest.fail(f"ChatEvent data is not JSON-serializable: {e}")


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_next_steps_tuple(self):
        """Handle empty next steps gracefully."""
        # Arrange - This shouldn't normally happen, but test robustness
        streaming_event = NextStepsEvent(
            step=1,
            next_steps=(),
        )

        # Act
        chat_event = convert_streaming_event_to_chat_event(
            event=streaming_event,
            conversation_id="conv_test",
            message_id="msg_test",
        )

        # Assert
        assert chat_event.type == ChatEventType.NEXT_STEPS
        assert "next_steps" in chat_event.data
        assert len(chat_event.data["next_steps"]) == 0

    def test_missing_message_id(self):
        """Handle missing message_id parameter."""
        # Arrange
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Test",
            description=None,
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters=None,
        )

        streaming_event = NextStepsEvent(
            step=1,
            next_steps=(option,),
        )

        # Act
        chat_event = convert_streaming_event_to_chat_event(
            event=streaming_event,
            conversation_id="conv_test",
            message_id=None,  # No message ID
        )

        # Assert - Should still work, just without message_id in data
        assert chat_event.type == ChatEventType.NEXT_STEPS
        assert "next_steps" in chat_event.data
