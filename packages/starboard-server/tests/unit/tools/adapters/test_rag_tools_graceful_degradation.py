"""Tests for build_analytics_context graceful degradation.

When the embedding endpoint is unavailable (404, timeout, etc.), the tool
should return an empty RAGContext instead of propagating the error.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.tools.adapters.rag_tools import AnalyticsContextTools


def _make_tools(
    *,
    search_side_effect: Exception | None = None,
    search_return: MagicMock | None = None,
) -> AnalyticsContextTools:
    """Build an AnalyticsContextTools with mocked dependencies."""
    vector_store = MagicMock()

    if search_side_effect:
        vector_store.search_multi_collection = AsyncMock(
            side_effect=search_side_effect
        )
    elif search_return:
        vector_store.search_multi_collection = AsyncMock(
            return_value=search_return
        )
    else:
        mock_ctx = MagicMock()
        mock_ctx.tables = []
        mock_ctx.nuance = []
        mock_ctx.codebook = []
        mock_ctx.facets = []
        mock_ctx.learnings = []
        mock_ctx.model_dump.return_value = {"tables": [], "nuance": []}
        vector_store.search_multi_collection = AsyncMock(return_value=mock_ctx)

    embedding_provider = MagicMock()
    return AnalyticsContextTools(
        vector_store=vector_store,
        embedding_provider=embedding_provider,
    )


class TestBuildAnalyticsContextGracefulDegradation:
    """Embedding failures should not crash the analytics agent."""

    @pytest.mark.asyncio
    async def test_returns_empty_context_on_endpoint_not_found(self):
        import httpx
        from openai import NotFoundError

        error = NotFoundError(
            message="ENDPOINT_NOT_FOUND",
            response=httpx.Response(404, request=httpx.Request("POST", "http://test")),
            body={"error_code": "ENDPOINT_NOT_FOUND"},
        )
        tools = _make_tools(search_side_effect=error)

        result = await tools.build_analytics_context(
            user_query="Analyze costs for job 123",
            rag_resource_domains=["finops_billing"],
        )

        assert isinstance(result, dict)
        assert result.get("tables") == []
        assert result.get("nuance") == []

    @pytest.mark.asyncio
    async def test_returns_empty_context_on_connection_error(self):
        tools = _make_tools(
            search_side_effect=ConnectionError("Connection refused")
        )

        result = await tools.build_analytics_context(
            user_query="Analyze costs",
        )

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_returns_empty_context_on_timeout(self):

        tools = _make_tools(
            search_side_effect=TimeoutError("Embedding timed out")
        )

        result = await tools.build_analytics_context(
            user_query="Analyze costs",
        )

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_normal_path_still_works(self):
        """Verify the happy path is unaffected by the error handling."""
        mock_ctx = MagicMock()
        mock_ctx.tables = [MagicMock()]
        mock_ctx.nuance = [MagicMock(), MagicMock()]
        mock_ctx.codebook = []
        mock_ctx.facets = []
        mock_ctx.learnings = []
        mock_ctx.model_dump.return_value = {
            "tables": ["t1"],
            "nuance": ["n1", "n2"],
            "codebook": [],
            "facets": [],
            "learnings": [],
        }

        tools = _make_tools(search_return=mock_ctx)

        result = await tools.build_analytics_context(
            user_query="Show billing data",
        )

        assert isinstance(result, dict)
        tools.vector_store.search_multi_collection.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_analytics_sql_tools_returns_handle_on_error(self):
        """When analytics_sql_tools is set but embeddings fail, still returns."""
        import httpx
        from openai import NotFoundError

        error = NotFoundError(
            message="ENDPOINT_NOT_FOUND",
            response=httpx.Response(404, request=httpx.Request("POST", "http://test")),
            body={"error_code": "ENDPOINT_NOT_FOUND"},
        )

        vector_store = MagicMock()
        vector_store.search_multi_collection = AsyncMock(side_effect=error)

        analytics_sql_tools = MagicMock()
        analytics_sql_tools.store_rag_context.return_value = "ctx_handle_123"

        tools = AnalyticsContextTools(
            vector_store=vector_store,
            embedding_provider=MagicMock(),
            analytics_sql_tools=analytics_sql_tools,
        )

        result = await tools.build_analytics_context(
            user_query="Analyze costs",
        )

        assert result["context_handle"] == "ctx_handle_123"
        assert result["summary"]["tables_found"] == 0
        assert result["summary"]["nuance_found"] == 0
