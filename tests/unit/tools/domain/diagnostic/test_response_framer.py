# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Unit tests for ResponseFramer - frames diagnostic responses based on confidence.

Tests cover:
- High confidence (≥90%): Definitive diagnosis
- Medium-high confidence (70-89%): Likely diagnosis + confirmation
- Medium confidence (50-69%): Hypothesis + questions
- Low confidence (<50%): Multiple possibilities
"""

from __future__ import annotations

import pytest
from starboard_server.tools.domain.diagnostic.response_framer import (
    ConfidenceLevel,
    DiagnosticFinding,
    FramedResponse,
    ResponseFramer,
)


@pytest.fixture
def framer() -> ResponseFramer:
    """Create ResponseFramer instance."""
    return ResponseFramer()


# =============================================================================
# CONFIDENCE LEVEL DETERMINATION
# =============================================================================


class TestConfidenceLevelDetermination:
    """Tests for determining confidence level from score."""

    def test_definitive_at_90(self, framer: ResponseFramer) -> None:
        """90% confidence is definitive."""
        level = framer.get_confidence_level(0.90)
        assert level == ConfidenceLevel.DEFINITIVE

    def test_definitive_at_95(self, framer: ResponseFramer) -> None:
        """95% confidence is definitive."""
        level = framer.get_confidence_level(0.95)
        assert level == ConfidenceLevel.DEFINITIVE

    def test_likely_at_85(self, framer: ResponseFramer) -> None:
        """85% confidence is likely."""
        level = framer.get_confidence_level(0.85)
        assert level == ConfidenceLevel.LIKELY

    def test_likely_at_70(self, framer: ResponseFramer) -> None:
        """70% confidence is likely."""
        level = framer.get_confidence_level(0.70)
        assert level == ConfidenceLevel.LIKELY

    def test_hypothesis_at_65(self, framer: ResponseFramer) -> None:
        """65% confidence is hypothesis."""
        level = framer.get_confidence_level(0.65)
        assert level == ConfidenceLevel.HYPOTHESIS

    def test_hypothesis_at_50(self, framer: ResponseFramer) -> None:
        """50% confidence is hypothesis."""
        level = framer.get_confidence_level(0.50)
        assert level == ConfidenceLevel.HYPOTHESIS

    def test_uncertain_at_45(self, framer: ResponseFramer) -> None:
        """45% confidence is uncertain."""
        level = framer.get_confidence_level(0.45)
        assert level == ConfidenceLevel.UNCERTAIN

    def test_uncertain_at_0(self, framer: ResponseFramer) -> None:
        """0% confidence is uncertain."""
        level = framer.get_confidence_level(0.0)
        assert level == ConfidenceLevel.UNCERTAIN


# =============================================================================
# DEFINITIVE RESPONSE FRAMING
# =============================================================================


class TestDefinitiveFraming:
    """Tests for definitive (≥90%) response framing."""

    def test_definitive_uses_confident_language(self, framer: ResponseFramer) -> None:
        """Definitive response uses confident language."""
        finding = DiagnosticFinding(
            diagnosis="Java heap space exhaustion",
            confidence=0.95,
            evidence=["OutOfMemoryError: Java heap space in logs"],
            root_cause="Executor memory insufficient for data size",
        )
        response = framer.frame(finding)

        assert response.confidence_level == ConfidenceLevel.DEFINITIVE
        # Should use definitive language
        assert any(
            phrase in response.framed_diagnosis.lower()
            for phrase in ["the issue is", "the root cause is", "this is caused by"]
        )

    def test_definitive_includes_evidence(self, framer: ResponseFramer) -> None:
        """Definitive response cites evidence."""
        finding = DiagnosticFinding(
            diagnosis="Exit code 137 - OOM killed",
            confidence=0.92,
            evidence=["Exit code 137", "OOMKilled annotation"],
            root_cause="Container memory limit exceeded",
        )
        response = framer.frame(finding)

        assert len(response.evidence_citations) > 0
        assert "Exit code 137" in response.evidence_citations[0]

    def test_definitive_has_remediation(self, framer: ResponseFramer) -> None:
        """Definitive response includes remediation steps."""
        finding = DiagnosticFinding(
            diagnosis="Shuffle fetch failed",
            confidence=0.90,
            evidence=["FetchFailedException in logs"],
            root_cause="Network timeout during shuffle",
            remediation=["Increase shuffle timeout", "Check network health"],
        )
        response = framer.frame(finding)

        assert response.remediation_steps is not None
        assert len(response.remediation_steps) > 0


# =============================================================================
# LIKELY RESPONSE FRAMING
# =============================================================================


class TestLikelyFraming:
    """Tests for likely (70-89%) response framing."""

    def test_likely_uses_hedged_language(self, framer: ResponseFramer) -> None:
        """Likely response uses hedged language."""
        finding = DiagnosticFinding(
            diagnosis="Data skew issue",
            confidence=0.75,
            evidence=["Straggler tasks observed"],
            root_cause="Uneven data distribution",
        )
        response = framer.frame(finding)

        assert response.confidence_level == ConfidenceLevel.LIKELY
        # Should use hedged language
        assert any(
            phrase in response.framed_diagnosis.lower()
            for phrase in ["likely", "appears to be", "most likely", "probably"]
        )

    def test_likely_includes_confirmation_steps(self, framer: ResponseFramer) -> None:
        """Likely response includes confirmation steps."""
        finding = DiagnosticFinding(
            diagnosis="Memory pressure",
            confidence=0.80,
            evidence=["GC overhead warnings"],
            root_cause="Insufficient executor memory",
        )
        response = framer.frame(finding)

        assert response.confirmation_steps is not None
        assert len(response.confirmation_steps) > 0

    def test_likely_mentions_additional_evidence_needed(
        self, framer: ResponseFramer
    ) -> None:
        """Likely response mentions what would increase confidence."""
        finding = DiagnosticFinding(
            diagnosis="Connection timeout",
            confidence=0.72,
            evidence=["Timeout errors in logs"],
            root_cause="Network instability",
        )
        response = framer.frame(finding)

        # Should mention what would help confirm
        assert response.additional_evidence_needed is not None


# =============================================================================
# HYPOTHESIS RESPONSE FRAMING
# =============================================================================


class TestHypothesisFraming:
    """Tests for hypothesis (50-69%) response framing."""

    def test_hypothesis_uses_tentative_language(self, framer: ResponseFramer) -> None:
        """Hypothesis response uses tentative language."""
        finding = DiagnosticFinding(
            diagnosis="Possible serialization issue",
            confidence=0.55,
            evidence=["Task failures observed"],
            root_cause="Non-serializable object in closure",
        )
        response = framer.frame(finding)

        assert response.confidence_level == ConfidenceLevel.HYPOTHESIS
        # Should use tentative language
        assert any(
            phrase in response.framed_diagnosis.lower()
            for phrase in ["possible", "might be", "could be", "may be", "hypothesis"]
        )

    def test_hypothesis_asks_specific_questions(self, framer: ResponseFramer) -> None:
        """Hypothesis response asks specific questions."""
        finding = DiagnosticFinding(
            diagnosis="Possible disk issue",
            confidence=0.60,
            evidence=["I/O errors observed"],
            root_cause="Disk space or throughput",
        )
        response = framer.frame(finding)

        assert response.clarifying_questions is not None
        assert len(response.clarifying_questions) > 0

    def test_hypothesis_mentions_alternatives(self, framer: ResponseFramer) -> None:
        """Hypothesis response mentions alternative diagnoses."""
        finding = DiagnosticFinding(
            diagnosis="Possible network issue",
            confidence=0.58,
            evidence=["Connection errors"],
            root_cause="Network connectivity",
            alternatives=["Firewall blocking", "DNS issues"],
        )
        response = framer.frame(finding)

        assert response.alternative_diagnoses is not None
        assert len(response.alternative_diagnoses) > 0


# =============================================================================
# UNCERTAIN RESPONSE FRAMING
# =============================================================================


class TestUncertainFraming:
    """Tests for uncertain (<50%) response framing."""

    def test_uncertain_presents_multiple_possibilities(
        self, framer: ResponseFramer
    ) -> None:
        """Uncertain response presents multiple possibilities."""
        finding = DiagnosticFinding(
            diagnosis="Unknown failure",
            confidence=0.30,
            evidence=["Job failed"],
            root_cause="Multiple possible causes",
            alternatives=["Memory issue", "Network issue", "Configuration error"],
        )
        response = framer.frame(finding)

        assert response.confidence_level == ConfidenceLevel.UNCERTAIN
        assert response.alternative_diagnoses is not None
        assert len(response.alternative_diagnoses) >= 1

    def test_uncertain_requests_more_information(self, framer: ResponseFramer) -> None:
        """Uncertain response requests more information."""
        finding = DiagnosticFinding(
            diagnosis="Unclear error",
            confidence=0.25,
            evidence=["Error message truncated"],
            root_cause="Unknown",
        )
        response = framer.frame(finding)

        assert response.additional_evidence_needed is not None
        assert len(response.additional_evidence_needed) > 0

    def test_uncertain_uses_exploratory_language(self, framer: ResponseFramer) -> None:
        """Uncertain response uses exploratory language."""
        finding = DiagnosticFinding(
            diagnosis="Ambiguous failure",
            confidence=0.40,
            evidence=["Generic error"],
            root_cause="Unknown",
        )
        response = framer.frame(finding)

        # Should use exploratory language
        assert any(
            phrase in response.framed_diagnosis.lower()
            for phrase in [
                "unable to determine",
                "insufficient evidence",
                "need more",
                "several possibilities",
                "cannot conclusively",
            ]
        )


# =============================================================================
# RESPONSE STRUCTURE
# =============================================================================


class TestResponseStructure:
    """Tests for response structure."""

    def test_response_has_required_fields(self, framer: ResponseFramer) -> None:
        """Response has all required fields."""
        finding = DiagnosticFinding(
            diagnosis="Test diagnosis",
            confidence=0.75,
            evidence=["Test evidence"],
        )
        response = framer.frame(finding)

        assert isinstance(response, FramedResponse)
        assert hasattr(response, "framed_diagnosis")
        assert hasattr(response, "confidence_level")
        assert hasattr(response, "confidence_score")
        assert hasattr(response, "evidence_citations")

    def test_response_preserves_confidence_score(self, framer: ResponseFramer) -> None:
        """Response preserves original confidence score."""
        finding = DiagnosticFinding(
            diagnosis="Test",
            confidence=0.82,
            evidence=[],
        )
        response = framer.frame(finding)

        assert response.confidence_score == 0.82

    def test_response_has_summary(self, framer: ResponseFramer) -> None:
        """Response has a summary."""
        finding = DiagnosticFinding(
            diagnosis="Memory exhaustion",
            confidence=0.90,
            evidence=["OOM error"],
            root_cause="Insufficient memory",
        )
        response = framer.frame(finding)

        assert response.summary is not None
        assert len(response.summary) > 0


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_evidence(self, framer: ResponseFramer) -> None:
        """Handle empty evidence list."""
        finding = DiagnosticFinding(
            diagnosis="Test",
            confidence=0.50,
            evidence=[],
        )
        response = framer.frame(finding)
        assert isinstance(response, FramedResponse)

    def test_boundary_90(self, framer: ResponseFramer) -> None:
        """Test boundary at exactly 90%."""
        level = framer.get_confidence_level(0.90)
        assert level == ConfidenceLevel.DEFINITIVE

    def test_boundary_70(self, framer: ResponseFramer) -> None:
        """Test boundary at exactly 70%."""
        level = framer.get_confidence_level(0.70)
        assert level == ConfidenceLevel.LIKELY

    def test_boundary_50(self, framer: ResponseFramer) -> None:
        """Test boundary at exactly 50%."""
        level = framer.get_confidence_level(0.50)
        assert level == ConfidenceLevel.HYPOTHESIS

    def test_confidence_over_100(self, framer: ResponseFramer) -> None:
        """Handle confidence > 1.0."""
        level = framer.get_confidence_level(1.5)
        assert level == ConfidenceLevel.DEFINITIVE

    def test_negative_confidence(self, framer: ResponseFramer) -> None:
        """Handle negative confidence."""
        level = framer.get_confidence_level(-0.5)
        assert level == ConfidenceLevel.UNCERTAIN
