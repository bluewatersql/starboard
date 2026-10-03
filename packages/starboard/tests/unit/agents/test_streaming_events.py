# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for streaming events module.

This module provides comprehensive testing for:
- All StreamingEvent types (Thinking, ToolStart, ToolProgress, etc.)
- Event creation and validation
- Immutability (frozen=True)
- Factory functions
- String representations
- Pydantic validation

Follows Python AI Agent Engineering Standards:
- 100% coverage target (critical path)
- Test edge cases (empty, null, extreme values)
- Test error paths
- Descriptive test names
"""

import pytest  # pyright: ignore[reportMissingImports]
from pydantic import ValidationError
from starboard.agents.events import (
    CheckpointEvent,
    ErrorEvent,
    EventType,
    FinalOutputEvent,
    InterruptReceivedEvent,
    ReplanEvent,
    SolicitationEvent,
    StepCompleteEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolProgressEvent,
    ToolStartEvent,
    UserInputRequestEvent,
    UserInputResponseEvent,
    create_checkpoint_event,
    create_error_event,
    create_final_output_event,
    create_interrupt_received_event,
    create_replan_event,
    create_solicitation_event,
    create_step_complete_event,
    # Factory functions (not all event types have factories)
    create_thinking_event,
    create_tool_end_event,
    create_tool_start_event,
    create_user_input_request_event,
)

# ============================================================================
# EventType Enum Tests
# ============================================================================


class TestEventType:
    """Test suite for EventType enum."""

    def test_all_event_types_defined(self):
        """Test that all expected event types are defined."""
        expected_types = {
            "thinking",
            "tool_start",
            "tool.progress",
            "tool_end",
            "step.complete",
            "step.start",  # Added for step lifecycle
            "user_input_request",
            "user_input_response",
            "final_output",
            "error",
            "next_steps",  # Phase 1: Pattern 1 (Option Selection)
            "checkpoint",
            "interrupt.received",  # Changed from interrupt_received
            "replan",
            "solicitation",
            "clarification.request",  # Phase 1: Pattern 4 (Clarification)
            "handoff",  # Phase 1: Pattern 3 (Agent Routing)
        }

        actual_types = {e.value for e in EventType}
        assert actual_types == expected_types

    def test_event_type_values(self):
        """Test that event types have correct values."""
        assert EventType.THINKING.value == "thinking"
        assert EventType.TOOL_START.value == "tool_start"
        assert EventType.ERROR.value == "error"
        assert EventType.CHECKPOINT.value == "checkpoint"


# ============================================================================
# ThinkingEvent Tests
# ============================================================================


class TestThinkingEvent:
    """Test suite for ThinkingEvent."""

    def test_create_thinking_event(self):
        """Test creating a ThinkingEvent."""
        event = ThinkingEvent(step=1, content="Let me analyze...", is_complete=False)

        assert event.type == EventType.THINKING
        assert event.step == 1
        assert event.content == "Let me analyze..."
        assert event.is_complete is False

    def test_thinking_event_complete(self):
        """Test ThinkingEvent with is_complete=True."""
        event = ThinkingEvent(step=2, content="Analysis complete.", is_complete=True)

        assert event.is_complete is True
        assert event.content == "Analysis complete."

    def test_thinking_event_empty_content(self):
        """Test ThinkingEvent with empty content."""
        event = ThinkingEvent(step=1, content="", is_complete=False)

        assert event.content == ""

    def test_thinking_event_str_representation(self):
        """Test __str__ method of ThinkingEvent."""
        event = ThinkingEvent(
            step=3,
            content="This is a long thinking text that exceeds 50 characters",
            is_complete=False,
        )

        str_repr = str(event)
        assert "[Step 3]" in str_repr
        assert "Thinking:" in str_repr

    def test_thinking_event_immutable(self):
        """Test that ThinkingEvent is immutable (frozen)."""
        event = ThinkingEvent(step=1, content="Test", is_complete=False)

        with pytest.raises(ValidationError):
            event.content = "Modified"  # Should raise error

    def test_thinking_event_negative_step_fails(self):
        """Test that negative step number fails validation."""
        with pytest.raises(ValidationError):
            ThinkingEvent(step=-1, content="Test", is_complete=False)

    def test_thinking_event_default_is_complete(self):
        """Test that is_complete defaults to False."""
        event = ThinkingEvent(step=1, content="Test")

        assert event.is_complete is False


# ============================================================================
# ToolStartEvent Tests
# ============================================================================


class TestToolStartEvent:
    """Test suite for ToolStartEvent."""

    def test_create_tool_start_event(self):
        """Test creating a ToolStartEvent."""
        event = ToolStartEvent(
            step=2,
            tool_name="get_table_metadata",
            friendly_name="Fetch Table Metadata",
            tool_call_id="call_123",
            arguments={"table_name": "users"},
        )

        assert event.type == EventType.TOOL_START
        assert event.step == 2
        assert event.tool_name == "get_table_metadata"
        assert event.friendly_name == "Fetch Table Metadata"
        assert event.tool_call_id == "call_123"
        assert event.arguments == {"table_name": "users"}

    def test_tool_start_event_empty_arguments(self):
        """Test ToolStartEvent with no arguments."""
        event = ToolStartEvent(
            step=1,
            tool_name="test_tool",
            friendly_name="Test Tool",
            tool_call_id="call_1",
        )

        assert event.arguments == {}

    def test_tool_start_event_str_representation(self):
        """Test __str__ method of ToolStartEvent."""
        event = ToolStartEvent(
            step=5,
            tool_name="analyze",
            friendly_name="Analyze Query Plan",
            tool_call_id="call_1",
            arguments={},
        )

        str_repr = str(event)
        assert "[Step 5]" in str_repr
        assert "Tool Start:" in str_repr
        assert "Analyze Query Plan" in str_repr


# ============================================================================
# ToolProgressEvent Tests
# ============================================================================


class TestToolProgressEvent:
    """Test suite for ToolProgressEvent."""

    def test_create_tool_progress_event(self):
        """Test creating a ToolProgressEvent."""
        event = ToolProgressEvent(
            step=2,
            tool_name="analyze_query",
            tool_call_id="call_123",
            progress=50.0,
            message="Analyzing execution plan...",
        )

        assert event.type == EventType.TOOL_PROGRESS
        assert event.step == 2
        assert event.tool_name == "analyze_query"
        assert event.tool_call_id == "call_123"
        assert event.progress == 50.0
        assert event.message == "Analyzing execution plan..."

    def test_tool_progress_event_no_message(self):
        """Test ToolProgressEvent with no message."""
        event = ToolProgressEvent(
            step=1, tool_name="test", tool_call_id="call_1", progress=75.5
        )

        assert event.message is None

    def test_tool_progress_event_zero_progress(self):
        """Test ToolProgressEvent with 0% progress."""
        event = ToolProgressEvent(
            step=1, tool_name="test", tool_call_id="call_1", progress=0.0
        )

        assert event.progress == 0.0

    def test_tool_progress_event_hundred_progress(self):
        """Test ToolProgressEvent with 100% progress."""
        event = ToolProgressEvent(
            step=1, tool_name="test", tool_call_id="call_1", progress=100.0
        )

        assert event.progress == 100.0

    def test_tool_progress_event_invalid_progress_negative(self):
        """Test that negative progress fails validation."""
        with pytest.raises(ValidationError):
            ToolProgressEvent(
                step=1, tool_name="test", tool_call_id="call_1", progress=-1.0
            )

    def test_tool_progress_event_invalid_progress_over_100(self):
        """Test that progress > 100 fails validation."""
        with pytest.raises(ValidationError):
            ToolProgressEvent(
                step=1, tool_name="test", tool_call_id="call_1", progress=101.0
            )

    def test_tool_progress_event_str_representation(self):
        """Test __str__ method of ToolProgressEvent."""
        event = ToolProgressEvent(
            step=3, tool_name="analyze", tool_call_id="call_1", progress=67.8
        )

        str_repr = str(event)
        assert "[Step 3]" in str_repr
        assert "Tool Progress:" in str_repr
        assert "analyze" in str_repr
        assert "68%" in str_repr or "67%" in str_repr  # Formatted progress


# ============================================================================
# ToolEndEvent Tests
# ============================================================================


class TestToolEndEvent:
    """Test suite for ToolEndEvent."""

    def test_create_tool_end_event_success(self):
        """Test creating a successful ToolEndEvent."""
        event = ToolEndEvent(
            step=2,
            tool_name="fetch_metadata",
            friendly_name="Fetch Metadata",
            tool_call_id="call_123",
            success=True,
            result_summary="Table has 5 columns",
            duration_seconds=0.5,
        )

        assert event.type == EventType.TOOL_END
        assert event.step == 2
        assert event.success is True
        assert event.result_summary == "Table has 5 columns"
        assert event.error is None
        assert event.duration_seconds == 0.5

    def test_create_tool_end_event_failure(self):
        """Test creating a failed ToolEndEvent."""
        event = ToolEndEvent(
            step=3,
            tool_name="analyze",
            friendly_name="Analyze Query",
            tool_call_id="call_456",
            success=False,
            error="Connection timeout",
            duration_seconds=30.0,
        )

        assert event.success is False
        assert event.error == "Connection timeout"
        assert event.result_summary is None

    def test_tool_end_event_negative_duration_fails(self):
        """Test that negative duration fails validation."""
        with pytest.raises(ValidationError):
            ToolEndEvent(
                step=1,
                tool_name="test",
                friendly_name="Test",
                tool_call_id="call_1",
                success=True,
                duration_seconds=-1.0,
            )

    def test_tool_end_event_str_representation_success(self):
        """Test __str__ method for successful tool end."""
        event = ToolEndEvent(
            step=4,
            tool_name="test",
            friendly_name="Test Tool",
            tool_call_id="call_1",
            success=True,
            duration_seconds=1.0,
        )

        str_repr = str(event)
        assert "[Step 4]" in str_repr
        assert "Tool End:" in str_repr
        assert "Success" in str_repr

    def test_tool_end_event_str_representation_error(self):
        """Test __str__ method for failed tool end."""
        event = ToolEndEvent(
            step=5,
            tool_name="test",
            friendly_name="Test Tool",
            tool_call_id="call_1",
            success=False,
            error="Failed",
            duration_seconds=0.1,
        )

        str_repr = str(event)
        assert "[Step 5]" in str_repr
        assert "Tool End:" in str_repr
        assert "Error" in str_repr


# ============================================================================
# StepCompleteEvent Tests
# ============================================================================


class TestStepCompleteEvent:
    """Test suite for StepCompleteEvent."""

    def test_create_step_complete_event(self):
        """Test creating a StepCompleteEvent."""
        event = StepCompleteEvent(
            step=2,
            tools_called=["resolve_query", "analyze_query", "get_metadata"],
            reasoning="Analyzed the query plan",
        )

        assert event.type == EventType.STEP_COMPLETE
        assert event.step == 2
        assert len(event.tools_called) == 3
        assert event.reasoning == "Analyzed the query plan"

    def test_step_complete_event_final_step(self):
        """Test StepCompleteEvent with tools called."""
        event = StepCompleteEvent(
            step=10,
            tools_called=["final_tool"],
            reasoning="Final step completed",
        )

        assert event.step == 10
        assert len(event.tools_called) == 1

    def test_step_complete_event_no_tools(self):
        """Test StepCompleteEvent with no tools called."""
        event = StepCompleteEvent(
            step=1,
            tools_called=[],
        )

        assert event.tools_called == []
        assert len(event.tools_called) == 0

    def test_step_complete_event_negative_values_fail(self):
        """Test that negative step values fail validation."""
        with pytest.raises(ValidationError):
            StepCompleteEvent(step=-1, tools_called=[])

    def test_step_complete_event_str_representation(self):
        """Test __str__ method of StepCompleteEvent."""
        event = StepCompleteEvent(step=6, tools_called=["tool1", "tool2"])

        str_repr = str(event)
        assert "[Step 6]" in str_repr
        assert "Complete" in str_repr

    def test_step_complete_event_factory_with_tools(self):
        """Test that factory function works with tool list."""
        event = create_step_complete_event(
            step=7,
            tools_called=["tool1", "tool2", "tool3", "tool4", "tool5"],
            reasoning="Executed multiple tools",
        )

        assert event.step == 7
        assert len(event.tools_called) == 5
        assert event.reasoning == "Executed multiple tools"


# ============================================================================
# ErrorEvent Tests
# ============================================================================


class TestErrorEvent:
    """Test suite for ErrorEvent."""

    def test_create_error_event(self):
        """Test creating an ErrorEvent."""
        event = ErrorEvent(
            step=3,
            error="Tool execution failed",
            error_type="ToolExecutionError",
            is_recoverable=True,
            context={"partial_result": "Partial data: 50% complete"},
        )

        assert event.type == EventType.ERROR
        assert event.step == 3
        assert event.error_type == "ToolExecutionError"
        assert event.error == "Tool execution failed"
        assert event.is_recoverable is True
        assert event.context.get("partial_result") == "Partial data: 50% complete"

    def test_error_event_not_recoverable(self):
        """Test ErrorEvent with no recovery possible."""
        event = ErrorEvent(
            step=1,
            error="Something went wrong",
            error_type="GenericError",
            is_recoverable=False,
        )

        assert event.is_recoverable is False
        assert event.context == {}

    def test_error_event_str_representation(self):
        """Test __str__ method of ErrorEvent."""
        event = ErrorEvent(step=7, error="API returned 500", error_type="APIError")

        str_repr = str(event)
        assert "[Step 7]" in str_repr
        assert "Error" in str_repr
        assert "API returned 500" in str_repr


# ============================================================================
# UserInputRequestEvent Tests
# ============================================================================


class TestUserInputRequestEvent:
    """Test suite for UserInputRequestEvent."""

    def test_create_user_input_request_event(self):
        """Test creating a UserInputRequestEvent."""
        event = UserInputRequestEvent(
            step=2,
            question="Which table should I analyze?",
            context="I found multiple tables matching your description",
            suggestions=["users", "orders", "products"],
            timeout_seconds=60,
            request_id="req_123",
        )

        assert event.type == EventType.USER_INPUT_REQUEST
        assert event.step == 2
        assert event.question == "Which table should I analyze?"
        assert event.context == "I found multiple tables matching your description"
        assert event.suggestions == ["users", "orders", "products"]
        assert event.timeout_seconds == 60
        assert event.request_id == "req_123"

    def test_user_input_request_event_minimal(self):
        """Test UserInputRequestEvent with minimal fields."""
        event = UserInputRequestEvent(step=1, question="Proceed?", request_id="req_1")

        assert event.context is None
        assert event.suggestions == []
        assert event.timeout_seconds is None

    def test_user_input_request_event_str_representation(self):
        """Test __str__ method of UserInputRequestEvent."""
        event = UserInputRequestEvent(
            step=3,
            question="A very long question that exceeds 50 characters for truncation test?",
            request_id="req_2",
        )

        str_repr = str(event)
        assert "[Step 3]" in str_repr
        assert "User Input Request:" in str_repr


# ============================================================================
# UserInputResponseEvent Tests
# ============================================================================


class TestUserInputResponseEvent:
    """Test suite for UserInputResponseEvent."""

    def test_create_user_input_response_event(self):
        """Test creating a UserInputResponseEvent."""
        event = UserInputResponseEvent(
            step=2,
            request_id="req_123",
            user_response="warehouse_prod",
            timed_out=False,
        )

        assert event.type == EventType.USER_INPUT_RESPONSE
        assert event.step == 2
        assert event.request_id == "req_123"
        assert event.user_response == "warehouse_prod"
        assert event.timed_out is False

    def test_user_input_response_event_timed_out(self):
        """Test UserInputResponseEvent with timeout."""
        event = UserInputResponseEvent(
            step=3, request_id="req_456", user_response="", timed_out=True
        )

        assert event.timed_out is True
        assert event.user_response == ""

    def test_user_input_response_event_str_representation_success(self):
        """Test __str__ method for successful response."""
        event = UserInputResponseEvent(
            step=2,
            request_id="req_1",
            user_response="My response text",
            timed_out=False,
        )

        str_repr = str(event)
        assert "[Step 2]" in str_repr
        assert "User Input" in str_repr
        assert "chars" in str_repr

    def test_user_input_response_event_str_representation_timeout(self):
        """Test __str__ method for timed out response."""
        event = UserInputResponseEvent(
            step=4, request_id="req_2", user_response="", timed_out=True
        )

        str_repr = str(event)
        assert "[Step 4]" in str_repr
        assert "timeout" in str_repr


# ============================================================================
# FinalOutputEvent Tests
# ============================================================================


class TestFinalOutputEvent:
    """Test suite for FinalOutputEvent."""

    def test_create_final_output_event_with_dict(self):
        """Test creating FinalOutputEvent with dictionary output."""
        output_data = {
            "summary": "Query is slow due to missing index",
            "recommendations": ["Add index on user_id"],
            "cost_usd": 0.05,
        }
        event = FinalOutputEvent(output=output_data)

        assert event.output == output_data

    def test_create_final_output_event_with_string(self):
        """Test creating FinalOutputEvent with string output."""
        event = FinalOutputEvent(output="Analysis complete")

        assert event.output == "Analysis complete"

    def test_final_output_event_str_representation(self):
        """Test __str__ method of FinalOutputEvent."""
        event = FinalOutputEvent(output={"result": "success"})

        str_repr = str(event)
        assert "Final Output:" in str_repr


# ============================================================================
# CheckpointEvent Tests
# ============================================================================


class TestCheckpointEvent:
    """Test suite for CheckpointEvent."""

    def test_create_checkpoint_event(self):
        """Test creating a CheckpointEvent."""
        event = CheckpointEvent(
            step=5,
            checkpoint_id="chk_789",
            checkpoint_type="reasoning_step",
            can_interrupt=True,
        )

        assert event.type == EventType.CHECKPOINT
        assert event.step == 5
        assert event.checkpoint_id == "chk_789"
        assert event.checkpoint_type == "reasoning_step"
        assert event.can_interrupt is True

    def test_checkpoint_event_no_interrupt(self):
        """Test CheckpointEvent with can_interrupt=False."""
        event = CheckpointEvent(
            step=3,
            checkpoint_id="chk_no_int",
            checkpoint_type="tool_call",
            can_interrupt=False,
            metadata={"tool_name": "analyze"},
        )

        assert event.can_interrupt is False
        assert event.metadata == {"tool_name": "analyze"}

    def test_checkpoint_event_str_representation(self):
        """Test __str__ method of CheckpointEvent."""
        event = CheckpointEvent(
            step=7,
            checkpoint_id="chk_xyz",
            checkpoint_type="reasoning_step",
            can_interrupt=True,
        )

        str_repr = str(event)
        assert "[Step 7]" in str_repr
        assert "Checkpoint:" in str_repr
        assert "chk_xyz" in str_repr


# ============================================================================
# InterruptReceivedEvent Tests
# ============================================================================


class TestInterruptReceivedEvent:
    """Test suite for InterruptReceivedEvent."""

    def test_create_interrupt_received_event(self):
        """Test creating an InterruptReceivedEvent."""
        event = InterruptReceivedEvent(
            step=4,
            input_id="input_xyz789",
            input_type="context_injection",
            content_preview="Focus on partition pruning...",
            checkpoint_id="chk_abc123",
        )

        assert event.type == EventType.INTERRUPT_RECEIVED
        assert event.step == 4
        assert event.input_id == "input_xyz789"
        assert event.input_type == "context_injection"
        assert event.content_preview == "Focus on partition pruning..."
        assert event.checkpoint_id == "chk_abc123"

    def test_interrupt_received_event_str_representation(self):
        """Test __str__ method of InterruptReceivedEvent."""
        event = InterruptReceivedEvent(
            step=8,
            input_id="input_123",
            input_type="cancel",
            content_preview="User cancelled",
            checkpoint_id="chk_1",
        )

        str_repr = str(event)
        assert "[Step 8]" in str_repr
        assert "Interrupt:" in str_repr
        assert "cancel" in str_repr


# ============================================================================
# ReplanEvent Tests
# ============================================================================


class TestReplanEvent:
    """Test suite for ReplanEvent."""

    def test_create_replan_event(self):
        """Test creating a ReplanEvent."""
        event = ReplanEvent(
            step=6,
            decision_id="dec_def456",
            strategy="soft_replan",
            reasoning="User clarified DB schema; update query only",
            impact_score=0.6,
            affected_steps=[2, 3],
            actions=["Update SQL in step 3", "Re-run step 3"],
        )

        assert event.type == EventType.REPLAN
        assert event.step == 6
        assert event.decision_id == "dec_def456"
        assert event.strategy == "soft_replan"
        assert event.reasoning == "User clarified DB schema; update query only"
        assert event.impact_score == 0.6
        assert event.affected_steps == [2, 3]
        assert event.actions == ["Update SQL in step 3", "Re-run step 3"]

    def test_replan_event_str_representation(self):
        """Test __str__ method of ReplanEvent."""
        event = ReplanEvent(
            step=9,
            decision_id="dec_1",
            strategy="hard_replan",
            reasoning="Major context change",
            impact_score=0.85,
            affected_steps=[8, 9],
            actions=["Reset state"],
        )

        str_repr = str(event)
        assert "[Step 9]" in str_repr
        assert "Replan:" in str_repr
        assert "hard_replan" in str_repr


# ============================================================================
# SolicitationEvent Tests
# ============================================================================


class TestSolicitationEvent:
    """Test suite for SolicitationEvent."""

    def test_create_solicitation_event(self):
        """Test creating a SolicitationEvent."""
        event = SolicitationEvent(
            step=7,
            solicitation_id="sol_ghi789",
            question="Which service principal should I use?",
            context="Need credentials to access production database",
            expected_response_type="text",
            suggestions=["sp-prod-reader", "sp-prod-writer"],
            timeout_seconds=300,
        )

        assert event.type == EventType.SOLICITATION
        assert event.step == 7
        assert event.solicitation_id == "sol_ghi789"
        assert event.question == "Which service principal should I use?"
        assert event.context == "Need credentials to access production database"
        assert event.expected_response_type == "text"
        assert event.suggestions == ["sp-prod-reader", "sp-prod-writer"]
        assert event.timeout_seconds == 300

    def test_solicitation_event_str_representation(self):
        """Test __str__ method of SolicitationEvent."""
        event = SolicitationEvent(
            step=10,
            solicitation_id="sol_1",
            question="A very long solicitation question that exceeds 50 characters for testing?",
            expected_response_type="text",
        )

        str_repr = str(event)
        assert "[Step 10]" in str_repr
        assert "Solicitation:" in str_repr


# ============================================================================
# Factory Function Tests
# ============================================================================


class TestFactoryFunctions:
    """Test suite for factory functions."""

    def test_create_thinking_event_factory(self):
        """Test create_thinking_event factory function."""
        event = create_thinking_event(step=1, content="Thinking...", is_complete=False)

        assert isinstance(event, ThinkingEvent)
        assert event.step == 1
        assert event.content == "Thinking..."

    def test_create_tool_start_event_factory(self):
        """Test create_tool_start_event factory function."""
        event = create_tool_start_event(
            step=2,
            tool_name="test",
            friendly_name="Test Tool",
            tool_call_id="call_1",
            arguments={"key": "value"},
        )

        assert isinstance(event, ToolStartEvent)
        assert event.tool_name == "test"

    def test_create_tool_start_event_factory_with_table_metadata(self):
        """Test create_tool_start_event with table metadata tool (triggers logging)."""
        event = create_tool_start_event(
            step=3,
            tool_name="get_table_metadata",
            friendly_name=None,  # Test auto-generation and logging
            tool_call_id="call_2",
            arguments={"table_name": "users"},
        )

        assert isinstance(event, ToolStartEvent)
        assert event.tool_name == "get_table_metadata"
        # Friendly name should be auto-generated
        assert event.friendly_name is not None

    def test_create_tool_end_event_factory(self):
        """Test create_tool_end_event factory function."""
        event = create_tool_end_event(
            step=2,
            tool_name="test",
            friendly_name="Test",
            tool_call_id="call_1",
            success=True,
            result_summary="Success",
            error=None,
            duration_seconds=1.0,
        )

        assert isinstance(event, ToolEndEvent)
        assert event.success is True

    def test_create_step_complete_event_factory(self):
        """Test create_step_complete_event factory function."""
        event = create_step_complete_event(
            step=3,
            tools_called=["tool1", "tool2"],
            reasoning="Step completed successfully",
        )

        assert isinstance(event, StepCompleteEvent)
        assert len(event.tools_called) == 2

    def test_create_user_input_request_event_factory(self):
        """Test create_user_input_request_event factory function."""
        event = create_user_input_request_event(
            step=4,
            question="Which option?",
            request_id="req_1",
            context="Choose one",
            suggestions=["A", "B"],
            timeout_seconds=30,
        )

        assert isinstance(event, UserInputRequestEvent)
        assert event.question == "Which option?"

    def test_create_final_output_event_factory(self):
        """Test create_final_output_event factory function."""
        event = create_final_output_event(output={"result": "done"})

        assert isinstance(event, FinalOutputEvent)
        assert event.output == {"result": "done"}

    def test_create_error_event_factory(self):
        """Test create_error_event factory function."""
        event = create_error_event(
            step=5,
            error="Test failed",
            error_type="TestError",
            is_recoverable=True,
            context={"partial_result": "Partial data"},
        )

        assert isinstance(event, ErrorEvent)
        assert event.error_type == "TestError"
        assert event.error == "Test failed"

    def test_create_checkpoint_event_factory(self):
        """Test create_checkpoint_event factory function."""
        event = create_checkpoint_event(
            step=6,
            checkpoint_id="chk_1",
            checkpoint_type="reasoning_step",
            can_interrupt=True,
            metadata={"test": "data"},
        )

        assert isinstance(event, CheckpointEvent)
        assert event.checkpoint_id == "chk_1"
        assert event.checkpoint_type == "reasoning_step"

    def test_create_interrupt_received_event_factory(self):
        """Test create_interrupt_received_event factory function."""
        event = create_interrupt_received_event(
            step=7,
            input_id="input_1",
            input_type="cancel",
            content_preview="Cancelled by user",
            checkpoint_id="chk_1",
        )

        assert isinstance(event, InterruptReceivedEvent)
        assert event.input_type == "cancel"
        assert event.input_id == "input_1"

    def test_create_replan_event_factory(self):
        """Test create_replan_event factory function."""
        event = create_replan_event(
            step=8,
            decision_id="dec_1",
            strategy="soft_replan",
            reasoning="Context changed",
            impact_score=0.5,
            affected_steps=[7, 8],
            actions=["Update plan"],
        )

        assert isinstance(event, ReplanEvent)
        assert event.reasoning == "Context changed"
        assert event.strategy == "soft_replan"

    def test_create_solicitation_event_factory(self):
        """Test create_solicitation_event factory function."""
        event = create_solicitation_event(
            step=9,
            solicitation_id="sol_1",
            question="Enter value",
            expected_response_type="int",
            suggestions=["1", "2"],
            timeout_seconds=60,
        )

        assert isinstance(event, SolicitationEvent)
        assert event.solicitation_id == "sol_1"
        assert event.question == "Enter value"


# ============================================================================
# Pydantic Model Tests
# ============================================================================


class TestPydanticValidation:
    """Test Pydantic validation and serialization."""

    def test_event_serialization_to_dict(self):
        """Test serializing event to dictionary."""
        event = ThinkingEvent(step=1, content="Test", is_complete=False)
        data = event.model_dump()

        assert data["type"] == "thinking"
        assert data["step"] == 1
        assert data["content"] == "Test"
        assert data["is_complete"] is False

    def test_event_serialization_to_json(self):
        """Test serializing event to JSON."""
        event = ToolStartEvent(
            step=2, tool_name="test", friendly_name="Test", tool_call_id="call_1"
        )
        json_str = event.model_dump_json()

        assert '"type":"tool_start"' in json_str or '"type": "tool_start"' in json_str
        assert '"step":2' in json_str or '"step": 2' in json_str

    def test_event_parse_from_dict(self):
        """Test parsing event from dictionary."""
        data = {
            "type": "thinking",
            "step": 3,
            "content": "Parsing test",
            "is_complete": True,
        }
        event = ThinkingEvent(**data)

        assert event.step == 3
        assert event.content == "Parsing test"
        assert event.is_complete is True

    def test_event_missing_required_field_fails(self):
        """Test that missing required fields fail validation."""
        with pytest.raises(ValidationError):
            ThinkingEvent(step=1)  # Missing 'content'

    def test_event_wrong_type_fails(self):
        """Test that wrong types fail validation."""
        with pytest.raises(ValidationError):
            ThinkingEvent(step="not_a_number", content="Test")


# ============================================================================
# Edge Cases and Special Scenarios
# ============================================================================


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_very_long_content(self):
        """Test event with very long content."""
        long_content = "x" * 10000
        event = ThinkingEvent(step=1, content=long_content, is_complete=False)

        assert len(event.content) == 10000

    def test_unicode_content(self):
        """Test event with unicode characters."""
        event = ThinkingEvent(
            step=1, content="Unicode: 你好 🎉 émoji", is_complete=False
        )

        assert "你好" in event.content
        assert "🎉" in event.content

    def test_special_characters_in_tool_name(self):
        """Test tool event with special characters."""
        event = ToolStartEvent(
            step=1,
            tool_name="get_table_metadata",
            friendly_name="Fetch: Table's Metadata (v2)",
            tool_call_id="call-123",
        )

        assert event.friendly_name == "Fetch: Table's Metadata (v2)"

    def test_zero_step_number(self):
        """Test event with step=0."""
        event = ThinkingEvent(step=0, content="Initial", is_complete=False)

        assert event.step == 0

    def test_very_large_step_number(self):
        """Test event with very large step number."""
        event = ThinkingEvent(step=99999, content="Test", is_complete=False)

        assert event.step == 99999

    def test_empty_suggestions_list(self):
        """Test UserInputRequestEvent with empty suggestions."""
        event = UserInputRequestEvent(
            step=1, question="Yes or no?", request_id="req_1", suggestions=[]
        )

        assert event.suggestions == []

    def test_null_optional_fields(self):
        """Test that None values work for optional fields."""
        event = ToolEndEvent(
            step=1,
            tool_name="test",
            friendly_name="Test",
            tool_call_id="call_1",
            success=True,
            result_summary=None,
            error=None,
            duration_seconds=0.5,
        )

        assert event.result_summary is None
        assert event.error is None
