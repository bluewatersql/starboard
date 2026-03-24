# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Unit tests for ExitCodeTriager.

Tests cover:
- Signal decoding (128+N exit codes)
- Hypothesis generation
- Proof signal matching
- Confidence scoring
"""

import pytest
from starboard_server.tools.domain.diagnostic.exit_code_triager import (
    ExitCodeTriager,
    HypothesisType,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def triager() -> ExitCodeTriager:
    """Create triager instance."""
    return ExitCodeTriager()


# =============================================================================
# SIGNAL DECODING TESTS
# =============================================================================


class TestSignalDecoding:
    """Tests for Unix signal decoding."""

    def test_exit_137_is_sigkill(self, triager: ExitCodeTriager) -> None:
        """Exit code 137 = 128 + 9 = SIGKILL."""
        result = triager.triage(137)

        assert result.is_signal
        assert result.signal_number == 9
        assert result.primary_hypothesis.signal_info is not None
        assert result.primary_hypothesis.signal_info.name == "SIGKILL"

    def test_exit_143_is_sigterm(self, triager: ExitCodeTriager) -> None:
        """Exit code 143 = 128 + 15 = SIGTERM."""
        result = triager.triage(143)

        assert result.is_signal
        assert result.signal_number == 15
        assert result.primary_hypothesis.signal_info is not None
        assert result.primary_hypothesis.signal_info.name == "SIGTERM"

    def test_exit_139_is_sigsegv(self, triager: ExitCodeTriager) -> None:
        """Exit code 139 = 128 + 11 = SIGSEGV."""
        result = triager.triage(139)

        assert result.is_signal
        assert result.signal_number == 11
        assert result.primary_hypothesis.signal_info is not None
        assert result.primary_hypothesis.signal_info.name == "SIGSEGV"

    def test_exit_0_success(self, triager: ExitCodeTriager) -> None:
        """Exit code 0 is success."""
        result = triager.triage(0)

        assert not result.is_signal
        assert result.signal_number is None
        assert "success" in result.raw_interpretation.lower()

    def test_exit_1_general_error(self, triager: ExitCodeTriager) -> None:
        """Exit code 1 is general error."""
        result = triager.triage(1)

        assert not result.is_signal
        assert result.primary_hypothesis.hypothesis_type == HypothesisType.UNKNOWN

    def test_unknown_signal(self, triager: ExitCodeTriager) -> None:
        """Unknown signal numbers are handled."""
        result = triager.triage(200)  # 128 + 72 = unknown signal

        assert result.is_signal
        assert result.signal_number == 72
        # Should still work, just without signal info
        assert "signal 72" in result.raw_interpretation.lower()


# =============================================================================
# HYPOTHESIS GENERATION TESTS
# =============================================================================


class TestHypothesisGeneration:
    """Tests for hypothesis generation."""

    def test_exit_137_default_oom(self, triager: ExitCodeTriager) -> None:
        """Exit 137 defaults to OOM hypothesis."""
        result = triager.triage(137)

        assert result.primary_hypothesis.hypothesis_type == HypothesisType.OOM

    def test_exit_143_default_cancellation(self, triager: ExitCodeTriager) -> None:
        """Exit 143 defaults to cancellation hypothesis."""
        result = triager.triage(143)

        assert result.primary_hypothesis.hypothesis_type == HypothesisType.CANCELLATION

    def test_exit_139_default_crash(self, triager: ExitCodeTriager) -> None:
        """Exit 139 (SIGSEGV) defaults to crash hypothesis."""
        result = triager.triage(139)

        assert result.primary_hypothesis.hypothesis_type == HypothesisType.CRASH

    def test_provides_alternative_hypotheses(self, triager: ExitCodeTriager) -> None:
        """Alternative hypotheses are provided."""
        result = triager.triage(137)

        # Should have at least one alternative
        assert len(result.alternative_hypotheses) >= 1


# =============================================================================
# PROOF SIGNAL TESTS
# =============================================================================


class TestProofSignals:
    """Tests for proof signal matching."""

    def test_oomkilled_increases_oom_confidence(self, triager: ExitCodeTriager) -> None:
        """OOMKilled in context increases OOM confidence."""
        result_without = triager.triage(137, "")
        result_with = triager.triage(137, "Container was OOMKilled")

        # Find OOM hypothesis in both
        oom_without = next(
            (
                h
                for h in [result_without.primary_hypothesis]
                + list(result_without.alternative_hypotheses)
                if h.hypothesis_type == HypothesisType.OOM
            ),
            None,
        )
        oom_with = next(
            (
                h
                for h in [result_with.primary_hypothesis]
                + list(result_with.alternative_hypotheses)
                if h.hypothesis_type == HypothesisType.OOM
            ),
            None,
        )

        assert oom_without is not None
        assert oom_with is not None
        assert oom_with.confidence >= oom_without.confidence

    def test_cancellation_evidence_increases_cancellation(
        self, triager: ExitCodeTriager
    ) -> None:
        """Cancellation evidence increases cancellation confidence for 143."""
        result_without = triager.triage(143, "")
        result_with = triager.triage(143, "Job was cancelled by user")

        assert (
            result_with.primary_hypothesis.hypothesis_type
            == HypothesisType.CANCELLATION
        )
        assert (
            result_with.primary_hypothesis.confidence
            >= result_without.primary_hypothesis.confidence
        )

    def test_negative_signal_reduces_confidence_for_137(
        self, triager: ExitCodeTriager
    ) -> None:
        """Cancellation evidence reduces OOM confidence for 137."""
        result_oom = triager.triage(137, "Container was OOMKilled")
        result_cancelled = triager.triage(137, "job cancellation requested")

        # OOM confidence should be higher when OOMKilled present
        oom_conf_with_evidence = result_oom.primary_hypothesis.confidence
        oom_conf_with_cancellation = next(
            (
                h.confidence
                for h in [result_cancelled.primary_hypothesis]
                + list(result_cancelled.alternative_hypotheses)
                if h.hypothesis_type == HypothesisType.OOM
            ),
            0.0,
        )

        # With OOMKilled evidence, OOM confidence should be higher
        assert oom_conf_with_evidence >= oom_conf_with_cancellation

    def test_supporting_evidence_tracked(self, triager: ExitCodeTriager) -> None:
        """Supporting evidence is tracked in hypothesis."""
        result = triager.triage(137, "Container was OOMKilled, oom-killer invoked")

        oom_hypothesis = result.primary_hypothesis
        assert oom_hypothesis.hypothesis_type == HypothesisType.OOM
        assert len(oom_hypothesis.supporting_evidence) >= 1

    def test_multiple_proof_signals_accumulate(self, triager: ExitCodeTriager) -> None:
        """Multiple proof signals increase confidence more."""
        result_one = triager.triage(137, "OOMKilled")
        result_multiple = triager.triage(
            137, "OOMKilled and oom-killer invoked with OutOfMemoryError"
        )

        assert (
            result_multiple.primary_hypothesis.confidence
            >= result_one.primary_hypothesis.confidence
        )


# =============================================================================
# NEXT STEPS TESTS
# =============================================================================


class TestNextSteps:
    """Tests for recommended next steps."""

    def test_oom_hypothesis_has_steps(self, triager: ExitCodeTriager) -> None:
        """OOM hypothesis includes relevant next steps."""
        result = triager.triage(137)

        oom_hypothesis = result.primary_hypothesis
        assert len(oom_hypothesis.next_steps) >= 1
        # Should mention memory-related investigation
        steps_text = " ".join(oom_hypothesis.next_steps).lower()
        assert "memory" in steps_text or "gc" in steps_text

    def test_cancellation_hypothesis_has_steps(self, triager: ExitCodeTriager) -> None:
        """Cancellation hypothesis includes relevant next steps."""
        result = triager.triage(143)

        cancel_hypothesis = result.primary_hypothesis
        assert len(cancel_hypothesis.next_steps) >= 1
        steps_text = " ".join(cancel_hypothesis.next_steps).lower()
        assert "cancel" in steps_text or "timeout" in steps_text


# =============================================================================
# RAW INTERPRETATION TESTS
# =============================================================================


class TestRawInterpretation:
    """Tests for raw interpretation string."""

    def test_interpretation_includes_exit_code(self, triager: ExitCodeTriager) -> None:
        """Interpretation includes the exit code."""
        result = triager.triage(137)

        assert "137" in result.raw_interpretation

    def test_interpretation_includes_signal_name(
        self, triager: ExitCodeTriager
    ) -> None:
        """Interpretation includes signal name for known signals."""
        result = triager.triage(137)

        assert "SIGKILL" in result.raw_interpretation

    def test_interpretation_for_non_signal(self, triager: ExitCodeTriager) -> None:
        """Interpretation for non-signal exit code."""
        result = triager.triage(1)

        assert "1" in result.raw_interpretation
        assert "128" not in result.raw_interpretation  # Not a signal calculation


# =============================================================================
# DECODE EXIT CODE TESTS
# =============================================================================


class TestDecodeExitCode:
    """Tests for quick exit code decoding."""

    def test_decode_success(self, triager: ExitCodeTriager) -> None:
        """Decode exit code 0."""
        assert triager.decode_exit_code(0) == "Success"

    def test_decode_sigkill(self, triager: ExitCodeTriager) -> None:
        """Decode SIGKILL."""
        assert "SIGKILL" in triager.decode_exit_code(137)

    def test_decode_sigterm(self, triager: ExitCodeTriager) -> None:
        """Decode SIGTERM."""
        assert "SIGTERM" in triager.decode_exit_code(143)

    def test_decode_unknown_signal(self, triager: ExitCodeTriager) -> None:
        """Decode unknown signal."""
        result = triager.decode_exit_code(200)
        assert "Signal 72" in result or "72" in result

    def test_decode_command_not_found(self, triager: ExitCodeTriager) -> None:
        """Decode command not found (127)."""
        assert "not found" in triager.decode_exit_code(127).lower()


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_exit_128_boundary(self, triager: ExitCodeTriager) -> None:
        """Exit code 128 is boundary (not a signal)."""
        result = triager.triage(128)

        # 128 is exactly the boundary
        assert not result.is_signal

    def test_exit_129_is_signal_1(self, triager: ExitCodeTriager) -> None:
        """Exit code 129 = 128 + 1 = SIGHUP."""
        result = triager.triage(129)

        assert result.is_signal
        assert result.signal_number == 1

    def test_empty_context(self, triager: ExitCodeTriager) -> None:
        """Empty context still produces valid result."""
        result = triager.triage(137, "")

        assert result.primary_hypothesis is not None
        assert result.primary_hypothesis.confidence > 0

    def test_very_long_context(self, triager: ExitCodeTriager) -> None:
        """Very long context is handled."""
        long_context = "OOMKilled " * 1000
        result = triager.triage(137, long_context)

        assert result.primary_hypothesis.hypothesis_type == HypothesisType.OOM
