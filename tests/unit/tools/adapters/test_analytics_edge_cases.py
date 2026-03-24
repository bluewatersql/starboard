"""Edge case tests for Analytics SQL Tools.

Tests for:
- Concurrent context caching (thread safety)
- Cache TTL expiration behavior
- Large result sets
- Memory management
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest
from starboard_core.rag.models import RAGContext, RAGTableContext
from starboard_server.tools.adapters.analytics_sql_tools import AnalyticsSQLTools
from starboard_server.tools.domain.analytics_sql.sql_validator import SQLValidator

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_client():
    """Mock LLM client."""
    client = MagicMock()
    client.max_tokens = 4096
    client.json_response = AsyncMock(
        return_value={
            "sql": "SELECT * FROM system.billing.usage",
            "explanation": "Test query",
            "confidence": 0.9,
            "missing_context": [],
            "confidence_reasoning": "Complete",
            "visualization_hints": {},
        }
    )
    return client


@pytest.fixture
def mock_sql_executor():
    """Mock SQL executor."""
    executor = MagicMock()
    executor.execute_sql = AsyncMock(return_value=pl.DataFrame({"col1": [1, 2, 3]}))
    return executor


@pytest.fixture
def analytics_sql_tools(mock_llm_client, mock_sql_executor):
    """Create AnalyticsSQLTools instance."""
    validator = SQLValidator(sql_executor=mock_sql_executor)
    return AnalyticsSQLTools(
        llm_client=mock_llm_client,
        sql_executor=mock_sql_executor,
        sql_validator=validator,
        result_cache=None,
    )


@pytest.fixture
def sample_rag_context():
    """Sample RAG context."""
    return RAGContext(
        tables=[
            RAGTableContext(
                table_name="system.billing.usage",
                description="Usage data",
                table_columns="col1, col2",
                domain="finops_billing",
            )
        ],
        nuances=[],
        codebook=[],
        facets=[],
        learnings=[],
    )


# ============================================================================
# Concurrent Caching Tests
# ============================================================================


class TestConcurrentCaching:
    """Tests for concurrent context caching behavior."""

    @pytest.mark.asyncio
    async def test_concurrent_context_storage(
        self,
        analytics_sql_tools,
        sample_rag_context,
    ):
        """Test concurrent context storage doesn't cause conflicts."""
        # Store multiple contexts concurrently
        tasks = [
            asyncio.create_task(
                asyncio.to_thread(
                    analytics_sql_tools.store_rag_context, sample_rag_context
                )
            )
            for _ in range(10)
        ]

        handles = await asyncio.gather(*tasks)

        # All handles should be unique
        assert len(handles) == 10
        assert len(set(handles)) == 10, "Handles should be unique"

        # All contexts should be retrievable
        for handle in handles:
            context = analytics_sql_tools._retrieve_rag_context(handle)
            assert context is not None
            assert len(context.tables) == 1

    @pytest.mark.asyncio
    async def test_concurrent_context_retrieval(
        self,
        analytics_sql_tools,
        sample_rag_context,
    ):
        """Test concurrent context retrieval is thread-safe."""
        # Store one context
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Retrieve it concurrently multiple times
        tasks = [
            asyncio.create_task(
                asyncio.to_thread(analytics_sql_tools._retrieve_rag_context, handle)
            )
            for _ in range(20)
        ]

        contexts = await asyncio.gather(*tasks)

        # All retrievals should succeed
        assert all(ctx is not None for ctx in contexts)
        assert all(len(ctx.tables) == 1 for ctx in contexts)

    @pytest.mark.asyncio
    async def test_concurrent_sql_generation_with_same_context(
        self,
        analytics_sql_tools,
        sample_rag_context,
    ):
        """Test concurrent SQL generation with same context handle."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Generate SQL concurrently with same handle
        tasks = [
            analytics_sql_tools.build_sql_query(
                user_query=f"Query {i}",
                context_handle=handle,
            )
            for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r["success"] is True for r in results)
        assert all("sql" in r for r in results)


# ============================================================================
# Cache TTL Expiration Tests
# ============================================================================


class TestCacheTTLExpiration:
    """Tests for cache TTL expiration behavior."""

    def test_context_ttl_default_value(self, analytics_sql_tools):
        """Test default TTL is set correctly."""
        assert analytics_sql_tools._context_ttl == 3600  # 1 hour

    def test_expired_context_cleaned_up(
        self,
        analytics_sql_tools,
        sample_rag_context,
    ):
        """Test expired contexts are cleaned up."""
        # Store a context
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Verify it exists
        assert analytics_sql_tools._retrieve_rag_context(handle) is not None

        # Manually expire it by setting old timestamp
        analytics_sql_tools._context_timestamps[handle] = (
            time.time() - 3700
        )  # 61+ minutes ago

        # Run cleanup
        analytics_sql_tools._cleanup_expired_contexts()

        # Should be removed
        assert handle not in analytics_sql_tools._rag_context_cache
        assert handle not in analytics_sql_tools._context_timestamps

    def test_non_expired_context_preserved(
        self,
        analytics_sql_tools,
        sample_rag_context,
    ):
        """Test non-expired contexts are preserved during cleanup."""
        # Store contexts
        handle1 = analytics_sql_tools.store_rag_context(sample_rag_context)
        handle2 = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Expire only handle1
        analytics_sql_tools._context_timestamps[handle1] = time.time() - 3700
        analytics_sql_tools._context_timestamps[handle2] = time.time()  # Fresh

        # Run cleanup
        analytics_sql_tools._cleanup_expired_contexts()

        # handle1 should be removed, handle2 should remain
        assert handle1 not in analytics_sql_tools._rag_context_cache
        assert handle2 in analytics_sql_tools._rag_context_cache
        assert analytics_sql_tools._retrieve_rag_context(handle2) is not None

    def test_context_expiration_near_ttl_boundary(
        self,
        analytics_sql_tools,
        sample_rag_context,
    ):
        """Test context behavior near TTL boundary."""
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Set timestamp to slightly more than TTL seconds ago
        analytics_sql_tools._context_timestamps[handle] = (
            time.time() - 3601
        )  # 1 second past TTL

        # Should be expired (> TTL)
        analytics_sql_tools._cleanup_expired_contexts()
        assert handle not in analytics_sql_tools._rag_context_cache

    def test_cleanup_with_empty_cache(self, analytics_sql_tools):
        """Test cleanup with empty cache doesn't cause errors."""
        # Should not raise any exceptions
        analytics_sql_tools._cleanup_expired_contexts()

        assert len(analytics_sql_tools._rag_context_cache) == 0
        assert len(analytics_sql_tools._context_timestamps) == 0


# ============================================================================
# Large Result Set Tests
# ============================================================================


class TestLargeResultSets:
    """Tests for handling large SQL result sets."""

    @pytest.mark.asyncio
    async def test_large_dataframe_profiling(
        self,
        analytics_sql_tools,
        mock_sql_executor,
    ):
        """Test profiling of large dataframes."""
        # Create a large dataframe (10K rows)
        large_df = pl.DataFrame(
            {
                "warehouse_name": [f"warehouse_{i % 100}" for i in range(10000)],
                "total_cost": [float(i * 1.5) for i in range(10000)],
                "usage_date": [f"2024-{(i % 12) + 1:02d}-01" for i in range(10000)],
            }
        )

        mock_sql_executor.execute_sql.return_value = large_df

        # Execute query
        result = await analytics_sql_tools.execute_sql_query(
            sql="SELECT * FROM system.billing.usage",
        )

        # Should handle large dataframe
        assert "formatted_results" in result
        assert result["row_count"] == 10000

        # Profile should include statistics
        formatted = result["formatted_results"]
        assert "numeric_stats" in formatted
        assert "categorical_stats" in formatted

        # Sample rows should be limited
        assert len(formatted["sample_rows"]) <= 20  # Max sample size

    @pytest.mark.asyncio
    async def test_very_wide_dataframe(
        self,
        analytics_sql_tools,
        mock_sql_executor,
    ):
        """Test handling of dataframes with many columns."""
        # Create dataframe with 50 columns
        wide_df = pl.DataFrame(
            {f"col_{i}": [i * j for j in range(100)] for i in range(50)}
        )

        mock_sql_executor.execute_sql.return_value = wide_df

        # Execute query
        result = await analytics_sql_tools.execute_sql_query(
            sql="SELECT * FROM system.billing.usage",
        )

        # Should handle wide dataframe
        assert result["row_count"] == 100
        formatted = result["formatted_results"]
        assert formatted["column_count"] == 50

    @pytest.mark.asyncio
    async def test_dataframe_with_many_unique_values(
        self,
        analytics_sql_tools,
        mock_sql_executor,
    ):
        """Test profiling of dataframe with high cardinality columns."""
        # Create dataframe with many unique values
        high_cardinality_df = pl.DataFrame(
            {
                "unique_id": [f"id_{i}" for i in range(5000)],
                "value": list(range(5000)),
            }
        )

        mock_sql_executor.execute_sql.return_value = high_cardinality_df

        # Execute query
        result = await analytics_sql_tools.execute_sql_query(
            sql="SELECT * FROM system.billing.usage",
        )

        # Should handle high cardinality
        assert result["row_count"] == 5000
        formatted = result["formatted_results"]

        # Categorical stats should report high cardinality
        if (
            "categorical_stats" in formatted
            and "unique_id" in formatted["categorical_stats"]
        ):
            assert formatted["categorical_stats"]["unique_id"]["n_unique"] == 5000


# ============================================================================
# Memory Management Tests
# ============================================================================


class TestMemoryManagement:
    """Tests for memory management and resource cleanup."""

    def test_cache_growth_is_bounded(
        self,
        analytics_sql_tools,
        sample_rag_context,
    ):
        """Test that cache doesn't grow unbounded."""
        # Store many contexts
        handles = []
        for _ in range(100):
            handle = analytics_sql_tools.store_rag_context(sample_rag_context)
            handles.append(handle)

        # All should be stored initially
        assert len(analytics_sql_tools._rag_context_cache) == 100

        # Expire half of them
        for _, handle in enumerate(handles[:50]):
            analytics_sql_tools._context_timestamps[handle] = time.time() - 3700

        # Run cleanup
        analytics_sql_tools._cleanup_expired_contexts()

        # Cache should be reduced
        assert len(analytics_sql_tools._rag_context_cache) == 50

    def test_context_cache_independent_instances(
        self,
        mock_llm_client,
        mock_sql_executor,
        sample_rag_context,
    ):
        """Test that each AnalyticsSQLTools instance has independent cache."""
        validator = SQLValidator(sql_executor=mock_sql_executor)

        # Create two instances
        tools1 = AnalyticsSQLTools(
            llm_client=mock_llm_client,
            sql_executor=mock_sql_executor,
            sql_validator=validator,
        )

        tools2 = AnalyticsSQLTools(
            llm_client=mock_llm_client,
            sql_executor=mock_sql_executor,
            sql_validator=validator,
        )

        # Store context in tools1
        handle1 = tools1.store_rag_context(sample_rag_context)

        # Should not exist in tools2
        assert handle1 not in tools2._rag_context_cache
        assert tools2._retrieve_rag_context(handle1) is None

        # Store in tools2
        handle2 = tools2.store_rag_context(sample_rag_context)

        # Should not exist in tools1
        assert handle2 not in tools1._rag_context_cache


# ============================================================================
# Edge Case Integration Tests
# ============================================================================


class TestEdgeCaseIntegration:
    """Integration tests for edge cases."""

    @pytest.mark.asyncio
    async def test_workflow_with_context_expiration(
        self,
        analytics_sql_tools,
        sample_rag_context,
    ):
        """Test workflow when context expires mid-operation."""
        # Store context
        handle = analytics_sql_tools.store_rag_context(sample_rag_context)

        # Verify it works initially
        result1 = await analytics_sql_tools.build_sql_query(
            user_query="Test query",
            context_handle=handle,
        )
        assert result1["success"] is True

        # Expire the context
        analytics_sql_tools._context_timestamps[handle] = time.time() - 3700
        analytics_sql_tools._cleanup_expired_contexts()

        # Should fail now
        result2 = await analytics_sql_tools.build_sql_query(
            user_query="Test query",
            context_handle=handle,
        )
        assert result2["success"] is False
        assert (
            "not found" in result2["error"].lower()
            or "invalid" in result2["error"].lower()
        )
