"""Unit tests for query result cache.

Following TDD: These tests define the expected behavior before implementation.
Tests cover data_reference generation, DataFrame caching, retrieval, and errors.

Target Coverage: ≥80%
"""

from __future__ import annotations

import contextlib

import polars as pl
import pytest
from starboard_server.adapters.state.inmemory.cache_store import InMemoryCacheStore
from starboard_server.tools.services.query_result_cache import (
    QueryResultCache,
    generate_data_reference,
)


class TestGenerateDataReference:
    """Test suite for data reference generation."""

    def test_generate_reference_basic(self):
        """Test basic data_reference generation."""
        query_id = "test-query-123"
        parameters = {"start_date": "2024-01-01", "end_date": "2024-01-31"}

        ref = generate_data_reference(query_id, parameters)

        assert ref.startswith("data_ref_")
        assert len(ref) == 25  # data_ref_ (9) + hash (16)

    def test_generate_reference_deterministic_within_minute(self):
        """Test data_reference is deterministic within same minute."""
        query_id = "test-query-123"
        parameters = {"start_date": "2024-01-01"}

        ref1 = generate_data_reference(query_id, parameters)
        ref2 = generate_data_reference(query_id, parameters)

        # Should be same within same minute window
        assert ref1 == ref2

    def test_generate_reference_different_query_id(self):
        """Test different query IDs generate different references."""
        parameters = {"date": "2024-01-01"}

        ref1 = generate_data_reference("query1", parameters)
        ref2 = generate_data_reference("query2", parameters)

        assert ref1 != ref2

    def test_generate_reference_different_parameters(self):
        """Test different parameters generate different references."""
        query_id = "test-query"

        ref1 = generate_data_reference(query_id, {"date": "2024-01-01"})
        ref2 = generate_data_reference(query_id, {"date": "2024-01-02"})

        assert ref1 != ref2

    def test_generate_reference_empty_parameters(self):
        """Test data_reference works with empty parameters."""
        query_id = "test-query"
        parameters = {}

        ref = generate_data_reference(query_id, parameters)

        assert ref.startswith("data_ref_")
        assert len(ref) == 25

    def test_generate_reference_parameter_order_invariant(self):
        """Test parameter order doesn't affect reference."""
        query_id = "test-query"

        # Note: Python 3.7+ dicts are ordered, so this tests dict conversion
        ref1 = generate_data_reference(query_id, {"a": "1", "b": "2"})
        ref2 = generate_data_reference(query_id, {"b": "2", "a": "1"})

        # After sorting in implementation, should be same
        # (This test documents expected behavior - may need adjustment)
        # For now, we expect order to matter (simpler implementation)
        # Future: Could sort keys for order-invariance
        assert ref1 == ref2  # May need to update implementation to sort


class TestQueryResultCache:
    """Test suite for QueryResultCache."""

    @pytest.fixture
    def cache_store(self):
        """Create InMemoryCacheStore for testing."""
        return InMemoryCacheStore(max_size=500)

    @pytest.fixture
    def result_cache(self, cache_store):
        """Create QueryResultCache with mock store."""
        return QueryResultCache(cache_store=cache_store, default_ttl=600)

    @pytest.mark.asyncio
    async def test_cache_result_basic(self, result_cache):
        """Test caching a DataFrame result."""
        df = pl.DataFrame({"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]})

        query_id = "test-query-123"
        parameters = {"start_date": "2024-01-01"}

        data_ref = await result_cache.cache_result(query_id, parameters, df)

        assert data_ref.startswith("data_ref_")
        assert len(data_ref) == 25

    @pytest.mark.asyncio
    async def test_cache_result_stores_correct_structure(
        self, result_cache, cache_store
    ):
        """Test cached result has correct structure."""
        df = pl.DataFrame(
            {"job_id": ["j1", "j2"], "cost": [100.50, 200.75], "count": [5, 10]}
        )

        query_id = "cost-query"
        parameters = {"month": "2024-01"}

        data_ref = await result_cache.cache_result(query_id, parameters, df)

        # Retrieve directly from cache store (key is namespaced with "data:" prefix)
        namespaced_key = f"data:{data_ref}"
        cached = await cache_store.get(namespaced_key)

        assert cached is not None
        assert "rows" in cached
        assert "columns" in cached
        assert "dtypes" in cached
        assert "row_count" in cached

        assert len(cached["rows"]) == 2
        assert cached["columns"] == ["job_id", "cost", "count"]
        assert cached["row_count"] == 2

    @pytest.mark.asyncio
    async def test_get_cached_data_success(self, result_cache):
        """Test retrieving cached data successfully."""
        df = pl.DataFrame({"id": [1, 2], "value": ["a", "b"]})

        query_id = "test-query"
        parameters = {"param": "value"}

        # Cache the result
        data_ref = await result_cache.cache_result(query_id, parameters, df)

        # Retrieve the cached data
        cached_data = await result_cache.get_cached_data(data_ref)

        assert cached_data is not None
        assert "rows" in cached_data
        assert "columns" in cached_data
        assert cached_data["columns"] == ["id", "value"]
        assert len(cached_data["rows"]) == 2

    @pytest.mark.asyncio
    async def test_get_cached_data_not_found(self, result_cache):
        """Test retrieving non-existent data_reference raises error."""
        with pytest.raises(ValueError) as exc_info:
            await result_cache.get_cached_data("data_ref_nonexistent123")

        assert "not found or expired" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cached_data_preserves_types(self, result_cache):
        """Test cached data preserves DataFrame types."""
        df = pl.DataFrame(
            {
                "int_col": [1, 2, 3],
                "float_col": [1.1, 2.2, 3.3],
                "str_col": ["a", "b", "c"],
                "bool_col": [True, False, True],
            }
        )

        data_ref = await result_cache.cache_result("q1", {}, df)
        cached_data = await result_cache.get_cached_data(data_ref)

        # Check dtypes are preserved
        assert "dtypes" in cached_data
        assert "int_col" in cached_data["dtypes"]
        assert "float_col" in cached_data["dtypes"]
        assert "str_col" in cached_data["dtypes"]
        assert "bool_col" in cached_data["dtypes"]

    @pytest.mark.asyncio
    async def test_cached_data_preserves_rows(self, result_cache):
        """Test cached data preserves row data accurately."""
        df = pl.DataFrame(
            {
                "job_id": ["job_123", "job_456"],
                "list_cost": [1234.56, 789.12],
                "usage_date": ["2024-11-01", "2024-11-02"],
            }
        )

        data_ref = await result_cache.cache_result("q1", {}, df)
        cached_data = await result_cache.get_cached_data(data_ref)

        # Check row data
        rows = cached_data["rows"]
        assert len(rows) == 2
        assert rows[0]["job_id"] == "job_123"
        assert rows[0]["list_cost"] == 1234.56
        assert rows[1]["job_id"] == "job_456"

    @pytest.mark.asyncio
    async def test_cache_empty_dataframe(self, result_cache):
        """Test caching empty DataFrame."""
        df = pl.DataFrame(schema={"id": pl.Int64, "name": pl.Utf8})

        data_ref = await result_cache.cache_result("q1", {}, df)
        cached_data = await result_cache.get_cached_data(data_ref)

        assert cached_data["row_count"] == 0
        assert cached_data["rows"] == []
        assert cached_data["columns"] == ["id", "name"]

    @pytest.mark.asyncio
    async def test_cache_large_dataframe(self, result_cache):
        """Test caching large DataFrame."""
        # Create 1000-row DataFrame
        df = pl.DataFrame(
            {
                "id": list(range(1000)),
                "value": [f"val_{i}" for i in range(1000)],
                "score": [i * 0.5 for i in range(1000)],
            }
        )

        data_ref = await result_cache.cache_result("large-query", {}, df)
        cached_data = await result_cache.get_cached_data(data_ref)

        assert cached_data["row_count"] == 1000
        assert len(cached_data["rows"]) == 1000
        assert cached_data["rows"][0]["id"] == 0
        assert cached_data["rows"][999]["id"] == 999

    @pytest.mark.asyncio
    async def test_ttl_custom_override(self, cache_store):
        """Test custom TTL override."""
        result_cache = QueryResultCache(cache_store=cache_store, default_ttl=600)

        df = pl.DataFrame({"id": [1]})

        # Use custom TTL
        data_ref = await result_cache.cache_result(
            query_id="q1", parameters={}, df=df, ttl=300
        )

        # Should be cached (can't test expiration without time manipulation)
        cached = await result_cache.get_cached_data(data_ref)
        assert cached is not None

    @pytest.mark.asyncio
    async def test_same_query_different_params_different_refs(self, result_cache):
        """Test same query with different parameters gets different refs."""
        df = pl.DataFrame({"id": [1]})

        query_id = "same-query"

        ref1 = await result_cache.cache_result(query_id, {"date": "2024-01-01"}, df)
        ref2 = await result_cache.cache_result(query_id, {"date": "2024-01-02"}, df)

        assert ref1 != ref2

        # Both should be retrievable
        data1 = await result_cache.get_cached_data(ref1)
        data2 = await result_cache.get_cached_data(ref2)

        assert data1 is not None
        assert data2 is not None

    @pytest.mark.asyncio
    async def test_clear_cache(self, result_cache):
        """Test cache can be cleared."""
        df = pl.DataFrame({"id": [1]})

        data_ref = await result_cache.cache_result("q1", {}, df)

        # Verify cached
        cached = await result_cache.get_cached_data(data_ref)
        assert cached is not None

        # Clear cache
        await result_cache.clear()

        # Should no longer be cached
        with pytest.raises(ValueError):
            await result_cache.get_cached_data(data_ref)

    @pytest.mark.asyncio
    async def test_get_metrics(self, result_cache):
        """Test cache metrics tracking."""
        df = pl.DataFrame({"id": [1, 2]})

        # Cache a result
        data_ref = await result_cache.cache_result("q1", {}, df)

        # Initial metrics (no gets yet)
        metrics = result_cache.get_metrics()
        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.hit_rate == 0.0

        # Hit: successful retrieval
        await result_cache.get_cached_data(data_ref)
        metrics = result_cache.get_metrics()
        assert metrics.hits == 1
        assert metrics.misses == 0
        assert metrics.hit_rate == 1.0

        # Miss: non-existent key
        with contextlib.suppress(ValueError):
            await result_cache.get_cached_data("data_ref_nonexistent123")

        metrics = result_cache.get_metrics()
        assert metrics.hits == 1
        assert metrics.misses == 1
        assert metrics.hit_rate == 0.5


class TestIntegration:
    """Integration tests for QueryResultCache."""

    @pytest.mark.asyncio
    async def test_end_to_end_flow(self):
        """Test complete flow: cache → retrieve → use."""
        cache_store = InMemoryCacheStore(max_size=50)
        result_cache = QueryResultCache(cache_store=cache_store, default_ttl=600)

        # Create sample query result
        df = pl.DataFrame(
            {
                "job_id": ["job_123", "job_456", "job_789"],
                "job_name": ["ETL Pipeline", "ML Training", "Data Export"],
                "list_cost": [1234.56, 987.65, 543.21],
                "usage_start_time": [
                    "2024-11-01T00:00:00",
                    "2024-11-01T06:00:00",
                    "2024-11-01T12:00:00",
                ],
            }
        )

        # Cache the result
        query_id = "b733352d-a70c-452b-9890-16488d4a8ca6"  # Real query ID from catalog
        parameters = {"start_date": "2024-11-01", "end_date": "2024-11-30"}

        data_ref = await result_cache.cache_result(query_id, parameters, df)

        # Verify data_reference format
        assert data_ref.startswith("data_ref_")

        # Retrieve cached data
        cached_data = await result_cache.get_cached_data(data_ref)

        # Verify structure
        assert cached_data["row_count"] == 3
        assert cached_data["columns"] == [
            "job_id",
            "job_name",
            "list_cost",
            "usage_start_time",
        ]
        assert len(cached_data["rows"]) == 3

        # Verify data integrity
        assert cached_data["rows"][0]["job_id"] == "job_123"
        assert cached_data["rows"][0]["list_cost"] == 1234.56

        # Verify dtypes preserved
        assert "job_id" in cached_data["dtypes"]
        assert "list_cost" in cached_data["dtypes"]

    @pytest.mark.asyncio
    async def test_multiple_queries_cached_separately(self):
        """Test multiple different queries cached separately."""
        cache_store = InMemoryCacheStore(max_size=50)
        result_cache = QueryResultCache(cache_store=cache_store)

        df1 = pl.DataFrame({"result": ["query1_data"]})
        df2 = pl.DataFrame({"result": ["query2_data"]})
        df3 = pl.DataFrame({"result": ["query3_data"]})

        ref1 = await result_cache.cache_result("q1", {"param": "a"}, df1)
        ref2 = await result_cache.cache_result("q2", {"param": "b"}, df2)
        ref3 = await result_cache.cache_result("q3", {"param": "c"}, df3)

        # All should be different
        assert ref1 != ref2 != ref3

        # All should be retrievable
        data1 = await result_cache.get_cached_data(ref1)
        data2 = await result_cache.get_cached_data(ref2)
        data3 = await result_cache.get_cached_data(ref3)

        assert data1["rows"][0]["result"] == "query1_data"
        assert data2["rows"][0]["result"] == "query2_data"
        assert data3["rows"][0]["result"] == "query3_data"
