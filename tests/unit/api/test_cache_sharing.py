# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Test cache sharing between data and visualization endpoints.

This test validates that data cached during query execution
can be retrieved by both the /api/data endpoint and
/api/visualization/render endpoint.

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


class TestCacheSharing:
    """Test cache store sharing between endpoints."""

    @pytest.fixture
    def cache_store(self) -> InMemoryCacheStore:
        """Create shared cache store."""
        return InMemoryCacheStore()

    @pytest.fixture
    def result_cache(self, cache_store: InMemoryCacheStore) -> QueryResultCache:
        """Create result cache with shared store."""
        return QueryResultCache(cache_store=cache_store, default_ttl=3600)

    @pytest.mark.asyncio
    async def test_cached_data_accessible_after_caching(
        self, result_cache: QueryResultCache
    ):
        """Data cached via QueryResultCache should be accessible via get_cached_data()."""
        # Create test DataFrame
        df = pl.DataFrame(
            {
                "id": [1, 2, 3],
                "name": ["Alice", "Bob", "Charlie"],
                "value": [100.0, 200.0, 300.0],
            }
        )

        # Cache via QueryResultCache (same as analytics_service.py)
        data_reference = await result_cache.cache_result(
            query_id="test_query_123",
            parameters={"start_date": "2024-01-01"},
            df=df,
        )

        # Retrieve via result_cache (same as data.py endpoint would do)
        cached_data = await result_cache.get_cached_data(data_reference)

        # Assertions
        assert cached_data is not None
        assert "rows" in cached_data
        assert "columns" in cached_data
        assert len(cached_data["rows"]) == 3
        assert cached_data["columns"] == ["id", "name", "value"]

    @pytest.mark.asyncio
    async def test_cache_uses_namespaced_keys(
        self, cache_store: InMemoryCacheStore, result_cache: QueryResultCache
    ):
        """Verify result_cache stores data with namespaced keys."""
        df = pl.DataFrame({"x": [1]})

        data_reference = await result_cache.cache_result(
            query_id="test_query",
            parameters={},
            df=df,
        )

        # Data should be stored with namespaced key (data:data_ref_...)
        namespaced_key = f"data:{data_reference}"
        cached_data = await cache_store.get(namespaced_key)
        assert cached_data is not None, (
            f"Data not found at namespaced key {namespaced_key}"
        )

        # Direct access without namespace should NOT work
        raw_data = await cache_store.get(data_reference)
        assert raw_data is None, "Data should not be accessible without namespace"

    @pytest.mark.asyncio
    async def test_data_reference_format(self, result_cache: QueryResultCache):
        """Verify data_reference has expected format."""
        df = pl.DataFrame({"x": [1]})

        data_reference = await result_cache.cache_result(
            query_id="test_query",
            parameters={},
            df=df,
        )

        assert data_reference.startswith("data_ref_")
        assert len(data_reference) > 10  # data_ref_ + hash

    @pytest.mark.asyncio
    async def test_cache_metrics_tracking(self, result_cache: QueryResultCache):
        """Verify metrics are tracked for cache operations."""
        df = pl.DataFrame({"x": [1]})

        # Initial metrics
        metrics = result_cache.get_metrics()
        assert metrics.hits == 0
        assert metrics.misses == 0

        # Cache result
        data_reference = await result_cache.cache_result(
            query_id="test_query",
            parameters={},
            df=df,
        )

        # Get (cache hit)
        await result_cache.get_cached_data(data_reference)
        metrics = result_cache.get_metrics()
        assert metrics.hits == 1
        assert metrics.misses == 0
        assert metrics.hit_rate == 1.0

        # Get non-existent (cache miss)
        with contextlib.suppress(ValueError):
            await result_cache.get_cached_data("data_ref_nonexistent")

        metrics = result_cache.get_metrics()
        assert metrics.hits == 1
        assert metrics.misses == 1
        assert metrics.hit_rate == 0.5

    @pytest.mark.asyncio
    async def test_multiple_caches_share_store(self, cache_store: InMemoryCacheStore):
        """Verify multiple QueryResultCache instances can share a store."""
        cache1 = QueryResultCache(cache_store=cache_store, namespace="cache1")
        cache2 = QueryResultCache(cache_store=cache_store, namespace="cache2")

        df1 = pl.DataFrame({"value": [42]})
        df2 = pl.DataFrame({"value": [99]})

        # Cache in cache1 with unique query_id
        ref1 = await cache1.cache_result("query_for_cache1", {"unique": "cache1"}, df1)

        # Cache in cache2 with different query_id (different ref)
        ref2 = await cache2.cache_result("query_for_cache2", {"unique": "cache2"}, df2)

        # Ensure refs are different
        assert ref1 != ref2, "Data references should be different for different queries"

        # Both should be retrievable from their respective caches
        data1 = await cache1.get_cached_data(ref1)
        data2 = await cache2.get_cached_data(ref2)

        assert data1["rows"][0]["value"] == 42
        assert data2["rows"][0]["value"] == 99

        # Cross-cache access should fail (different namespaces)
        with pytest.raises(ValueError):
            await cache1.get_cached_data(ref2)

        with pytest.raises(ValueError):
            await cache2.get_cached_data(ref1)
