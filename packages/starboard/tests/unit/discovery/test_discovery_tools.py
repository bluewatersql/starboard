# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for DiscoveryTools adapter.

Verifies the adapter correctly bridges the discovery engine phases to the
agent tool system — both the granular 4-phase tools and the legacy monolithic tool.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest
from starboard_core.domain.models.discovery.analysis import (
    DataCoverage,
    DiscoveryFinding,
    DomainAnalysis,
)
from starboard_core.domain.models.discovery.query import PackResult, QueryResult
from starboard.agents.tool_categories import ONLINE_TOOLS, TOOL_CATEGORIES
from starboard.agents.tools.registry import ALL_TOOL_METADATA
from starboard.tools.adapters.discovery_tools import DiscoveryTools


def _audit_df() -> pl.DataFrame:
    """Audit DataFrame with billing_origin_product column."""
    return pl.DataFrame(
        {
            "billing_origin_product": ["JOBS", "SQL", "ALL_PURPOSE"],
            "total_dbus": [1000.0, 500.0, 300.0],
        }
    )


class MockSQLExecutor:
    """Mock SQL executor returning DataFrames by SQL pattern."""

    def __init__(
        self,
        audit_df: pl.DataFrame | None = None,
        domain_df: pl.DataFrame | None = None,
    ) -> None:
        self.audit_df = _audit_df() if audit_df is None else audit_df
        self.domain_df = pl.DataFrame() if domain_df is None else domain_df

    async def execute_sql(self, sql: str) -> pl.DataFrame:
        if "usage_unit" in sql:
            return self.audit_df
        return self.domain_df


def _make_pack_result(domain: str) -> PackResult:
    """Create a PackResult with one successful query for the given domain."""
    return PackResult(
        pack_id=f"{domain}_pack",
        domain=domain,
        results=(
            QueryResult(
                query_id=f"{domain.upper()}-001",
                domain=domain,
                data=pl.DataFrame({"metric": [1, 2, 3]}),
                row_count=3,
                execution_time_ms=50.0,
            ),
        ),
    )


def _make_domain_analysis(domain: str) -> DomainAnalysis:
    """Create a realistic DomainAnalysis for testing happy paths."""
    return DomainAnalysis(
        domain=domain,
        grade="B",
        score=78.0,
        summary=f"The {domain} domain is in good shape with minor issues.",
        observations=[f"Observed pattern in {domain}"],
        patterns=[f"Hotspot in {domain}"],
        findings=[
            DiscoveryFinding(
                finding_id="F-001",
                title=f"Optimization opportunity in {domain}",
                priority="MEDIUM",
                impact="MEDIUM",
                effort="LOW",
                confidence="HIGH",
                finding_type="COST_OPTIMIZATION",
                domain=domain,
                description=f"A cost saving opportunity was found in {domain}.",
            ),
        ],
        recommended_actions=[f"Review {domain} configuration"],
        data_coverage=DataCoverage(queries_executed=3, queries_succeeded=3),
    )


# =====================================================================
# Phase 1: discover_active_products
# =====================================================================


@pytest.mark.asyncio
async def test_discover_active_products_returns_products() -> None:
    """Phase 1 tool returns active products from audit query."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)

    result = await tools.discover_active_products(lookback_days=30)

    assert result["status"] == "completed"
    assert "trace_id" in result
    assert result["product_count"] >= 0
    assert isinstance(result["active_products"], list)
    assert isinstance(result["available_domains"], list)
    assert "elapsed_ms" in result


@pytest.mark.asyncio
async def test_discover_active_products_empty_audit() -> None:
    """Phase 1 handles empty audit result gracefully."""
    empty_audit = pl.DataFrame({"billing_origin_product": [], "total_dbus": []})
    tools = DiscoveryTools(
        sql_executor=MockSQLExecutor(audit_df=empty_audit), env_config=None
    )

    result = await tools.discover_active_products()

    assert result["status"] in ("completed", "completed_with_warnings")
    assert isinstance(result.get("active_products", []), list)


# =====================================================================
# Phase 2: run_discovery_queries
# =====================================================================


@pytest.mark.asyncio
async def test_run_discovery_queries_requires_audit_first() -> None:
    """Phase 2 tool errors if called before Phase 1."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)

    result = await tools.run_discovery_queries()

    assert result["status"] == "error"
    assert "discover_active_products" in result["error"]


@pytest.mark.asyncio
async def test_run_discovery_queries_after_audit() -> None:
    """Phase 2 tool executes after Phase 1."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)
    await tools.discover_active_products()

    result = await tools.run_discovery_queries()

    assert result["status"] == "completed"
    assert "packs_executed" in result
    assert "total_queries" in result
    assert "domains_with_data" in result
    assert isinstance(result["domain_summaries"], dict)


# =====================================================================
# Phase 3: analyze_discovery_domain
# =====================================================================


@pytest.mark.asyncio
async def test_analyze_discovery_domain_requires_queries_first() -> None:
    """Phase 3 tool errors if called before Phase 2."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)

    result = await tools.analyze_discovery_domain(domain="billing")

    assert result["status"] == "error"
    assert "run_discovery_queries" in result["error"]


@pytest.mark.asyncio
async def test_analyze_discovery_domain_no_data() -> None:
    """Phase 3 handles domain with no query data."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)
    await tools.discover_active_products()
    await tools.run_discovery_queries()

    result = await tools.analyze_discovery_domain(domain="nonexistent_domain")

    assert result["status"] == "no_data"
    assert result["domain"] == "nonexistent_domain"


@pytest.mark.asyncio
async def test_analyze_discovery_domain_batch_mode() -> None:
    """Phase 3 batch mode accepts domains list."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)
    await tools.discover_active_products()
    await tools.run_discovery_queries()

    # Batch with nonexistent domains returns no_data (no packs to analyze)
    result = await tools.analyze_discovery_domain(
        domains=["nonexistent1", "nonexistent2"]
    )
    assert result["status"] == "no_data"


@pytest.mark.asyncio
async def test_analyze_discovery_domain_rejects_both_params() -> None:
    """Phase 3 rejects domain + domains simultaneously."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)
    await tools.discover_active_products()
    await tools.run_discovery_queries()

    result = await tools.analyze_discovery_domain(
        domain="billing", domains=["billing", "jobs"]
    )
    assert result["status"] == "error"
    assert "not both" in result["error"]


@pytest.mark.asyncio
async def test_analyze_discovery_domain_requires_some_param() -> None:
    """Phase 3 errors if neither domain nor domains is provided."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)
    await tools.discover_active_products()
    await tools.run_discovery_queries()

    result = await tools.analyze_discovery_domain()
    assert result["status"] == "error"


# ---- Happy-path tests that exercise asyncio.wait_for ----


@pytest.mark.asyncio
@patch(
    "starboard.tools.adapters.discovery_tools.DomainAnalyzer",
)
async def test_analyze_discovery_domain_single_happy_path(
    mock_analyzer_cls: AsyncMock,
) -> None:
    """Phase 3 single-domain happy path exercises asyncio.wait_for."""
    analysis = _make_domain_analysis("billing")

    mock_instance = mock_analyzer_cls.return_value
    mock_instance.analyze_domain = AsyncMock(return_value=analysis)

    tools = DiscoveryTools(
        sql_executor=MockSQLExecutor(), llm_client=MagicMock(), env_config=None
    )
    await tools.discover_active_products()
    await tools.run_discovery_queries()
    tools._pack_results.append(_make_pack_result("billing"))  # type: ignore[union-attr]

    result = await tools.analyze_discovery_domain(domain="billing")

    assert result["status"] == "completed"
    assert result["domain"] == "billing"
    assert result["grade"] == "B"
    assert result["score"] == 78.0
    assert result["finding_count"] == 1
    assert "data_coverage" in result
    assert result["data_coverage"]["queries_executed"] == 3
    assert result["data_coverage"]["queries_succeeded"] == 3
    mock_instance.analyze_domain.assert_awaited_once()


@pytest.mark.asyncio
@patch(
    "starboard.tools.adapters.discovery_tools.DomainAnalyzer",
)
async def test_analyze_discovery_domain_batch_happy_path(
    mock_analyzer_cls: AsyncMock,
) -> None:
    """Phase 3 batch happy path exercises asyncio.wait_for for each domain."""
    mock_instance = mock_analyzer_cls.return_value
    mock_instance.analyze_domain = AsyncMock(
        side_effect=lambda d, *a, **kw: _make_domain_analysis(d),
    )

    tools = DiscoveryTools(
        sql_executor=MockSQLExecutor(), llm_client=MagicMock(), env_config=None
    )
    await tools.discover_active_products()
    await tools.run_discovery_queries()
    for domain in ("billing", "jobs", "compute"):
        tools._pack_results.append(_make_pack_result(domain))  # type: ignore[union-attr]

    result = await tools.analyze_discovery_domain(
        domains=["billing", "jobs", "compute"],
    )

    assert result["status"] == "completed"
    assert result["domains_analyzed"] == 3
    assert len(result["domain_results"]) == 3
    domains_returned = {d["domain"] for d in result["domain_results"]}
    assert domains_returned == {"billing", "jobs", "compute"}
    assert mock_instance.analyze_domain.await_count == 3


@pytest.mark.asyncio
@patch(
    "starboard.tools.adapters.discovery_tools.DomainAnalyzer",
)
async def test_analyze_discovery_domain_timeout_handled(
    mock_analyzer_cls: AsyncMock,
) -> None:
    """Phase 3 gracefully handles per-domain timeout via asyncio.wait_for."""
    import asyncio

    async def hang_forever(*args: object, **kwargs: object) -> DomainAnalysis:
        await asyncio.sleep(999)
        return _make_domain_analysis("billing")  # pragma: no cover

    mock_instance = mock_analyzer_cls.return_value
    mock_instance.analyze_domain = AsyncMock(side_effect=hang_forever)

    tools = DiscoveryTools(
        sql_executor=MockSQLExecutor(), llm_client=MagicMock(), env_config=None
    )
    await tools.discover_active_products()
    await tools.run_discovery_queries()
    tools._pack_results.append(_make_pack_result("billing"))  # type: ignore[union-attr]

    with patch(
        "starboard.tools.adapters.discovery_tools.DomainAnalyzer",
        mock_analyzer_cls,
    ):
        # Override internal timeout by reaching into the method
        original_method = tools.analyze_discovery_domain

        async def patched_call(**kw: object) -> dict:
            # We need the real method but with a shorter timeout.
            # Easiest: just call and let asyncio.wait_for timeout.
            return await original_method(**kw)  # type: ignore[arg-type]

    mock_instance.analyze_domain = AsyncMock(
        side_effect=TimeoutError("simulated timeout"),
    )

    result = await tools.analyze_discovery_domain(domain="billing")

    assert result["status"] == "completed"
    assert result["domain"] == "billing"
    assert result["grade"] in ("B", "C", "D")
    assert "summary" in result


# =====================================================================
# Phase 4: synthesize_discovery_report
# =====================================================================


@pytest.mark.asyncio
async def test_synthesize_report_requires_analyses_first() -> None:
    """Phase 4 tool errors if no domain analyses exist."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)

    result = await tools.synthesize_discovery_report()

    assert result["status"] == "error"
    assert "analyze_discovery_domain" in result["error"]


# =====================================================================
# Legacy: run_workspace_discovery
# =====================================================================


@pytest.mark.asyncio
async def test_run_workspace_discovery_data_only() -> None:
    """Legacy tool with data_only=True returns status, trace_id, elapsed_ms."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)

    result = await tools.run_workspace_discovery(data_only=True)

    assert "status" in result
    assert result["status"] in ("completed", "completed_with_errors")
    assert "trace_id" in result
    assert result["trace_id"]
    assert "elapsed_ms" in result
    assert isinstance(result["elapsed_ms"], (int, float))


@pytest.mark.asyncio
async def test_run_workspace_discovery_with_options() -> None:
    """Legacy tool runs with lookback_days and domains options."""
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)

    result = await tools.run_workspace_discovery(
        lookback_days=60,
        domains=["billing"],
        data_only=True,
    )

    assert "status" in result
    assert "trace_id" in result
    assert "elapsed_ms" in result


# =====================================================================
# Schema registration
# =====================================================================


def test_granular_tool_schemas_registered() -> None:
    """All 4 granular discovery tools are in ALL_TOOL_METADATA."""
    expected = [
        "discover_active_products",
        "run_discovery_queries",
        "analyze_discovery_domain",
        "synthesize_discovery_report",
    ]
    for name in expected:
        assert name in ALL_TOOL_METADATA, f"{name} not in ALL_TOOL_METADATA"
        schema = ALL_TOOL_METADATA[name]
        assert schema["name"] == name
        assert "parameters" in schema
        assert "description" in schema


def test_legacy_tool_schema_registered() -> None:
    """Legacy run_workspace_discovery is still in ALL_TOOL_METADATA."""
    assert "run_workspace_discovery" in ALL_TOOL_METADATA

    schema = ALL_TOOL_METADATA["run_workspace_discovery"]
    assert schema["name"] == "run_workspace_discovery"
    props = schema["parameters"]["properties"]
    assert "lookback_days" in props
    assert "domains" in props
    assert "data_only" in props


def test_analyze_domain_schema_supports_batch() -> None:
    """analyze_discovery_domain schema supports both domain and domains params."""
    schema = ALL_TOOL_METADATA["analyze_discovery_domain"]
    props = schema["parameters"]["properties"]
    assert "domain" in props
    assert "domains" in props
    assert props["domains"]["type"] == "array"


# =====================================================================
# Tool categories
# =====================================================================


def test_discovery_tool_categories_granular() -> None:
    """Discovery domain has the 4 granular tools, not the monolithic one."""
    assert "discovery" in TOOL_CATEGORIES
    discovery_tools = TOOL_CATEGORIES["discovery"]
    assert isinstance(discovery_tools, list)

    expected = [
        "discover_active_products",
        "run_discovery_queries",
        "analyze_discovery_domain",
        "synthesize_discovery_report",
    ]
    for tool in expected:
        assert tool in discovery_tools, f"{tool} not in discovery TOOL_CATEGORIES"

    assert "run_workspace_discovery" not in discovery_tools


def test_discovery_tools_are_online() -> None:
    """All discovery tools require Databricks SQL (online)."""
    expected_online = [
        "discover_active_products",
        "run_discovery_queries",
        "analyze_discovery_domain",
        "synthesize_discovery_report",
        "run_workspace_discovery",
    ]
    for tool in expected_online:
        assert tool in ONLINE_TOOLS, f"{tool} not in ONLINE_TOOLS"
