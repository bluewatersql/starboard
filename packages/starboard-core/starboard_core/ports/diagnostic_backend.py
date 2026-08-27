# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Diagnostic-backend port (Phase-2 C5, D-2.10).

A kernel-tier, SDK-free Protocol that classifies pasted diagnostic input into
candidates and analyzes a candidate into a structured result.

The PUBLIC adapter is backed by the native extractors + harvested evidence
model. A gated internal adapter (semantic layer + trace-RCA) is Phase 3 and does
not ship here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Candidate:
    """A classified unit of diagnostic input.

    Attributes:
        kind: Detected artifact kind (e.g. ``"stack_trace"``, ``"logs"``, ``"sql"``).
        raw: The verbatim input text for this candidate.
        ref: Optional external reference (id / URL / ticket) the input pointed at.
        confidence: Detection confidence (0.0-1.0).
        signals: Detection signals that contributed to classification.
    """

    kind: str
    raw: str
    ref: str = ""
    confidence: float = 0.0
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosticResult:
    """Structured diagnostic output.

    Attributes:
        summary: Human-readable summary of the analysis.
        root_causes: Candidate root-cause statements (most likely first).
        recommendations: Suggested next actions.
        confidence: Overall confidence (0.0-1.0).
        evidence: Stable evidence identifiers/snippets for citation.
        metadata: Optional adapter metadata.
    """

    summary: str
    root_causes: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class DiagnosticBackendPort(Protocol):
    """Classify pasted input and analyze a candidate into a result."""

    def classify(self, pasted: str) -> list[Candidate]:
        """Classify pasted diagnostic input into zero or more candidates."""
        ...

    async def analyze(self, candidate: Candidate) -> DiagnosticResult:
        """Analyze a single candidate into a structured diagnostic result."""
        ...
