"""Unit tests for agent next steps support.

Tests agent output with next steps for interactive conversation patterns.

Part of Phase 1: Foundation - Component 5
"""

import pytest
from starboard_server.agents.events import EventType, NextStepsEvent
from starboard_server.agents.state.agent_state import AgentOutput
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)


class TestAgentOutputWithNextSteps:
    """Test AgentOutput with next_steps field."""

    def test_agent_output_without_next_steps(self):
        """AgentOutput should work without next_steps (backward compatibility)."""
        output = AgentOutput(
            status="success",
            recommendations=[{"title": "Optimize query"}],
            reasoning_trace=[],
            steps_taken=3,
            tools_used=["resolve_query"],
            tokens_used=150,
            cost_usd=0.001,
            duration_seconds=2.5,
        )

        assert output.status == "success"
        assert output.next_steps is None

    def test_agent_output_with_empty_next_steps(self):
        """AgentOutput can have empty next_steps list."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=50,
            cost_usd=0.0001,
            duration_seconds=1.0,
            next_steps=[],
        )

        assert output.next_steps == []

    def test_agent_output_with_next_steps(self):
        """AgentOutput can include next step options."""
        next_steps = [
            NextStepOption(
                id="opt1",
                number=1,
                title="Optimize query",
                description="Rewrite query for better performance",
                action_type=ActionType.TOOL_CALL,
                target_agent=None,
                tool_name="optimize_query",
                parameters={"query_id": "123"},
            ),
            NextStepOption(
                id="opt2",
                number=2,
                title="Route to cost analyzer",
                description=None,
                action_type=ActionType.ROUTE,
                target_agent="cost_analyzer",
                tool_name=None,
                parameters=None,
            ),
        ]

        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=2,
            tools_used=["resolve_query"],
            tokens_used=200,
            cost_usd=0.002,
            duration_seconds=3.0,
            next_steps=next_steps,
        )

        assert output.next_steps is not None
        assert len(output.next_steps) == 2
        assert output.next_steps[0].number == 1
        assert output.next_steps[0].action_type == ActionType.TOOL_CALL
        assert output.next_steps[1].number == 2
        assert output.next_steps[1].action_type == ActionType.ROUTE

    def test_agent_output_validates_next_steps_count(self):
        """AgentOutput validates next_steps count (1-9 options)."""
        # More than 9 options should raise error
        too_many_steps = [
            NextStepOption(
                id=f"opt{i}",
                number=i,
                title=f"Option {i}",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            )
            for i in range(1, 11)  # 10 options
        ]

        with pytest.raises(ValueError, match="next_steps must contain 1-9 options"):
            AgentOutput(
                status="success",
                recommendations=[],
                reasoning_trace=[],
                steps_taken=1,
                tools_used=[],
                tokens_used=50,
                cost_usd=0.0001,
                duration_seconds=1.0,
                next_steps=too_many_steps,
            )

    def test_agent_output_validates_next_steps_numbers(self):
        """AgentOutput validates next_steps have sequential numbers."""
        # Non-sequential numbers should raise error
        invalid_steps = [
            NextStepOption(
                id="opt1",
                number=1,
                title="Option 1",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
            NextStepOption(
                id="opt3",
                number=3,  # Skipped 2!
                title="Option 3",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        ]

        with pytest.raises(ValueError, match="next_steps numbers must be sequential"):
            AgentOutput(
                status="success",
                recommendations=[],
                reasoning_trace=[],
                steps_taken=1,
                tools_used=[],
                tokens_used=50,
                cost_usd=0.0001,
                duration_seconds=1.0,
                next_steps=invalid_steps,
            )


class TestNextStepsEvent:
    """Test NextStepsEvent streaming event."""

    def test_next_steps_event_creation(self):
        """NextStepsEvent can be created with options."""
        next_steps = [
            NextStepOption(
                id="opt1",
                number=1,
                title="Analyze deeper",
                description="Investigate root cause",
                action_type=ActionType.TOOL_CALL,
                target_agent=None,
                tool_name="deep_analyze",
                parameters={},
            ),
        ]

        event = NextStepsEvent(
            step=5,
            next_steps=next_steps,
        )

        assert event.type == EventType.NEXT_STEPS
        assert event.step == 5
        assert len(event.next_steps) == 1
        assert event.next_steps[0].number == 1

    def test_next_steps_event_to_sse_data(self):
        """NextStepsEvent serializes to SSE format correctly."""
        next_steps = [
            NextStepOption(
                id="opt1",
                number=1,
                title="Option 1",
                description="First option",
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
            NextStepOption(
                id="opt2",
                number=2,
                title="Option 2",
                description="Second option",
                action_type=ActionType.ROUTE,
                target_agent="other_agent",
                tool_name=None,
                parameters=None,
            ),
        ]

        event = NextStepsEvent(step=3, next_steps=next_steps)
        sse_data = event.to_sse_data(message_id="msg-123")

        assert "message_id" in sse_data
        assert sse_data["message_id"] == "msg-123"
        assert "next_steps" in sse_data
        assert len(sse_data["next_steps"]) == 2
        assert sse_data["next_steps"][0]["number"] == 1
        assert sse_data["next_steps"][0]["title"] == "Option 1"
        assert sse_data["next_steps"][1]["number"] == 2
        assert sse_data["next_steps"][1]["action_type"] == "route"

    def test_next_steps_event_immutable(self):
        """NextStepsEvent is immutable."""
        next_steps = [
            NextStepOption(
                id="opt1",
                number=1,
                title="Test",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        ]

        event = NextStepsEvent(step=1, next_steps=next_steps)

        with pytest.raises(Exception):  # Pydantic frozen model error
            event.step = 2  # type: ignore


class TestAgentNextStepsIntegration:
    """Test integration of next steps with agent workflow."""

    def test_agent_output_serialization_with_next_steps(self):
        """AgentOutput with next_steps serializes correctly."""
        next_steps = [
            NextStepOption(
                id="opt1",
                number=1,
                title="Continue analysis",
                description=None,
                action_type=ActionType.TOOL_CALL,
                tool_name="analyze_more",
                target_agent=None,
                parameters={"depth": 2},
            ),
        ]

        output = AgentOutput(
            status="success",
            recommendations=[{"title": "Test recommendation"}],
            reasoning_trace=[{"step": 1, "action": "test"}],
            steps_taken=1,
            tools_used=["test_tool"],
            tokens_used=100,
            cost_usd=0.001,
            duration_seconds=2.0,
            next_steps=next_steps,
        )

        # Verify it can be converted to dict (for serialization)
        output_dict = output.__dict__
        assert "next_steps" in output_dict
        assert len(output_dict["next_steps"]) == 1

    def test_agent_output_with_next_steps_and_recommendations(self):
        """AgentOutput can have both recommendations and next_steps."""
        next_steps = [
            NextStepOption(
                id="opt1",
                number=1,
                title="Review recommendations",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        ]

        output = AgentOutput(
            status="success",
            recommendations=[
                {"title": "Add index", "priority": "high"},
                {"title": "Update schema", "priority": "medium"},
            ],
            reasoning_trace=[],
            steps_taken=3,
            tools_used=["analyze"],
            tokens_used=250,
            cost_usd=0.003,
            duration_seconds=4.0,
            next_steps=next_steps,
        )

        assert len(output.recommendations) == 2
        assert len(output.next_steps) == 1
        assert output.status == "success"


class TestBackwardCompatibility:
    """Test backward compatibility with existing agent outputs."""

    def test_existing_code_without_next_steps(self):
        """Existing code creating AgentOutput without next_steps still works."""
        # This is how existing code creates AgentOutput
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=2,
            tools_used=["tool1"],
            tokens_used=100,
            cost_usd=0.001,
            duration_seconds=1.5,
        )

        # Should have next_steps defaulting to None
        assert output.next_steps is None
        assert output.status == "success"

    def test_agent_output_dict_serialization(self):
        """AgentOutput can be serialized to dict (for JSON)."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=50,
            cost_usd=0.0001,
            duration_seconds=1.0,
            next_steps=None,
        )

        # Verify __dict__ works (used by JSON serializers)
        output_dict = output.__dict__
        assert "next_steps" in output_dict
        assert output_dict["next_steps"] is None
