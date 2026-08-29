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

The zero-arg factory builds the **real** dbr-doctor HTTP backend when the internal
deployment env is present (:class:`DbrDoctorConfig`); when it is absent it builds
an *unwired* backend whose methods raise a clean, actionable
:class:`MissingInternalConfigError` (never a silent stub). Tests inject their own
:class:`DoctorBackend`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from starboard_core.ports.diagnostic_backend import (
    Candidate,
    DiagnosticBackendPort,
    DiagnosticResult,
)

from starboard_internal._config import (
    DbrDoctorConfig,
    MissingInternalConfigError,
    missing_config_message,
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


class _UnwiredDoctorBackend:
    """Backend used when the internal deployment env is absent.

    Not a silent stub: both methods raise with the exact env vars to set.
    """

    def _raise(self) -> None:
        raise MissingInternalConfigError(
            missing_config_message(
                "DbrDoctorAdapter",
                _BACKEND_SOURCE,
                DbrDoctorConfig.REQUIRED,
                "DoctorBackend",
            )
        )

    def classify(self, pasted: str) -> list[Candidate]:  # noqa: ARG002
        self._raise()
        return []

    async def diagnose(self, candidate: Candidate) -> Mapping[str, Any]:  # noqa: ARG002
        self._raise()
        return {}


class _HttpDoctorBackend:
    """Real dbr-doctor backend: semantic classify + trace-RCA diagnose over HTTP.

    ``classify`` is synchronous (native detector parity) and ``diagnose`` is
    asynchronous, mirroring the port. HTTP clients are created per call.
    """

    def __init__(self, config: DbrDoctorConfig) -> None:
        self._config = config

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.token}"}

    def classify(self, pasted: str) -> list[Candidate]:
        import httpx

        with httpx.Client(timeout=self._config.timeout) as client:
            resp = client.post(
                f"{self._config.url}/classify",
                json={"pasted": pasted},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        candidates_raw = data.get("candidates", []) if isinstance(data, Mapping) else data
        # Defensive: only iterate a real list of mapping items. A scalar or a
        # list of non-mappings would otherwise iterate characters / raise
        # AttributeError on ``item.get`` — fail with a clear, typed error instead.
        if not isinstance(candidates_raw, list):
            raise TypeError(
                "dbr-doctor /classify returned a non-list candidates payload: "
                f"{type(candidates_raw).__name__}"
            )
        candidates: list[Candidate] = []
        for item in candidates_raw:
            if not isinstance(item, Mapping):
                raise TypeError(
                    "dbr-doctor /classify returned a non-mapping candidate item: "
                    f"{type(item).__name__}"
                )
            candidates.append(
                Candidate(
                    kind=str(item.get("kind", "unknown")),
                    raw=str(item.get("raw", pasted)),
                    ref=str(item.get("ref", "")),
                    confidence=float(item.get("confidence", 0.0)),
                    signals=tuple(item.get("signals", ())),
                )
            )
        return candidates

    async def diagnose(self, candidate: Candidate) -> Mapping[str, Any]:
        import httpx

        payload = {
            "kind": candidate.kind,
            "raw": candidate.raw,
            "ref": candidate.ref,
        }
        async with httpx.AsyncClient(timeout=self._config.timeout) as client:
            resp = await client.post(
                f"{self._config.url}/diagnose",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        return data if isinstance(data, Mapping) else {"summary": str(data)}


def _default_backend() -> DoctorBackend:
    """Build the real backend from the internal env, else an unwired backend."""
    config = DbrDoctorConfig.from_env()
    if config is None:
        return _UnwiredDoctorBackend()
    return _HttpDoctorBackend(config)


class DbrDoctorAdapter(DiagnosticBackendPort):
    """Classify + analyze pasted diagnostics via a :class:`DoctorBackend`.

    Args:
        backend: The dbr-doctor backend. When omitted, the real dbr-doctor backend
            is built from the internal deployment env when present, else an
            unwired backend that raises an actionable error on use.
    """

    def __init__(self, backend: DoctorBackend | None = None) -> None:
        self._backend: DoctorBackend = backend or _default_backend()

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
