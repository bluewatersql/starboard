# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Gated internal ``DiagnosticBackendPort`` adapter — dbr-doctor (Phase-3 D6).

Where the PUBLIC adapter (``NativeDiagnosticAdapter``) classifies pasted input
with the native detector + harvested evidence model, this internal adapter drives
the **dbr-doctor** semantic layer + trace-RCA (including the ``hmr_stack_hash``
correlation and an analysis URL). It is a strict SUPERSET: ``classify`` still
returns candidates and ``analyze`` still returns every public
:class:`DiagnosticResult` field (summary / root_causes / recommendations /
confidence / evidence), with the semantic/RCA enrichment added in ``metadata``
(UNIFIED_PLAN §3.5 additive invariant).

Internal runtime access is not available in this repo; the adapter is driven by
an injected :class:`DoctorBackend`. The zero-arg factory builds a default backend
that raises unless real dbr-doctor access is wired.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from starboard_core.ports.diagnostic_backend import (
    Candidate,
    DiagnosticBackendPort,
    DiagnosticResult,
)

#: Stable backend tag (internal-index-only identifier).
_BACKEND_SOURCE = "dbr-doctor"


@runtime_checkable
class DoctorBackend(Protocol):
    """dbr-doctor semantic-layer + trace-RCA backend. Test-injectable."""

    def classify(self, pasted: str) -> list[Candidate]:
        """Classify pasted input into candidates (semantic layer)."""
        ...

    async def diagnose(self, candidate: Candidate) -> Mapping[str, Any]:
        """Return a mapping with at least ``summary``; optionally ``root_causes``,
        ``recommendations``, ``confidence``, ``evidence``, ``trace_rca``,
        ``hmr_stack_hash``, ``analysis_url``."""
        ...


class _DefaultDoctorBackend:
    """Placeholder backend: real dbr-doctor access is external to this repo."""

    def classify(self, pasted: str) -> list[Candidate]:  # noqa: ARG002
        raise RuntimeError(
            "DbrDoctorAdapter requires internal dbr-doctor runtime access; "
            "inject a DoctorBackend to use this adapter."
        )

    async def diagnose(self, candidate: Candidate) -> Mapping[str, Any]:  # noqa: ARG002
        raise RuntimeError(
            "DbrDoctorAdapter requires internal dbr-doctor runtime access; "
            "inject a DoctorBackend to use this adapter."
        )


class DbrDoctorAdapter(DiagnosticBackendPort):
    """Classify + analyze pasted diagnostics via a :class:`DoctorBackend`.

    Args:
        backend: The dbr-doctor backend. When omitted, a default backend is used
            that raises on use (real internal access is wired at deploy time).
    """

    def __init__(self, backend: DoctorBackend | None = None) -> None:
        self._backend: DoctorBackend = backend or _DefaultDoctorBackend()

    def classify(self, pasted: str) -> list[Candidate]:
        if not pasted or not pasted.strip():
            return []
        return list(self._backend.classify(pasted))

    async def analyze(self, candidate: Candidate) -> DiagnosticResult:
        result = await self._backend.diagnose(candidate)
        metadata: dict[str, str] = {
            # Public-parity field (NativeDiagnosticAdapter also records this).
            "artifact_kind": candidate.kind,
            # --- additive enrichment (superset) ---
            "backend": _BACKEND_SOURCE,
            "semantic_layer": "true",
            "trace_rca": str(result.get("trace_rca", "")),
            "hmr_stack_hash": str(result.get("hmr_stack_hash", "")),
            "analysis_url": str(result.get("analysis_url", "")),
        }
        return DiagnosticResult(
            summary=str(result.get("summary", "")),
            root_causes=tuple(result.get("root_causes", ())),
            recommendations=tuple(result.get("recommendations", ())),
            confidence=float(result.get("confidence", 0.0)),
            evidence=tuple(result.get("evidence", ())),
            metadata=metadata,
        )
