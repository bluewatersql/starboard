"""Unit tests for reasoning loop fallback report generation.

Tests that the reasoning loop produces meaningful output even when
the agent finishes without calling the `complete` tool.
"""

from unittest.mock import MagicMock

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.domain.partial_report import generate_partial_report
from starboard_server.agents.domain.reasoning_loop import (
    reasoning_loop_stream,
)
from starboard_server.agents.events.user_events import FinalOutputEvent
from starboard_server.agents.state.agent_state import (
    AgentState,
    Message,
    WorkingMemory,
)


def _make_state(
    *,
    messages: list[Message] | None = None,
    tools_used: frozenset[str] | None = None,
    current_step: int = 0,
    budget_remaining: int = 10_000,
    completed: bool = False,
    final_output: dict | None = None,
) -> AgentState:
    """Helper to build an AgentState with minimal boilerplate."""
    wm = WorkingMemory()
    if tools_used:
        for t in tools_used:
            wm = wm.add_tool_used(t)
    return AgentState(
        user_id="test_user",
        conversation_history=tuple(messages or []),
        working_memory=wm,
        current_step=current_step,
        goal="test goal",
        mode=OptimizationMode.ONLINE,
        budget_remaining=budget_remaining,
        context={},
        completed=completed,
        final_output=final_output,
    )


class TestGeneratePartialReportExtractsToolResults:
    """Tests that generate_partial_report extracts real data from history."""

    def test_extracts_tool_result_content(self):
        """Tool result content appears in findings."""
        messages = [
            Message(role="user", content="Analyze workspace"),
            Message(
                role="assistant",
                content="Running discovery",
                metadata={
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "synthesize_discovery_report",
                                "arguments": "{}",
                            },
                        }
                    ]
                },
            ),
            Message(
                role="tool",
                content='{"status": "ok", "summary": "Found 5 expensive queries"}',
                name="synthesize_discovery_report",
                tool_call_id="c1",
                metadata={"tool_name": "synthesize_discovery_report"},
            ),
        ]
        state = _make_state(
            messages=messages,
            tools_used=frozenset(["synthesize_discovery_report"]),
            current_step=2,
        )
        config = AgentConfig(domain="query")

        report = generate_partial_report(state, config)

        assert report["report_type"] == "advisor"
        findings = report["analysis"]["findings"]
        assert len(findings) >= 1

        tool_finding = next(
            (f for f in findings if "synthesize_discovery_report" in f.get("id", "")),
            None,
        )
        assert tool_finding is not None
        assert "5 expensive queries" in tool_finding["recommendation"]

    def test_empty_conversation_still_produces_report(self):
        """Even with no tool results, a status finding is generated."""
        state = _make_state(current_step=1)
        config = AgentConfig(domain="query")

        report = generate_partial_report(state, config)

        assert "summary" in report
        assert "analysis" in report
        findings = report["analysis"]["findings"]
        assert len(findings) >= 1


class TestReasoningLoopFallbackReport:
    """Tests that reasoning_loop_stream generates fallback output.

    These tests verify the STEP 4b fallback: when the agent exits the
    reasoning loop without calling the `complete` tool, the loop should
    still produce a FinalOutputEvent with extracted content.
    """

    @pytest.mark.asyncio
    async def test_fallback_when_max_steps_reached_without_complete(self):
        """Agent hits max_steps without calling complete → fallback report."""
        tool_result_content = '{"found": "3 slow queries", "details": "query analysis results"}'
        messages = [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="Analyze my queries"),
            Message(
                role="assistant",
                content="Discovering active products",
                metadata={
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "discover_active_products",
                                "arguments": "{}",
                            },
                        }
                    ]
                },
            ),
            Message(
                role="tool",
                content=tool_result_content,
                name="discover_active_products",
                tool_call_id="c1",
                metadata={"tool_name": "discover_active_products"},
            ),
        ]

        # State at max_steps with no final_output (complete tool never called)
        state = _make_state(
            messages=messages,
            tools_used=frozenset(["discover_active_products"]),
            current_step=8,
            completed=False,
            final_output=None,
        )
        config = AgentConfig(max_steps=8, domain="query", enforce_budget=False)

        # Mock dependencies so the while loop exits immediately
        # (current_step >= max_steps, so should_continue_reasoning returns False)
        mock_reasoning = MagicMock()
        mock_executor = MagicMock()
        mock_streamer = MagicMock()
        mock_builder = MagicMock()
        mock_metrics = MagicMock()

        # Builder.build should return a proper AgentOutput
        from starboard_server.agents.state.agent_state import AgentOutput

        mock_builder.build.return_value = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=8,
            tools_used=["discover_active_products"],
            tokens_used=5000,
            cost_usd=0.001,
            duration_seconds=100.0,
            complete_report=None,
        )

        events = []
        async for event in reasoning_loop_stream(
            state=state,
            config=config,
            reasoning=mock_reasoning,
            executor=mock_executor,
            streamer=mock_streamer,
            builder=mock_builder,
            metrics=mock_metrics,
        ):
            events.append(event)

        # The builder should have been called with state that has final_output set
        assert mock_builder.build.called
        call_state = mock_builder.build.call_args[0][0]
        assert call_state.final_output is not None
        assert call_state.final_output["budget_exhausted"] is False
        assert "analysis" in call_state.final_output

        # A FinalOutputEvent should be the last event
        final_events = [e for e in events if isinstance(e, FinalOutputEvent)]
        assert len(final_events) == 1

    @pytest.mark.asyncio
    async def test_no_fallback_when_complete_tool_was_called(self):
        """When complete tool set final_output, no fallback is generated."""
        final_report = {
            "report_type": "advisor",
            "summary": {"overview": "Real analysis"},
            "analysis": {"findings": [{"title": "Real finding"}]},
        }

        # State where complete tool was called (final_output is set)
        state = _make_state(
            current_step=5,
            completed=True,
            final_output=final_report,
        )
        config = AgentConfig(max_steps=15, domain="query")

        mock_reasoning = MagicMock()
        mock_executor = MagicMock()
        mock_streamer = MagicMock()
        mock_builder = MagicMock()
        mock_metrics = MagicMock()

        from starboard_server.agents.state.agent_state import AgentOutput

        mock_builder.build.return_value = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=5,
            tools_used=[],
            tokens_used=3000,
            cost_usd=0.001,
            duration_seconds=50.0,
            complete_report=final_report,
        )

        events = []
        async for event in reasoning_loop_stream(
            state=state,
            config=config,
            reasoning=mock_reasoning,
            executor=mock_executor,
            streamer=mock_streamer,
            builder=mock_builder,
            metrics=mock_metrics,
        ):
            events.append(event)

        # Builder should receive the original final_output, not a fallback
        call_state = mock_builder.build.call_args[0][0]
        assert call_state.final_output is final_report
        assert call_state.final_output["summary"]["overview"] == "Real analysis"
