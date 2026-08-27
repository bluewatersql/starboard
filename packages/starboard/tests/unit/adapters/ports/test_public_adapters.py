# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the four PUBLIC port adapters (Phase-2 C5).

Each public adapter wraps existing native code behind its kernel-tier Protocol.
No new capability is added — only the port surface. Internal adapters are
Phase 3 and do not ship here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starboard.adapters.ports import (
    AnalyticsSqlAdapter,
    NativeDiagnosticAdapter,
    SdkDbfsLogAdapter,
    SingleWorkspaceFleetAdapter,
)
from starboard_core.ports.diagnostic_backend import DiagnosticBackendPort
from starboard_core.ports.fleet_sql import FleetQuery, FleetSqlPort
from starboard_core.ports.log_retrieval import LogQuery, LogRetrievalPort
from starboard_core.ports.nl_query import NLQueryPort, WorkspaceCtx

_ADAPTER_DIR = (
    Path(__file__).parents[5] / "starboard" / "starboard" / "adapters" / "ports"
)

_FORBIDDEN_TOKENS = (
    "centralized_system_tables",
    "fin_live_gold",
    "hmr_stack_hash",
    "logfood",
    "clickhouse",
    "go/",
    "e2-demo-field-eng",
    "ask_genie",
    "dbr-doctor",
    "logs-summariser",
)


class _FakeDBFSClient:
    """Minimal DBFSClient double: one file with fixed content."""

    def __init__(self, path: str, content: bytes) -> None:
        self._path = path
        self._content = content

    def dbfs_path_exists(self, dbfs_path: str) -> bool:
        return dbfs_path in (self._path,) or self._path.startswith(dbfs_path)

    def list_dbfs_files(self, dbfs_path: str, recursive: bool = True):
        return [{"path": self._path, "is_dir": False, "file_size": len(self._content)}]

    def read_dbfs_chunk(self, dbfs_path: str, offset: int, length: int):
        if offset >= len(self._content):
            return None
        return self._content[offset : offset + length]


@pytest.mark.unit
class TestPublicAdaptersSatisfyProtocols:
    def test_sdk_dbfs_log_adapter_satisfies_port(self) -> None:
        assert isinstance(SdkDbfsLogAdapter(dbfs_client=_FakeDBFSClient("/x", b"")), LogRetrievalPort)

    def test_native_diagnostic_adapter_satisfies_port(self) -> None:
        assert isinstance(NativeDiagnosticAdapter(), DiagnosticBackendPort)

    def test_analytics_sql_adapter_satisfies_port(self) -> None:
        assert isinstance(AnalyticsSqlAdapter(generator=object()), NLQueryPort)

    def test_single_workspace_fleet_adapter_satisfies_port(self) -> None:
        async def _exec(sql, params):
            return {"columns": [], "rows": []}

        assert isinstance(SingleWorkspaceFleetAdapter(executor=_exec), FleetSqlPort)


@pytest.mark.unit
class TestSdkDbfsLogAdapter:
    async def test_fetch_returns_bundle_from_dbfs_client(self) -> None:
        content = b"line one\nERROR: boom\nline three\n"
        client = _FakeDBFSClient("/cluster-logs/eventlog.json", content)
        adapter = SdkDbfsLogAdapter(dbfs_client=client)

        bundle = await adapter.fetch(
            LogQuery(entity="driver", entity_id="c-1", paths=("/cluster-logs/eventlog.json",))
        )

        assert "ERROR: boom" in bundle.text
        assert bundle.source
        assert bundle.line_count > 0

    async def test_bundle_text_is_consumable_by_evidence_extractor(self) -> None:
        # Round-trip: LogRetrievalPort output feeds the diagnostic substrate.
        from starboard.tools.domain.diagnostic.evidence_extractor import (
            EvidenceWindowExtractor,
        )

        content = (
            b"2024-01-01 INFO starting\n"
            b"java.lang.OutOfMemoryError: Java heap space\n"
            b"\tat org.apache.spark.Foo(Foo.scala:42)\n"
        )
        adapter = SdkDbfsLogAdapter(dbfs_client=_FakeDBFSClient("/logs/app", content))
        bundle = await adapter.fetch(
            LogQuery(entity="driver", entity_id="c-1", paths=("/logs/app",))
        )

        result = EvidenceWindowExtractor().extract(bundle.text)
        assert result.window_count >= 1


@pytest.mark.unit
class TestNativeDiagnosticAdapter:
    def test_classify_produces_candidate(self) -> None:
        adapter = NativeDiagnosticAdapter()
        candidates = adapter.classify(
            "Traceback (most recent call last):\n  File 'x.py'\nValueError: bad\n"
        )
        assert candidates
        assert candidates[0].raw

    async def test_analyze_produces_diagnostic_result(self) -> None:
        adapter = NativeDiagnosticAdapter()
        pasted = (
            "java.lang.OutOfMemoryError: Java heap space\n"
            "\tat org.apache.spark.Foo(Foo.scala:42)\n"
        )
        candidates = adapter.classify(pasted)
        result = await adapter.analyze(candidates[0])
        assert result.summary is not None
        # evidence window ids surface for citation
        assert isinstance(result.evidence, tuple)


@pytest.mark.unit
class TestAnalyticsSqlAdapter:
    async def test_ask_delegates_to_generator(self) -> None:
        class _FakeGenerator:
            async def generate(self, user_query, intent_context, rag_context, previous_errors=None):
                return {
                    "success": True,
                    "sql": "SELECT 1",
                    "explanation": "trivial",
                }

        adapter = AnalyticsSqlAdapter(generator=_FakeGenerator())
        answer = await adapter.ask("how many jobs?", WorkspaceCtx(host="https://x"))
        assert answer.success is True
        assert answer.sql == "SELECT 1"
        assert answer.explanation == "trivial"


@pytest.mark.unit
class TestSingleWorkspaceFleetAdapter:
    async def test_execute_maps_rows(self) -> None:
        captured: dict = {}

        async def _exec(sql, params):
            captured["sql"] = sql
            return {"columns": ["workspace_id", "dbus"], "rows": [["w1", 10], ["w2", 20]]}

        adapter = SingleWorkspaceFleetAdapter(executor=_exec)
        result = await adapter.execute(
            FleetQuery(sql="SELECT * FROM system.billing.usage", workspace_id="w1")
        )
        assert result.columns == ("workspace_id", "dbus")
        assert result.row_count == 2
        assert result.rows[0] == ("w1", 10)
        # public path executes single-workspace system.* SQL verbatim
        assert "system.billing.usage" in captured["sql"]


@pytest.mark.unit
class TestPublicAdapterGovernance:
    def test_no_internal_namespaces_in_adapter_source(self) -> None:
        offenders: list[str] = []
        for path in _ADAPTER_DIR.glob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for token in _FORBIDDEN_TOKENS:
                if token in text:
                    offenders.append(f"{path.name}:{token}")
        assert not offenders, f"internal identifier leaked into adapters: {offenders}"
