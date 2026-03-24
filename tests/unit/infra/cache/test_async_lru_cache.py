"""
Unit tests for AsyncLRUCache.

Tests cover:
- Basic get/set operations
- TTL expiration
- LRU eviction
- Per-key locking (stampede prevention)
- Cache metrics
"""

import asyncio

import pytest
from starboard_server.infra.cache.async_lru_cache import AsyncLRUCache


class TestAsyncLRUCacheBasics:
    """Basic cache operations tests."""

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """Should store and retrieve values."""
        cache = AsyncLRUCache(max_size=10)

        await cache.set("key1", "value1")
        value, found = await cache.get("key1")

        assert found is True
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_get_missing_key(self):
        """Should return (None, False) for missing keys."""
        cache = AsyncLRUCache(max_size=10)

        value, found = await cache.get("nonexistent")

        assert found is False
        assert value is None

    @pytest.mark.asyncio
    async def test_overwrite_existing_key(self):
        """Should overwrite existing values."""
        cache = AsyncLRUCache(max_size=10)

        await cache.set("key1", "value1")
        await cache.set("key1", "value2")
        value, found = await cache.get("key1")

        assert found is True
        assert value == "value2"

    @pytest.mark.asyncio
    async def test_different_value_types(self):
        """Should handle various Python types."""
        cache = AsyncLRUCache(max_size=10)

        # Dict
        await cache.set("dict", {"a": 1, "b": 2})
        val, _ = await cache.get("dict")
        assert val == {"a": 1, "b": 2}

        # List
        await cache.set("list", [1, 2, 3])
        val, _ = await cache.get("list")
        assert val == [1, 2, 3]

        # None
        await cache.set("none", None)
        val, found = await cache.get("none")
        assert found is True
        assert val is None


class TestAsyncLRUCacheTTL:
    """TTL expiration tests."""

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """Entries should expire after TTL."""
        cache = AsyncLRUCache(max_size=10, default_ttl=1)  # 1 second TTL

        await cache.set("key1", "value1")

        # Should be found immediately
        value, found = await cache.get("key1")
        assert found is True

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired
        value, found = await cache.get("key1")
        assert found is False

    @pytest.mark.asyncio
    async def test_custom_ttl_override(self):
        """Should use custom TTL when specified."""
        cache = AsyncLRUCache(max_size=10, default_ttl=10)

        await cache.set("key1", "value1", ttl=1)

        await asyncio.sleep(1.1)

        value, found = await cache.get("key1")
        assert found is False

    @pytest.mark.asyncio
    async def test_ttl_does_not_reset_by_default(self):
        """TTL should NOT reset by default (opt-in behavior).

        This ensures predictable cache expiration. reset_ttl_on_hit defaults
        to False to prevent hard-to-debug cache issues.
        """
        cache = AsyncLRUCache(
            max_size=10, default_ttl=1
        )  # Uses default reset_ttl_on_hit=False

        await cache.set("key1", "value1")

        # Access before expiration
        await asyncio.sleep(0.5)
        value, found = await cache.get("key1")
        assert found is True

        # Wait for original TTL to expire
        await asyncio.sleep(0.6)
        value, found = await cache.get("key1")
        assert found is False, "Entry should expire at original TTL (no implicit reset)"

    @pytest.mark.asyncio
    async def test_ttl_reset_on_hit_when_enabled(self):
        """TTL should reset when entry is accessed and reset_ttl_on_hit=True."""
        cache = AsyncLRUCache(max_size=10, default_ttl=2, reset_ttl_on_hit=True)

        await cache.set("key1", "value1")

        # Access multiple times with delays
        for _ in range(3):
            await asyncio.sleep(1.5)  # 75% of TTL
            value, found = await cache.get("key1")
            assert found is True, (
                "Entry should not expire when accessed with reset enabled"
            )

    @pytest.mark.asyncio
    async def test_no_ttl_reset_when_explicitly_disabled(self):
        """TTL should not reset when reset_ttl_on_hit is explicitly False."""
        cache = AsyncLRUCache(max_size=10, default_ttl=2, reset_ttl_on_hit=False)

        await cache.set("key1", "value1")

        # Access before expiration
        await asyncio.sleep(1.0)
        value, found = await cache.get("key1")
        assert found is True

        # Should still expire at original time
        await asyncio.sleep(1.1)
        value, found = await cache.get("key1")
        assert found is False


class TestAsyncLRUCacheEviction:
    """LRU eviction tests."""

    @pytest.mark.asyncio
    async def test_lru_eviction_at_capacity(self):
        """Oldest entries should be evicted when max_size is reached."""
        cache = AsyncLRUCache(max_size=3, default_ttl=60)

        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        # All should be present
        assert (await cache.get("a"))[1] is True
        assert (await cache.get("b"))[1] is True
        assert (await cache.get("c"))[1] is True

        # Adding 4th entry should evict "a" (first in, now least recently used)
        await cache.set("d", 4)

        # "a" should be evicted (was LRU before "b" and "c" were accessed)
        _, found = await cache.get("a")
        assert found is False

        # Others should still be present
        assert (await cache.get("b"))[1] is True
        assert (await cache.get("c"))[1] is True
        assert (await cache.get("d"))[1] is True

    @pytest.mark.asyncio
    async def test_access_updates_lru_order(self):
        """Accessing an entry should move it to most recently used."""
        cache = AsyncLRUCache(max_size=3, default_ttl=60)

        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        # Access "a" to make it most recently used
        await cache.get("a")

        # Add new entry - should evict "b" (now LRU)
        await cache.set("d", 4)

        # "b" should be evicted
        _, found_b = await cache.get("b")
        assert found_b is False

        # "a" should still be present (was accessed after set)
        _, found_a = await cache.get("a")
        assert found_a is True


class TestAsyncLRUCacheStampede:
    """Per-key locking / stampede prevention tests."""

    @pytest.mark.asyncio
    async def test_cache_prevents_stampede(self):
        """Concurrent requests for same key should only call function once."""
        cache = AsyncLRUCache(max_size=10, default_ttl=60)
        call_count = 0

        @cache.cached()
        async def slow_function(x: int) -> int:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Simulate slow API call
            return x * 2

        # Launch 10 concurrent requests for same key
        tasks = [slow_function(42) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # All should get same result
        assert all(r == 84 for r in results)

        # Function should only be called once (single-flight)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_different_keys_execute_independently(self):
        """Different keys should execute their functions independently."""
        cache = AsyncLRUCache(max_size=10, default_ttl=60)
        call_count = 0

        @cache.cached()
        async def my_function(x: int) -> int:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return x * 2

        # Call with different keys
        results = await asyncio.gather(
            my_function(1),
            my_function(2),
            my_function(3),
        )

        assert results == [2, 4, 6]
        assert call_count == 3  # Each key called once

    @pytest.mark.asyncio
    async def test_cached_decorator_with_prefix(self):
        """Cached decorator should use key prefix."""
        cache = AsyncLRUCache(max_size=10, default_ttl=60)
        call_count = 0

        @cache.cached(key_prefix="custom")
        async def get_data(id: int) -> dict:
            nonlocal call_count
            call_count += 1
            return {"id": id}

        # First call
        result1 = await get_data(123)
        assert result1 == {"id": 123}
        assert call_count == 1

        # Second call - cached
        result2 = await get_data(123)
        assert result2 == {"id": 123}
        assert call_count == 1  # Still 1 - cache hit


class TestAsyncLRUCacheMetrics:
    """Cache metrics tests."""

    @pytest.mark.asyncio
    async def test_hit_rate_tracking(self):
        """Should track cache hit rate correctly."""
        cache = AsyncLRUCache(max_size=10, default_ttl=60)

        # Initial state
        assert cache.hit_rate == 0.0

        # Set and get (1 miss from set, 1 hit from get)
        await cache.set("key1", "value1")
        await cache.get("key1")

        metrics = cache.get_metrics()
        assert metrics["hits"] == 1
        assert metrics["misses"] == 1
        assert metrics["hit_rate"] == 0.5

        # Another hit
        await cache.get("key1")
        metrics = cache.get_metrics()
        assert metrics["hits"] == 2
        assert metrics["misses"] == 1
        assert metrics["hit_rate"] == pytest.approx(0.667, rel=0.01)

    @pytest.mark.asyncio
    async def test_metrics_include_size(self):
        """Metrics should include current cache size."""
        cache = AsyncLRUCache(max_size=10, default_ttl=60)

        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        metrics = cache.get_metrics()
        assert metrics["size"] == 3
        assert metrics["max_size"] == 10


class TestAsyncLRUCacheManagement:
    """Cache management operations tests."""

    @pytest.mark.asyncio
    async def test_clear(self):
        """Clear should remove all entries."""
        cache = AsyncLRUCache(max_size=10)

        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        await cache.clear()

        # All entries should be gone
        assert (await cache.get("a"))[1] is False
        assert (await cache.get("b"))[1] is False
        assert (await cache.get("c"))[1] is False

        metrics = cache.get_metrics()
        assert metrics["size"] == 0

    @pytest.mark.asyncio
    async def test_invalidate_single_key(self):
        """Invalidate should remove specific entry."""
        cache = AsyncLRUCache(max_size=10)

        await cache.set("a", 1)
        await cache.set("b", 2)

        result = await cache.invalidate("a")

        assert result is True
        assert (await cache.get("a"))[1] is False
        assert (await cache.get("b"))[1] is True

    @pytest.mark.asyncio
    async def test_invalidate_missing_key(self):
        """Invalidate should return False for missing key."""
        cache = AsyncLRUCache(max_size=10)

        result = await cache.invalidate("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_prefix(self):
        """Invalidate prefix should remove all matching entries."""
        cache = AsyncLRUCache(max_size=10)

        await cache.set("user:1", {"name": "Alice"})
        await cache.set("user:2", {"name": "Bob"})
        await cache.set("order:1", {"total": 100})

        count = await cache.invalidate_prefix("user:")

        assert count == 2
        assert (await cache.get("user:1"))[1] is False
        assert (await cache.get("user:2"))[1] is False
        assert (await cache.get("order:1"))[1] is True


class TestAsyncLRUCacheKeyBuilding:
    """Cache key building tests."""

    @pytest.mark.asyncio
    async def test_key_builder_args_variation(self):
        """Different args should produce different cache keys."""
        cache = AsyncLRUCache(max_size=10, default_ttl=60)
        call_count = 0

        @cache.cached()
        async def get_item(id: int, version: str) -> dict:
            nonlocal call_count
            call_count += 1
            return {"id": id, "version": version}

        await get_item(1, "v1")
        await get_item(1, "v2")  # Different args = different key
        await get_item(2, "v1")  # Different args = different key

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_custom_key_builder(self):
        """Should use custom key builder when provided."""
        cache = AsyncLRUCache(max_size=10, default_ttl=60)

        def my_key_builder(user_id: int, **kwargs) -> str:
            return f"user:{user_id}"

        @cache.cached(key_builder=my_key_builder)
        async def get_user(user_id: int, include_details: bool = False) -> dict:
            return {"id": user_id, "details": include_details}

        # Same user_id with different kwargs should hit cache
        await get_user(123, include_details=False)
        await get_user(123, include_details=True)  # Same key due to custom builder

        metrics = cache.get_metrics()
        # 1 miss (first call) + 1 hit (second call)
        assert metrics["hits"] == 1
        assert metrics["misses"] == 1
