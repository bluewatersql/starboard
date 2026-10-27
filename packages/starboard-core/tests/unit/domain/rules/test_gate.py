# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the pure severity gate (Phase-3 D1c).

The gate is deterministic and model-free: it drops findings below a configured
severity / score / confidence floor and preserves input order in both
partitions. An unconfigured gate suppresses nothing.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.finding import (
    Confidence,
    Effort,
    Finding,
    Severity,
)
from starboard_core.domain.models.review import ReviewFinding
from starboard_core.domain.rules.gate import (
    SeverityGate,
    apply_severity_gate,
)


def _rf(
    fid: str,
    *,
    severity: Severity,
    impact: int = 3,
    effort: Effort = Effort.S,
    confidence: Confidence = Confidence.MEDIUM,
) -> ReviewFinding:
    return ReviewFinding(
        finding=Finding(
            id=fid,
            severity=severity,
            category="jobs",
            summary=fid,
            rationale="r",
            current_state="bad",
            suggested_fix="good",
            impact=impact,
            effort=effort,
            confidence=confidence,
        )
    )


@pytest.mark.unit
class TestSeverityGate:
    def test_default_gate_keeps_everything(self) -> None:
        findings = [
            _rf("a", severity=Severity.LOW, impact=1, effort=Effort.XL,
                confidence=Confidence.LOW),
            _rf("b", severity=Severity.CRITICAL),
        ]
        outcome = apply_severity_gate(findings, SeverityGate())
        assert outcome.kept_count == 2
        assert outcome.suppressed_count == 0

    def test_min_severity_suppresses_below_floor(self) -> None:
        findings = [
            _rf("low", severity=Severity.LOW),
            _rf("med", severity=Severity.MEDIUM),
            _rf("high", severity=Severity.HIGH),
        ]
        outcome = apply_severity_gate(
            findings, SeverityGate(min_severity=Severity.HIGH)
        )
        assert [rf.finding.id for rf in outcome.kept] == ["high"]
        assert [rf.finding.id for rf in outcome.suppressed] == ["low", "med"]

    def test_min_score_suppresses_low_priority(self) -> None:
        # medium×1/XL = 0.4 (below) vs high×4/XS = 12.0 (above).
        low = _rf("low", severity=Severity.MEDIUM, impact=1, effort=Effort.XL)
        high = _rf("high", severity=Severity.HIGH, impact=4, effort=Effort.XS)
        outcome = apply_severity_gate([low, high], SeverityGate(min_score=5.0))
        assert [rf.finding.id for rf in outcome.kept] == ["high"]

    def test_min_confidence_suppresses_unsure(self) -> None:
        findings = [
            _rf("lo", severity=Severity.HIGH, confidence=Confidence.LOW),
            _rf("hi", severity=Severity.HIGH, confidence=Confidence.HIGH),
        ]
        outcome = apply_severity_gate(
            findings, SeverityGate(min_confidence=Confidence.HIGH)
        )
        assert [rf.finding.id for rf in outcome.kept] == ["hi"]

    def test_order_preserved_and_deterministic(self) -> None:
        findings = [
            _rf("a", severity=Severity.HIGH),
            _rf("b", severity=Severity.LOW),
            _rf("c", severity=Severity.HIGH),
        ]
        gate = SeverityGate(min_severity=Severity.MEDIUM)
        first = apply_severity_gate(findings, gate)
        second = apply_severity_gate(findings, gate)
        assert [rf.finding.id for rf in first.kept] == ["a", "c"]
        assert [rf.finding.id for rf in first.kept] == [
            rf.finding.id for rf in second.kept
        ]

    def test_empty_input_is_empty_outcome(self) -> None:
        outcome = apply_severity_gate([], SeverityGate(min_severity=Severity.HIGH))
        assert outcome.kept_count == 0
        assert outcome.suppressed_count == 0
