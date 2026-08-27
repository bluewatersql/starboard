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

import pytest
from starboard_core.ports.log_retrieval import LogBundle, LogQuery
from starboard_internal.logs_summariser_adapter import (
    LogsSummariserAdapter,
    _DefaultTriageBackend,
)


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

    async def test_default_backend_raises_until_wired(self) -> None:
        adapter = LogsSummariserAdapter()
        with pytest.raises(RuntimeError, match="logs-summariser"):
            await adapter.fetch(LogQuery(entity="cluster", entity_id="abc"))

    def test_default_backend_type_is_placeholder(self) -> None:
        assert isinstance(LogsSummariserAdapter()._backend, _DefaultTriageBackend)
