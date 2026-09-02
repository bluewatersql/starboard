# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the reference-file (vector_backend="none") analytics context path.

build_analytics_context, with NO vector store injected, must:
- resolve domains (explicit param or extracted from the query) and load context
  from on-disk reference files, with no embedding call
- return the same token-efficient context handle contract downstream expects
- degrade to an empty context when no domain resolves / a file is missing
- re-point packaging: [vectorsearch] pins databricks-vectorsearch; sqlite-vec is
  not a default dependency
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starboard.tools.adapters.rag_tools import AnalyticsContextTools

# .../packages/starboard/tests/unit/tools/adapters/<file> -> parents[4] == starboard/
_PYPROJECT = Path(__file__).resolve().parents[4] / "pyproject.toml"


def _tools_with_handle() -> tuple[AnalyticsContextTools, MagicMock]:
    """AnalyticsContextTools on the reference-file path (no vector store)."""
    sql_tools = MagicMock()
    sql_tools.store_rag_context.return_value = "ctx_handle_ref"
    tools = AnalyticsContextTools(
        vector_store=None,
        embedding_provider=None,
        analytics_sql_tools=sql_tools,
    )
    return tools, sql_tools


class TestReferenceFilePath:
    @pytest.mark.asyncio
    async def test_explicit_domains_build_context_from_reference_files(self):
        tools, sql_tools = _tools_with_handle()

        result = await tools.build_analytics_context(
            user_query="Analyze DBU consumption trends",
            rag_resource_domains=["finops_billing"],
        )

        assert result["context_handle"] == "ctx_handle_ref"
        summary = result["summary"]
        # reference files for finops_billing carry tables/nuance/codebook/facets
        assert summary["tables_found"] > 0
        assert summary["nuance_found"] > 0
        assert summary["domains_searched"] == ["finops_billing"]

        # The stored context was sourced from reference files (populated).
        stored_ctx = sql_tools.store_rag_context.call_args.args[0]
        assert stored_ctx.tables
        assert all(t.domain == "finops_billing" for t in stored_ctx.tables)

    @pytest.mark.asyncio
    async def test_domains_resolved_from_query_tables(self):
        tools, _ = _tools_with_handle()

        result = await tools.build_analytics_context(
            user_query="Join system.billing.usage with system.billing.list_prices",
        )

        # finops_billing resolved from the referenced system tables
        assert result["summary"]["tables_found"] > 0
        assert "finops_billing" in result["summary"]["domains_searched"]

    @pytest.mark.asyncio
    async def test_no_embedding_call_on_reference_path(self):
        """The reference path never touches an embedding provider."""
        embedding = MagicMock()
        tools = AnalyticsContextTools(
            vector_store=None,
            embedding_provider=embedding,
            analytics_sql_tools=MagicMock(store_rag_context=MagicMock(return_value="h")),
        )

        await tools.build_analytics_context(
            user_query="costs",
            rag_resource_domains=["finops_billing"],
        )

        embedding.embed.assert_not_called()
        embedding.embed_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_domain_degrades_to_empty_context(self):
        tools, sql_tools = _tools_with_handle()

        result = await tools.build_analytics_context(
            user_query="something with no system tables at all",
            rag_resource_domains=["totally_unknown_domain"],
        )

        assert result["context_handle"] == "ctx_handle_ref"
        assert result["summary"]["tables_found"] == 0
        assert result["summary"]["nuance_found"] == 0

    @pytest.mark.asyncio
    async def test_no_domains_resolved_degrades_cleanly(self):
        tools, _ = _tools_with_handle()

        result = await tools.build_analytics_context(
            user_query="free text with no tables and no domains",
        )

        assert result["summary"]["tables_found"] == 0

    @pytest.mark.asyncio
    async def test_section_toggles_respected(self):
        tools, sql_tools = _tools_with_handle()

        await tools.build_analytics_context(
            user_query="costs",
            rag_resource_domains=["finops_billing"],
            include_tables=True,
            include_nuance=False,
            include_codebook=False,
            include_facets=False,
        )

        stored_ctx = sql_tools.store_rag_context.call_args.args[0]
        assert stored_ctx.tables
        assert stored_ctx.nuance == []


class TestPackagingExtras:
    def _extras(self) -> dict:
        data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        return data["project"]["optional-dependencies"]

    def test_vector_drivers_not_in_default_dependencies(self):
        # The vector/ANN stack was removed (reference-file RAG only); neither the
        # sqlite-vec nor the managed vector-search driver ships anywhere now.
        data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        default_deps = " ".join(data["project"]["dependencies"])
        assert "sqlite-vec" not in default_deps
        assert "databricks-vectorsearch" not in default_deps
        extras = self._extras()
        assert "vectorsearch" not in extras
        assert "sqlite" not in extras
