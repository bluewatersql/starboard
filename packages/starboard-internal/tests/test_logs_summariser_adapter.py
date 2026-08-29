# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the D6 internal ``LogRetrievalPort`` adapter (logs-summariser).

Driven by a stub triage backend (no live internal call). Asserts the adapter is
a strict superset of the public ``SdkDbfsLogAdapter``: every public ``LogBundle``
field is populated and the indexed-triage enrichment is additive.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import pytest
import respx
from starboard_core.ports.log_retrieval import LogBundle, LogQuery
from starboard_internal.logs_summariser_adapter import (
    LogsSummariserAdapter,
    _HttpTriageBackend,
    _UnwiredTriageBackend,
)

_ENV_VARS = (
    "STARBOARD_INTERNAL_LOGS_SUMMARISER_URL",
    "STARBOARD_INTERNAL_LOGS_SUMMARISER_TOKEN",
    "STARBOARD_INTERNAL_LOGS_SUMMARISER_KUBE_CONTEXT",
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class _StubTriageBackend:
    """Returns a canned indexed-triage result."""

    def __init__(self, result: Mapping[str, Any]) -> None:
        self._result = result
        self.calls: list[LogQuery] = []

    async def triage(self, ref: LogQuery) -> Mapping[str, Any]:
        self.calls.append(ref)
        return self._result


@pytest.mark.unit
class TestLogsSummariserAdapter:
    async def test_returns_bundle_with_public_fields_and_enrichment(self) -> None:
        backend = _StubTriageBackend(
            {
                "text": "line-a\nline-b",
                "line_count": 2,
                "paths": ("/idx/cluster/abc",),
                "summary": "OOM on executor 3",
                "severity": "ERROR",
                "rows": 42,
                "kube_context": "prod-aws-us-west-2",
            }
        )
        adapter = LogsSummariserAdapter(backend)
        bundle = await adapter.fetch(
            LogQuery(entity="cluster", entity_id="abc", paths=("/x",))
        )

        assert isinstance(bundle, LogBundle)
        # Public capability whole: text + provenance preserved.
        assert bundle.text == "line-a\nline-b"
        assert bundle.line_count == 2
        assert bundle.paths == ("/idx/cluster/abc",)
        # Public-parity metadata key present.
        assert bundle.metadata["entity"] == "cluster"
        # Additive enrichment.
        assert bundle.metadata["indexed"] == "true"
        assert bundle.metadata["triage_summary"] == "OOM on executor 3"
        assert bundle.metadata["severity"] == "ERROR"
        assert bundle.metadata["kube_context"] == "prod-aws-us-west-2"
        assert backend.calls[0].entity_id == "abc"

    async def test_defaults_line_count_and_paths_from_query(self) -> None:
        adapter = LogsSummariserAdapter(_StubTriageBackend({"text": "only-line"}))
        bundle = await adapter.fetch(
            LogQuery(entity="driver", entity_id="d1", paths=("/p1", "/p2"))
        )
        assert bundle.line_count == 1
        assert bundle.paths == ("/p1", "/p2")

    async def test_default_backend_raises_until_wired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        adapter = LogsSummariserAdapter()
        with pytest.raises(RuntimeError, match="logs-summariser") as exc:
            await adapter.fetch(LogQuery(entity="cluster", entity_id="abc"))
        # Actionable: names the exact env var to set (not a silent stub).
        assert "STARBOARD_INTERNAL_LOGS_SUMMARISER_URL" in str(exc.value)

    def test_default_backend_is_unwired_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        assert isinstance(LogsSummariserAdapter()._backend, _UnwiredTriageBackend)

    def test_real_backend_selected_when_env_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "STARBOARD_INTERNAL_LOGS_SUMMARISER_URL", "https://logs.internal/"
        )
        monkeypatch.setenv("STARBOARD_INTERNAL_LOGS_SUMMARISER_TOKEN", "tok")
        backend = LogsSummariserAdapter()._backend
        assert isinstance(backend, _HttpTriageBackend)
        # url is normalized (trailing slash stripped); no I/O happened.
        assert backend._config.url == "https://logs.internal"

    @respx.mock
    async def test_http_backend_calls_service_and_returns_triage(self) -> None:
        route = respx.post("https://logs.internal/triage").mock(
            return_value=httpx.Response(
                200,
                json={"text": "l1\nl2", "summary": "OOM", "severity": "ERROR"},
            )
        )
        from starboard_internal._config import LogsSummariserConfig

        backend = _HttpTriageBackend(
            LogsSummariserConfig(url="https://logs.internal", token="tok")
        )
        result = await backend.triage(LogQuery(entity="cluster", entity_id="c"))
        assert route.called
        assert result["summary"] == "OOM"
