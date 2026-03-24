"""
Unit Tests: EnvelopeTranslator

Tests for translating AgentOutput to AgentResultEnvelope.
"""

from datetime import UTC, datetime

import pytest
from starboard_server.agents.state.agent_state import AgentOutput
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)


class TestEnvelopeTranslator:
    """Tests for EnvelopeTranslator."""

    def test_translates_success_output(self) -> None:
        """Success AgentOutput becomes success envelope."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        output = AgentOutput(
            status="success",
            recommendations=[{"title": "Test"}],
            reasoning_trace=[{"step": 1}],
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

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="query",
            trace_id="trace_test_123",
        )

        assert envelope.status == "success"
        assert envelope.domain == "query"
        assert envelope.trace_id == "trace_test_123"
        assert envelope.report_type == "advisor"
        assert envelope.payload["report_type"] == "advisor"
        assert envelope.partial is None

    def test_translates_budget_exceeded(self) -> None:
        """budget_exceeded status maps correctly."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        output = AgentOutput(
            status="budget_exceeded",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=5,
            tools_used=["tool1"],
            tokens_used=10000,
            cost_usd=0.15,
            duration_seconds=30.0,
        )

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="job",
            trace_id="trace_budget",
        )

        assert envelope.status == "budget_exceeded"
        # Budget exceeded should have partial info
        assert envelope.partial is not None
        assert envelope.partial.reason == "budget_exceeded"

    def test_translates_max_steps_reached(self) -> None:
        """max_steps_reached status maps correctly."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        output = AgentOutput(
            status="max_steps_reached",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=10,
            tools_used=[],
            tokens_used=5000,
            cost_usd=0.075,
            duration_seconds=20.0,
        )

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="uc",
            trace_id="trace_maxsteps",
        )

        assert envelope.status == "max_steps_reached"

    def test_translates_error_output(self) -> None:
        """error status maps correctly with error message."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

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

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="analytics",
            trace_id="trace_error",
        )

        assert envelope.status == "error"
        assert len(envelope.errors) == 1
        assert envelope.errors[0].code == "AGENT_ERROR"
        assert "Provider timeout" in envelope.errors[0].message

    def test_extracts_metrics_correctly(self) -> None:
        """Metrics are extracted correctly from AgentOutput."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=7,
            tools_used=["tool1", "tool2"],
            tokens_used=2500,
            cost_usd=0.0375,
            duration_seconds=15.5,
        )

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="query",
            trace_id="trace_metrics",
        )

        assert envelope.metrics.tokens_used == 2500
        assert envelope.metrics.cost_usd == 0.0375
        assert envelope.metrics.duration_seconds == 15.5
        assert envelope.metrics.steps_taken == 7

    def test_preserves_next_steps(self) -> None:
        """next_steps from AgentOutput are preserved in envelope."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

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
            NextStepOption(
                id="step_2",
                number=2,
                title="Route to compute",
                description="Analyze cluster",
                action_type=ActionType.ROUTE,
                target_agent="compute",
                tool_name=None,
                parameters={"cluster_id": "abc"},
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

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="query",
            trace_id="trace_nextsteps",
        )

        assert len(envelope.next_steps) == 2
        assert envelope.next_steps[0]["id"] == "step_1"
        assert envelope.next_steps[0]["action_type"] == "continue"
        assert envelope.next_steps[1]["id"] == "step_2"
        assert envelope.next_steps[1]["target_agent"] == "compute"

    def test_infers_report_type_from_complete_report(self) -> None:
        """report_type is inferred from complete_report."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        for report_type in ["advisor", "analytics", "compute"]:
            output = AgentOutput(
                status="success",
                recommendations=[],
                reasoning_trace=[],
                steps_taken=1,
                tools_used=[],
                tokens_used=100,
                cost_usd=0.0015,
                duration_seconds=1.0,
                complete_report={"report_type": report_type},
            )

            translator = EnvelopeTranslator()
            envelope = translator.translate(
                output=output,
                domain="query",
                trace_id="trace_infer",
            )

            assert envelope.report_type == report_type

    def test_defaults_report_type_by_domain(self) -> None:
        """report_type defaults based on domain when not in complete_report."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        # Analytics domain defaults to analytics report
        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.0015,
            duration_seconds=1.0,
        )

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="analytics",
            trace_id="trace_default",
        )
        assert envelope.report_type == "analytics"

        # Warehouse domain defaults to compute report
        envelope = translator.translate(
            output=output,
            domain="warehouse",
            trace_id="trace_default2",
        )
        assert envelope.report_type == "compute"

        # Query domain defaults to advisor report
        envelope = translator.translate(
            output=output,
            domain="query",
            trace_id="trace_default3",
        )
        assert envelope.report_type == "advisor"

    def test_timestamp_is_set(self) -> None:
        """Envelope timestamp is set to current time."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        before = datetime.now(UTC)

        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.0015,
            duration_seconds=1.0,
        )

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="query",
            trace_id="trace_time",
        )

        after = datetime.now(UTC)

        assert before <= envelope.timestamp <= after

    def test_handles_none_complete_report(self) -> None:
        """Handles AgentOutput with complete_report=None."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.0015,
            duration_seconds=1.0,
            complete_report=None,
        )

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="query",
            trace_id="trace_none",
        )

        assert envelope.payload == {}
        assert envelope.report_type == "advisor"  # Default for query domain


class TestEnvelopeTranslatorEdgeCases:
    """Edge case tests for EnvelopeTranslator."""

    def test_handles_empty_next_steps(self) -> None:
        """Handles AgentOutput with empty next_steps."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.0015,
            duration_seconds=1.0,
            next_steps=[],
        )

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="query",
            trace_id="trace_empty",
        )

        assert envelope.next_steps == []

    def test_handles_none_next_steps(self) -> None:
        """Handles AgentOutput with next_steps=None."""
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        output = AgentOutput(
            status="success",
            recommendations=[],
            reasoning_trace=[],
            steps_taken=1,
            tools_used=[],
            tokens_used=100,
            cost_usd=0.0015,
            duration_seconds=1.0,
            next_steps=None,
        )

        translator = EnvelopeTranslator()
        envelope = translator.translate(
            output=output,
            domain="query",
            trace_id="trace_none_steps",
        )

        assert envelope.next_steps == []


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
