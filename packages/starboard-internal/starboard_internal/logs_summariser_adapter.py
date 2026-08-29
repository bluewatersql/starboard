# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Gated internal ``LogRetrievalPort`` adapter — logs-summariser (Phase-3 D6).

Where the PUBLIC adapter (``SdkDbfsLogAdapter``) parses *delivered* log4j/event
logs from DBFS/Volumes, this internal adapter drives **logs-summariser** indexed
ClickHouse triage: it retrieves the same log text **plus** an indexed triage
summary and severity. It is a strict SUPERSET of the public adapter — every
public ``LogBundle`` field is still populated (so closing the gate loses nothing,
UNIFIED_PLAN §3.5) and the enrichment lives additively in ``metadata``.

The zero-arg factory used by the entry-point provider builds the **real**
logs-summariser HTTP backend when the internal deployment env is present
(:class:`LogsSummariserConfig`); when it is absent it builds an *unwired* backend
whose ``triage`` raises a clean, actionable :class:`MissingInternalConfigError`
(never a silent stub). Tests inject their own :class:`LogTriageBackend`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from starboard_core.ports.log_retrieval import LogBundle, LogQuery, LogRetrievalPort

from starboard_internal._config import (
    LogsSummariserConfig,
    MissingInternalConfigError,
    missing_config_message,
)

#: Stable source/backend tag (internal-index-only identifier).
_BACKEND_SOURCE = "logs-summariser"


@runtime_checkable
class LogTriageBackend(Protocol):
    """Indexed log-triage backend (logs-summariser). Test-injectable."""

    async def triage(self, ref: LogQuery) -> Mapping[str, Any]:
        """Return a mapping with at least ``text``; optionally ``line_count``,
        ``paths``, ``summary``, ``severity``, ``rows``, ``kube_context``."""
        ...


class _UnwiredTriageBackend:
    """Backend used when the internal deployment env is absent.

    Not a silent stub: ``triage`` raises with the exact env vars to set.
    """

    async def triage(self, ref: LogQuery) -> Mapping[str, Any]:  # noqa: ARG002
        raise MissingInternalConfigError(
            missing_config_message(
                "LogsSummariserAdapter",
                _BACKEND_SOURCE,
                LogsSummariserConfig.REQUIRED,
                "LogTriageBackend",
            )
        )


class _HttpTriageBackend:
    """Real logs-summariser backend: indexed ClickHouse triage over HTTP JSON.

    Posts the log reference to the configured logs-summariser service and returns
    its indexed-triage JSON (text + summary + severity + row count). The HTTP
    client is created per call so no socket is held open at construction time.
    """

    def __init__(self, config: LogsSummariserConfig) -> None:
        self._config = config

    async def triage(self, ref: LogQuery) -> Mapping[str, Any]:
        import httpx

        payload: dict[str, Any] = {
            "entity": ref.entity,
            "entity_id": ref.entity_id,
            "paths": list(ref.paths),
            "time_window_hours": ref.time_window_hours,
            "filters": dict(ref.filters),
        }
        if self._config.kube_context:
            payload["kube_context"] = self._config.kube_context
        async with httpx.AsyncClient(timeout=self._config.timeout) as client:
            resp = await client.post(
                f"{self._config.url}/triage",
                json=payload,
                headers={"Authorization": f"Bearer {self._config.token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return data if isinstance(data, Mapping) else {"text": str(data)}


def _default_backend() -> LogTriageBackend:
    """Build the real backend from the internal env, else an unwired backend."""
    config = LogsSummariserConfig.from_env()
    if config is None:
        return _UnwiredTriageBackend()
    return _HttpTriageBackend(config)


class LogsSummariserAdapter(LogRetrievalPort):
    """Fetch indexed, triaged logs via a :class:`LogTriageBackend`.

    Args:
        backend: The triage backend. When omitted, the real logs-summariser
            backend is built from the internal deployment env when present, else
            an unwired backend that raises an actionable error on use.
        kube_context: Optional default ClickHouse kube context recorded in
            ``metadata`` when the backend does not supply one.
    """

    def __init__(
        self,
        backend: LogTriageBackend | None = None,
        *,
        kube_context: str | None = None,
    ) -> None:
        self._backend: LogTriageBackend = backend or _default_backend()
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
