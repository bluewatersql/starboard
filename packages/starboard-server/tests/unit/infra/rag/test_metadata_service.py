# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MetadataExtractor async conversion."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from starboard_core.rag.models import AnalysisResult
from starboard_server.infra.rag.services.metadata_service import MetadataExtractor

# ---------------------------------------------------------------------------
# Helpers / Stubs
# ---------------------------------------------------------------------------


class _FakeDatabricksClient:
    """Synchronous stub for DatabricksClient protocol."""

    def __init__(
        self, table_rows: list[dict[str, Any]], column_rows: list[dict[str, Any]]
    ):
        self.table_rows = table_rows
        self.column_rows = column_rows
        self.calls: list[str] = []

    def execute_query(self, query: str) -> list[dict[str, Any]]:
        self.calls.append(query)
        # Distinguish table vs column queries by keyword
        if "information_schema.tables" in query:
            return self.table_rows
        if "information_schema.columns" in query:
            return self.column_rows
        # discovery-by-example query
        return []


def _make_query_analyzer() -> MagicMock:
    """Return a mock QueryAnalyzer that returns empty analysis."""
    analyzer = MagicMock()
    analyzer.analyze_queries.return_value = AnalysisResult(
        success_count=0,
        failed_count=0,
        join_summary=[],
        raw_joins=[],
        raw_predicates=[],
        raw_aggregations=[],
    )
    analyzer.get_column_predicates.return_value = []
    analyzer.get_column_aggregations.return_value = []
    analyzer.get_join_columns.return_value = []
    analyzer._table_matches.return_value = False
    return analyzer


_TABLE_ROWS: list[dict[str, Any]] = [
    {
        "table_catalog": "system",
        "table_schema": "billing",
        "table_name": "usage",
        "table_type": "TABLE",
        "comment": "Billing usage",
    },
    {
        "table_catalog": "system",
        "table_schema": "billing",
        "table_name": "list_prices",
        "table_type": "TABLE",
        "comment": None,
    },
]

_COLUMN_ROWS: list[dict[str, Any]] = [
    {
        "column_name": "usage_date",
        "data_type": "DATE",
        "is_nullable": "YES",
        "comment": "Date of usage",
    },
    {
        "column_name": "sku_name",
        "data_type": "STRING",
        "is_nullable": "NO",
        "comment": None,
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMetadataExtractorInit:
    """Tests for MetadataExtractor.__init__."""

    def test_default_max_workers(self) -> None:
        client = _FakeDatabricksClient([], [])
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer)
        assert extractor.max_workers == 5

    def test_explicit_max_workers(self) -> None:
        client = _FakeDatabricksClient([], [])
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer, max_workers=3)
        assert extractor.max_workers == 3

    def test_semaphore_matches_max_workers(self) -> None:
        client = _FakeDatabricksClient([], [])
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer, max_workers=4)
        # asyncio.Semaphore exposes _value for inspection
        assert extractor._semaphore._value == 4  # type: ignore[attr-defined]


class TestExtractTables:
    """Tests for MetadataExtractor.extract_tables (async)."""

    @pytest.mark.asyncio
    async def test_returns_tables_with_columns(self) -> None:
        client = _FakeDatabricksClient(_TABLE_ROWS, _COLUMN_ROWS)
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer, max_workers=2)

        tables = await extractor.extract_tables(schemas=["billing"], catalog="system")

        assert len(tables) == 2
        # Every table should have columns populated (same stub returns same cols)
        for table in tables:
            assert len(table.columns) == 2

    @pytest.mark.asyncio
    async def test_excluded_tables_are_skipped(self) -> None:
        client = _FakeDatabricksClient(_TABLE_ROWS, _COLUMN_ROWS)
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer)

        tables = await extractor.extract_tables(
            schemas=["billing"],
            catalog="system",
            excluded_tables=["system.billing.usage"],
        )

        names = [t.table_name for t in tables]
        assert "usage" not in names
        assert "list_prices" in names

    @pytest.mark.asyncio
    async def test_discovery_by_example_runs_once(self) -> None:
        """_discover_by_example is called exactly once across multiple extract calls."""
        client = _FakeDatabricksClient(_TABLE_ROWS, _COLUMN_ROWS)
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer)

        await extractor.extract_tables(schemas=["billing"])
        await extractor.extract_tables(schemas=["billing"])

        # analyze_queries should only have been called once
        assert analyzer.analyze_queries.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_schema_returns_empty_list(self) -> None:
        client = _FakeDatabricksClient([], [])
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer)

        tables = await extractor.extract_tables(schemas=["empty_schema"])
        assert tables == []

    @pytest.mark.asyncio
    async def test_table_fetch_failure_raises(self) -> None:
        """If the top-level table query fails, extract_tables re-raises."""

        class _ErrorClient:
            def execute_query(self, query: str) -> list[dict[str, Any]]:
                if "information_schema.tables" in query:
                    raise RuntimeError("connection refused")
                return []

        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(_ErrorClient(), analyzer)

        with pytest.raises(RuntimeError, match="connection refused"):
            await extractor.extract_tables(schemas=["billing"])


class TestExtractColumnsParallel:
    """Tests for _extract_columns_parallel graceful degradation."""

    @pytest.mark.asyncio
    async def test_column_failure_yields_empty_columns(self) -> None:
        """If column extraction fails for a table, that table gets empty columns."""

        class _FailingColumnClient:
            def execute_query(self, query: str) -> list[dict[str, Any]]:
                if "information_schema.tables" in query:
                    return _TABLE_ROWS
                # column query always fails
                raise RuntimeError("column fetch failed")

        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(_FailingColumnClient(), analyzer)

        tables = await extractor.extract_tables(schemas=["billing"])

        # Tables should still be returned, just with empty columns
        assert len(tables) == 2
        for table in tables:
            assert table.columns == []

    @pytest.mark.asyncio
    async def test_semaphore_bounds_concurrency(self) -> None:
        """Semaphore is acquired for each column fetch."""
        import asyncio

        _acquired: list[int] = []
        original_acquire = asyncio.Semaphore.acquire

        client = _FakeDatabricksClient(_TABLE_ROWS, _COLUMN_ROWS)
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer, max_workers=1)

        # Patch semaphore to track acquisitions
        acquire_count = 0

        real_sem = extractor._semaphore

        async def counting_acquire() -> None:
            nonlocal acquire_count
            acquire_count += 1
            await original_acquire(real_sem)

        extractor._semaphore.acquire = counting_acquire  # type: ignore[method-assign]

        await extractor.extract_tables(schemas=["billing"])
        # One acquisition per table (2 tables in _TABLE_ROWS)
        assert acquire_count == 2


class TestExtractColumns:
    """Tests for the async extract_columns method."""

    @pytest.mark.asyncio
    async def test_invalid_table_name_raises(self) -> None:
        client = _FakeDatabricksClient([], [])
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer)

        with pytest.raises(ValueError, match="Invalid table name format"):
            await extractor.extract_columns("bad_name")

    @pytest.mark.asyncio
    async def test_returns_column_metadata(self) -> None:
        client = _FakeDatabricksClient([], _COLUMN_ROWS)
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer)

        columns = await extractor.extract_columns("system.billing.usage")

        assert len(columns) == 2
        assert columns[0].column_name == "usage_date"
        assert columns[0].data_type == "DATE"
        assert columns[0].is_nullable is True
        assert columns[1].column_name == "sku_name"
        assert columns[1].is_nullable is False

    @pytest.mark.asyncio
    async def test_sdk_failure_re_raises(self) -> None:
        class _ErrorClient:
            def execute_query(self, query: str) -> list[dict[str, Any]]:
                raise OSError("network error")

        extractor = MetadataExtractor(_ErrorClient(), _make_query_analyzer())
        with pytest.raises(OSError, match="network error"):
            await extractor.extract_columns("system.billing.usage")


class TestDiscoverByExample:
    """Tests for _discover_by_example."""

    @pytest.mark.asyncio
    async def test_sets_analysis_result(self) -> None:
        client = _FakeDatabricksClient([], [])
        analyzer = _make_query_analyzer()
        extractor = MetadataExtractor(client, analyzer)

        assert extractor._analysis_result is None
        await extractor._discover_by_example()
        assert extractor._analysis_result is not None

    @pytest.mark.asyncio
    async def test_failure_sets_empty_analysis_result(self) -> None:
        """If the discovery query fails, an empty AnalysisResult is stored."""

        class _ErrorClient:
            def execute_query(self, query: str) -> list[dict[str, Any]]:
                raise RuntimeError("discovery failed")

        extractor = MetadataExtractor(_ErrorClient(), _make_query_analyzer())
        await extractor._discover_by_example()

        assert extractor._analysis_result is not None
        assert extractor._analysis_result.success_count == 0
        assert extractor._analysis_result.failed_count == 1


class TestNoThreadPoolExecutor:
    """Verify ThreadPoolExecutor is not imported or used."""

    def test_no_threadpoolexecutor_import(self) -> None:
        import importlib
        import importlib.util

        spec = importlib.util.find_spec(
            "starboard_server.infra.rag.services.metadata_service"
        )
        assert spec is not None
        assert spec.origin is not None

        with open(spec.origin) as f:
            source = f.read()

        assert "ThreadPoolExecutor" not in source, (
            "metadata_service.py must not use ThreadPoolExecutor"
        )
