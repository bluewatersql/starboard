# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for B2: Conversation History Reload Accuracy.

Verifies that thinking_steps, tool_calls, and tool_positions are correctly
stored in message metadata and can be retrieved from conversation history.
"""

from starboard_server.api.models import Message, ToolCall
from starboard_server.api.models.enums import MessageRole


class TestHistoryMetadataPreservation:
    """Test that message metadata is correctly preserved."""

    def test_message_can_store_thinking_steps_in_metadata(self):
        """Message model should accept thinking_steps in metadata."""
        thinking_steps = [
            {
                "id": "resolve_query",
                "title": "Resolving Query",
                "status": "completed",
                "startTime": 1234567890000,
                "endTime": 1234567893000,
            },
            {
                "id": "execute_sql",
                "title": "Execute SQL",
                "status": "completed",
                "startTime": 1234567893000,
                "endTime": 1234567896000,
            },
        ]

        message = Message(
            id="msg_123",
            conversation_id="conv_456",
            role=MessageRole.ASSISTANT,
            content="I found the results.",
            metadata={"thinking_steps": thinking_steps},
        )

        assert "thinking_steps" in message.metadata
        assert len(message.metadata["thinking_steps"]) == 2
        assert message.metadata["thinking_steps"][0]["id"] == "resolve_query"

    def test_message_can_store_tool_positions_in_metadata(self):
        """Message model should accept tool_positions in metadata."""
        tool_positions = [
            {
                "tool_call_id": "tc_001",
                "position": 150,
                "display": "inline",
            },
        ]

        message = Message(
            id="msg_123",
            conversation_id="conv_456",
            role=MessageRole.ASSISTANT,
            content="I'll execute the query.",
            metadata={"tool_positions": tool_positions},
        )

        assert "tool_positions" in message.metadata
        assert len(message.metadata["tool_positions"]) == 1
        assert message.metadata["tool_positions"][0]["tool_call_id"] == "tc_001"

    def test_message_with_tool_calls(self):
        """Message model should accept tool_calls."""
        tool_calls = [
            ToolCall(
                tool_call_id="tc_001",
                tool_name="execute_sql",
                friendly_name="Execute SQL",
                status="completed",
                output="Retrieved 10 rows",
            ),
        ]

        message = Message(
            id="msg_123",
            conversation_id="conv_456",
            role=MessageRole.ASSISTANT,
            content="I found the results.",
            tool_calls=tool_calls,
        )

        assert len(message.tool_calls) == 1
        assert message.tool_calls[0].tool_name == "execute_sql"

    def test_complete_message_with_all_metadata(self):
        """Test message with all metadata fields for history reload."""
        thinking_steps = [
            {
                "id": "resolve_query",
                "title": "Resolving Query",
                "status": "completed",
            },
        ]
        tool_positions = [
            {"tool_call_id": "tc_001", "position": 100, "display": "inline"},
        ]
        tool_calls = [
            ToolCall(
                tool_call_id="tc_001",
                tool_name="execute_sql",
                friendly_name="Execute SQL",
                status="completed",
            ),
        ]

        message = Message(
            id="msg_123",
            conversation_id="conv_456",
            role=MessageRole.ASSISTANT,
            content="Analysis complete.",
            metadata={
                "thinking_steps": thinking_steps,
                "tool_positions": tool_positions,
                "complete_report": {"report_type": "analytics"},
            },
            tool_calls=tool_calls,
        )

        # Verify all fields are present
        assert "thinking_steps" in message.metadata
        assert "tool_positions" in message.metadata
        assert "complete_report" in message.metadata
        assert len(message.tool_calls) == 1


class TestFrontendMetadataPromotion:
    """
    Test the frontend metadata promotion logic (simulated).

    The frontend's messageStore.setMessages() promotes fields from metadata
    to top-level for easier access in components.
    """

    def simulate_frontend_promotion(self, message_dict: dict) -> dict:
        """
        Simulate frontend's setMessages promotion logic.

        This mirrors the logic in frontend/lib/store/messageStore.ts:
        - Promotes tool_positions from metadata to top level
        - Promotes thinking_steps from metadata to top level
        - Promotes complete_report from metadata to top level
        """
        msg = message_dict.copy()
        metadata = msg.get("metadata", {})

        # Promote tool_positions (Phase 2)
        tool_positions = (
            msg.get("tool_positions") or metadata.get("tool_positions") or []
        )

        # Promote thinking_steps (B2 fix)
        thinking_steps = (
            msg.get("thinking_steps") or metadata.get("thinking_steps") or []
        )

        # Promote complete_report
        complete_report = msg.get("complete_report") or metadata.get("complete_report")

        return {
            **msg,
            "tool_calls": msg.get("tool_calls", []),
            "tool_positions": tool_positions,
            "thinking_steps": thinking_steps,
            "complete_report": complete_report,
        }

    def test_thinking_steps_promoted_from_metadata(self):
        """thinking_steps should be promoted from metadata to top level."""
        message_from_api = {
            "id": "msg_123",
            "role": "assistant",
            "content": "Result",
            "metadata": {
                "thinking_steps": [
                    {"id": "step1", "title": "Step 1", "status": "completed"},
                ],
            },
        }

        promoted = self.simulate_frontend_promotion(message_from_api)

        assert "thinking_steps" in promoted
        assert len(promoted["thinking_steps"]) == 1
        assert promoted["thinking_steps"][0]["id"] == "step1"

    def test_tool_positions_promoted_from_metadata(self):
        """tool_positions should be promoted from metadata to top level."""
        message_from_api = {
            "id": "msg_123",
            "role": "assistant",
            "content": "Result",
            "metadata": {
                "tool_positions": [
                    {"tool_call_id": "tc1", "position": 50, "display": "inline"},
                ],
            },
        }

        promoted = self.simulate_frontend_promotion(message_from_api)

        assert "tool_positions" in promoted
        assert len(promoted["tool_positions"]) == 1
        assert promoted["tool_positions"][0]["tool_call_id"] == "tc1"

    def test_existing_top_level_takes_precedence(self):
        """If field exists at top level, don't override from metadata."""
        message_from_api = {
            "id": "msg_123",
            "role": "assistant",
            "content": "Result",
            "thinking_steps": [
                {"id": "top_level", "title": "Top", "status": "completed"},
            ],
            "metadata": {
                "thinking_steps": [
                    {"id": "from_metadata", "title": "Meta", "status": "completed"},
                ],
            },
        }

        promoted = self.simulate_frontend_promotion(message_from_api)

        # Top-level should take precedence
        assert promoted["thinking_steps"][0]["id"] == "top_level"

    def test_empty_arrays_when_not_present(self):
        """Should return empty arrays when neither top-level nor metadata has data."""
        message_from_api = {
            "id": "msg_123",
            "role": "assistant",
            "content": "Result",
            "metadata": {},
        }

        promoted = self.simulate_frontend_promotion(message_from_api)

        assert promoted["thinking_steps"] == []
        assert promoted["tool_positions"] == []
        assert promoted["tool_calls"] == []
