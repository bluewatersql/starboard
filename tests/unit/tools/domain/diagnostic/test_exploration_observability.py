"""Tests for exploration observability and telemetry."""

import pytest
from starboard_server.tools.domain.diagnostic.exploration_observability import (
    ExplorationMetrics,
    ExplorationTelemetry,
    StepMetrics,
)


class TestStepMetrics:
    """Tests for StepMetrics dataclass."""

    def test_create_step_metrics(self) -> None:
        """Should create valid step metrics."""
        metrics = StepMetrics(
            strategy="detect_type",
            latency_ms=150,
            confidence_before=0.0,
            confidence_after=0.6,
            findings_count=3,
        )
        assert metrics.strategy == "detect_type"
        assert metrics.latency_ms == 150
        assert metrics.confidence_delta == 0.6

    def test_confidence_delta_calculation(self) -> None:
        """Should calculate confidence delta correctly."""
        metrics = StepMetrics(
            strategy="match_patterns",
            latency_ms=200,
            confidence_before=0.5,
            confidence_after=0.85,
            findings_count=2,
        )
        assert metrics.confidence_delta == pytest.approx(0.35, abs=0.01)

    def test_step_metrics_with_error(self) -> None:
        """Should handle steps that errored."""
        metrics = StepMetrics(
            strategy="extract_evidence",
            latency_ms=50,
            confidence_before=0.3,
            confidence_after=0.3,  # No change on error
            findings_count=0,
            error="Failed to extract evidence",
        )
        assert metrics.error == "Failed to extract evidence"
        assert metrics.confidence_delta == 0.0


class TestExplorationMetrics:
    """Tests for ExplorationMetrics aggregate."""

    def test_create_exploration_metrics(self) -> None:
        """Should create valid exploration metrics."""
        step1 = StepMetrics("detect_type", 100, 0.0, 0.5, 2)
        step2 = StepMetrics("match_patterns", 200, 0.5, 0.8, 3)

        metrics = ExplorationMetrics(
            exploration_id="exp_123",
            artifact_type="stack_trace",
            steps=[step1, step2],
        )
        assert metrics.exploration_id == "exp_123"
        assert len(metrics.steps) == 2

    def test_total_latency(self) -> None:
        """Should calculate total latency across steps."""
        steps = [
            StepMetrics("detect_type", 100, 0.0, 0.5, 2),
            StepMetrics("extract_evidence", 150, 0.5, 0.6, 4),
            StepMetrics("match_patterns", 200, 0.6, 0.85, 3),
        ]
        metrics = ExplorationMetrics("exp_1", "logs", steps)
        assert metrics.total_latency_ms == 450

    def test_final_confidence(self) -> None:
        """Should return final confidence from last step."""
        steps = [
            StepMetrics("detect_type", 100, 0.0, 0.5, 2),
            StepMetrics("match_patterns", 200, 0.5, 0.85, 3),
        ]
        metrics = ExplorationMetrics("exp_1", "logs", steps)
        assert metrics.final_confidence == 0.85

    def test_confidence_progression(self) -> None:
        """Should track confidence progression across steps."""
        steps = [
            StepMetrics("detect_type", 100, 0.0, 0.4, 2),
            StepMetrics("extract_evidence", 100, 0.4, 0.5, 3),
            StepMetrics("match_patterns", 100, 0.5, 0.75, 2),
            StepMetrics("correlate", 100, 0.75, 0.9, 1),
        ]
        metrics = ExplorationMetrics("exp_1", "stack_trace", steps)
        progression = metrics.confidence_progression
        assert progression == [0.0, 0.4, 0.5, 0.75, 0.9]

    def test_step_count(self) -> None:
        """Should return correct step count."""
        steps = [
            StepMetrics("detect_type", 100, 0.0, 0.5, 2),
            StepMetrics("match_patterns", 200, 0.5, 0.8, 3),
            StepMetrics("synthesize", 150, 0.8, 0.9, 1),
        ]
        metrics = ExplorationMetrics("exp_1", "logs", steps)
        assert metrics.step_count == 3

    def test_strategies_used(self) -> None:
        """Should list all strategies used."""
        steps = [
            StepMetrics("detect_type", 100, 0.0, 0.5, 2),
            StepMetrics("extract_evidence", 100, 0.5, 0.6, 3),
            StepMetrics("match_patterns", 200, 0.6, 0.8, 2),
        ]
        metrics = ExplorationMetrics("exp_1", "logs", steps)
        assert metrics.strategies_used == [
            "detect_type",
            "extract_evidence",
            "match_patterns",
        ]

    def test_error_count(self) -> None:
        """Should count steps with errors."""
        steps = [
            StepMetrics("detect_type", 100, 0.0, 0.5, 2),
            StepMetrics("extract_evidence", 50, 0.5, 0.5, 0, error="Parse error"),
            StepMetrics("match_patterns", 200, 0.5, 0.7, 2),
        ]
        metrics = ExplorationMetrics("exp_1", "logs", steps)
        assert metrics.error_count == 1

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        steps = [
            StepMetrics("detect_type", 100, 0.0, 0.5, 2),
        ]
        metrics = ExplorationMetrics("exp_1", "logs", steps)
        data = metrics.to_dict()

        assert data["exploration_id"] == "exp_1"
        assert data["artifact_type"] == "logs"
        assert data["step_count"] == 1
        assert data["total_latency_ms"] == 100
        assert data["final_confidence"] == 0.5


class TestExplorationTelemetry:
    """Tests for ExplorationTelemetry event emission."""

    @pytest.fixture
    def telemetry(self) -> ExplorationTelemetry:
        """Create a telemetry instance."""
        return ExplorationTelemetry()

    def test_start_exploration(self, telemetry: ExplorationTelemetry) -> None:
        """Should start exploration tracking."""
        exp_id = telemetry.start_exploration("stack_trace")
        assert exp_id is not None
        assert telemetry.current_exploration_id == exp_id

    def test_record_step(self, telemetry: ExplorationTelemetry) -> None:
        """Should record a step execution."""
        telemetry.start_exploration("logs")
        telemetry.record_step(
            strategy="detect_type",
            latency_ms=150,
            confidence_before=0.0,
            confidence_after=0.5,
            findings_count=3,
        )

        metrics = telemetry.get_current_metrics()
        assert metrics is not None
        assert len(metrics.steps) == 1
        assert metrics.steps[0].strategy == "detect_type"

    def test_record_multiple_steps(self, telemetry: ExplorationTelemetry) -> None:
        """Should record multiple steps in sequence."""
        telemetry.start_exploration("error_message")

        telemetry.record_step("detect_type", 100, 0.0, 0.4, 2)
        telemetry.record_step("extract_evidence", 150, 0.4, 0.6, 5)
        telemetry.record_step("match_patterns", 200, 0.6, 0.85, 3)

        metrics = telemetry.get_current_metrics()
        assert metrics is not None
        assert len(metrics.steps) == 3
        assert metrics.total_latency_ms == 450
        assert metrics.final_confidence == 0.85

    def test_record_step_with_error(self, telemetry: ExplorationTelemetry) -> None:
        """Should record step errors."""
        telemetry.start_exploration("logs")
        telemetry.record_step(
            strategy="extract_ids",
            latency_ms=50,
            confidence_before=0.5,
            confidence_after=0.5,
            findings_count=0,
            error="No IDs found in artifact",
        )

        metrics = telemetry.get_current_metrics()
        assert metrics is not None
        assert metrics.steps[0].error == "No IDs found in artifact"

    def test_end_exploration(self, telemetry: ExplorationTelemetry) -> None:
        """Should finalize exploration metrics."""
        telemetry.start_exploration("stack_trace")
        telemetry.record_step("detect_type", 100, 0.0, 0.6, 3)
        telemetry.record_step("match_patterns", 200, 0.6, 0.9, 2)

        metrics = telemetry.end_exploration()

        assert metrics is not None
        assert metrics.step_count == 2
        assert metrics.final_confidence == 0.9
        assert telemetry.current_exploration_id is None

    def test_get_history(self, telemetry: ExplorationTelemetry) -> None:
        """Should maintain history of explorations."""
        # First exploration
        telemetry.start_exploration("logs")
        telemetry.record_step("detect_type", 100, 0.0, 0.5, 2)
        telemetry.end_exploration()

        # Second exploration
        telemetry.start_exploration("stack_trace")
        telemetry.record_step("detect_type", 150, 0.0, 0.7, 4)
        telemetry.end_exploration()

        history = telemetry.get_history()
        assert len(history) == 2
        assert history[0].artifact_type == "logs"
        assert history[1].artifact_type == "stack_trace"

    def test_get_aggregate_stats(self, telemetry: ExplorationTelemetry) -> None:
        """Should compute aggregate statistics."""
        # Create several explorations with different characteristics
        telemetry.start_exploration("logs")
        telemetry.record_step("detect_type", 100, 0.0, 0.5, 2)
        telemetry.record_step("match_patterns", 200, 0.5, 0.8, 3)
        telemetry.end_exploration()

        telemetry.start_exploration("stack_trace")
        telemetry.record_step("detect_type", 150, 0.0, 0.6, 3)
        telemetry.record_step("extract_evidence", 100, 0.6, 0.7, 4)
        telemetry.record_step("match_patterns", 250, 0.7, 0.9, 2)
        telemetry.end_exploration()

        stats = telemetry.get_aggregate_stats()

        assert stats["exploration_count"] == 2
        assert stats["avg_step_count"] == pytest.approx(2.5)  # (2 + 3) / 2
        assert stats["avg_latency_ms"] == pytest.approx(400)  # (300 + 500) / 2
        assert stats["avg_final_confidence"] == pytest.approx(0.85)  # (0.8 + 0.9) / 2


class TestTelemetryContextManager:
    """Tests for context manager usage."""

    def test_context_manager_basic(self) -> None:
        """Should work as a context manager."""
        telemetry = ExplorationTelemetry()

        with telemetry.exploration("logs") as exp_id:
            assert exp_id is not None
            telemetry.record_step("detect_type", 100, 0.0, 0.5, 2)

        # After context, exploration should be ended
        assert telemetry.current_exploration_id is None
        assert len(telemetry.get_history()) == 1

    def test_context_manager_with_exception(self) -> None:
        """Should handle exceptions gracefully."""
        telemetry = ExplorationTelemetry()

        try:
            with telemetry.exploration("stack_trace"):
                telemetry.record_step("detect_type", 100, 0.0, 0.5, 2)
                raise ValueError("Test error")
        except ValueError:
            pass

        # Should still record the exploration
        assert telemetry.current_exploration_id is None
        history = telemetry.get_history()
        assert len(history) == 1


class TestLatencyTracking:
    """Tests for per-strategy latency tracking."""

    @pytest.fixture
    def telemetry_with_data(self) -> ExplorationTelemetry:
        """Create telemetry with sample data."""
        telemetry = ExplorationTelemetry()

        # Multiple explorations with various latencies
        for _ in range(3):
            telemetry.start_exploration("logs")
            telemetry.record_step("detect_type", 100 + _ * 20, 0.0, 0.5, 2)
            telemetry.record_step("match_patterns", 200 + _ * 30, 0.5, 0.8, 3)
            telemetry.end_exploration()

        return telemetry

    def test_latency_by_strategy(
        self, telemetry_with_data: ExplorationTelemetry
    ) -> None:
        """Should track latency per strategy."""
        latencies = telemetry_with_data.get_latency_by_strategy()

        assert "detect_type" in latencies
        assert "match_patterns" in latencies
        # Each strategy called 3 times
        assert len(latencies["detect_type"]) == 3
        assert len(latencies["match_patterns"]) == 3

    def test_latency_percentiles(
        self, telemetry_with_data: ExplorationTelemetry
    ) -> None:
        """Should compute latency percentiles."""
        percentiles = telemetry_with_data.get_latency_percentiles("detect_type")

        assert "p50" in percentiles
        assert "p95" in percentiles
        assert "p99" in percentiles
        # Values should be in reasonable range
        assert 100 <= percentiles["p50"] <= 140
        assert percentiles["p95"] >= percentiles["p50"]

    def test_latency_percentiles_unknown_strategy(
        self, telemetry_with_data: ExplorationTelemetry
    ) -> None:
        """Should handle unknown strategy gracefully."""
        percentiles = telemetry_with_data.get_latency_percentiles("unknown_strategy")
        assert percentiles == {}
