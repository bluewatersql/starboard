"""
Unit Tests: FinalOutputEvent Envelope Emission

Tests for envelope generation in FinalOutputEvent.to_sse_data().
"""

import pytest
from starboard_server.agents.events.user_events import FinalOutputEvent
from starboard_server.agents.state.agent_state import AgentOutput
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)


class TestFinalOutputEventEnvelope:
    """Tests for envelope emission in FinalOutputEvent."""

    def test_sse_data_includes_envelope_when_domain_provided(self) -> None:
        """SSE output includes envelope under output.envelope when domain provided."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=3,
            tools_used=["tool1"],
            tokens_used=1500,
            cost_usd=0.025,
            duration_seconds=12.5,
            complete_report={
                "report_type": "advisor",
                "summary": {"overview": "Test analysis"},
            },
        )

        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(
            message_id="msg_test_123",
            domain="query",
            trace_id="trace_abc",
        )

        # Envelope should be present
        assert "envelope" in sse_data["output"]
        envelope = sse_data["output"]["envelope"]

        # Check envelope fields
        assert envelope["schema_version"] == "1.0"
        assert envelope["domain"] == "query"
        assert envelope["trace_id"] == "trace_abc"
        assert envelope["status"] == "success"
        assert envelope["report_type"] == "advisor"

    def test_sse_data_preserves_existing_fields(self) -> None:
        """Existing complete_report and next_steps unchanged when envelope added."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=3,
            tools_used=["tool1"],
            tokens_used=1500,
            cost_usd=0.025,
            duration_seconds=12.5,
            complete_report={
                "report_type": "advisor",
                "summary": {"overview": "Test analysis"},
            },
        )

        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(
            message_id="msg_test_123",
            domain="query",
            trace_id="trace_abc",
        )

        # Existing fields must still be present
        assert sse_data["message_id"] == "msg_test_123"
        assert "complete_report" in sse_data["output"]
        assert sse_data["output"]["complete_report"]["report_type"] == "advisor"
        assert sse_data["output"]["tokens_used"] == 1500
        assert sse_data["output"]["cost_usd"] == 0.025

    def test_sse_data_no_envelope_without_domain(self) -> None:
        """No envelope generated when domain not provided (backward compatible)."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.0,
        )

        event = FinalOutputEvent(output=output)
        # Call without domain/trace_id (old behavior)
        sse_data = event.to_sse_data(message_id="msg_test")

        # Envelope should NOT be present
        assert "envelope" not in sse_data["output"]

    def test_envelope_includes_metrics(self) -> None:
        """Envelope metrics match AgentOutput metrics."""
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=5,
            tools_used=["tool1", "tool2"],
            tokens_used=2500,
            cost_usd=0.0375,
            duration_seconds=15.5,
        )

        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(
            message_id="msg_test",
            domain="query",
            trace_id="trace_metrics",
        )

        envelope = sse_data["output"]["envelope"]
        assert envelope["metrics"]["tokens_used"] == 2500
        assert envelope["metrics"]["cost_usd"] == 0.0375
        assert envelope["metrics"]["duration_seconds"] == 15.5
        assert envelope["metrics"]["steps_taken"] == 5

    def test_envelope_includes_next_steps(self) -> None:
        """Envelope next_steps serialized correctly."""
        next_steps = [
            NextStepOption(
                id="step_1",
                number=1,
                title="Continue",
                description="Keep going",
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        ]
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=3,
            tools_used=[],
            tokens_used=1000,
            cost_usd=0.015,
            duration_seconds=5.0,
            next_steps=next_steps,
        )

        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(
            message_id="msg_test",
            domain="query",
            trace_id="trace_nextsteps",
        )

        envelope = sse_data["output"]["envelope"]
        assert len(envelope["next_steps"]) == 1
        assert envelope["next_steps"][0]["id"] == "step_1"
        assert envelope["next_steps"][0]["action_type"] == "continue"

    def test_envelope_handles_budget_exceeded(self) -> None:
        """Envelope has partial info for budget_exceeded."""
        output = AgentOutput(
            status="budget_exceeded",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=10,
            tools_used=[],
            tokens_used=10000,
            cost_usd=0.15,
            duration_seconds=30.0,
        )

        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(
            message_id="msg_test",
            domain="job",
            trace_id="trace_budget",
        )

        envelope = sse_data["output"]["envelope"]
        assert envelope["status"] == "budget_exceeded"
        assert envelope["partial"] is not None
        assert envelope["partial"]["reason"] == "budget_exceeded"

    def test_envelope_handles_error_status(self) -> None:
        """Envelope has structured errors for error status."""
        output = AgentOutput(
            status="error",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.0015,
            duration_seconds=0.5,
            error_message="Provider timeout",
        )

        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(
            message_id="msg_test",
            domain="analytics",
            trace_id="trace_error",
        )

        envelope = sse_data["output"]["envelope"]
        assert envelope["status"] == "error"
        assert len(envelope["errors"]) == 1
        assert envelope["errors"][0]["code"] == "AGENT_ERROR"
        assert "Provider timeout" in envelope["errors"][0]["message"]


class TestFinalOutputEventBackwardCompatibility:
    """Tests ensuring backward compatibility."""

    def test_existing_contract_tests_still_pass(self) -> None:
        """Verify structure expected by contract tests is preserved."""
        output = AgentOutput(
            status="success",
            recommendations=[{"title": "Test"}],
            reasoning_trace=[{"step": 1}],
            steps_taken=1,
            tools_used=["test_tool"],
            tokens_used=100,
            cost_usd=0.01,
            duration_seconds=1.5,
        )

        event = FinalOutputEvent(output=output)
        sse_data = event.to_sse_data(message_id="msg_test_123")

        # Contract test assertions
        assert "message_id" in sse_data
        assert "output" in sse_data
        assert "formatted_markdown" in sse_data

        assert sse_data["message_id"] == "msg_test_123"
        assert sse_data["output"]["status"] == "success"
        assert sse_data["output"]["tokens_used"] == 100
        assert sse_data["output"]["cost_usd"] == 0.01

    def test_all_status_values_work(self) -> None:
        """All status values work with and without envelope."""
        for status in ["success", "error", "budget_exceeded", "max_steps_reached"]:
            output = AgentOutput(
                status=status,  # type: ignore
                recommendations=[],
                reasoning_trace=[],
                steps_taken=1,
                tools_used=[],
                tokens_used=100,
                cost_usd=0.01,
                duration_seconds=1.0,
                error_message="Error" if status == "error" else None,
            )

            event = FinalOutputEvent(output=output)

            # Without envelope
            sse_data = event.to_sse_data(message_id="msg_test")
            assert sse_data["output"]["status"] == status
            assert "envelope" not in sse_data["output"]

            # With envelope
            sse_data = event.to_sse_data(
                message_id="msg_test",
                domain="query",
                trace_id="trace_test",
            )
            assert sse_data["output"]["status"] == status
            assert "envelope" in sse_data["output"]
            assert sse_data["output"]["envelope"]["status"] == status


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
