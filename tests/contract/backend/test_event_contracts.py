# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Contract Tests: Backend Event Generation

Generates SSE event fixtures for frontend validation. These tests ensure that
the actual output of `to_sse_data()` methods matches what the frontend expects.

Generated fixtures are validated by frontend tests to catch schema drift.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from starboard_server.agents.events import (
    ClarificationRequestEvent,
    ErrorEvent,
    FinalOutputEvent,
    NextStepsEvent,
    StepCompleteEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from starboard_server.agents.state import AgentOutput
from starboard_server.api.event_converter import convert_streaming_event_to_chat_event
from starboard_server.api.models.enums import EventType

# Fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)


def save_fixture(filename: str, data: Any) -> None:
    """Save fixture data to JSON file."""
    filepath = FIXTURES_DIR / filename
    filepath.write_text(json.dumps(data, indent=2, default=str))
    print(f"✅ Generated: {filepath}")


class TestFinalOutputEventContract:
    """Contract tests for final_output event."""

    def test_all_status_variations(self):
        """Generate final_output fixtures for all status values."""
        statuses = [
            "success",
            "error",
            "budget_exceeded",
            "max_steps_reached",
            "unknown",
        ]
        fixtures = {}

        for status in statuses:
            output = AgentOutput(
                status=status,  # type: ignore
                recommendations=[
                    {
                        "title": "Test Recommendation",
                        "category": "test",
                        "impact": "high",
                    }
                ],
                reasoning_trace=[{"step": 1, "action": "test"}],
                steps_taken=1,
                tools_used=["test_tool"],
                tokens_used=100,
                cost_usd=0.01,
                duration_seconds=1.5,
                error_message="Test error" if status == "error" else None,
            )

            event = FinalOutputEvent(output=output)
            fixtures[status] = event.to_sse_data(message_id="msg_test_123")

        save_fixture("final_output.json", fixtures)
        assert len(fixtures) == len(statuses)

    def test_null_report_fields(self):
        """Generate final_output with null complete_report."""
        # This is a common case when agent completes with minimal output
        output = AgentOutput(
            status="unknown",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=0,
            tools_used=[],
            tokens_used=0,
            cost_usd=0.0,
            duration_seconds=0.0,
        )

        event = FinalOutputEvent(output=output)
        fixture = event.to_sse_data(message_id="msg_test_null")

        save_fixture("final_output_null_reports.json", fixture)

        # Verify structure
        assert fixture["message_id"] == "msg_test_null"
        assert "output" in fixture
        assert fixture["output"]["status"] == "unknown"


class TestThinkingEventContract:
    """Contract tests for thinking (message.delta) events."""

    def test_thinking_event(self):
        """Generate thinking event fixture (converts to message.delta)."""
        event = ThinkingEvent(
            step=1,
            content="Analyzing the query to identify optimization opportunities...",
        )

        # Convert to SSE format
        chat_event = convert_streaming_event_to_chat_event(
            event=event,
            conversation_id="conv_test_123",
            message_id="msg_test_thinking",
        )

        # Extract the data payload
        fixture = {
            "event_type": chat_event.type.value,
            "data": chat_event.data,
        }

        save_fixture("thinking_message_delta.json", fixture)

        assert chat_event.type == EventType.MESSAGE_DELTA
        assert "delta" in chat_event.data


class TestToolEventContracts:
    """Contract tests for tool events."""

    def test_tool_start(self):
        """Generate tool.call.start event fixture."""
        event = ToolStartEvent(
            step=1,
            tool_name="fetch_table_metadata",
            friendly_name="Fetching Table Metadata for main.users",
            tool_call_id="call_test_123",
            arguments={"table_name": "main.users", "include_stats": True},
        )

        fixture = event.to_sse_data(message_id="msg_test_tool")
        save_fixture("tool_call_start.json", fixture)

        assert fixture["message_id"] == "msg_test_tool"
        assert "tool_call" in fixture
        assert fixture["tool_call"]["tool_name"] == "fetch_table_metadata"
        assert fixture["tool_call"]["status"] == "running"

    def test_tool_end_success(self):
        """Generate tool.call.result event for successful tool execution."""
        event = ToolEndEvent(
            step=1,
            tool_name="fetch_table_metadata",
            friendly_name="Fetching Table Metadata for main.users",
            tool_call_id="call_test_123",
            success=True,
            result_summary="Found table with 5 columns, 1M rows",
            error=None,
            duration_seconds=0.5,
        )

        fixture = event.to_sse_data(message_id="msg_test_tool_success")
        save_fixture("tool_call_result_success.json", fixture)

        assert fixture["message_id"] == "msg_test_tool_success"
        assert fixture["tool_call"]["success"] is True
        assert fixture["tool_call"]["status"] == "completed"
        assert fixture["tool_call"]["error"] is None

    def test_tool_end_failure(self):
        """Generate tool.call.result event for failed tool execution."""
        event = ToolEndEvent(
            step=1,
            tool_name="fetch_table_metadata",
            friendly_name="Fetching Table Metadata for main.users",
            tool_call_id="call_test_123",
            success=False,
            result_summary=None,
            error="Table not found",
            duration_seconds=0.2,
        )

        fixture = event.to_sse_data(message_id="msg_test_tool_failure")
        save_fixture("tool_call_result_failure.json", fixture)

        assert fixture["message_id"] == "msg_test_tool_failure"
        assert fixture["tool_call"]["success"] is False
        assert fixture["tool_call"]["status"] == "failed"
        assert fixture["tool_call"]["error"] == "Table not found"


class TestNextStepsEventContract:
    """Contract tests for next_steps events."""

    def test_next_steps_event(self):
        """Generate next_steps event fixture."""
        event = NextStepsEvent(
            step=1,
            next_steps=[
                {
                    "action_type": "message",
                    "label": "Provide query ID",
                    "message": "What's the query ID you need help with?",
                },
                {
                    "action_type": "message",
                    "label": "Show me the SQL",
                    "message": "Can you paste the SQL query text?",
                },
            ],
        )

        # Convert to SSE format
        chat_event = convert_streaming_event_to_chat_event(
            event=event,
            conversation_id="conv_test_123",
            message_id="msg_test_next_steps",
        )

        fixture = {
            "event_type": chat_event.type.value,
            "data": chat_event.data,
        }

        save_fixture("next_steps.json", fixture)

        assert chat_event.type == EventType.NEXT_STEPS
        assert "next_steps" in chat_event.data


class TestClarificationEventContract:
    """Contract tests for clarification events."""

    def test_clarification_request(self):
        """Generate clarification_request event fixture."""
        event = ClarificationRequestEvent(
            step=1,
            clarification_id="clar_test_123",
            clarification_type="ambiguous_reference",
            question="Which table are you referring to?",
            options=[
                {"option_id": "opt_1", "label": "users table", "value": "users"},
                {"option_id": "opt_2", "label": "orders table", "value": "orders"},
            ],
            allow_custom_response=False,
            is_required=True,
        )

        # Convert to SSE format
        chat_event = convert_streaming_event_to_chat_event(
            event=event,
            conversation_id="conv_test_123",
            message_id="msg_test_clarification",
        )

        fixture = {
            "event_type": chat_event.type.value,
            "data": chat_event.data,
        }

        save_fixture("clarification_request.json", fixture)

        assert chat_event.type == EventType.CLARIFICATION_REQUEST
        assert "question" in chat_event.data


class TestErrorEventContract:
    """Contract tests for error event."""

    def test_error_event(self):
        """Generate error event fixture (converts to error event type)."""
        event = ErrorEvent(
            step=1,
            error_type="TEST_ERROR",
            error="Test error occurred",
            is_recoverable=True,
        )

        # Convert to SSE format
        chat_event = convert_streaming_event_to_chat_event(
            event=event,
            conversation_id="conv_test_123",
            message_id="msg_test_error",
        )

        fixture = {
            "event_type": chat_event.type.value,
            "data": chat_event.data,
        }

        save_fixture("error_event.json", fixture)

        # ErrorEvent converts to ERROR event type
        assert chat_event.type == EventType.ERROR
        assert "error" in chat_event.data


class TestStepCompleteContract:
    """Contract tests for step.complete event."""

    def test_step_complete(self):
        """Generate step.complete event fixture."""
        event = StepCompleteEvent(
            step=1,
            tools_called=["fetch_table_metadata", "analyze_query_plan"],
        )

        fixture = event.to_sse_data(message_id="msg_test_step")
        save_fixture("step_complete.json", fixture)

        assert fixture["message_id"] == "msg_test_step"
        assert fixture["tools_called"] == ["fetch_table_metadata", "analyze_query_plan"]


# Test runner
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
