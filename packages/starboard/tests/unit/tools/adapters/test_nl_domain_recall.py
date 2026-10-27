# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for NL→domain recall: keyword-based domain resolution without system-table hints.

Covers:
- Unit tests of resolve_domains_from_nl_query (keyword map + resolver)
- Integration tests via AnalyticsContextTools.build_analytics_context (reference-file path)
  verifying that previously-empty NL queries now return bounded non-empty context.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starboard.infra.rag.domain_keywords import resolve_domains_from_nl_query
from starboard.tools.adapters.rag_tools import AnalyticsContextTools

# ---------------------------------------------------------------------------
# Unit tests: keyword resolver
# ---------------------------------------------------------------------------


class TestResolveDomainsFromNLQuery:
    """resolve_domains_from_nl_query: deterministic keyword→domain mapping."""

    def test_warehouse_slow_resolves_compute_warehouses(self):
        domains = resolve_domains_from_nl_query("why is my warehouse slow")
        assert "compute_warehouses" in domains

    def test_job_fail_resolves_workload_jobs(self):
        domains = resolve_domains_from_nl_query("why did my job fail")
        assert "workload_jobs" in domains

    def test_stale_resolves_storage_or_governance(self):
        domains = resolve_domains_from_nl_query("which tables are stale")
        assert any(
            d in domains for d in ("storage_optimization", "governance_unity_catalog")
        )

    def test_unrecognized_query_returns_empty(self):
        domains = resolve_domains_from_nl_query("free text with no tables and no domains")
        assert domains == []

    def test_empty_query_returns_empty(self):
        domains = resolve_domains_from_nl_query("")
        assert domains == []

    def test_max_domains_bounds_result(self):
        """Long queries with many matching keywords are bounded by max_domains."""
        long_query = (
            "job failed warehouse slow cost expensive cluster autoscale "
            "vacuum optimize storage audit lineage endpoint"
        )
        domains = resolve_domains_from_nl_query(long_query, max_domains=3)
        assert len(domains) <= 3

    def test_cost_resolves_finops_billing(self):
        domains = resolve_domains_from_nl_query("how much does this job cost")
        assert "finops_billing" in domains

    def test_cluster_autoscale_resolves_compute_clusters(self):
        domains = resolve_domains_from_nl_query("why is my cluster autoscaling")
        assert "compute_clusters" in domains

    def test_case_insensitive_matching(self):
        lower = resolve_domains_from_nl_query("warehouse slow")
        upper = resolve_domains_from_nl_query("WAREHOUSE SLOW")
        mixed = resolve_domains_from_nl_query("Warehouse Slow")
        assert lower == upper == mixed

    def test_returns_list(self):
        result = resolve_domains_from_nl_query("why is my warehouse slow")
        assert isinstance(result, list)

    def test_default_max_domains_is_bounded(self):
        """Default max_domains is small enough to avoid flooding the agent."""
        domains = resolve_domains_from_nl_query(
            "job failed warehouse slow cost expensive cluster autoscale "
            "vacuum optimize storage audit lineage endpoint"
        )
        assert len(domains) <= 5  # sanity cap; actual default is 3


# ---------------------------------------------------------------------------
# Integration tests: AnalyticsContextTools on the reference-file path
# ---------------------------------------------------------------------------


def _tools_no_vector_store() -> tuple[AnalyticsContextTools, MagicMock]:
    """AnalyticsContextTools on the reference-file path (no vector store)."""
    sql_tools = MagicMock()
    sql_tools.store_rag_context.return_value = "ctx_handle_nl"
    tools = AnalyticsContextTools(
        analytics_sql_tools=sql_tools,
    )
    return tools, sql_tools


class TestNLDomainRecallIntegration:
    """NL queries without system-table hints now return non-empty bounded context."""

    @pytest.mark.asyncio
    async def test_warehouse_slow_returns_nonempty_context(self):
        tools, sql_tools = _tools_no_vector_store()
        result = await tools.build_analytics_context(
            user_query="why is my warehouse slow",
        )
        assert result["summary"]["tables_found"] > 0, (
            "Expected non-empty context for warehouse NL query"
        )
        assert "compute_warehouses" in (result["summary"]["domains_searched"] or [])

    @pytest.mark.asyncio
    async def test_job_fail_returns_nonempty_context(self):
        tools, _ = _tools_no_vector_store()
        result = await tools.build_analytics_context(
            user_query="why did my job fail",
        )
        assert result["summary"]["tables_found"] > 0, (
            "Expected non-empty context for jobs NL query"
        )
        assert "workload_jobs" in (result["summary"]["domains_searched"] or [])

    @pytest.mark.asyncio
    async def test_stale_tables_returns_nonempty_context(self):
        tools, _ = _tools_no_vector_store()
        result = await tools.build_analytics_context(
            user_query="which tables are stale",
        )
        assert result["summary"]["tables_found"] > 0, (
            "Expected non-empty context for stale-tables NL query"
        )

    @pytest.mark.asyncio
    async def test_explicit_domains_override_nl_keywords(self):
        """Annotated queries: explicit rag_resource_domains still win over NL keywords."""
        tools, sql_tools = _tools_no_vector_store()
        result = await tools.build_analytics_context(
            user_query="why is my warehouse slow",
            rag_resource_domains=["finops_billing"],
        )
        # Only finops_billing was requested; NL-detected compute_warehouses is ignored
        assert result["summary"]["domains_searched"] == ["finops_billing"]
        stored_ctx = sql_tools.store_rag_context.call_args.args[0]
        assert all(t.domain == "finops_billing" for t in stored_ctx.tables)

    @pytest.mark.asyncio
    async def test_previously_empty_nl_query_now_returns_bounded_context(self):
        """Regression: queries that previously returned empty now return context via keyword map."""
        tools, _ = _tools_no_vector_store()
        # No system.*.* references — previously always returned empty RAGContext
        result = await tools.build_analytics_context(
            user_query="why did my job fail",
        )
        assert result["summary"]["tables_found"] > 0
        domains = result["summary"]["domains_searched"] or []
        # Bounded: keyword resolver caps at max_domains (default 3)
        assert len(domains) <= 5

    @pytest.mark.asyncio
    async def test_system_table_query_resolves_from_table_not_keywords(self):
        """System table references → table-mapping path (keyword matching not needed)."""
        tools, _ = _tools_no_vector_store()
        result = await tools.build_analytics_context(
            user_query="Join system.billing.usage with system.billing.list_prices",
        )
        domains = result["summary"]["domains_searched"] or []
        assert "finops_billing" in domains
        assert result["summary"]["tables_found"] > 0

    @pytest.mark.asyncio
    async def test_truly_free_text_still_returns_empty(self):
        """Queries with no recognizable keywords still degrade to empty context."""
        tools, _ = _tools_no_vector_store()
        result = await tools.build_analytics_context(
            user_query="free text with no tables and no domains",
        )
        assert result["summary"]["tables_found"] == 0
