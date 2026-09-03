# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Additive-invariant parity tests across the public-backed ports (UNIFIED_PLAN §3.5).

For each port that has BOTH a public and an internal adapter, the REAL public
adapter is registered as ``public`` and the REAL internal adapter (driven by a
stub backend — no live internal call) as ``internal``. The tests assert:

* **Gate CLOSED** -> the PUBLIC adapter is selected and its capability contract
  still holds (it returns a well-formed port DTO).
* **Gate OPEN** -> the INTERNAL adapter is selected and its output is a strict
  SUPERSET: the public DTO fields are still present, plus additive enrichment.

This is the merge gate proving no capability is lost when the gate closes.

``NL_QUERY`` is intentionally excluded: the native-first simplification removed
the public NL→SQL adapter (public NL Q&A is delegated to the host's native
Genie), so there is no public baseline to prove parity against. The internal
``CuratedGenieRoomAdapter`` remains a gated, internal-only enhancement and is
covered by ``test_seam.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from starboard.adapters.ports import (
    NativeDiagnosticAdapter,
    SdkDbfsLogAdapter,
    SingleWorkspaceFleetAdapter,
)
from starboard.ports.registry import Port, PortRegistry
from starboard_core.ports.diagnostic_backend import Candidate
from starboard_core.ports.fleet_sql import FleetQuery
from starboard_core.ports.log_retrieval import LogBundle, LogQuery
from starboard_internal.centralized_fleet_adapter import CentralizedFleetSqlAdapter
from starboard_internal.dbr_doctor_adapter import DbrDoctorAdapter
from starboard_internal.logs_summariser_adapter import LogsSummariserAdapter

_STACK_TRACE = (
    "Traceback (most recent call last):\n"
    '  File "job.py", line 10, in <module>\n'
    "    raise RuntimeError('boom')\n"
    "RuntimeError: boom"
)


# --- fakes for the PUBLIC adapter collaborators ------------------------------
class _FakeDBFS:
    def dbfs_path_exists(self, path: str) -> bool:
        return True

    def list_dbfs_files(self, path: str, recursive: bool = False) -> list[dict]:
        return [{"path": "/logs/app.log", "is_dir": False}]

    def read_dbfs_chunk(self, path: str, offset: int, length: int) -> bytes:
        return b"" if offset else b"ERROR boom\nWARN noise"


async def _fake_executor(sql: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"columns": ["c"], "rows": [(1,)]}


# --- stubs for the INTERNAL adapter backends ---------------------------------
class _StubTriage:
    async def triage(self, ref: LogQuery) -> Mapping[str, Any]:
        return {"text": "indexed line", "summary": "OOM", "severity": "ERROR"}


class _StubDoctor:
    def classify(self, pasted: str) -> list[Candidate]:
        return [Candidate(kind="stack_trace", raw=pasted)]

    async def diagnose(self, candidate: Candidate) -> Mapping[str, Any]:
        return {
            "summary": "semantic RCA",
            "root_causes": ("oom",),
            "confidence": 0.9,
            "hmr_stack_hash": "h1",
        }


def _registry() -> PortRegistry:
    reg = PortRegistry()
    reg.register_public(Port.LOG_RETRIEVAL, SdkDbfsLogAdapter(dbfs_client=_FakeDBFS()))
    reg.register_public(Port.DIAGNOSTIC_BACKEND, NativeDiagnosticAdapter())
    reg.register_public(Port.FLEET_SQL, SingleWorkspaceFleetAdapter(_fake_executor))

    reg.register_internal(Port.LOG_RETRIEVAL, LogsSummariserAdapter(_StubTriage()))
    reg.register_internal(Port.DIAGNOSTIC_BACKEND, DbrDoctorAdapter(_StubDoctor()))
    reg.register_internal(Port.FLEET_SQL, CentralizedFleetSqlAdapter(_fake_executor))
    return reg


@pytest.mark.unit
class TestGateClosedKeepsPublicCapability:
    async def test_log_retrieval_public_selected(self) -> None:
        adapter = _registry().select_adapter(Port.LOG_RETRIEVAL, gate_open=False)
        assert isinstance(adapter, SdkDbfsLogAdapter)
        bundle = await adapter.fetch(LogQuery(entity="cluster", entity_id="c", paths=("/l",)))
        assert isinstance(bundle, LogBundle)
        assert bundle.text  # capability produced content

    def test_diagnostic_public_selected(self) -> None:
        adapter = _registry().select_adapter(Port.DIAGNOSTIC_BACKEND, gate_open=False)
        assert isinstance(adapter, NativeDiagnosticAdapter)
        assert adapter.classify(_STACK_TRACE)  # capability holds

    async def test_fleet_public_selected(self) -> None:
        adapter = _registry().select_adapter(Port.FLEET_SQL, gate_open=False)
        assert isinstance(adapter, SingleWorkspaceFleetAdapter)
        result = await adapter.execute(FleetQuery(sql="SELECT c FROM system.billing.usage"))
        assert result.columns == ("c",)


@pytest.mark.unit
class TestGateOpenInternalIsSuperset:
    async def test_log_retrieval_internal_superset(self) -> None:
        reg = _registry()
        pub = await reg.select_adapter(Port.LOG_RETRIEVAL, gate_open=False).fetch(
            LogQuery(entity="cluster", entity_id="c", paths=("/l",))
        )
        internal_adapter = reg.select_adapter(Port.LOG_RETRIEVAL, gate_open=True)
        assert isinstance(internal_adapter, LogsSummariserAdapter)
        got = await internal_adapter.fetch(LogQuery(entity="cluster", entity_id="c"))
        # Every public LogBundle field is still present.
        assert set(vars(pub)) == set(vars(got))
        assert got.text and "entity" in got.metadata  # public-parity preserved
        assert got.metadata["indexed"] == "true"  # additive enrichment

    async def test_diagnostic_internal_superset(self) -> None:
        reg = _registry()
        internal_adapter = reg.select_adapter(Port.DIAGNOSTIC_BACKEND, gate_open=True)
        assert isinstance(internal_adapter, DbrDoctorAdapter)
        result = await internal_adapter.analyze(Candidate(kind="stack_trace", raw="x"))
        assert result.summary and "artifact_kind" in result.metadata  # public parity
        assert result.metadata["semantic_layer"] == "true"  # additive

    async def test_fleet_internal_superset(self) -> None:
        reg = _registry()
        internal_adapter = reg.select_adapter(Port.FLEET_SQL, gate_open=True)
        assert isinstance(internal_adapter, CentralizedFleetSqlAdapter)
        result = await internal_adapter.execute(
            FleetQuery(sql="SELECT c FROM system.billing.usage", workspace_id="w")
        )
        assert result.columns == ("c",)  # public field present
        assert "workspace_id" in result.metadata  # public-parity key
        assert result.metadata["cross_account"] == "true"  # additive
