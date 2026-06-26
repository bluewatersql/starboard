# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit Tests: AgentResultEnvelope Models

Tests for the envelope pattern models used to standardize agent responses.
These tests verify model construction, validation, and serialization.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError


class TestAgentMetrics:
    """Tests for AgentMetrics model."""

    def test_valid_metrics(self) -> None:
        """AgentMetrics accepts valid non-negative values."""
        from starboard_server.agents.output.envelope import AgentMetrics

        metrics = AgentMetrics(
            tokens_used=1500,
            cost_usd=0.025,
            duration_seconds=12.5,
            steps_taken=5,
        )
        assert metrics.tokens_used == 1500
        assert metrics.cost_usd == 0.025
        assert metrics.duration_seconds == 12.5
        assert metrics.steps_taken == 5

    def test_zero_values_valid(self) -> None:
        """AgentMetrics accepts zero values."""
        from starboard_server.agents.output.envelope import AgentMetrics

        metrics = AgentMetrics(
            tokens_used=0,
            cost_usd=0.0,
            duration_seconds=0.0,
            steps_taken=0,
        )
        assert metrics.tokens_used == 0
        assert metrics.cost_usd == 0.0

    def test_negative_tokens_rejected(self) -> None:
        """AgentMetrics rejects negative tokens_used."""
        from starboard_server.agents.output.envelope import AgentMetrics

        with pytest.raises(ValidationError) as exc_info:
            AgentMetrics(
                tokens_used=-1,
                cost_usd=0.01,
                duration_seconds=1.0,
                steps_taken=1,
            )
        assert "tokens_used" in str(exc_info.value)

    def test_negative_cost_rejected(self) -> None:
        """AgentMetrics rejects negative cost_usd."""
        from starboard_server.agents.output.envelope import AgentMetrics

        with pytest.raises(ValidationError) as exc_info:
            AgentMetrics(
                tokens_used=100,
                cost_usd=-0.01,
                duration_seconds=1.0,
                steps_taken=1,
            )
        assert "cost_usd" in str(exc_info.value)


class TestStructuredError:
    """Tests for StructuredError model."""

    def test_minimal_error(self) -> None:
        """StructuredError with required fields only."""
        from starboard_server.agents.output.envelope import StructuredError

        error = StructuredError(
            code="VALIDATION_ERROR",
            message="Field 'summary' is required",
        )
        assert error.code == "VALIDATION_ERROR"
        assert error.message == "Field 'summary' is required"
        assert error.field is None
        assert error.details is None

    def test_full_error(self) -> None:
        """StructuredError with all optional fields."""
        from starboard_server.agents.output.envelope import StructuredError

        error = StructuredError(
            code="SCHEMA_MISMATCH",
            message="Expected string, got int",
            field="summary.overview",
            details={"expected": "str", "got": "int"},
        )
        assert error.field == "summary.overview"
        assert error.details["expected"] == "str"


class TestPartialInfo:
    """Tests for PartialInfo model."""

    def test_valid_reasons(self) -> None:
        """PartialInfo accepts all valid reasons."""
        from starboard_server.agents.output.envelope import PartialInfo

        valid_reasons = [
            "budget_exceeded",
            "timeout",
            "validation_failed",
            "agent_stuck",
        ]
        for reason in valid_reasons:
            info = PartialInfo(reason=reason)  # type: ignore
            assert info.reason == reason
            assert info.is_partial is True

    def test_invalid_reason_rejected(self) -> None:
        """PartialInfo rejects invalid reasons."""
        from starboard_server.agents.output.envelope import PartialInfo

        with pytest.raises(ValidationError):
            PartialInfo(reason="invalid_reason")  # type: ignore

    def test_with_missing_fields(self) -> None:
        """PartialInfo can specify missing fields."""
        from starboard_server.agents.output.envelope import PartialInfo

        info = PartialInfo(
            reason="validation_failed",
            missing_fields=["analysis.findings", "summary.overview"],
            recovery_hint="Re-run with more context",
        )
        assert len(info.missing_fields) == 2
        assert "analysis.findings" in info.missing_fields
        assert info.recovery_hint == "Re-run with more context"


class TestAgentResultEnvelope:
    """Tests for AgentResultEnvelope model."""

    def test_success_envelope(self) -> None:
        """AgentResultEnvelope for successful response."""
        from starboard_server.agents.output.envelope import (
            ENVELOPE_VERSION,
            AgentMetrics,
            AgentResultEnvelope,
        )

        envelope = AgentResultEnvelope(
            domain="query",
            timestamp=datetime.now(UTC),
            trace_id="trace_abc123",
            status="success",
            report_type="advisor",
            payload={"report_type": "advisor", "summary": {"overview": "Test"}},
            metrics=AgentMetrics(
                tokens_used=1000,
                cost_usd=0.015,
                duration_seconds=5.0,
                steps_taken=3,
            ),
        )
        assert envelope.schema_version == ENVELOPE_VERSION
        assert envelope.domain == "query"
        assert envelope.status == "success"
        assert envelope.report_type == "advisor"
        assert envelope.partial is None
        assert len(envelope.errors) == 0

    def test_partial_envelope(self) -> None:
        """AgentResultEnvelope for partial response."""
        from starboard_server.agents.output.envelope import (
            AgentMetrics,
            AgentResultEnvelope,
            PartialInfo,
        )

        envelope = AgentResultEnvelope(
            domain="job",
            timestamp=datetime.now(UTC),
            trace_id="trace_xyz789",
            status="partial",
            report_type="advisor",
            payload={"summary": {"overview": "Incomplete analysis"}},
            metrics=AgentMetrics(
                tokens_used=500,
                cost_usd=0.0075,
                duration_seconds=2.5,
                steps_taken=2,
            ),
            partial=PartialInfo(
                reason="budget_exceeded",
                missing_fields=["analysis.findings"],
                recovery_hint="Continue analysis for full findings",
            ),
        )
        assert envelope.status == "partial"
        assert envelope.partial is not None
        assert envelope.partial.reason == "budget_exceeded"
        assert "analysis.findings" in envelope.partial.missing_fields

    def test_error_envelope(self) -> None:
        """AgentResultEnvelope for error response."""
        from starboard_server.agents.output.envelope import (
            AgentMetrics,
            AgentResultEnvelope,
            StructuredError,
        )

        envelope = AgentResultEnvelope(
            domain="analytics",
            timestamp=datetime.now(UTC),
            trace_id="trace_err001",
            status="error",
            report_type="analytics",
            payload={},
            metrics=AgentMetrics(
                tokens_used=100,
                cost_usd=0.0015,
                duration_seconds=0.5,
                steps_taken=1,
            ),
            errors=[
                StructuredError(
                    code="PROVIDER_ERROR",
                    message="LLM provider returned error",
                    details={"status_code": 500},
                ),
            ],
        )
        assert envelope.status == "error"
        assert len(envelope.errors) == 1
        assert envelope.errors[0].code == "PROVIDER_ERROR"

    def test_valid_status_values(self) -> None:
        """AgentResultEnvelope accepts all valid status values."""
        from starboard_server.agents.output.envelope import (
            AgentMetrics,
            AgentResultEnvelope,
        )

        valid_statuses = [
            "success",
            "partial",
            "budget_exceeded",
            "max_steps_reached",
            "error",
        ]
        for status in valid_statuses:
            envelope = AgentResultEnvelope(
                domain="query",
                timestamp=datetime.now(UTC),
                trace_id="trace_test",
                status=status,  # type: ignore
                report_type="advisor",
                payload={},
                metrics=AgentMetrics(
                    tokens_used=100,
                    cost_usd=0.01,
                    duration_seconds=1.0,
                    steps_taken=1,
                ),
            )
            assert envelope.status == status

    def test_invalid_status_rejected(self) -> None:
        """AgentResultEnvelope rejects invalid status values."""
        from starboard_server.agents.output.envelope import (
            AgentMetrics,
            AgentResultEnvelope,
        )

        with pytest.raises(ValidationError):
            AgentResultEnvelope(
                domain="query",
                timestamp=datetime.now(UTC),
                trace_id="trace_test",
                status="invalid_status",  # type: ignore
                report_type="advisor",
                payload={},
                metrics=AgentMetrics(
                    tokens_used=100,
                    cost_usd=0.01,
                    duration_seconds=1.0,
                    steps_taken=1,
                ),
            )

    def test_valid_report_types(self) -> None:
        """AgentResultEnvelope accepts all valid report types."""
        from starboard_server.agents.output.envelope import (
            AgentMetrics,
            AgentResultEnvelope,
        )

        valid_report_types = ["advisor", "analytics", "compute"]
        for report_type in valid_report_types:
            envelope = AgentResultEnvelope(
                domain="query",
                timestamp=datetime.now(UTC),
                trace_id="trace_test",
                status="success",
                report_type=report_type,  # type: ignore
                payload={},
                metrics=AgentMetrics(
                    tokens_used=100,
                    cost_usd=0.01,
                    duration_seconds=1.0,
                    steps_taken=1,
                ),
            )
            assert envelope.report_type == report_type

    def test_next_steps_serialization(self) -> None:
        """AgentResultEnvelope serializes next_steps correctly."""
        from starboard_server.agents.output.envelope import (
            AgentMetrics,
            AgentResultEnvelope,
        )

        next_steps = [
            {
                "id": "step_1",
                "number": 1,
                "title": "Continue",
                "action_type": "continue",
            },
            {
                "id": "step_2",
                "number": 2,
                "title": "Route to compute",
                "action_type": "route",
                "target_agent": "compute",
            },
        ]
        envelope = AgentResultEnvelope(
            domain="query",
            timestamp=datetime.now(UTC),
            trace_id="trace_test",
            status="success",
            report_type="advisor",
            payload={},
            metrics=AgentMetrics(
                tokens_used=100,
                cost_usd=0.01,
                duration_seconds=1.0,
                steps_taken=1,
            ),
            next_steps=next_steps,
        )
        assert len(envelope.next_steps) == 2
        assert envelope.next_steps[0]["id"] == "step_1"
        assert envelope.next_steps[1]["target_agent"] == "compute"

    def test_model_dump_includes_all_fields(self) -> None:
        """model_dump() includes all envelope fields."""
        from starboard_server.agents.output.envelope import (
            AgentMetrics,
            AgentResultEnvelope,
        )

        envelope = AgentResultEnvelope(
            domain="query",
            timestamp=datetime.now(UTC),
            trace_id="trace_test",
            status="success",
            report_type="advisor",
            payload={"report_type": "advisor"},
            metrics=AgentMetrics(
                tokens_used=100,
                cost_usd=0.01,
                duration_seconds=1.0,
                steps_taken=1,
            ),
        )
        data = envelope.model_dump()

        # Required envelope fields
        assert "schema_version" in data
        assert "domain" in data
        assert "timestamp" in data
        assert "trace_id" in data
        assert "status" in data
        assert "report_type" in data
        assert "payload" in data
        assert "metrics" in data
        assert "partial" in data
        assert "errors" in data
        assert "next_steps" in data


class TestEnvelopeVersion:
    """Tests for envelope versioning."""

    def test_envelope_version_constant(self) -> None:
        """ENVELOPE_VERSION constant exists and is valid."""
        from starboard_server.agents.output.envelope import ENVELOPE_VERSION

        assert ENVELOPE_VERSION == "1.0"

    def test_default_version_matches_constant(self) -> None:
        """Default schema_version matches ENVELOPE_VERSION."""
        from starboard_server.agents.output.envelope import (
            ENVELOPE_VERSION,
            AgentMetrics,
            AgentResultEnvelope,
        )

        envelope = AgentResultEnvelope(
            domain="query",
            timestamp=datetime.now(UTC),
            trace_id="trace_test",
            status="success",
            report_type="advisor",
            payload={},
            metrics=AgentMetrics(
                tokens_used=100,
                cost_usd=0.01,
                duration_seconds=1.0,
                steps_taken=1,
            ),
        )
        assert envelope.schema_version == ENVELOPE_VERSION


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
