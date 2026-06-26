# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration test for data cache sharing between endpoints.

This test verifies that data cached during query execution
can be retrieved by the /api/data/{data_reference} endpoint.

Bug fix verification for: B1 - Analytics Report 404 on Chart Render

MIGRATION (Phase 4):
    - Updated to work with CacheStore protocol and NamespacedCache
    - Tests now use QueryResultCache.get_cached_data() instead of direct store access
    - Metric assertions replace internal state checks
"""

import contextlib

import polars as pl
import pytest
from starboard_server.adapters.state.inmemory.cache_store import InMemoryCacheStore
from starboard_server.tools.services.query_result_cache import QueryResultCache


class TestDataCacheIntegration:
    """Integration tests for data cache flow."""

    @pytest.mark.asyncio
    async def test_cache_roundtrip(self):
        """
        Simulates the full flow:
        1. Analytics service caches query result
        2. Data endpoint retrieves the same result via QueryResultCache

        This mimics what happens when:
        - Query executes and charts render
        - User clicks "Show Data" to view table
        """
        # Create shared cache store (same as what container.cache_store provides)
        cache_store = InMemoryCacheStore()

        # Create QueryResultCache (same as tool_factory.py)
        result_cache = QueryResultCache(cache_store=cache_store, default_ttl=3600)

        # Simulate query execution result
        df = pl.DataFrame(
            {
                "job_id": ["job_001", "job_002", "job_003"],
                "cost_usd": [150.50, 250.75, 350.00],
                "run_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            }
        )

        # Cache result (same as analytics_service.py)
        data_reference = await result_cache.cache_result(
            query_id="top_k_jobs_by_cost",
            parameters={"start_date": "2024-01-01", "end_date": "2024-01-31", "k": 10},
            df=df,
        )

        print(f"Cached data with reference: {data_reference}")

        # Simulate data endpoint access via QueryResultCache
        # This is exactly what GET /api/data/{data_reference} does
        cached_data = await result_cache.get_cached_data(data_reference)

        # Verify data is accessible
        assert cached_data is not None

        # Verify structure
        assert "rows" in cached_data
        assert "columns" in cached_data
        assert "row_count" in cached_data

        # Verify content
        assert len(cached_data["rows"]) == 3
        assert cached_data["columns"] == ["job_id", "cost_usd", "run_date"]
        assert cached_data["row_count"] == 3

    @pytest.mark.asyncio
    async def test_different_cache_instances_with_shared_store(self):
        """
        Demonstrates that multiple QueryResultCache instances can share
        the same underlying store as long as they use the same namespace.
        """
        # Single shared store
        shared_store = InMemoryCacheStore()

        # Two result cache instances with SAME namespace
        cache_writer = QueryResultCache(cache_store=shared_store, namespace="data")
        cache_reader = QueryResultCache(cache_store=shared_store, namespace="data")

        df = pl.DataFrame({"x": [1, 2, 3]})

        # Cache in first instance
        data_reference = await cache_writer.cache_result(
            query_id="test",
            parameters={},
            df=df,
        )

        # Retrieve from second instance (same namespace = same data)
        cached_data = await cache_reader.get_cached_data(data_reference)
        assert cached_data is not None
        assert len(cached_data["rows"]) == 3

    @pytest.mark.asyncio
    async def test_different_namespaces_isolated(self):
        """
        Demonstrates that different namespaces isolate their data.
        """
        # Single shared store
        shared_store = InMemoryCacheStore()

        # Two result cache instances with DIFFERENT namespaces
        cache_ns1 = QueryResultCache(cache_store=shared_store, namespace="ns1")
        cache_ns2 = QueryResultCache(cache_store=shared_store, namespace="ns2")

        df = pl.DataFrame({"x": [1, 2, 3]})

        # Cache in ns1
        data_reference = await cache_ns1.cache_result(
            query_id="test",
            parameters={},
            df=df,
        )

        # Should NOT be retrievable from ns2 (different namespace)
        with pytest.raises(ValueError, match="not found or expired"):
            await cache_ns2.get_cached_data(data_reference)

        # But retrievable from ns1
        cached_data = await cache_ns1.get_cached_data(data_reference)
        assert cached_data is not None

    @pytest.mark.asyncio
    async def test_cache_store_identity_via_namespace(self):
        """
        Verify that the same cache store instance is used via namespace.

        In the real app, container.cache_store should be the SAME instance
        passed to tool_factory and used by data.py.
        """
        # Single shared store
        shared_store = InMemoryCacheStore()
        store_id = id(shared_store)

        # Create result cache with shared store
        result_cache = QueryResultCache(cache_store=shared_store, default_ttl=3600)

        # Verify the underlying store is the same instance
        # (Access via internal _store.store for verification)
        assert id(result_cache._store.store) == store_id

    @pytest.mark.asyncio
    async def test_metrics_across_operations(self):
        """
        Verify metrics are tracked correctly across multiple operations.
        """
        cache_store = InMemoryCacheStore()
        result_cache = QueryResultCache(cache_store=cache_store, default_ttl=3600)

        df = pl.DataFrame({"value": [1, 2, 3]})

        # Cache multiple results
        ref1 = await result_cache.cache_result("q1", {"a": 1}, df)
        ref2 = await result_cache.cache_result("q2", {"b": 2}, df)

        # Access both (2 hits)
        await result_cache.get_cached_data(ref1)
        await result_cache.get_cached_data(ref2)

        # Access non-existent (1 miss)
        with contextlib.suppress(ValueError):
            await result_cache.get_cached_data("data_ref_nonexistent")

        # Verify metrics
        metrics = result_cache.get_metrics()
        assert metrics.hits == 2
        assert metrics.misses == 1
        assert metrics.hit_rate == pytest.approx(0.666, rel=0.01)
