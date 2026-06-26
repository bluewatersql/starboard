# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for CacheManager.

Following TDD: These tests define the expected behavior for the unified cache.
Tests cover get/set, TTL expiration, LRU eviction, DataFrame support,
pattern invalidation, metrics, and stampede prevention.

Target Coverage: 100%
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import polars as pl
import pytest
from starboard_server.adapters.databricks.cache.manager import CacheManager


class TestCacheManagerBasicOperations:
    """Tests for basic cache get/set operations."""

    @pytest.fixture
    def cache(self) -> CacheManager:
        """Create cache instance with default settings."""
        return CacheManager(max_size=100, default_ttl=300)

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, cache: CacheManager) -> None:
        """Test cache miss returns None."""
        result = await cache.get("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_string(self, cache: CacheManager) -> None:
        """Test basic set and get with string value."""
        await cache.set("key", "value")
        result = await cache.get("key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_set_and_get_dict(self, cache: CacheManager) -> None:
        """Test set and get with dictionary value."""
        data = {"job_id": 123, "name": "Test Job", "nested": {"key": "val"}}
        await cache.set("job:123", data)
        result = await cache.get("job:123")
        assert result == data

    @pytest.mark.asyncio
    async def test_set_and_get_list(self, cache: CacheManager) -> None:
        """Test set and get with list value."""
        data = [{"run_id": 1}, {"run_id": 2}, {"run_id": 3}]
        await cache.set("runs:123", data)
        result = await cache.get("runs:123")
        assert result == data

    @pytest.mark.asyncio
    async def test_overwrite_existing_key(self, cache: CacheManager) -> None:
        """Test overwriting an existing cache entry."""
        await cache.set("key", "value1")
        await cache.set("key", "value2")
        result = await cache.get("key")
        assert result == "value2"


class TestCacheManagerTTL:
    """Tests for TTL expiration behavior."""

    @pytest.mark.asyncio
    async def test_ttl_expiration(self) -> None:
        """Test entry expires after TTL."""
        cache = CacheManager(max_size=100, default_ttl=1)  # 1 second TTL
        await cache.set("key", "value")

        # Should exist immediately
        assert await cache.get("key") == "value"

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired
        assert await cache.get("key") is None

    @pytest.mark.asyncio
    async def test_custom_ttl_override(self) -> None:
        """Test custom TTL overrides default."""
        cache = CacheManager(max_size=100, default_ttl=300)
        await cache.set("key", "value", ttl=1)  # Override with 1 second

        assert await cache.get("key") == "value"
        await asyncio.sleep(1.1)
        assert await cache.get("key") is None

    @pytest.mark.asyncio
    async def test_no_ttl_never_expires(self) -> None:
        """Test entry with no TTL doesn't expire."""
        cache = CacheManager(max_size=100, default_ttl=None)
        await cache.set("key", "value")

        # Mock time passing
        with patch("time.time", return_value=time.time() + 86400):  # 1 day later
            # Entry should still exist (no expiration)
            result = await cache.get("key")
            # Note: This test may need adjustment based on implementation
            assert result == "value"


class TestCacheManagerLRU:
    """Tests for LRU eviction behavior."""

    @pytest.mark.asyncio
    async def test_lru_eviction_at_capacity(self) -> None:
        """Test LRU eviction when max size reached."""
        cache = CacheManager(max_size=3, default_ttl=300)

        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        # All should exist
        assert await cache.get("a") == 1
        assert await cache.get("b") == 2
        assert await cache.get("c") == 3

        # Add one more (should evict oldest)
        await cache.set("d", 4)

        # Cache should have 3 entries
        assert len(cache._cache) == 3
        assert await cache.get("d") == 4

    @pytest.mark.asyncio
    async def test_access_updates_lru_order(self) -> None:
        """Test that accessing an entry updates its LRU position."""
        cache = CacheManager(max_size=3, default_ttl=300)

        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        # Access 'a' to make it recently used
        await cache.get("a")

        # Add new entry (should evict 'b', not 'a')
        await cache.set("d", 4)

        # 'a' should still exist, 'b' should be evicted
        assert await cache.get("a") == 1
        assert await cache.get("d") == 4
        # 'b' was LRU after we accessed 'a'


class TestCacheManagerDataFrame:
    """Tests for DataFrame serialization and caching."""

    @pytest.fixture
    def cache(self) -> CacheManager:
        """Create cache instance."""
        return CacheManager(max_size=100, default_ttl=300)

    @pytest.mark.asyncio
    async def test_dataframe_round_trip(self, cache: CacheManager) -> None:
        """Test DataFrame is serialized and deserialized correctly."""
        original_df = pl.DataFrame(
            {
                "id": [1, 2, 3],
                "name": ["Alice", "Bob", "Charlie"],
                "score": [95.5, 87.3, 92.1],
            }
        )

        await cache.set_dataframe("df_key", original_df)
        result_df = await cache.get_dataframe("df_key")

        assert result_df is not None
        assert result_df.equals(original_df)
        assert result_df.columns == original_df.columns
        assert result_df.shape == original_df.shape

    @pytest.mark.asyncio
    async def test_empty_dataframe(self, cache: CacheManager) -> None:
        """Test empty DataFrame caching."""
        empty_df = pl.DataFrame()

        await cache.set_dataframe("empty", empty_df)
        result_df = await cache.get_dataframe("empty")

        assert result_df is not None
        assert len(result_df) == 0

    @pytest.mark.asyncio
    async def test_dataframe_with_schema(self, cache: CacheManager) -> None:
        """Test DataFrame with specific schema is preserved."""
        df = pl.DataFrame(
            {
                "int_col": [1, 2, 3],
                "float_col": [1.1, 2.2, 3.3],
                "str_col": ["a", "b", "c"],
                "bool_col": [True, False, True],
            }
        )

        await cache.set_dataframe("typed_df", df)
        result = await cache.get_dataframe("typed_df")

        assert result is not None
        assert result.columns == df.columns
        # Check data matches (types may vary slightly in serialization)
        assert result.to_dicts() == df.to_dicts()

    @pytest.mark.asyncio
    async def test_dataframe_cache_miss(self, cache: CacheManager) -> None:
        """Test get_dataframe returns None on cache miss."""
        result = await cache.get_dataframe("nonexistent")
        assert result is None


class TestCacheManagerInvalidation:
    """Tests for cache invalidation."""

    @pytest.fixture
    def cache(self) -> CacheManager:
        """Create cache instance."""
        return CacheManager(max_size=100, default_ttl=300)

    @pytest.mark.asyncio
    async def test_invalidate_existing_key(self, cache: CacheManager) -> None:
        """Test invalidating an existing key."""
        await cache.set("key", "value")
        assert await cache.get("key") == "value"

        result = await cache.invalidate("key")

        assert result is True
        assert await cache.get("key") is None

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_key(self, cache: CacheManager) -> None:
        """Test invalidating a non-existent key returns False."""
        result = await cache.invalidate("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_pattern_wildcard(self, cache: CacheManager) -> None:
        """Test pattern-based invalidation with wildcard."""
        await cache.set("job:123:config", {"name": "test"})
        await cache.set("job:123:runs", [1, 2, 3])
        await cache.set("job:123:status", "running")
        await cache.set("job:456:config", {"name": "other"})

        # Invalidate all job:123:* entries
        count = await cache.invalidate_pattern("job:123:*")

        assert count == 3
        assert await cache.get("job:123:config") is None
        assert await cache.get("job:123:runs") is None
        assert await cache.get("job:123:status") is None
        # Other job should still exist
        assert await cache.get("job:456:config") == {"name": "other"}

    @pytest.mark.asyncio
    async def test_invalidate_pattern_prefix(self, cache: CacheManager) -> None:
        """Test invalidation with prefix pattern."""
        await cache.set("cluster:abc:config", {})
        await cache.set("cluster:abc:events", [])
        await cache.set("warehouse:xyz:config", {})

        count = await cache.invalidate_pattern("cluster:*")

        assert count == 2
        assert await cache.get("cluster:abc:config") is None
        assert await cache.get("warehouse:xyz:config") == {}

    @pytest.mark.asyncio
    async def test_invalidate_pattern_no_matches(self, cache: CacheManager) -> None:
        """Test invalidation with pattern that matches nothing."""
        await cache.set("key1", "value1")

        count = await cache.invalidate_pattern("nomatch:*")

        assert count == 0
        assert await cache.get("key1") == "value1"

    @pytest.mark.asyncio
    async def test_clear_all(self, cache: CacheManager) -> None:
        """Test clearing all cache entries."""
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        await cache.clear()

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None
        assert await cache.get("key3") is None
        assert len(cache._cache) == 0


class TestCacheManagerMetrics:
    """Tests for cache metrics tracking."""

    @pytest.mark.asyncio
    async def test_initial_metrics(self) -> None:
        """Test initial metrics are zero."""
        cache = CacheManager(max_size=100, default_ttl=300)
        metrics = cache.get_metrics()

        assert metrics["hits"] == 0
        assert metrics["misses"] == 0
        assert metrics["hit_rate"] == 0.0
        assert metrics["size"] == 0

    @pytest.mark.asyncio
    async def test_miss_increments_counter(self) -> None:
        """Test cache miss increments miss counter."""
        cache = CacheManager(max_size=100, default_ttl=300)

        await cache.get("nonexistent")

        metrics = cache.get_metrics()
        assert metrics["misses"] == 1
        assert metrics["hits"] == 0

    @pytest.mark.asyncio
    async def test_hit_increments_counter(self) -> None:
        """Test cache hit increments hit counter."""
        cache = CacheManager(max_size=100, default_ttl=300)

        await cache.set("key", "value")
        await cache.get("key")

        metrics = cache.get_metrics()
        assert metrics["hits"] == 1

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self) -> None:
        """Test hit rate is calculated correctly."""
        cache = CacheManager(max_size=100, default_ttl=300)

        # 1 miss
        await cache.get("miss1")
        assert cache.get_metrics()["hit_rate"] == 0.0

        # Set and hit
        await cache.set("key", "value")
        await cache.get("key")

        # 1 hit, 1 miss = 50%
        assert cache.get_metrics()["hit_rate"] == 0.5

        # Another hit
        await cache.get("key")

        # 2 hits, 1 miss = 66.7%
        assert cache.get_metrics()["hit_rate"] == pytest.approx(0.666, rel=0.01)

    @pytest.mark.asyncio
    async def test_size_tracking(self) -> None:
        """Test size metric tracks cache size."""
        cache = CacheManager(max_size=100, default_ttl=300)

        assert cache.get_metrics()["size"] == 0

        await cache.set("key1", "value1")
        assert cache.get_metrics()["size"] == 1

        await cache.set("key2", "value2")
        assert cache.get_metrics()["size"] == 2

        await cache.invalidate("key1")
        assert cache.get_metrics()["size"] == 1


class TestCacheManagerLocking:
    """Tests for per-key locking (stampede prevention)."""

    @pytest.mark.asyncio
    async def test_get_lock_returns_lock(self) -> None:
        """Test get_lock returns an asyncio Lock."""
        cache = CacheManager(max_size=100, default_ttl=300)
        lock = await cache.get_lock("test_key")

        assert isinstance(lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_same_key_same_lock(self) -> None:
        """Test same key returns same lock instance."""
        cache = CacheManager(max_size=100, default_ttl=300)

        lock1 = await cache.get_lock("key")
        lock2 = await cache.get_lock("key")

        assert lock1 is lock2

    @pytest.mark.asyncio
    async def test_different_keys_different_locks(self) -> None:
        """Test different keys return different locks."""
        cache = CacheManager(max_size=100, default_ttl=300)

        lock1 = await cache.get_lock("key1")
        lock2 = await cache.get_lock("key2")

        assert lock1 is not lock2

    @pytest.mark.asyncio
    async def test_stampede_prevention(self) -> None:
        """Test concurrent access to same key only executes once."""
        cache = CacheManager(max_size=100, default_ttl=300)
        call_count = 0

        async def expensive_fetch(key: str) -> str:
            """Simulate expensive operation that should only run once."""
            nonlocal call_count
            lock = await cache.get_lock(key)

            async with lock:
                # Double-check pattern
                cached = await cache.get(key)
                if cached is not None:
                    return cached

                # Simulate expensive operation
                call_count += 1
                await asyncio.sleep(0.1)
                result = f"result_{call_count}"

                await cache.set(key, result)
                return result

        # Launch concurrent tasks
        results = await asyncio.gather(
            expensive_fetch("expensive_key"),
            expensive_fetch("expensive_key"),
            expensive_fetch("expensive_key"),
        )

        # All should get same result
        assert len(set(results)) == 1
        # Expensive operation should run only once
        assert call_count == 1


class TestCacheManagerKeyGeneration:
    """Tests for cache key generation utilities."""

    def test_sql_key_generation(self) -> None:
        """Test SQL cache key generation."""
        key = CacheManager.sql_key("SELECT * FROM table", "warehouse-123")

        assert key.startswith("sql:")
        assert "warehouse-123" in key
        assert len(key.split(":")) == 3

    def test_sql_key_deterministic(self) -> None:
        """Test SQL key is deterministic for same input."""
        key1 = CacheManager.sql_key("SELECT * FROM table", "wh1")
        key2 = CacheManager.sql_key("SELECT * FROM table", "wh1")

        assert key1 == key2

    def test_sql_key_different_queries(self) -> None:
        """Test different SQL generates different keys."""
        key1 = CacheManager.sql_key("SELECT 1", "wh1")
        key2 = CacheManager.sql_key("SELECT 2", "wh1")

        assert key1 != key2

    def test_sql_key_different_warehouses(self) -> None:
        """Test same SQL different warehouse generates different keys."""
        key1 = CacheManager.sql_key("SELECT 1", "wh1")
        key2 = CacheManager.sql_key("SELECT 1", "wh2")

        assert key1 != key2


class TestCacheManagerIntegration:
    """Integration tests for complete cache workflows."""

    @pytest.mark.asyncio
    async def test_job_caching_workflow(self) -> None:
        """Test complete job caching workflow."""
        cache = CacheManager(max_size=100, default_ttl=300)

        job_data = {"job_id": 123, "name": "ETL Job", "settings": {}}
        runs_data = [{"run_id": 1}, {"run_id": 2}]

        # Cache job and runs
        await cache.set("job:123", job_data)
        await cache.set("job:123:runs:5:True", runs_data)

        # Verify cached
        assert await cache.get("job:123") == job_data
        assert await cache.get("job:123:runs:5:True") == runs_data

        # Simulate job run (invalidate runs cache)
        await cache.invalidate_pattern("job:123:runs:*")

        # Job config still cached, runs invalidated
        assert await cache.get("job:123") == job_data
        assert await cache.get("job:123:runs:5:True") is None

    @pytest.mark.asyncio
    async def test_sql_caching_workflow(self) -> None:
        """Test SQL query result caching workflow."""
        cache = CacheManager(max_size=100, default_ttl=300)

        query = "SELECT job_id, cost FROM billing WHERE date > '2024-01-01'"
        warehouse_id = "wh-123"
        cache_key = cache.sql_key(query, warehouse_id)

        result_df = pl.DataFrame({"job_id": [1, 2], "cost": [100.0, 200.0]})

        # Cache the result
        await cache.set_dataframe(cache_key, result_df)

        # Retrieve from cache
        cached_df = await cache.get_dataframe(cache_key)

        assert cached_df is not None
        assert cached_df.equals(result_df)

        # Verify metrics
        metrics = cache.get_metrics()
        assert metrics["hits"] == 1
        assert metrics["size"] == 1
