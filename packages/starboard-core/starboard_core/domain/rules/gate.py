# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Severity gate — suppress sub-threshold / low-confidence findings (Phase-3 D1c).

The severity gate is the **deterministic, model-free** first stage of the D1c
finding-quality pipeline: before the (optional) validator council spends any
model calls, it drops findings that fall below a configured severity, score, or
confidence floor. This keeps low-impact noise from surfacing and bounds how many
findings the council is asked to critique.

It is **pure and I/O-free** — no ``databricks-sdk`` / ``openai`` / ``fastapi`` /
``mcp``, no model calls. The model-calling validator council (which consumes a
gate's kept set) lives in the ``starboard`` server tier, not the kernel.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from starboard_core.domain.models.finding import (
    SEVERITY_WEIGHTS,
    Confidence,
    Severity,
)
from starboard_core.domain.models.review import ReviewFinding

# Confidence ordering (higher index = more confident) for threshold comparison.
_CONFIDENCE_ORDER: dict[Confidence, int] = {
    Confidence.LOW: 0,
    Confidence.MEDIUM: 1,
    Confidence.HIGH: 2,
}


class SeverityGate(BaseModel):
    """Thresholds that decide whether a candidate finding may surface.

    A finding **passes** the gate only when it clears every floor:

    * its severity weight is at least ``min_severity``'s weight,
    * its priority score is at least ``min_score``, and
    * its confidence is at least ``min_confidence``.

    The defaults are permissive (``low`` / ``0.0`` / ``low``) so an
    unconfigured gate suppresses nothing — the gate is opt-in tuning, never a
    silent default filter.
    """

    model_config = ConfigDict(frozen=True)

    min_severity: Severity = Field(
        default=Severity.LOW,
        description="Lowest severity allowed to surface (inclusive).",
    )
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        description="Lowest priority score allowed to surface (inclusive).",
    )
    min_confidence: Confidence = Field(
        default=Confidence.LOW,
        description="Lowest confidence allowed to surface (inclusive).",
    )

    def allows(self, finding: ReviewFinding) -> bool:
        """Return True when ``finding`` clears every configured floor."""
        f = finding.finding
        if SEVERITY_WEIGHTS[f.severity] < SEVERITY_WEIGHTS[self.min_severity]:
            return False
        if f.score < self.min_score:
            return False
        return (
            _CONFIDENCE_ORDER[f.confidence]
            >= _CONFIDENCE_ORDER[self.min_confidence]
        )


class GateOutcome(BaseModel):
    """The partition of findings a :class:`SeverityGate` produced.

    Order within ``kept`` and ``suppressed`` preserves the input order, so the
    outcome is fully deterministic for a given input + gate.
    """

    model_config = ConfigDict(frozen=True)

    kept: tuple[ReviewFinding, ...] = ()
    suppressed: tuple[ReviewFinding, ...] = ()

    @property
    def kept_count(self) -> int:
        """Number of findings that passed the gate."""
        return len(self.kept)

    @property
    def suppressed_count(self) -> int:
        """Number of findings the gate suppressed."""
        return len(self.suppressed)


def apply_severity_gate(
    findings: Sequence[ReviewFinding], gate: SeverityGate
) -> GateOutcome:
    """Partition ``findings`` into kept vs. suppressed by the gate's floors.

    Pure and deterministic: input order is preserved in both partitions and no
    finding is mutated. Never raises on empty input (returns an empty outcome).
    """
    kept: list[ReviewFinding] = []
    suppressed: list[ReviewFinding] = []
    for finding in findings:
        (kept if gate.allows(finding) else suppressed).append(finding)
    return GateOutcome(kept=tuple(kept), suppressed=tuple(suppressed))


__all__ = [
    "GateOutcome",
    "SeverityGate",
    "apply_severity_gate",
]
