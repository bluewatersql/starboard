# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Gated internal ``LogRetrievalPort`` adapter — logs-summariser (Phase-3 D6).

Where the PUBLIC adapter (``SdkDbfsLogAdapter``) parses *delivered* log4j/event
logs from DBFS/Volumes, this internal adapter drives **logs-summariser** indexed
ClickHouse triage: it retrieves the same log text **plus** an indexed triage
summary and severity. It is a strict SUPERSET of the public adapter — every
public ``LogBundle`` field is still populated (so closing the gate loses nothing,
UNIFIED_PLAN §3.5) and the enrichment lives additively in ``metadata``.

Internal runtime access is not available in this repo; the adapter is driven by
an injected :class:`LogTriageBackend`. The zero-arg factory used by the
entry-point provider builds a default backend that raises unless real internal
access is wired, so the seam registers cleanly without shipping a live client.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from starboard_core.ports.log_retrieval import LogBundle, LogQuery, LogRetrievalPort

#: Stable source/backend tag (internal-index-only identifier).
_BACKEND_SOURCE = "logs-summariser"


@runtime_checkable
class LogTriageBackend(Protocol):
    """Indexed log-triage backend (logs-summariser). Test-injectable."""

    async def triage(self, ref: LogQuery) -> Mapping[str, Any]:
        """Return a mapping with at least ``text``; optionally ``line_count``,
        ``paths``, ``summary``, ``severity``, ``rows``, ``kube_context``."""
        ...


class _DefaultTriageBackend:
    """Placeholder backend: real logs-summariser access is external to this repo."""

    async def triage(self, ref: LogQuery) -> Mapping[str, Any]:  # noqa: ARG002
        raise RuntimeError(
            "LogsSummariserAdapter requires internal logs-summariser runtime "
            "access; inject a LogTriageBackend to use this adapter."
        )


class LogsSummariserAdapter(LogRetrievalPort):
    """Fetch indexed, triaged logs via a :class:`LogTriageBackend`.

    Args:
        backend: The triage backend. When omitted, a default backend is used
            that raises on use (real internal access is wired at deploy time).
        kube_context: Optional default ClickHouse kube context recorded in
            ``metadata`` when the backend does not supply one.
    """

    def __init__(
        self,
        backend: LogTriageBackend | None = None,
        *,
        kube_context: str | None = None,
    ) -> None:
        self._backend: LogTriageBackend = backend or _DefaultTriageBackend()
        self._kube_context = kube_context

    async def fetch(self, ref: LogQuery) -> LogBundle:
        result = await self._backend.triage(ref)
        text = str(result.get("text", ""))
        line_count = int(
            result.get("line_count", text.count("\n") + 1 if text else 0)
        )
        paths = tuple(result.get("paths", ref.paths))
        metadata: dict[str, str] = {
            # Public-parity field (SdkDbfsLogAdapter also records this).
            "entity": ref.entity,
            # --- additive enrichment (superset) ---
            "backend": _BACKEND_SOURCE,
            "indexed": "true",
            "triage_summary": str(result.get("summary", "")),
            "severity": str(result.get("severity", "")),
            "indexed_rows": str(result.get("rows", "")),
            "kube_context": str(
                result.get("kube_context", self._kube_context or "")
            ),
        }
        return LogBundle(
            text=text,
            source=_BACKEND_SOURCE,
            line_count=line_count,
            paths=paths,
            metadata=metadata,
        )
