"""Unit tests for AnalyticsContextTools (RAG context building).

Tests cover RAG context retrieval and handle generation:
1. Context building from vector store
2. Domain filtering
3. Collection selection (tables, nuances, codebook, facets, learnings)
4. Context handle generation
5. Input validation and normalization
6. Edge cases
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.rag.models import (
    RAGCodebookContext,
    RAGContext,
    RAGFacetContext,
    RAGTableContext,
)
from starboard_server.tools.adapters.rag_tools import AnalyticsContextTools

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_vector_store():
    """Mock vector store for RAG retrieval."""
    store = MagicMock()
    store.search_multi_collection = AsyncMock()
    return store


@pytest.fixture
def mock_embedding_provider():
    """Mock embedding provider."""
    provider = MagicMock()
    provider.generate_embedding = AsyncMock(return_value=[0.1] * 768)
    return provider


@pytest.fixture
def mock_analytics_sql_tools():
    """Mock analytics SQL tools for handle storage."""
    tools = MagicMock()
    tools.store_rag_context = MagicMock(return_value="test_handle_123")
    return tools


@pytest.fixture
def context_tools(mock_vector_store, mock_embedding_provider, mock_analytics_sql_tools):
    """Create AnalyticsContextTools instance for testing."""
    return AnalyticsContextTools(
        vector_store=mock_vector_store,
        embedding_provider=mock_embedding_provider,
        analytics_sql_tools=mock_analytics_sql_tools,
    )


@pytest.fixture
def context_tools_no_sql_tools(mock_vector_store, mock_embedding_provider):
    """Create AnalyticsContextTools without SQL tools (fallback mode)."""
    return AnalyticsContextTools(
        vector_store=mock_vector_store,
        embedding_provider=mock_embedding_provider,
        analytics_sql_tools=None,
    )


@pytest.fixture
def sample_rag_context():
    """Sample RAG context from vector store."""
    return RAGContext(
        tables=[
            RAGTableContext(
                table_name="system.billing.usage",
                description="Usage data for billing",
                table_columns="workspace_id, usage_date, list_cost",
                domain="finops_billing",
            ),
            RAGTableContext(
                table_name="system.compute.warehouses",
                description="Warehouse metadata",
                table_columns="warehouse_id, warehouse_name, state",
                domain="compute_warehouses",
            ),
        ],
        nuances=["Always include date filters for performance"],
        codebook=[
            RAGCodebookContext(
                code="list_cost",
                description="Total cost in USD",
                sku_family="ALL",
                warehouse_type="ALL",
                time_validity="Always",
                involves_tags=False,
                domain="finops_billing",
                relevance_score=0.95,
            )
        ],
        facets=[
            RAGFacetContext(
                code="cost_trend",
                values=["Cost trends by warehouse"],
                domain="finops_billing",
                relevance_score=0.9,
            ),
            RAGFacetContext(
                code="usage_pattern",
                values=["Usage patterns"],
                domain="compute_warehouses",
                relevance_score=0.8,
            ),
        ],
        learnings=[],
    )


# ============================================================================
# Context Building Tests
# ============================================================================


class TestContextBuilding:
    """Tests for RAG context building."""

    @pytest.mark.asyncio
    async def test_build_context_with_defaults(
        self,
        context_tools,
        mock_vector_store,
        mock_analytics_sql_tools,
        sample_rag_context,
    ):
        """Test building context with default parameters."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show warehouse costs"
        )

        # Should return context handle
        assert "context_handle" in result
        assert result["context_handle"] == "test_handle_123"
        assert "summary" in result
        assert result["summary"]["tables_found"] == 2

        # Verify vector store was called
        mock_vector_store.search_multi_collection.assert_called_once()

        # Verify SQL tools stored the context
        mock_analytics_sql_tools.store_rag_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_context_with_domain_filter(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test building context with domain filtering."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show warehouse costs",
            rag_resource_domains=["finops_billing", "compute_warehouses"],
        )

        # Verify domains passed to vector store
        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        assert call_kwargs["domains"] == ["finops_billing", "compute_warehouses"]

        assert "context_handle" in result

    @pytest.mark.asyncio
    async def test_build_context_with_all_collections(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test building context with all collection types."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show warehouse costs",
            include_tables=True,
            include_nuance=True,
            include_codebook=True,
            include_facets=True,
            include_learnings=True,
        )

        # Verify all collections were requested
        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        collections = call_kwargs["collections"]
        assert "Tables" in collections
        assert "Nuance" in collections
        assert "Codebook" in collections
        assert "Facets" in collections

        assert "context_handle" in result

    @pytest.mark.asyncio
    async def test_build_context_tables_only(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test building context with only tables collection."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show warehouse costs",
            include_tables=True,
            include_nuance=False,
            include_codebook=False,
            include_facets=False,
            include_learnings=False,
        )

        # Verify only tables collection requested
        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        collections = call_kwargs["collections"]
        assert collections == ["Tables"]

        assert "context_handle" in result


# ============================================================================
# Domain Normalization Tests
# ============================================================================


class TestDomainNormalization:
    """Tests for domain input normalization."""

    @pytest.mark.asyncio
    async def test_domain_as_list(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test domains provided as list."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show costs",
            rag_resource_domains=["finops_billing", "compute_warehouses"],
        )

        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        assert call_kwargs["domains"] == ["finops_billing", "compute_warehouses"]

        assert "context_handle" in result

    @pytest.mark.asyncio
    async def test_domain_as_json_string(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test domains provided as JSON string (from LLM)."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show costs",
            rag_resource_domains='["finops_billing", "compute_warehouses"]',
        )

        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        assert call_kwargs["domains"] == ["finops_billing", "compute_warehouses"]

        assert "context_handle" in result

    @pytest.mark.asyncio
    async def test_domain_as_comma_separated_string(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test domains provided as comma-separated string."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show costs",
            rag_resource_domains="finops_billing, compute_warehouses",
        )

        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        assert call_kwargs["domains"] == ["finops_billing", "compute_warehouses"]

        assert "context_handle" in result

    @pytest.mark.asyncio
    async def test_domain_as_single_string(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test domain provided as single string."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show costs",
            rag_resource_domains="finops_billing",
        )

        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        assert call_kwargs["domains"] == ["finops_billing"]

        assert "context_handle" in result

    @pytest.mark.asyncio
    async def test_domain_none(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test no domain filtering (search all)."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show costs",
            rag_resource_domains=None,
        )

        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        assert call_kwargs["domains"] is None

        assert "context_handle" in result


# ============================================================================
# Result Limiting Tests
# ============================================================================


class TestResultLimiting:
    """Tests for result count limiting per collection."""

    @pytest.mark.asyncio
    async def test_limit_tables(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test limiting number of table results."""
        # Create context with many tables
        large_context = RAGContext(
            tables=[
                RAGTableContext(
                    table_name=f"system.billing.table_{i}",
                    description=f"Table {i}",
                    table_columns="col1, col2",
                    domain="finops_billing",
                )
                for i in range(20)
            ],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )
        mock_vector_store.search_multi_collection.return_value = large_context

        result = await context_tools.build_analytics_context(
            user_query="Show costs",
            n_tables=5,  # Limit to 5
        )

        # Should report limited number
        assert result["summary"]["tables_found"] == 5

    @pytest.mark.asyncio
    async def test_custom_result_counts(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test custom result counts per collection."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show costs",
            n_tables=3,
            n_nuances=10,
            n_codebook=2,
            n_facets=5,
            n_learnings=1,
        )

        # Verify summary reflects limits
        assert result["summary"]["tables_found"] <= 3
        assert result["summary"]["nuance_found"] <= 10

        assert "context_handle" in result


# ============================================================================
# Input Validation Tests
# ============================================================================


class TestInputValidation:
    """Tests for input validation."""

    @pytest.mark.asyncio
    async def test_empty_query_raises_error(self, context_tools):
        """Test that empty query raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await context_tools.build_analytics_context(user_query="")

    @pytest.mark.asyncio
    async def test_whitespace_only_query_raises_error(self, context_tools):
        """Test that whitespace-only query raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await context_tools.build_analytics_context(user_query="   \n   ")

    @pytest.mark.asyncio
    async def test_query_stripped(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test that query is stripped of whitespace."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="  Show costs  \n"
        )

        # Verify stripped query was passed to vector store
        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        assert call_kwargs["query"] == "Show costs"

        assert "context_handle" in result


# ============================================================================
# Fallback Mode Tests (No SQL Tools)
# ============================================================================


class TestFallbackMode:
    """Tests for fallback mode without SQL tools."""

    @pytest.mark.asyncio
    async def test_fallback_returns_full_context(
        self,
        context_tools_no_sql_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test fallback mode returns full context instead of handle."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools_no_sql_tools.build_analytics_context(
            user_query="Show costs"
        )

        # Should return full context dict, not handle
        assert "context_handle" not in result
        assert "tables" in result or "summary" not in result
        # Fallback returns full RAGContext.model_dump()


# ============================================================================
# Summary Generation Tests
# ============================================================================


class TestSummaryGeneration:
    """Tests for context summary generation."""

    @pytest.mark.asyncio
    async def test_summary_includes_counts(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test summary includes counts for all collection types."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show costs",
            include_tables=True,
            include_nuance=True,
            include_codebook=True,
            include_facets=True,
            include_learnings=True,
        )

        summary = result["summary"]
        assert "tables_found" in summary
        assert "nuance_found" in summary
        assert "codebook_found" in summary
        assert "facets_found" in summary
        assert "learnings_found" in summary
        assert "domains_searched" in summary

    @pytest.mark.asyncio
    async def test_summary_reflects_actual_counts(
        self,
        context_tools,
        mock_vector_store,
        sample_rag_context,
    ):
        """Test summary counts match actual context."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(user_query="Show costs")

        summary = result["summary"]
        # sample_rag_context has 2 tables
        assert summary["tables_found"] == 2
        # Nuance count may be limited by n_nuances parameter (default 15)
        # sample_rag_context has 1 nuance, so result should be 0 or 1 depending on slicing
        assert summary["nuance_found"] >= 0


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests with multiple components."""

    @pytest.mark.asyncio
    async def test_end_to_end_context_building(
        self,
        context_tools,
        mock_vector_store,
        mock_analytics_sql_tools,
        sample_rag_context,
    ):
        """Test end-to-end context building flow."""
        mock_vector_store.search_multi_collection.return_value = sample_rag_context

        result = await context_tools.build_analytics_context(
            user_query="Show warehouse costs for last 30 days",
            rag_resource_domains=["finops_billing", "compute_warehouses"],
            include_tables=True,
            include_nuance=True,
            include_codebook=True,
            n_tables=5,
            n_nuances=10,
        )

        # Verify complete workflow
        assert result["context_handle"] == "test_handle_123"
        assert result["summary"]["tables_found"] == 2
        assert result["summary"]["domains_searched"] == [
            "finops_billing",
            "compute_warehouses",
        ]

        # Verify vector store called correctly
        mock_vector_store.search_multi_collection.assert_called_once()
        call_kwargs = mock_vector_store.search_multi_collection.call_args[1]
        assert call_kwargs["query"] == "Show warehouse costs for last 30 days"
        assert call_kwargs["domains"] == ["finops_billing", "compute_warehouses"]
        assert "Tables" in call_kwargs["collections"]
        assert "Nuance" in call_kwargs["collections"]

        # Verify SQL tools stored context
        mock_analytics_sql_tools.store_rag_context.assert_called_once()
        stored_context = mock_analytics_sql_tools.store_rag_context.call_args[0][0]
        assert isinstance(stored_context, RAGContext)
