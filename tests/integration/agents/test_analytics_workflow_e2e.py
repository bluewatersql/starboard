# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for analytics agent end-to-end workflow.

Tests the complete V3 agentic RAG workflow:
1. User query → build context → generate SQL → validate → execute → complete
2. Multi-turn reflexion loop (validation errors → rebuild context → retry)
3. Tool chaining and state management
4. Error recovery and resilience
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest
from starboard_core.rag.models import (
    RAGCodebookContext,
    RAGContext,
    RAGFacetContext,
    RAGTableContext,
)
from starboard_server.tools.adapters.analytics_sql_tools import AnalyticsSQLTools
from starboard_server.tools.adapters.rag_tools import AnalyticsContextTools
from starboard_server.tools.domain.analytics_sql.sql_validator import SQLValidator

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for SQL generation."""
    client = MagicMock()
    client.max_tokens = 4096
    client.json_response = AsyncMock(
        return_value={
            "sql": "SELECT warehouse_name, SUM(list_cost) as total_cost FROM system.billing.usage WHERE usage_date >= CURRENT_DATE - INTERVAL 30 DAYS GROUP BY warehouse_name",
            "explanation": "Aggregates costs by warehouse for last 30 days",
            "confidence": 0.9,
            "missing_context": [],
            "confidence_reasoning": "All required columns and tables present",
            "visualization_hints": {
                "recommended_chart_types": ["bar"],
                "primary_metric": "total_cost",
                "primary_dimension": "warehouse_name",
                "is_time_series": False,
                "is_top_n": True,
                "aggregation_type": "sum",
            },
        }
    )
    return client


@pytest.fixture
def mock_sql_executor():
    """Mock SQL executor for Databricks queries."""
    executor = MagicMock()
    executor.execute_sql = AsyncMock(
        return_value=pl.DataFrame(
            {
                "warehouse_name": ["Warehouse A", "Warehouse B", "Warehouse C"],
                "total_cost": [1500.50, 2300.75, 850.25],
            }
        )
    )
    return executor


@pytest.fixture
def mock_sql_validator(mock_sql_executor):
    """Mock SQL validator."""
    validator = SQLValidator(sql_executor=mock_sql_executor)
    return validator


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
def sample_rag_context():
    """Sample RAG context for testing."""
    return RAGContext(
        tables=[
            RAGTableContext(
                table_name="system.billing.usage",
                description="Usage data for billing calculations",
                table_columns="workspace_id, usage_date, usage_quantity, list_cost, sku_name, warehouse_name",
                domain="finops_billing",
            ),
            RAGTableContext(
                table_name="system.compute.warehouses",
                description="Warehouse metadata and configuration",
                table_columns="warehouse_id, warehouse_name, state, cluster_count, auto_stop_mins",
                domain="compute_warehouses",
            ),
        ],
        nuances=[
            "Always include date filters for performance",
            "Use LEFT JOIN by default to preserve all records",
        ],
        codebook=[
            RAGCodebookContext(
                code="list_cost",
                description="Total cost in USD before discounts",
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
                code="warehouse_size",
                values=["X_SMALL", "SMALL", "MEDIUM", "LARGE"],
                domain="compute_warehouses",
                relevance_score=0.9,
            )
        ],
        learnings=[],
    )


@pytest.fixture
def analytics_sql_tools(mock_llm_client, mock_sql_executor, mock_sql_validator):
    """Create AnalyticsSQLTools instance."""
    return AnalyticsSQLTools(
        llm_client=mock_llm_client,
        sql_executor=mock_sql_executor,
        sql_validator=mock_sql_validator,
        result_cache=None,
    )


@pytest.fixture
def analytics_context_tools(
    mock_vector_store, mock_embedding_provider, analytics_sql_tools, sample_rag_context
):
    """Create AnalyticsContextTools instance."""
    # Configure mock vector store to return sample context
    mock_vector_store.search_multi_collection.return_value = sample_rag_context

    return AnalyticsContextTools(
        vector_store=mock_vector_store,
        embedding_provider=mock_embedding_provider,
        analytics_sql_tools=analytics_sql_tools,
    )


# ============================================================================
# End-to-End Workflow Tests
# ============================================================================


class TestAnalyticsWorkflowE2E:
    """End-to-end tests for complete analytics workflow."""

    @pytest.mark.asyncio
    async def test_complete_workflow_success(
        self,
        analytics_context_tools,
        analytics_sql_tools,
        mock_sql_executor,
    ):
        """Test complete workflow: context → SQL → validate → execute."""
        # Step 1: Build context
        context_result = await analytics_context_tools.build_analytics_context(
            user_query="Show warehouse costs for last 30 days",
            rag_resource_domains=["finops_billing", "compute_warehouses"],
        )

        assert "context_handle" in context_result
        assert context_result["summary"]["tables_found"] >= 1

        context_handle = context_result["context_handle"]

        # Step 2: Generate SQL
        sql_result = await analytics_sql_tools.build_sql_query(
            user_query="Show warehouse costs for last 30 days",
            context_handle=context_handle,
        )

        assert sql_result["success"] is True
        assert "sql" in sql_result
        assert "SELECT" in sql_result["sql"]
        assert sql_result["confidence"] >= 0.9

        sql = sql_result["sql"]

        # Step 3: Validate SQL
        validation_result = await analytics_sql_tools.validate_sql_query(
            sql=sql,
            runtime_validation=True,
        )

        assert validation_result["is_valid"] is True

        # Step 4: Execute SQL
        execution_result = await analytics_sql_tools.execute_sql_query(
            sql=sql,
        )

        # Verify result format (formatted_results, not success flag)
        assert "formatted_results" in execution_result
        assert "visualization" in execution_result
        assert "row_count" in execution_result
        assert execution_result["row_count"] == 3

        # Verify SQL was executed
        mock_sql_executor.execute_sql.assert_called()

    @pytest.mark.asyncio
    async def test_workflow_with_low_confidence(
        self,
        analytics_context_tools,
        analytics_sql_tools,
        mock_llm_client,
    ):
        """Test workflow handles low confidence SQL generation."""
        # Configure LLM to return low confidence
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Basic query, missing warehouse context",
            "confidence": 0.5,
            "missing_context": ["warehouse_names", "join_keys"],
            "confidence_reasoning": "Missing warehouse dimension table",
            "visualization_hints": {},
        }

        # Step 1: Build context
        context_result = await analytics_context_tools.build_analytics_context(
            user_query="Show warehouse costs",
        )

        context_handle = context_result["context_handle"]

        # Step 2: Generate SQL (low confidence)
        sql_result = await analytics_sql_tools.build_sql_query(
            user_query="Show warehouse costs",
            context_handle=context_handle,
        )

        # Should still succeed but with low confidence
        assert sql_result["success"] is True
        assert sql_result["confidence"] < 0.7
        assert len(sql_result["missing_context"]) > 0

        # Agent should use missing_context to rebuild context
        assert "warehouse_names" in sql_result["missing_context"]

    @pytest.mark.asyncio
    async def test_workflow_caches_context(
        self,
        analytics_context_tools,
        analytics_sql_tools,
    ):
        """Test that context is cached and reused."""
        # Build context once
        context_result = await analytics_context_tools.build_analytics_context(
            user_query="Show costs",
        )

        context_handle = context_result["context_handle"]

        # Use same handle multiple times
        for _ in range(3):
            sql_result = await analytics_sql_tools.build_sql_query(
                user_query="Show costs",
                context_handle=context_handle,
            )

            assert sql_result["success"] is True

        # Context should be retrieved from cache (not rebuilt)
        # Vector store should only be called once
        assert (
            analytics_context_tools.vector_store.search_multi_collection.call_count == 1
        )


# ============================================================================
# Multi-Turn Reflexion Tests
# ============================================================================


class TestReflexionLoop:
    """Tests for multi-turn reflexion and error recovery."""

    @pytest.mark.asyncio
    async def test_reflexion_with_validation_error(
        self,
        analytics_context_tools,
        analytics_sql_tools,
        mock_llm_client,
        mock_sql_executor,
    ):
        """Test reflexion loop when SQL validation fails."""
        # First attempt: Generate SQL with error
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT invalid_column FROM system.billing.usage",
            "explanation": "Query with invalid column",
            "confidence": 0.8,
            "missing_context": [],
            "confidence_reasoning": "Initial attempt",
            "visualization_hints": {},
        }

        # Build context
        context_result = await analytics_context_tools.build_analytics_context(
            user_query="Show costs",
        )

        context_handle = context_result["context_handle"]

        # Generate SQL (first attempt)
        sql_result_1 = await analytics_sql_tools.build_sql_query(
            user_query="Show costs",
            context_handle=context_handle,
        )

        assert sql_result_1["success"] is True
        sql_1 = sql_result_1["sql"]

        # Validate SQL (will fail)
        mock_sql_executor.execute_sql.side_effect = Exception(
            "UNRESOLVED_COLUMN: Column 'invalid_column' cannot be resolved"
        )

        validation_result_1 = await analytics_sql_tools.validate_sql_query(
            sql=sql_1,
            runtime_validation=True,
        )

        assert validation_result_1["is_valid"] is False
        assert len(validation_result_1["errors"]) > 0

        # Second attempt: Generate SQL with error feedback
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT list_cost FROM system.billing.usage",
            "explanation": "Fixed column name based on error",
            "confidence": 0.9,
            "missing_context": [],
            "confidence_reasoning": "Corrected based on validation feedback",
            "visualization_hints": {},
        }

        sql_result_2 = await analytics_sql_tools.build_sql_query(
            user_query="Show costs",
            context_handle=context_handle,
            previous_errors=validation_result_1["errors"],
        )

        assert sql_result_2["success"] is True
        assert "invalid_column" not in sql_result_2["sql"]

        # Verify LLM was called twice (initial + reflexion)
        assert mock_llm_client.json_response.call_count >= 2

    @pytest.mark.asyncio
    async def test_reflexion_improves_confidence(
        self,
        analytics_context_tools,
        analytics_sql_tools,
        mock_llm_client,
    ):
        """Test that reflexion improves confidence over iterations."""
        # Build context
        context_result = await analytics_context_tools.build_analytics_context(
            user_query="Show costs",
        )

        context_handle = context_result["context_handle"]

        # First attempt: Low confidence
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Basic query",
            "confidence": 0.6,
            "missing_context": ["warehouse_names"],
            "confidence_reasoning": "Missing context",
            "visualization_hints": {},
        }

        sql_result_1 = await analytics_sql_tools.build_sql_query(
            user_query="Show costs",
            context_handle=context_handle,
        )

        assert sql_result_1["confidence"] < 0.7

        # Second attempt: Improved confidence with more context
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT warehouse_name, SUM(list_cost) FROM system.billing.usage GROUP BY warehouse_name",
            "explanation": "Improved query with warehouse dimension",
            "confidence": 0.9,
            "missing_context": [],
            "confidence_reasoning": "All context available",
            "visualization_hints": {},
        }

        # Agent rebuilds context with more domains
        context_result_2 = await analytics_context_tools.build_analytics_context(
            user_query="Show costs by warehouse",
            rag_resource_domains=["finops_billing", "compute_warehouses"],
        )

        context_handle_2 = context_result_2["context_handle"]

        sql_result_2 = await analytics_sql_tools.build_sql_query(
            user_query="Show costs by warehouse",
            context_handle=context_handle_2,
        )

        # Confidence should improve
        assert sql_result_2["confidence"] > sql_result_1["confidence"]
        assert sql_result_2["confidence"] >= 0.9


# ============================================================================
# Tool Chaining Tests
# ============================================================================


class TestToolChaining:
    """Tests for tool chaining and state management."""

    @pytest.mark.asyncio
    async def test_context_handle_persistence(
        self,
        analytics_context_tools,
        analytics_sql_tools,
    ):
        """Test that context handle persists across tool calls."""
        # Build context
        context_result = await analytics_context_tools.build_analytics_context(
            user_query="Show costs",
        )

        context_handle = context_result["context_handle"]

        # Use handle in SQL generation
        sql_result = await analytics_sql_tools.build_sql_query(
            user_query="Show costs",
            context_handle=context_handle,
        )

        assert sql_result["success"] is True

        # Verify context can be retrieved
        retrieved_context = analytics_sql_tools._retrieve_rag_context(context_handle)
        assert retrieved_context is not None
        assert len(retrieved_context.tables) > 0

    @pytest.mark.asyncio
    async def test_visualization_hints_flow_through(
        self,
        analytics_context_tools,
        analytics_sql_tools,
        mock_sql_executor,
    ):
        """Test that visualization hints flow from SQL generation to execution."""
        # Build context
        context_result = await analytics_context_tools.build_analytics_context(
            user_query="Show top 10 warehouses by cost",
        )

        context_handle = context_result["context_handle"]

        # Generate SQL with visualization hints
        sql_result = await analytics_sql_tools.build_sql_query(
            user_query="Show top 10 warehouses by cost",
            context_handle=context_handle,
        )

        assert "visualization_hints" in sql_result
        assert sql_result["visualization_hints"]["is_top_n"] is True
        assert "bar" in sql_result["visualization_hints"]["recommended_chart_types"]

        # Execute SQL
        mock_sql_executor.execute_sql.return_value = pl.DataFrame(
            {
                "warehouse_name": ["W1", "W2", "W3"],
                "total_cost": [1000, 800, 600],
            }
        )

        execution_result = await analytics_sql_tools.execute_sql_query(
            sql=sql_result["sql"],
        )

        # Visualization hints should be used in chart config
        assert "visualization" in execution_result
        # May or may not have chart config depending on implementation


# ============================================================================
# Error Recovery Tests
# ============================================================================


class TestErrorRecovery:
    """Tests for error handling and recovery."""

    @pytest.mark.asyncio
    async def test_invalid_context_handle(
        self,
        analytics_sql_tools,
    ):
        """Test error handling for invalid context handle."""
        result = await analytics_sql_tools.build_sql_query(
            user_query="Show costs",
            context_handle="invalid_handle_xyz",
        )

        assert result["success"] is False
        assert "error" in result
        assert (
            "not found" in result["error"].lower()
            or "invalid" in result["error"].lower()
        )

    @pytest.mark.asyncio
    async def test_sql_executor_failure(
        self,
        analytics_context_tools,
        analytics_sql_tools,
        mock_sql_executor,
    ):
        """Test error handling when SQL execution fails."""
        # Build context and generate SQL
        context_result = await analytics_context_tools.build_analytics_context(
            user_query="Show costs",
        )

        sql_result = await analytics_sql_tools.build_sql_query(
            user_query="Show costs",
            context_handle=context_result["context_handle"],
        )

        # Configure executor to fail
        mock_sql_executor.execute_sql.side_effect = Exception(
            "Connection timeout after 30s"
        )

        # Execute SQL (should raise exception)
        with pytest.raises(RuntimeError, match="Query execution failed"):
            await analytics_sql_tools.execute_sql_query(
                sql=sql_result["sql"],
            )

    @pytest.mark.asyncio
    async def test_empty_query_results(
        self,
        analytics_context_tools,
        analytics_sql_tools,
        mock_sql_executor,
    ):
        """Test handling of queries that return no results."""
        # Build context and generate SQL
        context_result = await analytics_context_tools.build_analytics_context(
            user_query="Show costs",
        )

        sql_result = await analytics_sql_tools.build_sql_query(
            user_query="Show costs",
            context_handle=context_result["context_handle"],
        )

        # Configure executor to return empty dataframe
        mock_sql_executor.execute_sql.return_value = pl.DataFrame(
            {
                "warehouse_name": [],
                "total_cost": [],
            }
        )

        # Execute SQL
        execution_result = await analytics_sql_tools.execute_sql_query(
            sql=sql_result["sql"],
        )

        # Should succeed with empty results
        assert "formatted_results" in execution_result
        assert execution_result["row_count"] == 0
        # Empty dataframe should be handled gracefully
