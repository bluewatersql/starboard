"""Tests for RootCauseSynthesizer."""

import pytest
from starboard_server.tools.domain.diagnostic.models import (
    ExplorationSummary,
    PrimarySymptom,
)
from starboard_server.tools.domain.diagnostic.root_cause_synthesizer import (
    RootCauseSynthesizer,
    SynthesisResult,
    ToolOutput,
)


class TestToolOutput:
    """Tests for ToolOutput dataclass."""

    def test_create_tool_output(self) -> None:
        """Should create a valid tool output."""
        output = ToolOutput(
            tool_name="get_run_output",
            run_id="12345",
            result={"error": "OutOfMemoryError", "state": "FAILED"},
            latency_ms=250,
        )
        assert output.tool_name == "get_run_output"
        assert output.result["error"] == "OutOfMemoryError"
        assert output.latency_ms == 250

    def test_tool_output_with_error(self) -> None:
        """Should handle tool outputs with errors."""
        output = ToolOutput(
            tool_name="get_cluster_events",
            run_id=None,
            result=None,
            error="Cluster not found",
            latency_ms=50,
        )
        assert output.error == "Cluster not found"
        assert output.result is None


class TestSynthesisResult:
    """Tests for SynthesisResult dataclass."""

    def test_create_synthesis_result(self) -> None:
        """Should create a valid synthesis result."""
        result = SynthesisResult(
            primary_symptom=PrimarySymptom.OOM,
            root_causes=["Java heap space exhausted", "GC overhead limit exceeded"],
            confidence=0.88,
            evidence_chain=[
                "stack trace shows OOM",
                "run output confirms FAILED state",
            ],
            recommended_actions=["Increase driver memory", "Enable dynamic allocation"],
        )
        assert result.primary_symptom == PrimarySymptom.OOM
        assert len(result.root_causes) == 2
        assert result.confidence == 0.88

    def test_synthesis_to_exploration_summary(self) -> None:
        """Should convert to ExplorationSummary."""
        result = SynthesisResult(
            primary_symptom=PrimarySymptom.SHUFFLE_FAILURE,
            root_causes=["network timeout"],
            confidence=0.75,
            evidence_chain=["shuffle fetch failed in logs"],
            recommended_actions=["check network config"],
            tool_calls_made=["get_run_output", "get_cluster_events"],
            patterns_matched=["shuffle_fetch_failed"],
            steps_completed=4,
        )
        summary = result.to_exploration_summary()
        assert isinstance(summary, ExplorationSummary)
        assert summary.final_confidence == 0.75
        assert summary.steps_completed == 4
        assert "shuffle_fetch_failed" in (summary.patterns_matched or [])


class TestRootCauseSynthesizer:
    """Tests for RootCauseSynthesizer class."""

    @pytest.fixture
    def synthesizer(self) -> RootCauseSynthesizer:
        """Create a RootCauseSynthesizer instance."""
        return RootCauseSynthesizer()

    def test_synthesize_oom_from_tool_outputs(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Should synthesize OOM root cause from tool outputs."""
        tool_outputs = [
            ToolOutput(
                tool_name="get_run_output",
                run_id="12345",
                result={
                    "state": "FAILED",
                    "error": "java.lang.OutOfMemoryError: Java heap space",
                    "cluster_id": "0123-456789-abc",
                },
                latency_ms=200,
            ),
        ]
        exploration_findings = {
            "artifact_type": "stack_trace",
            "matched_patterns": ["java_heap_space"],
            "evidence_refs": ["EV001"],
            "initial_confidence": 0.7,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        assert result.primary_symptom == PrimarySymptom.OOM
        assert result.confidence >= 0.8  # Tool confirmation should boost confidence
        assert any("heap" in cause.lower() for cause in result.root_causes)

    def test_synthesize_shuffle_failure(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Should synthesize shuffle failure from exploration findings."""
        tool_outputs = [
            ToolOutput(
                tool_name="get_run_output",
                run_id="67890",
                result={
                    "state": "FAILED",
                    "error": "FetchFailedException: Unable to fetch blocks",
                },
                latency_ms=180,
            ),
        ]
        exploration_findings = {
            "artifact_type": "logs",
            "matched_patterns": ["shuffle_fetch_failed"],
            "evidence_refs": ["EV002", "EV003"],
            "initial_confidence": 0.65,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        assert result.primary_symptom == PrimarySymptom.SHUFFLE_FAILURE
        assert result.confidence >= 0.7

    def test_synthesize_with_no_tool_outputs(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Should synthesize from exploration findings alone (OFFLINE mode)."""
        tool_outputs: list[ToolOutput] = []
        exploration_findings = {
            "artifact_type": "error_message",
            "matched_patterns": ["uc_permission_denied"],
            "evidence_refs": ["EV001"],
            "initial_confidence": 0.8,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        assert result.primary_symptom == PrimarySymptom.PERMISSION
        # No tool confirmation, so confidence shouldn't increase
        assert result.confidence <= 0.85

    def test_synthesize_with_failed_tool(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Should handle tool failures gracefully."""
        tool_outputs = [
            ToolOutput(
                tool_name="get_run_output",
                run_id="12345",
                result=None,
                error="Run not found",
                latency_ms=50,
            ),
        ]
        exploration_findings = {
            "artifact_type": "logs",
            "matched_patterns": ["java_heap_space"],
            "evidence_refs": ["EV001"],
            "initial_confidence": 0.7,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        # Should still produce a result, just without tool confirmation
        assert result.primary_symptom == PrimarySymptom.OOM
        assert result.confidence <= 0.75  # No boost from failed tool

    def test_synthesize_correlates_multiple_patterns(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Should correlate multiple patterns into unified diagnosis."""
        tool_outputs = [
            ToolOutput(
                tool_name="get_run_output",
                run_id="12345",
                result={
                    "state": "FAILED",
                    "error": "Container killed by YARN for exceeding memory limits",
                },
                latency_ms=200,
            ),
        ]
        exploration_findings = {
            "artifact_type": "logs",
            "matched_patterns": ["java_heap_space", "gc_overhead", "container_killed"],
            "evidence_refs": ["EV001", "EV002", "EV003"],
            "initial_confidence": 0.6,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        # Multiple correlated patterns should increase confidence
        assert result.primary_symptom == PrimarySymptom.OOM
        assert result.confidence >= 0.85
        assert len(result.root_causes) >= 2  # Should identify multiple causes

    def test_synthesize_unknown_pattern(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Should handle unknown patterns gracefully."""
        tool_outputs: list[ToolOutput] = []
        exploration_findings = {
            "artifact_type": "logs",
            "matched_patterns": [],
            "evidence_refs": [],
            "initial_confidence": 0.3,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        assert result.primary_symptom == PrimarySymptom.UNKNOWN
        assert result.confidence < 0.5

    def test_synthesize_includes_recommended_actions(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Should include actionable recommendations."""
        tool_outputs = [
            ToolOutput(
                tool_name="get_run_output",
                run_id="12345",
                result={"state": "FAILED", "error": "OutOfMemoryError"},
                latency_ms=200,
            ),
        ]
        exploration_findings = {
            "artifact_type": "stack_trace",
            "matched_patterns": ["java_heap_space"],
            "evidence_refs": ["EV001"],
            "initial_confidence": 0.75,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        assert len(result.recommended_actions) >= 1
        # Should have memory-related recommendations for OOM
        assert any(
            "memory" in action.lower() or "heap" in action.lower()
            for action in result.recommended_actions
        )


class TestConfidenceModifiers:
    """Tests for confidence adjustment logic."""

    @pytest.fixture
    def synthesizer(self) -> RootCauseSynthesizer:
        return RootCauseSynthesizer()

    def test_tool_confirmation_boosts_confidence(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Tool output confirming pattern should boost confidence."""
        base_findings = {
            "artifact_type": "logs",
            "matched_patterns": ["java_heap_space"],
            "evidence_refs": ["EV001"],
            "initial_confidence": 0.6,
        }

        # Without tool confirmation
        result_no_tool = synthesizer.synthesize([], base_findings)

        # With tool confirmation
        tool_outputs = [
            ToolOutput(
                tool_name="get_run_output",
                run_id="12345",
                result={"state": "FAILED", "error": "OutOfMemoryError"},
                latency_ms=200,
            ),
        ]
        result_with_tool = synthesizer.synthesize(tool_outputs, base_findings)

        assert result_with_tool.confidence > result_no_tool.confidence

    def test_contradictory_evidence_reduces_confidence(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Contradictory tool output should reduce confidence."""
        tool_outputs = [
            ToolOutput(
                tool_name="get_run_output",
                run_id="12345",
                result={"state": "SUCCESS"},  # Contradicts failure pattern
                latency_ms=200,
            ),
        ]
        exploration_findings = {
            "artifact_type": "logs",
            "matched_patterns": ["java_heap_space"],
            "evidence_refs": ["EV001"],
            "initial_confidence": 0.8,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        # Contradictory evidence should reduce confidence
        assert result.confidence < 0.8

    def test_multiple_tool_confirmations_compound(
        self, synthesizer: RootCauseSynthesizer
    ) -> None:
        """Multiple confirming tools should compound confidence boost."""
        tool_outputs = [
            ToolOutput(
                tool_name="get_run_output",
                run_id="12345",
                result={"state": "FAILED", "error": "OutOfMemoryError"},
                latency_ms=200,
            ),
            ToolOutput(
                tool_name="get_cluster_events",
                run_id=None,
                result={"events": [{"type": "DRIVER_OOM"}]},
                latency_ms=150,
            ),
        ]
        exploration_findings = {
            "artifact_type": "logs",
            "matched_patterns": ["java_heap_space"],
            "evidence_refs": ["EV001"],
            "initial_confidence": 0.6,
        }

        result = synthesizer.synthesize(tool_outputs, exploration_findings)

        # Multiple confirmations should boost confidence significantly
        # Initial 0.6 + TOOL_CONFIRMATION_BOOST(0.15) + MULTI_TOOL_BOOST(0.05) = 0.8
        assert result.confidence >= 0.75
