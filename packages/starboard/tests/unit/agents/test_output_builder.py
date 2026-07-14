# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for OutputBuilder.

Tests reasoning trace building and output assembly from agent state.
"""

from datetime import datetime

from starboard_core.domain.models.llm import OptimizationMode
from starboard.agents.config.agent_config import AgentConfig
from starboard.agents.domain.output_builder import OutputBuilder
from starboard.agents.state.agent_state import (
    AgentState,
    Message,
    WorkingMemory,
)


def _make_state(
    *,
    messages: list[Message] | None = None,
    current_step: int = 0,
    completed: bool = False,
    final_output: dict | None = None,
) -> AgentState:
    """Helper to build an AgentState with minimal boilerplate."""
    return AgentState(
        user_id="test_user",
        conversation_history=tuple(messages or []),
        working_memory=WorkingMemory(),
        current_step=current_step,
        goal="test goal",
        mode=OptimizationMode.ONLINE,
        budget_remaining=10_000,
        context={},
        completed=completed,
        final_output=final_output,
    )


class TestBuildReasoningTrace:
    """Tests for OutputBuilder._build_reasoning_trace."""

    def _builder(self) -> OutputBuilder:
        return OutputBuilder(config=AgentConfig())

    def test_empty_history_uses_step_count_fallback(self):
        """When no assistant messages exist, produce step-count entries."""
        state = _make_state(current_step=3)
        trace = self._builder()._build_reasoning_trace(state)

        assert len(trace) == 3
        for i, entry in enumerate(trace, 1):
            assert entry["step"] == i
            assert entry["action"] == "reasoning"

    def test_extracts_tool_calls_from_assistant_messages(self):
        """Tool call names appear in the trace action field."""
        messages = [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="Analyze query"),
            Message(
                role="assistant",
                content="Let me look at the query plan",
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "resolve_query",
                                "arguments": "{}",
                            },
                        }
                    ]
                },
            ),
            Message(
                role="tool",
                content="Query found",
                name="resolve_query",
                tool_call_id="call_1",
            ),
        ]
        state = _make_state(messages=messages, current_step=1)
        trace = self._builder()._build_reasoning_trace(state)

        assert len(trace) == 1
        assert trace[0]["action"] == "resolve_query"
        assert trace[0]["tool_calls"] == ["resolve_query"]
        assert "query plan" in trace[0]["thinking"]

    def test_multiple_tool_calls_in_single_step(self):
        """Multiple tool calls in one assistant message are comma-joined."""
        messages = [
            Message(
                role="assistant",
                content="Fetching both",
                metadata={
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "tool_a", "arguments": "{}"},
                        },
                        {
                            "id": "c2",
                            "type": "function",
                            "function": {"name": "tool_b", "arguments": "{}"},
                        },
                    ]
                },
            ),
        ]
        state = _make_state(messages=messages, current_step=1)
        trace = self._builder()._build_reasoning_trace(state)

        assert trace[0]["action"] == "tool_a, tool_b"

    def test_assistant_message_without_tools_shows_reasoning(self):
        """Assistant messages without tool calls show 'reasoning' as action."""
        messages = [
            Message(role="assistant", content="I'm thinking about the problem"),
        ]
        state = _make_state(messages=messages, current_step=1)
        trace = self._builder()._build_reasoning_trace(state)

        assert trace[0]["action"] == "reasoning"
        assert trace[0]["tool_calls"] is None

    def test_thinking_content_is_truncated(self):
        """Long thinking content is truncated with ellipsis."""
        long_content = "x" * 500
        messages = [
            Message(role="assistant", content=long_content),
        ]
        state = _make_state(messages=messages, current_step=1)
        trace = self._builder()._build_reasoning_trace(state)

        assert len(trace[0]["thinking"]) <= 303  # 300 + "..."
        assert trace[0]["thinking"].endswith("...")

    def test_multi_step_trace(self):
        """Multiple assistant messages produce sequential step numbers."""
        messages = [
            Message(role="assistant", content="Step 1 thinking"),
            Message(
                role="assistant",
                content="Step 2 with tool",
                metadata={
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "analyze_plan",
                                "arguments": "{}",
                            },
                        }
                    ]
                },
            ),
            Message(role="assistant", content="Step 3 conclusion"),
        ]
        state = _make_state(messages=messages, current_step=3)
        trace = self._builder()._build_reasoning_trace(state)

        assert len(trace) == 3
        assert trace[0]["step"] == 1
        assert trace[1]["step"] == 2
        assert trace[2]["step"] == 3
        assert trace[1]["action"] == "analyze_plan"

    def test_trace_entries_have_timestamps(self):
        """Every trace entry includes a timestamp."""
        messages = [
            Message(role="assistant", content="Some thinking"),
        ]
        state = _make_state(messages=messages, current_step=1)
        trace = self._builder()._build_reasoning_trace(state)

        assert "timestamp" in trace[0]
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(trace[0]["timestamp"])


class TestOutputBuilderBuild:
    """Tests for the full OutputBuilder.build flow."""

    def test_build_with_final_output(self):
        """When state has final_output, it's used as complete_report."""
        final = {
            "report_type": "advisor",
            "summary": {"overview": "All good"},
            "analysis": {
                "findings": [{"title": "Use partitioning", "category": "PERFORMANCE"}]
            },
        }
        state = _make_state(
            current_step=3,
            completed=True,
            final_output=final,
        )

        builder = OutputBuilder(config=AgentConfig())
        output = builder.build(state)

        assert output.status == "success"
        assert output.complete_report is not None
        assert output.complete_report["summary"]["overview"] == "All good"
        assert len(output.recommendations) == 1
        assert output.recommendations[0]["title"] == "Use partitioning"

    def test_build_without_final_output(self):
        """When state has no final_output, report and recommendations are empty."""
        state = _make_state(current_step=5, completed=True)

        builder = OutputBuilder(config=AgentConfig())
        output = builder.build(state)

        assert output.status == "success"
        assert output.complete_report is None
        assert output.recommendations == []

    def test_build_max_steps_status(self):
        """Status reflects max_steps_reached when step limit hit."""
        config = AgentConfig(max_steps=3)
        state = _make_state(current_step=3, completed=False)

        builder = OutputBuilder(config=config)
        output = builder.build(state)

        assert output.status == "max_steps_reached"
