# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for event to_sse_data() serialization methods.

This module tests that all StreamingEvent subclasses correctly implement
the to_sse_data() method and produce the expected data structure for SSE broadcasting.
"""

from starboard_server.agents.events import (
    CheckpointEvent,
    ErrorEvent,
    FinalOutputEvent,
    InterruptReceivedEvent,
    ReplanEvent,
    SolicitationEvent,
    StepCompleteEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
    UserInputRequestEvent,
    UserInputResponseEvent,
)


class TestThinkingEventSerialization:
    """Test ThinkingEvent.to_sse_data()."""

    def test_to_sse_data_with_message_id(self):
        """Should nest content in delta object and include message_id."""
        event = ThinkingEvent(step=1, content="Analyzing query...")
        data = event.to_sse_data(message_id="msg_123")

        assert data == {
            "message_id": "msg_123",
            "delta": {
                "content": "Analyzing query...",
            },
        }

    def test_to_sse_data_without_message_id(self):
        """Should nest content in delta object, message_id can be None."""
        event = ThinkingEvent(step=1, content="Hello")
        data = event.to_sse_data(message_id=None)

        assert data == {
            "message_id": None,
            "delta": {
                "content": "Hello",
            },
        }


class TestToolStartEventSerialization:
    """Test ToolStartEvent.to_sse_data()."""

    def test_to_sse_data_with_all_fields(self):
        """Should nest tool data under tool_call key with status running."""
        event = ToolStartEvent(
            step=2,
            tool_name="get_table_metadata",
            friendly_name="Getting Table Metadata for main.users",
            tool_call_id="call_abc123",
            arguments={"table_name": "users"},
        )
        data = event.to_sse_data(message_id="msg_456")

        assert data == {
            "message_id": "msg_456",
            "tool_call": {
                "tool_name": "get_table_metadata",
                "friendly_name": "Getting Table Metadata for main.users",
                "tool_call_id": "call_abc123",
                "arguments": {"table_name": "users"},
                "status": "running",
            },
        }


class TestToolEndEventSerialization:
    """Test ToolEndEvent.to_sse_data()."""

    def test_to_sse_data_success(self):
        """Should include status=completed for successful tool execution."""
        event = ToolEndEvent(
            step=2,
            tool_name="get_table_metadata",
            friendly_name="Getting Table Metadata",
            tool_call_id="call_abc123",
            success=True,
            result_summary="Table has 5 columns",
            error=None,
            duration_seconds=0.5,
        )
        data = event.to_sse_data(message_id="msg_789")

        assert data == {
            "message_id": "msg_789",
            "tool_call": {
                "tool_name": "get_table_metadata",
                "friendly_name": "Getting Table Metadata",
                "tool_call_id": "call_abc123",
                "success": True,
                "status": "completed",
                "result": "Table has 5 columns",
                "error": None,
                "duration_ms": 500,
            },
        }

    def test_to_sse_data_failure(self):
        """Should include status=failed for failed tool execution."""
        event = ToolEndEvent(
            step=2,
            tool_name="get_table_metadata",
            friendly_name="Getting Table Metadata",
            tool_call_id="call_abc123",
            success=False,
            result_summary=None,
            error="Table not found",
            duration_seconds=0.2,
        )
        data = event.to_sse_data(message_id="msg_789")

        assert data["tool_call"]["status"] == "failed"
        assert data["tool_call"]["success"] is False
        assert data["tool_call"]["error"] == "Table not found"


class TestStepCompleteEventSerialization:
    """Test StepCompleteEvent.to_sse_data()."""

    def test_to_sse_data(self):
        """Should include all step metrics."""
        event = StepCompleteEvent(
            step=3,
            reasoning="Analyzed query plan successfully",
            tools_called=["analyze_query_plan", "fetch_metadata"],
        )
        data = event.to_sse_data(message_id="msg_xyz")

        assert data["message_id"] == "msg_xyz"
        assert data["step"] == 3
        assert data["reasoning"] == "Analyzed query plan successfully"
        assert data["tools_called"] == ["analyze_query_plan", "fetch_metadata"]


class TestFinalOutputEventSerialization:
    """Test FinalOutputEvent.to_sse_data()."""

    def test_to_sse_data_with_report(self):
        """Should nest output data and include formatted/complete reports."""

        # Create a mock output object
        class MockOutput:
            status = "success"
            complete_report = {"summary": {"overview": "Test report"}}
            tokens_used = 1000
            cost_usd = 0.05
            duration_seconds = 5.0
            steps_taken = 3

        event = FinalOutputEvent(output=MockOutput())
        data = event.to_sse_data(message_id="msg_final")

        assert data["message_id"] == "msg_final"
        assert "output" in data
        assert data["output"]["status"] == "success"
        assert data["output"]["tokens_used"] == 1000
        assert data["output"]["cost_usd"] == 0.05
        assert data["output"]["duration_seconds"] == 5.0
        assert data["output"]["steps_taken"] == 3
        assert "complete_report" in data["output"]
        # formatted_report is no longer included - clients generate markdown from complete_report


class TestErrorEventSerialization:
    """Test ErrorEvent.to_sse_data()."""

    def test_to_sse_data(self):
        """Should format as error event with structured error data."""
        event = ErrorEvent(
            step=2,
            error="Tool failed to execute",
            error_type="ToolExecutionError",
            is_recoverable=True,
        )
        data = event.to_sse_data(message_id="msg_err")

        assert data == {
            "message_id": "msg_err",
            "error": {
                "message": "Tool failed to execute",
                "type": "ToolExecutionError",
                "is_recoverable": True,
                "context": {},
            },
        }


class TestCheckpointEventSerialization:
    """Test CheckpointEvent.to_sse_data()."""

    def test_to_sse_data(self):
        """Should include all checkpoint fields."""
        event = CheckpointEvent(
            step=3,
            checkpoint_id="ckpt_abc123",
            checkpoint_type="reasoning_step",
            can_interrupt=True,
            metadata={"key": "value"},
        )
        data = event.to_sse_data(message_id="msg_ckpt")

        assert data["message_id"] == "msg_ckpt"
        assert data["checkpoint_id"] == "ckpt_abc123"
        assert data["checkpoint_type"] == "reasoning_step"
        assert data["can_interrupt"] is True
        assert data["metadata"] == {"key": "value"}


class TestInterruptReceivedEventSerialization:
    """Test InterruptReceivedEvent.to_sse_data()."""

    def test_to_sse_data(self):
        """Should include all interrupt fields."""
        event = InterruptReceivedEvent(
            step=3,
            input_id="input_xyz789",
            input_type="context_injection",
            content_preview="Focus on partition pruning...",
            checkpoint_id="ckpt_abc123",
        )
        data = event.to_sse_data(message_id="msg_int")

        assert data["message_id"] == "msg_int"
        assert data["input_id"] == "input_xyz789"
        assert data["input_type"] == "context_injection"
        assert data["content_preview"] == "Focus on partition pruning..."
        assert data["checkpoint_id"] == "ckpt_abc123"


class TestReplanEventSerialization:
    """Test ReplanEvent.to_sse_data()."""

    def test_to_sse_data(self):
        """Should include all replan fields."""
        event = ReplanEvent(
            step=4,
            decision_id="dec_def456",
            strategy="soft_replan",
            reasoning="User clarified schema",
            impact_score=0.6,
            affected_steps=[2, 3],
            actions=["Update SQL", "Re-run step 3"],
        )
        data = event.to_sse_data(message_id="msg_replan")

        assert data["message_id"] == "msg_replan"
        assert data["decision_id"] == "dec_def456"
        assert data["strategy"] == "soft_replan"
        assert data["reasoning"] == "User clarified schema"
        assert data["impact_score"] == 0.6
        assert data["affected_steps"] == [2, 3]
        assert data["actions"] == ["Update SQL", "Re-run step 3"]


class TestSolicitationEventSerialization:
    """Test SolicitationEvent.to_sse_data()."""

    def test_to_sse_data(self):
        """Should include all solicitation fields."""
        event = SolicitationEvent(
            step=2,
            solicitation_id="sol_ghi789",
            question="Which service principal?",
            context="Need credentials for DB",
            expected_response_type="text",
            suggestions=["sp-prod-reader", "sp-prod-writer"],
            timeout_seconds=300,
        )
        data = event.to_sse_data(message_id="msg_sol")

        assert data["message_id"] == "msg_sol"
        assert data["solicitation_id"] == "sol_ghi789"
        assert data["question"] == "Which service principal?"
        assert data["context"] == "Need credentials for DB"
        assert data["expected_response_type"] == "text"
        assert data["suggestions"] == ["sp-prod-reader", "sp-prod-writer"]
        assert data["timeout_seconds"] == 300


class TestUserInputRequestEventSerialization:
    """Test UserInputRequestEvent.to_sse_data()."""

    def test_to_sse_data(self):
        """Should include all user input request fields."""
        event = UserInputRequestEvent(
            step=2,
            question="Which warehouse to use?",
            context="Multiple warehouses found",
            suggestions=["warehouse_prod", "warehouse_dev"],
            timeout_seconds=300,
            request_id="input_abc123",
        )
        data = event.to_sse_data(message_id="msg_input")

        assert data["message_id"] == "msg_input"
        assert data["request_id"] == "input_abc123"
        assert data["question"] == "Which warehouse to use?"
        assert data["context"] == "Multiple warehouses found"
        assert data["suggestions"] == ["warehouse_prod", "warehouse_dev"]
        assert data["timeout_seconds"] == 300


class TestUserInputResponseEventSerialization:
    """Test UserInputResponseEvent.to_sse_data()."""

    def test_to_sse_data(self):
        """Should include all user input response fields."""
        event = UserInputResponseEvent(
            step=2,
            request_id="input_abc123",
            user_response="warehouse_prod",
            timed_out=False,
        )
        data = event.to_sse_data(message_id="msg_response")

        assert data["message_id"] == "msg_response"
        assert data["request_id"] == "input_abc123"
        assert data["user_response"] == "warehouse_prod"
        assert data["timed_out"] is False

    def test_to_sse_data_timeout(self):
        """Should handle timeout case."""
        event = UserInputResponseEvent(
            step=2,
            request_id="input_abc123",
            user_response="",
            timed_out=True,
        )
        data = event.to_sse_data(message_id="msg_response")

        assert data["timed_out"] is True
