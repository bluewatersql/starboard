# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Kernel-tier tests for the four internal-data-enablement ports (Phase-2 C5).

The ports (``LogRetrievalPort``, ``DiagnosticBackendPort``, ``NLQueryPort``,
``FleetSqlPort``) are typing-only Protocols that live alongside
``state_store.py`` in the SDK-free kernel. These tests prove:

- the port modules import with ``databricks-sdk`` absent (kernel boundary),
- the Protocols are structurally satisfiable (PEP 544),
- no internal namespace leaks into the shipped port surface (governance §7).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[3]

# Meta-path finder that simulates an environment with ``databricks-sdk`` absent.
_BLOCK_DATABRICKS = """
import sys
import importlib.abc


class _Blocker(importlib.abc.MetaPathFinder):
    def __init__(self, prefix):
        self._prefix = prefix

    def find_spec(self, name, path, target=None):
        if name == self._prefix or name.startswith(self._prefix + "."):
            raise ImportError(f"simulated-absent: {name}")
        return None


sys.meta_path.insert(0, _Blocker("databricks"))
"""

_PORT_MODULES = (
    "starboard_core.ports.log_retrieval",
    "starboard_core.ports.diagnostic_backend",
    "starboard_core.ports.nl_query",
    "starboard_core.ports.fleet_sql",
)

# Internal namespaces / identifiers that must never appear in the public port
# surface (UNIFIED_PLAN §7 red-lines).
_FORBIDDEN_TOKENS = (
    "centralized_system_tables",
    "fin_live_gold",
    "hmr_stack_hash",
    "eng_dp_debug_tools",
    "logfood",
    "clickhouse",
    "go/",
    "e2-demo-field-eng",
)


def _run_isolated(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_DATABRICKS + body],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


@pytest.mark.unit
class TestPortsImportWithoutSDK:
    def test_all_ports_import_without_databricks_sdk(self) -> None:
        body = f"""
import importlib
import sys

for mod in {list(_PORT_MODULES)!r}:
    importlib.import_module(mod)

assert "databricks" not in sys.modules, sorted(
    m for m in sys.modules if m.startswith("databricks")
)
print("OK")
"""
        proc = _run_isolated(body)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout


@pytest.mark.unit
class TestPortsAreStructural:
    def test_log_retrieval_protocol_is_structural(self) -> None:
        from starboard_core.ports.log_retrieval import (
            LogBundle,
            LogQuery,
            LogRetrievalPort,
        )

        class _Impl:
            async def fetch(self, ref: LogQuery) -> LogBundle:
                return LogBundle(text="", source="test")

        assert isinstance(_Impl(), LogRetrievalPort)

    def test_diagnostic_backend_protocol_is_structural(self) -> None:
        from starboard_core.ports.diagnostic_backend import (
            Candidate,
            DiagnosticBackendPort,
            DiagnosticResult,
        )

        class _Impl:
            def classify(self, pasted: str) -> list[Candidate]:
                return []

            async def analyze(self, candidate: Candidate) -> DiagnosticResult:
                return DiagnosticResult(summary="")

        assert isinstance(_Impl(), DiagnosticBackendPort)

    def test_nl_query_protocol_is_structural(self) -> None:
        from starboard_core.ports.nl_query import NLAnswer, NLQueryPort, WorkspaceCtx

        class _Impl:
            async def ask(self, question: str, ctx: WorkspaceCtx) -> NLAnswer:
                return NLAnswer(success=True)

        assert isinstance(_Impl(), NLQueryPort)

    def test_fleet_sql_protocol_is_structural(self) -> None:
        from starboard_core.ports.fleet_sql import FleetQuery, FleetResult, FleetSqlPort

        class _Impl:
            async def execute(self, query: FleetQuery) -> FleetResult:
                return FleetResult(columns=(), rows=())

        assert isinstance(_Impl(), FleetSqlPort)

    def test_ports_exported_from_package(self) -> None:
        from starboard_core import ports

        for name in (
            "LogRetrievalPort",
            "DiagnosticBackendPort",
            "NLQueryPort",
            "FleetSqlPort",
        ):
            assert hasattr(ports, name), name


@pytest.mark.unit
class TestPortDTOs:
    def test_log_query_and_bundle_construct(self) -> None:
        from starboard_core.ports.log_retrieval import LogBundle, LogQuery

        q = LogQuery(entity="driver", entity_id="c-123", paths=("dbfs:/a",))
        assert q.time_window_hours == 2.0
        b = LogBundle(text="line1\nline2", source="sdk-dbfs", line_count=2)
        assert b.line_count == 2

    def test_fleet_result_defaults(self) -> None:
        from starboard_core.ports.fleet_sql import FleetResult

        r = FleetResult(columns=("a",), rows=((1,),))
        assert r.columns == ("a",)


@pytest.mark.unit
class TestPortGovernance:
    def test_no_internal_namespaces_in_port_source(self) -> None:
        ports_dir = _CORE_DIR / "starboard_core" / "ports"
        offenders: list[str] = []
        for name in (
            "log_retrieval.py",
            "diagnostic_backend.py",
            "nl_query.py",
            "fleet_sql.py",
        ):
            text = (ports_dir / name).read_text(encoding="utf-8").lower()
            for token in _FORBIDDEN_TOKENS:
                if token in text:
                    offenders.append(f"{name}:{token}")
        assert not offenders, f"internal namespace leaked into ports: {offenders}"
