# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for MCP composite tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from starboard_server.mcp.composite_tools import (
    CompositeResult,
    get_job_summary,
    get_query_analysis,
    get_table_profile,
    get_workspace_overview,
)


def _make_executor(**overrides: Any) -> AsyncMock:
    """Create a mock tool executor with configurable per-tool results."""
    defaults: dict[str, Any] = {
        "resolve_job": {"job_id": "123", "name": "etl-job"},
        "get_job_config": {"cluster_id": "abc", "schedule": "daily"},
        "resolve_query": {
            "sql_text": "SELECT 1",
            "statement_id": "stmt-1",
        },
        "get_query_runtime_metrics": {"duration_ms": 500, "rows": 100},
        "analyze_query_plan": {"plan": "scan", "recommendations": []},
        "get_table_metadata": {"columns": 5, "format": "delta"},
        "get_table_history": {"operations": ["WRITE", "OPTIMIZE"]},
        "list_clusters": {"clusters": [{"id": "c1"}]},
        "get_warehouse_portfolio": {"warehouses": [{"id": "w1"}]},
    }
    defaults.update(overrides)

    async def _executor(tool_name: str, **kwargs: Any) -> dict[str, Any]:
        if tool_name in defaults:
            val = defaults[tool_name]
            if isinstance(val, Exception):
                raise val
            return val
        raise RuntimeError(f"Unknown tool: {tool_name}")

    return AsyncMock(side_effect=_executor)


class TestCompositeResult:
    """Tests for CompositeResult data class."""

    def test_status_success(self) -> None:
        r = CompositeResult(data={"a": 1}, errors=[])
        assert r.status == "success"

    def test_status_partial(self) -> None:
        r = CompositeResult(data={"a": 1}, errors=["oops"], partial=True)
        assert r.status == "partial"

    def test_status_error(self) -> None:
        r = CompositeResult(data={}, errors=["fatal"])
        assert r.status == "error"

    def test_is_frozen(self) -> None:
        r = CompositeResult(data={"a": 1})
        with pytest.raises(AttributeError):
            r.partial = True  # type: ignore[misc]


class TestGetJobSummary:
    """Tests for get_job_summary composite."""

    @pytest.mark.asyncio()
    async def test_happy_path(self) -> None:
        executor = _make_executor()
        result = await get_job_summary(executor, target="etl-job")
        assert result.status == "success"
        assert "job" in result.data
        assert "config" in result.data

    @pytest.mark.asyncio()
    async def test_resolve_fails(self) -> None:
        executor = _make_executor(resolve_job=RuntimeError("not found"))
        result = await get_job_summary(executor, target="bad")
        assert result.status == "error"
        assert "resolve_job" in result.errors[0]

    @pytest.mark.asyncio()
    async def test_config_fails(self) -> None:
        executor = _make_executor(get_job_config=RuntimeError("timeout"))
        result = await get_job_summary(executor, target="etl-job")
        assert result.status == "partial"
        assert "job" in result.data
        assert "config" not in result.data
        assert len(result.errors) == 1


class TestGetQueryAnalysis:
    """Tests for get_query_analysis composite."""

    @pytest.mark.asyncio()
    async def test_happy_path(self) -> None:
        executor = _make_executor()
        result = await get_query_analysis(executor, target="SELECT 1")
        assert result.status == "success"
        assert "query" in result.data
        assert "metrics" in result.data
        assert "plan_analysis" in result.data

    @pytest.mark.asyncio()
    async def test_resolve_fails(self) -> None:
        executor = _make_executor(resolve_query=RuntimeError("bad sql"))
        result = await get_query_analysis(executor, target="bad")
        assert result.status == "error"

    @pytest.mark.asyncio()
    async def test_metrics_fail_plan_succeed(self) -> None:
        executor = _make_executor(get_query_runtime_metrics=RuntimeError("timeout"))
        result = await get_query_analysis(executor, target="SELECT 1")
        assert result.status == "partial"
        assert "plan_analysis" in result.data
        assert "metrics" not in result.data


class TestGetTableProfile:
    """Tests for get_table_profile composite."""

    @pytest.mark.asyncio()
    async def test_happy_path(self) -> None:
        executor = _make_executor()
        result = await get_table_profile(executor, table="cat.sch.tbl")
        assert result.status == "success"
        assert "metadata" in result.data
        assert "recent_history" in result.data

    @pytest.mark.asyncio()
    async def test_history_fails(self) -> None:
        executor = _make_executor(get_table_history=RuntimeError("timeout"))
        result = await get_table_profile(executor, table="cat.sch.tbl")
        assert result.status == "partial"
        assert "metadata" in result.data
        assert "recent_history" not in result.data


class TestGetWorkspaceOverview:
    """Tests for get_workspace_overview composite."""

    @pytest.mark.asyncio()
    async def test_happy_path(self) -> None:
        executor = _make_executor()
        result = await get_workspace_overview(executor)
        assert result.status == "success"
        assert "clusters" in result.data
        assert "warehouses" in result.data

    @pytest.mark.asyncio()
    async def test_clusters_fail(self) -> None:
        executor = _make_executor(list_clusters=RuntimeError("timeout"))
        result = await get_workspace_overview(executor)
        assert result.status == "partial"
        assert "warehouses" in result.data
        assert "clusters" not in result.data

    @pytest.mark.asyncio()
    async def test_both_fail(self) -> None:
        executor = _make_executor(
            list_clusters=RuntimeError("err1"),
            get_warehouse_portfolio=RuntimeError("err2"),
        )
        result = await get_workspace_overview(executor)
        assert result.status == "error"
        assert len(result.errors) == 2
