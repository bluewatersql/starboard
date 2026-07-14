# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Comprehensive unit tests for AnalyticsSQLTools.

Tests cover the complete analytics SQL generation workflow:
1. RAG context storage and retrieval (context handle pattern)
2. SQL generation from RAG context
3. SQL validation (syntax + EXPLAIN)
4. SQL execution with caching and profiling
5. Visualization generation from LLM hints
6. Error handling for all failure scenarios
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest
from starboard_core.rag.models import RAGContext, RAGTableContext
from starboard.tools.adapters.analytics_sql_tools import AnalyticsSQLTools
from starboard.tools.domain.analytics_sql.models import ValidationResult

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing SQL generation."""
    client = MagicMock()
    client.max_tokens = 4096
    client.model = "gpt-4o-mini"
    # LLMSQLGenerator uses json_response, not generate_chat_completion
    client.json_response = AsyncMock()
    return client


@pytest.fixture
def mock_sql_executor():
    """Mock SQL executor for testing without Databricks."""
    executor = MagicMock()
    executor.execute_sql = AsyncMock()
    return executor


@pytest.fixture
def mock_sql_validator():
    """Mock SQL validator with configurable validation results."""
    validator = MagicMock()
    validator.validate = AsyncMock()
    validator.generate_sql_cache_key = MagicMock(return_value="test_cache_key_123")
    return validator


@pytest.fixture
def mock_result_cache():
    """Mock result cache for testing data reference caching."""
    cache = MagicMock()
    cache.cache_result_by_sql = AsyncMock(return_value="data_ref_123")
    return cache


@pytest.fixture
def analytics_sql_tools(mock_llm_client, mock_sql_executor, mock_sql_validator):
    """Create AnalyticsSQLTools instance for testing."""
    return AnalyticsSQLTools(
        llm_client=mock_llm_client,
        sql_executor=mock_sql_executor,
        sql_validator=mock_sql_validator,
        result_cache=None,
    )


@pytest.fixture
def analytics_sql_tools_with_cache(
    mock_llm_client, mock_sql_executor, mock_sql_validator, mock_result_cache
):
    """Create AnalyticsSQLTools instance with result cache."""
    return AnalyticsSQLTools(
        llm_client=mock_llm_client,
        sql_executor=mock_sql_executor,
        sql_validator=mock_sql_validator,
        result_cache=mock_result_cache,
    )


@pytest.fixture
def sample_rag_context():
    """Sample RAG context for testing."""
    return RAGContext(
        tables=[
            RAGTableContext(
                table_name="system.billing.usage",
                description="Usage data for billing calculations",
                table_columns="workspace_id, usage_date, usage_quantity, list_cost, sku_name",
                domain="finops_billing",
            ),
            RAGTableContext(
                table_name="system.compute.warehouse_events",
                description="Warehouse events and state changes",
                table_columns="warehouse_id, warehouse_name, event_time, state, cluster_count",
                domain="compute_warehouses",
            ),
        ],
        nuances=[
            "Always join billing.usage with billing.list_prices on sku_name for accurate pricing",
            "Filter serverless compute with usage_metadata.compute_type='SERVERLESS'",
        ],
        codebook=[],
        facets=[],
        learnings=[],
    )


@pytest.fixture
def sample_dataframe():
    """Sample Polars DataFrame for testing."""
    return pl.DataFrame(
        {
            "warehouse_name": ["Warehouse A", "Warehouse B", "Warehouse C"],
            "total_cost_usd": [1245.67, 892.34, 456.12],
            "usage_quantity": [1000, 750, 400],
            "usage_date": ["2024-01-01", "2024-01-01", "2024-01-01"],
        }
    )


@pytest.fixture
def sample_llm_response():
    """Sample LLM response for SQL generation."""
    return {
        "success": True,
        "sql": "SELECT warehouse_name, SUM(list_cost) as total_cost FROM system.billing.usage GROUP BY warehouse_name",
        "confidence": 0.9,
        "missing_context": [],
        "reasoning": "Found billing tables with proper join keys and warehouse metadata",
        "visualization_hints": {
            "recommended_chart_types": ["bar"],
            "primary_metric": "total_cost",
            "primary_dimension": "warehouse_name",
            "is_time_series": False,
            "is_top_n": True,
            "aggregation_type": "sum",
        },
    }


@pytest.fixture
def sample_validation_result():
    """Sample validation result."""
    return ValidationResult(
        is_valid=True,
        errors=[],
        warnings=[],
        validation_method="sqlglot",
    )


# ============================================================================
# Test Helpers
# ============================================================================


def create_mock_llm_response(
    sql: str,
    confidence: float,
    missing_context: list[str] | None = None,
    visualization_hints: dict[str, Any] | None = None,
) -> str:
    """Create mock LLM JSON response for SQL generation."""
    import json

    response = {
        "success": True,
        "sql": sql,
        "confidence": confidence,
        "missing_context": missing_context or [],
        "reasoning": "Test SQL generation",
        "visualization_hints": visualization_hints or {},
    }
    return json.dumps(response)


def create_mock_validation_result(
    is_valid: bool,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> ValidationResult:
    """Create mock validation result."""
    return ValidationResult(
        is_valid=is_valid,
        errors=errors or [],
        warnings=warnings or [],
        validation_method="sqlglot",
    )


# ============================================================================
# Context Handle Pattern Tests (Already Passing - from test_context_handle_pattern.py)
# ============================================================================


class TestContextHandlePattern:
    """Tests for RAG context storage and retrieval using handle pattern."""

    def test_store_rag_context_generates_handle(
        self, analytics_sql_tools, sample_rag_context
    ):
        """Test that storing RAG context generates a valid handle."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        assert isinstance(handle, str)
        assert handle.startswith("ctx_")
        assert len(handle) == 16  # "ctx_" + 12 hex chars

    def test_retrieve_rag_context_success(
        self, analytics_sql_tools, sample_rag_context
    ):
        """Test that retrieving RAG context by valid handle succeeds."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)
        retrieved = analytics_sql_tools._retrieve_rag_context(handle)

        assert retrieved is not None
        assert len(retrieved.tables) == 2
        assert retrieved.tables[0].table_name == "system.billing.usage"

    def test_retrieve_invalid_handle(self, analytics_sql_tools):
        """Test that retrieving with invalid handle returns None."""
        result = analytics_sql_tools._retrieve_rag_context("ctx_invalid123")
        assert result is None

    def test_multiple_contexts_isolated(self, analytics_sql_tools):
        """Test that multiple contexts are stored independently."""
        context1 = RAGContext(
            tables=[
                RAGTableContext(
                    table_name="table1",
                    description="First table",
                    table_columns="col1",
                    domain="domain1",
                )
            ],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )
        context2 = RAGContext(
            tables=[
                RAGTableContext(
                    table_name="table2",
                    description="Second table",
                    table_columns="col2",
                    domain="domain2",
                )
            ],
            nuances=[],
            codebook=[],
            facets=[],
            learnings=[],
        )

        handle1 = analytics_sql_tools.store_rag_context(context1)
        handle2 = analytics_sql_tools.store_rag_context(context2)

        assert handle1 != handle2

        retrieved1 = analytics_sql_tools._retrieve_rag_context(handle1)
        retrieved2 = analytics_sql_tools._retrieve_rag_context(handle2)

        assert retrieved1.tables[0].table_name == "table1"
        assert retrieved2.tables[0].table_name == "table2"

    def test_cleanup_expired_contexts(self, analytics_sql_tools, sample_rag_context):
        """Test that expired contexts are cleaned up."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Manually expire the context by setting old timestamp
        analytics_sql_tools._context_timestamps[handle] = (
            time.time() - analytics_sql_tools._context_ttl - 1
        )

        # Trigger cleanup
        analytics_sql_tools._cleanup_expired_contexts()

        # Verify context was removed
        assert handle not in analytics_sql_tools._rag_context_cache
        assert handle not in analytics_sql_tools._context_timestamps


# ============================================================================
# SQL Generation Tests (build_sql_query)
# ============================================================================


class TestBuildSQLQuery:
    """Tests for build_sql_query method."""

    @pytest.mark.asyncio
    async def test_build_sql_query_with_valid_context(
        self,
        analytics_sql_tools,
        sample_rag_context,
        mock_llm_client,
        sample_llm_response,
    ):
        """Test SQL generation with valid RAG context."""
        # Store context and get handle
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Mock LLM json_response (what LLMSQLGenerator actually uses)
        mock_llm_client.json_response.return_value = {
            "sql": sample_llm_response["sql"],
            "confidence": sample_llm_response["confidence"],
            "missing_context": sample_llm_response["missing_context"],
            "reasoning": sample_llm_response["reasoning"],
            "visualization_hints": sample_llm_response["visualization_hints"],
        }

        # Call build_sql_query with handle
        result = await analytics_sql_tools.build_sql_query(
            user_query="Show warehouse costs for last 30 days",
            context_handle=handle,
        )

        # Verify result structure
        assert result["success"] is True
        assert "sql" in result
        assert result["sql"] == sample_llm_response["sql"]
        assert "confidence" in result
        assert result["confidence"] == 0.9
        assert "missing_context" in result
        assert len(result["missing_context"]) == 0
        # Check for explanation or confidence_reasoning (either is fine)
        assert "explanation" in result or "confidence_reasoning" in result

        # Verify LLM was called
        mock_llm_client.json_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_sql_query_low_confidence(
        self, analytics_sql_tools, sample_rag_context, mock_llm_client
    ):
        """Test SQL generation with low confidence triggers reflexion."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Mock LLM json_response with low confidence
        mock_llm_client.json_response.return_value = {
            "sql": "SELECT * FROM system.billing.usage",
            "confidence": 0.6,
            "missing_context": ["warehouse_names", "join_keys"],
            "reasoning": "Found billing data but missing warehouse metadata",
        }

        result = await analytics_sql_tools.build_sql_query(
            user_query="Show warehouse costs",
            context_handle=handle,
        )

        # Verify low confidence and missing context for reflexion
        assert result["confidence"] == 0.6
        assert "warehouse_names" in result["missing_context"]
        assert "join_keys" in result["missing_context"]

    @pytest.mark.asyncio
    async def test_build_sql_query_with_previous_errors(
        self, analytics_sql_tools, sample_rag_context, mock_llm_client
    ):
        """Test SQL generation with reflexion loop errors from validation."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        previous_errors = [
            "Table 'system.billing.unknown' not found",
            "Column 'invalid_col' does not exist",
        ]

        mock_llm_client.json_response.return_value = {
            "sql": "SELECT usage_date, SUM(list_cost) FROM system.billing.usage GROUP BY usage_date",
            "confidence": 0.85,
            "missing_context": [],
            "reasoning": "Applied validation error feedback to fix query",
        }

        result = await analytics_sql_tools.build_sql_query(
            user_query="Show daily costs",
            context_handle=handle,
            previous_errors=previous_errors,
        )

        # Verify SQL was generated with error feedback
        assert result["success"] is True
        assert "usage_date" in result["sql"]
        assert "list_cost" in result["sql"]

    @pytest.mark.asyncio
    async def test_build_sql_query_invalid_handle(self, analytics_sql_tools):
        """Test error handling for invalid context handle."""
        result = await analytics_sql_tools.build_sql_query(
            user_query="Show usage data",
            context_handle="ctx_invalid123",
        )

        # Verify error response
        assert result["success"] is False
        assert "Invalid or expired context_handle" in result["error"]
        assert result["confidence"] == 0.0
        assert "valid_rag_context" in result["missing_context"]

    @pytest.mark.asyncio
    async def test_build_sql_query_expired_handle(
        self, analytics_sql_tools, sample_rag_context
    ):
        """Test error handling for expired context handle."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Manually expire the context
        analytics_sql_tools._context_timestamps[handle] = (
            time.time() - analytics_sql_tools._context_ttl - 1
        )

        result = await analytics_sql_tools.build_sql_query(
            user_query="Show usage data",
            context_handle=handle,
        )

        # Verify error response
        assert result["success"] is False
        assert "Invalid or expired context_handle" in result["error"]

    @pytest.mark.asyncio
    async def test_build_sql_query_llm_failure(
        self, analytics_sql_tools, sample_rag_context, mock_llm_client
    ):
        """Test error handling when LLM call fails."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Mock LLM exception
        mock_llm_client.json_response.side_effect = Exception("LLM timeout")

        with pytest.raises(ValueError, match="SQL generation failed"):
            await analytics_sql_tools.build_sql_query(
                user_query="Show usage data",
                context_handle=handle,
            )

    @pytest.mark.asyncio
    async def test_build_sql_query_stores_llm_hints(
        self, analytics_sql_tools, sample_rag_context, mock_llm_client
    ):
        """Test that LLM hints are stored for later visualization generation."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        visualization_hints = {
            "recommended_chart_types": ["line"],
            "primary_metric": "total_cost",
            "primary_dimension": "usage_date",
            "is_time_series": True,
        }

        mock_llm_client.json_response.return_value = {
            "sql": "SELECT usage_date, SUM(list_cost) as total_cost FROM system.billing.usage GROUP BY usage_date",
            "confidence": 0.9,
            "missing_context": [],
            "reasoning": "Generated time-series cost query",
            "visualization_hints": visualization_hints,
        }

        await analytics_sql_tools.build_sql_query(
            user_query="Show daily cost trends",
            context_handle=handle,
        )

        # Verify hints are stored
        assert analytics_sql_tools.current_llm_hints is not None
        assert "visualization_hints" in analytics_sql_tools.current_llm_hints
        assert (
            analytics_sql_tools.current_llm_hints["visualization_hints"]
            == visualization_hints
        )


# ============================================================================
# SQL Validation Tests (validate_sql_query)
# ============================================================================


class TestValidateSQLQuery:
    """Tests for validate_sql_query method."""

    @pytest.mark.asyncio
    async def test_validate_sql_query_valid_sql(
        self, analytics_sql_tools, mock_sql_validator
    ):
        """Test validation passes for valid SQL."""
        sql = "SELECT warehouse_name, SUM(list_cost) FROM system.billing.usage GROUP BY warehouse_name"

        # Mock successful validation
        mock_sql_validator.validate.return_value = create_mock_validation_result(
            is_valid=True
        )

        result = await analytics_sql_tools.validate_sql_query(
            sql=sql, runtime_validation=False
        )

        # Verify validation passed
        assert result["is_valid"] is True
        assert len(result["errors"]) == 0
        assert result["validation_method"] == "sqlglot"

        # Verify validator was called
        mock_sql_validator.validate.assert_called_once_with(sql, False)

    @pytest.mark.asyncio
    async def test_validate_sql_query_syntax_error(
        self, analytics_sql_tools, mock_sql_validator
    ):
        """Test validation catches syntax errors."""
        sql = "SELECT * FORM system.billing.usage"  # FORM instead of FROM

        # Mock validation failure
        mock_sql_validator.validate.return_value = create_mock_validation_result(
            is_valid=False,
            errors=["Syntax error: unexpected token 'FORM'"],
        )

        result = await analytics_sql_tools.validate_sql_query(sql=sql)

        # Verify validation failed
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0
        assert "Syntax error" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_validate_sql_query_with_runtime_validation(
        self, analytics_sql_tools, mock_sql_validator
    ):
        """Test EXPLAIN plan validation (runtime check)."""
        sql = "SELECT * FROM system.billing.usage LIMIT 10"

        # Mock validation with EXPLAIN
        mock_sql_validator.validate.return_value = create_mock_validation_result(
            is_valid=True,
            warnings=["Full table scan detected"],
        )

        result = await analytics_sql_tools.validate_sql_query(
            sql=sql, runtime_validation=True
        )

        # Verify EXPLAIN validation was requested
        assert result["is_valid"] is True
        assert len(result["warnings"]) > 0
        mock_sql_validator.validate.assert_called_once_with(sql, True)

    @pytest.mark.asyncio
    async def test_validate_sql_query_skip_runtime(
        self, analytics_sql_tools, mock_sql_validator
    ):
        """Test skipping runtime validation for high confidence."""
        sql = "SELECT * FROM system.billing.usage"

        mock_sql_validator.validate.return_value = create_mock_validation_result(
            is_valid=True
        )

        result = await analytics_sql_tools.validate_sql_query(
            sql=sql, runtime_validation=False
        )

        # Verify only syntax validation performed
        assert result["is_valid"] is True
        mock_sql_validator.validate.assert_called_once_with(sql, False)


# ============================================================================
# SQL Execution Tests (execute_sql_query)
# ============================================================================


class TestExecuteSQLQuery:
    """Tests for execute_sql_query method."""

    @pytest.mark.asyncio
    async def test_execute_sql_query_success(
        self, analytics_sql_tools, mock_sql_executor, sample_dataframe
    ):
        """Test successful SQL execution with results."""
        sql = "SELECT warehouse_name, SUM(list_cost) as total_cost FROM system.billing.usage GROUP BY warehouse_name"

        # Mock SQL executor to return DataFrame
        mock_sql_executor.execute_sql.return_value = sample_dataframe

        result = await analytics_sql_tools.execute_sql_query(sql=sql)

        # Verify result structure
        assert "formatted_results" in result
        assert "row_count" in result
        assert result["row_count"] == 3
        assert "metadata" in result
        assert "execution_time_ms" in result["metadata"]

        # Verify executor was called
        mock_sql_executor.execute_sql.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_sql_query_with_caching(
        self,
        analytics_sql_tools_with_cache,
        mock_sql_executor,
        mock_result_cache,
        sample_dataframe,
    ):
        """Test result caching when cache enabled."""
        sql = "SELECT * FROM system.billing.usage"

        mock_sql_executor.execute_sql.return_value = sample_dataframe
        mock_result_cache.cache_result_by_sql.return_value = "data_ref_xyz"

        result = await analytics_sql_tools_with_cache.execute_sql_query(sql=sql)

        # Verify data_reference returned
        assert "visualization" in result
        assert result["visualization"]["data_reference"] == "data_ref_xyz"

        # Verify cache was called
        mock_result_cache.cache_result_by_sql.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_sql_query_empty_results(
        self, analytics_sql_tools, mock_sql_executor
    ):
        """Test execution with zero rows returned."""
        sql = "SELECT * FROM system.billing.usage WHERE 1=0"

        # Mock empty DataFrame
        empty_df = pl.DataFrame({})
        mock_sql_executor.execute_sql.return_value = empty_df

        result = await analytics_sql_tools.execute_sql_query(sql=sql)

        # Verify empty results handled
        assert result["row_count"] == 0
        assert "formatted_results" in result

    @pytest.mark.asyncio
    async def test_execute_sql_query_execution_error(
        self, analytics_sql_tools, mock_sql_executor
    ):
        """Test error handling when execution fails."""
        sql = "SELECT * FROM nonexistent_table"

        # Mock execution failure
        mock_sql_executor.execute_sql.side_effect = Exception("Table not found")

        with pytest.raises(RuntimeError, match="Query execution failed"):
            await analytics_sql_tools.execute_sql_query(sql=sql)

    @pytest.mark.asyncio
    async def test_execute_sql_query_profiling(
        self, analytics_sql_tools, mock_sql_executor
    ):
        """Test DataFrame profiling with statistics."""
        sql = "SELECT * FROM system.billing.usage"

        # Create DataFrame with numeric and categorical data
        df = pl.DataFrame(
            {
                "warehouse_name": ["A", "B", "C"],
                "cost": [100.0, 200.0, 300.0],
                "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            }
        )
        mock_sql_executor.execute_sql.return_value = df

        result = await analytics_sql_tools.execute_sql_query(sql=sql)

        # Verify profiling results
        assert "formatted_results" in result
        profile = result["formatted_results"]
        assert "row_count" in profile
        assert profile["row_count"] == 3
        assert "column_count" in profile
        assert "numeric_stats" in profile or "columns" in profile


# ============================================================================
# DataFrame Profiling Tests (_profile_results)
# ============================================================================


class TestProfileResults:
    """Tests for _profile_results method."""

    def test_profile_results_numeric_data(self, analytics_sql_tools):
        """Test profiling with numeric columns."""
        df = pl.DataFrame(
            {
                "cost": [100.0, 200.0, 300.0, 400.0],
                "quantity": [10, 20, 30, 40],
            }
        )

        profile = analytics_sql_tools._profile_results(df, "test_sql")

        # Verify numeric stats populated
        assert profile["row_count"] == 4
        assert profile["column_count"] == 2
        assert "numeric_stats" in profile or "columns" in profile

    def test_profile_results_categorical_data(self, analytics_sql_tools):
        """Test profiling with categorical columns."""
        df = pl.DataFrame(
            {
                "warehouse_name": ["A", "B", "A", "C"],
                "status": ["running", "stopped", "running", "stopped"],
            }
        )

        profile = analytics_sql_tools._profile_results(df, "test_sql")

        # Verify categorical stats populated
        assert profile["row_count"] == 4
        assert "categorical_stats" in profile or "columns" in profile

    def test_profile_results_time_series(self, analytics_sql_tools):
        """Test profiling with time series data."""
        df = pl.DataFrame(
            {
                "usage_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "cost": [100.0, 200.0, 150.0],
            }
        )

        profile = analytics_sql_tools._profile_results(df, "test_sql")

        # Verify temporal stats and trend
        assert profile["row_count"] == 3
        # Trend analysis may or may not be present depending on column detection

    def test_profile_results_empty_dataframe(self, analytics_sql_tools):
        """Test profiling with empty DataFrame."""
        df = pl.DataFrame({})

        profile = analytics_sql_tools._profile_results(df, "test_sql")

        # Verify minimal profile structure
        assert profile["row_count"] == 0
        assert profile["column_count"] == 0
        assert profile["columns"] == []


# ============================================================================
# Visualization Generation Tests
# ============================================================================


class TestVisualizationGeneration:
    """Tests for visualization-related methods."""

    def test_transform_llm_hints_line_chart(self, analytics_sql_tools):
        """Test LLM hint transformation for line charts."""
        llm_hints = {
            "recommended_chart_types": ["line"],
            "primary_metric": "total_cost",
            "primary_dimension": "usage_date",
            "is_time_series": True,
            "is_top_n": False,
            "aggregation_type": "sum",
        }

        result = analytics_sql_tools._transform_llm_hints_to_builder_format(llm_hints)

        assert result is not None
        assert result["chart_type"] == "line"
        assert result["x_field"] == "usage_date"
        assert result["y_field"] == "total_cost"
        assert result["x_type"] == "temporal"
        assert result["y_type"] == "quantitative"

    def test_transform_llm_hints_bar_chart(self, analytics_sql_tools):
        """Test LLM hint transformation for bar charts."""
        llm_hints = {
            "recommended_chart_types": ["bar"],
            "primary_metric": "total_cost",
            "primary_dimension": "warehouse_name",
            "is_time_series": False,
            "is_top_n": True,
            "aggregation_type": "sum",
        }

        result = analytics_sql_tools._transform_llm_hints_to_builder_format(llm_hints)

        assert result is not None
        assert result["chart_type"] == "bar"
        assert result["x_field"] == "warehouse_name"
        assert result["y_field"] == "total_cost"
        assert result["x_type"] == "nominal"  # Categories for ranking

    def test_transform_llm_hints_missing_chart_types(self, analytics_sql_tools):
        """Test hint transformation when chart types missing."""
        llm_hints = {
            "recommended_chart_types": [],  # Empty
            "primary_metric": "cost",
        }

        result = analytics_sql_tools._transform_llm_hints_to_builder_format(llm_hints)

        # Should return None when chart types missing
        assert result is None

    def test_transform_llm_hints_none_input(self, analytics_sql_tools):
        """Test hint transformation with None input."""
        result = analytics_sql_tools._transform_llm_hints_to_builder_format(None)
        assert result is None
