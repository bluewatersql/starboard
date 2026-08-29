# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the D6 internal ``DiagnosticBackendPort`` adapter (dbr-doctor).

Driven by a stub backend (no live internal call). Asserts the adapter is a strict
superset of the public ``NativeDiagnosticAdapter``: ``analyze`` returns every
public ``DiagnosticResult`` field and the semantic-layer/trace-RCA enrichment is
additive.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import pytest
import respx
from starboard_core.ports.diagnostic_backend import Candidate, DiagnosticResult
from starboard_internal.dbr_doctor_adapter import (
    DbrDoctorAdapter,
    _HttpDoctorBackend,
    _UnwiredDoctorBackend,
)

_ENV_VARS = (
    "STARBOARD_INTERNAL_DBR_DOCTOR_URL",
    "STARBOARD_INTERNAL_DBR_DOCTOR_TOKEN",
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class _StubDoctorBackend:
    def __init__(self, result: Mapping[str, Any]) -> None:
        self._result = result

    def classify(self, pasted: str) -> list[Candidate]:
        return [Candidate(kind="stack_trace", raw=pasted, confidence=0.9)]

    async def diagnose(self, candidate: Candidate) -> Mapping[str, Any]:
        return self._result


@pytest.mark.unit
class TestDbrDoctorAdapter:
    async def test_analyze_has_public_fields_and_enrichment(self) -> None:
        backend = _StubDoctorBackend(
            {
                "summary": "Executor lost due to OOM",
                "root_causes": ("heap exhaustion",),
                "recommendations": ("increase executor memory",),
                "confidence": 0.82,
                "evidence": ("win-1", "win-2"),
                "trace_rca": "spark-stage-4",
                "hmr_stack_hash": "abc123",
                "analysis_url": "https://internal.example/analysis/1",
            }
        )
        adapter = DbrDoctorAdapter(backend)
        result = await adapter.analyze(Candidate(kind="stack_trace", raw="boom"))

        assert isinstance(result, DiagnosticResult)
        # Public capability whole.
        assert result.summary == "Executor lost due to OOM"
        assert result.root_causes == ("heap exhaustion",)
        assert result.recommendations == ("increase executor memory",)
        assert result.confidence == 0.82
        assert result.evidence == ("win-1", "win-2")
        # Public-parity metadata key present.
        assert result.metadata["artifact_kind"] == "stack_trace"
        # Additive enrichment.
        assert result.metadata["semantic_layer"] == "true"
        assert result.metadata["trace_rca"] == "spark-stage-4"
        assert result.metadata["hmr_stack_hash"] == "abc123"

    def test_classify_delegates_and_empty_input_is_empty(self) -> None:
        adapter = DbrDoctorAdapter(_StubDoctorBackend({"summary": "x"}))
        assert adapter.classify("   ") == []
        candidates = adapter.classify("Traceback ...")
        assert candidates and candidates[0].kind == "stack_trace"

    async def test_default_backend_raises_until_wired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        adapter = DbrDoctorAdapter()
        with pytest.raises(RuntimeError, match="dbr-doctor") as exc:
            await adapter.analyze(Candidate(kind="logs", raw="x"))
        assert "STARBOARD_INTERNAL_DBR_DOCTOR_URL" in str(exc.value)

    def test_classify_also_raises_actionably_until_wired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        with pytest.raises(RuntimeError, match="dbr-doctor"):
            DbrDoctorAdapter().classify("Traceback ...")

    def test_default_backend_is_unwired_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        assert isinstance(DbrDoctorAdapter()._backend, _UnwiredDoctorBackend)

    def test_real_backend_selected_when_env_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STARBOARD_INTERNAL_DBR_DOCTOR_URL", "https://doctor.internal")
        monkeypatch.setenv("STARBOARD_INTERNAL_DBR_DOCTOR_TOKEN", "tok")
        assert isinstance(DbrDoctorAdapter()._backend, _HttpDoctorBackend)

    @respx.mock
    async def test_http_backend_classify_and_diagnose(self) -> None:
        from starboard_internal._config import DbrDoctorConfig

        respx.post("https://doctor.internal/classify").mock(
            return_value=httpx.Response(
                200,
                json={"candidates": [{"kind": "stack_trace", "raw": "boom"}]},
            )
        )
        respx.post("https://doctor.internal/diagnose").mock(
            return_value=httpx.Response(
                200, json={"summary": "RCA", "hmr_stack_hash": "h9"}
            )
        )
        backend = _HttpDoctorBackend(
            DbrDoctorConfig(url="https://doctor.internal", token="tok")
        )
        candidates = backend.classify("boom")
        assert candidates and candidates[0].kind == "stack_trace"
        diag = await backend.diagnose(candidates[0])
        assert diag["hmr_stack_hash"] == "h9"
