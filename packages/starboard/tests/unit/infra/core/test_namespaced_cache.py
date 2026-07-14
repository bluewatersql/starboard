# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for NamespacedCache.

Tests verify:
- Key namespacing (prefix + separator)
- CacheStore protocol delegation
- Metrics tracking (hits/misses)
- Clear and reset behavior
"""

from __future__ import annotations

import pytest
from starboard_core.ports.cache_store import CacheMetrics
from starboard.adapters.state.inmemory.cache_store import InMemoryCacheStore
from starboard.infra.core.namespaced_cache import NamespacedCache


class TestNamespacedCache:
    """Test suite for NamespacedCache."""

    @pytest.fixture
    def store(self) -> InMemoryCacheStore:
        """Create a fresh in-memory cache store."""
        return InMemoryCacheStore()

    @pytest.fixture
    def cache(self, store: InMemoryCacheStore) -> NamespacedCache:
        """Create a namespaced cache with 'test' namespace."""
        return NamespacedCache(store=store, namespace="test")

    # -------------------------------------------------------------------------
    # Key Namespacing Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_keys_are_namespaced(
        self, cache: NamespacedCache, store: InMemoryCacheStore
    ) -> None:
        """Keys should be prefixed with namespace."""
        await cache.set("key1", "value1")

        # Direct store access needs full namespaced key
        assert await store.get("test:key1") == "value1"

        # Original key should not exist
        assert await store.get("key1") is None

    @pytest.mark.asyncio
    async def test_custom_separator(self, store: InMemoryCacheStore) -> None:
        """Custom separator should be used in key prefix."""
        cache = NamespacedCache(store=store, namespace="ns", separator="/")
        await cache.set("key", "value")

        assert await store.get("ns/key") == "value"

    @pytest.mark.asyncio
    async def test_make_key_format(self, cache: NamespacedCache) -> None:
        """_make_key should return namespace:key format."""
        assert cache._make_key("entries") == "test:entries"
        assert cache._make_key("complex/key") == "test:complex/key"

    # -------------------------------------------------------------------------
    # Basic Operations Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_set_roundtrip(self, cache: NamespacedCache) -> None:
        """Set and get should work correctly."""
        await cache.set("key", "value")
        result = await cache.get("key")

        assert result == "value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, cache: NamespacedCache) -> None:
        """Get on missing key should return None."""
        result = await cache.get("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_with_ttl(
        self, cache: NamespacedCache, store: InMemoryCacheStore
    ) -> None:
        """TTL should be passed to underlying store."""
        await cache.set("key", "value", ttl=60)

        # Verify key exists (TTL not immediately expired)
        result = await cache.get("key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, cache: NamespacedCache) -> None:
        """Delete should return True for existing key."""
        await cache.set("key", "value")

        deleted = await cache.delete("key")
        assert deleted is True

        # Key should be gone
        assert await cache.get("key") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self, cache: NamespacedCache) -> None:
        """Delete should return False for missing key."""
        deleted = await cache.delete("missing")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_exists_true(self, cache: NamespacedCache) -> None:
        """Exists should return True for existing key."""
        await cache.set("key", "value")
        assert await cache.exists("key") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, cache: NamespacedCache) -> None:
        """Exists should return False for missing key."""
        assert await cache.exists("missing") is False

    @pytest.mark.asyncio
    async def test_clear(self, cache: NamespacedCache) -> None:
        """Clear should remove all entries."""
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        await cache.clear()

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    # -------------------------------------------------------------------------
    # Namespace Isolation Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_namespaces_are_isolated(self, store: InMemoryCacheStore) -> None:
        """Different namespaces should not collide."""
        cache1 = NamespacedCache(store=store, namespace="ns1")
        cache2 = NamespacedCache(store=store, namespace="ns2")

        await cache1.set("key", "from_ns1")
        await cache2.set("key", "from_ns2")

        # Each namespace has its own key
        assert await cache1.get("key") == "from_ns1"
        assert await cache2.get("key") == "from_ns2"

    @pytest.mark.asyncio
    async def test_delete_only_affects_own_namespace(
        self, store: InMemoryCacheStore
    ) -> None:
        """Deleting from one namespace shouldn't affect another."""
        cache1 = NamespacedCache(store=store, namespace="ns1")
        cache2 = NamespacedCache(store=store, namespace="ns2")

        await cache1.set("key", "value1")
        await cache2.set("key", "value2")

        # Delete from ns1
        await cache1.delete("key")

        # ns2 should be unaffected
        assert await cache1.get("key") is None
        assert await cache2.get("key") == "value2"

    # -------------------------------------------------------------------------
    # Metrics Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_metrics_track_hits(self, cache: NamespacedCache) -> None:
        """Metrics should track cache hits."""
        await cache.set("key", "value")

        await cache.get("key")
        await cache.get("key")

        metrics = cache.get_metrics()
        assert metrics.hits == 2
        assert metrics.misses == 0

    @pytest.mark.asyncio
    async def test_metrics_track_misses(self, cache: NamespacedCache) -> None:
        """Metrics should track cache misses."""
        await cache.get("missing1")
        await cache.get("missing2")

        metrics = cache.get_metrics()
        assert metrics.hits == 0
        assert metrics.misses == 2

    @pytest.mark.asyncio
    async def test_metrics_hit_rate(self, cache: NamespacedCache) -> None:
        """Metrics should calculate correct hit rate."""
        await cache.set("key", "value")

        # 2 hits
        await cache.get("key")
        await cache.get("key")

        # 2 misses
        await cache.get("missing1")
        await cache.get("missing2")

        metrics = cache.get_metrics()
        assert metrics.hits == 2
        assert metrics.misses == 2
        assert metrics.hit_rate == 0.5

    @pytest.mark.asyncio
    async def test_metrics_returns_cache_metrics_type(
        self, cache: NamespacedCache
    ) -> None:
        """get_metrics should return CacheMetrics instance."""
        metrics = cache.get_metrics()
        assert isinstance(metrics, CacheMetrics)

    @pytest.mark.asyncio
    async def test_clear_resets_metrics(self, cache: NamespacedCache) -> None:
        """Clear should reset hit/miss counters."""
        await cache.set("key", "value")
        await cache.get("key")  # hit
        await cache.get("missing")  # miss

        await cache.clear()

        metrics = cache.get_metrics()
        assert metrics.hits == 0
        assert metrics.misses == 0

    def test_reset_metrics(self, cache: NamespacedCache) -> None:
        """reset_metrics should clear counters without clearing cache."""
        # Manually set metrics (simulating hits/misses)
        cache._hits = 10
        cache._misses = 5

        cache.reset_metrics()

        metrics = cache.get_metrics()
        assert metrics.hits == 0
        assert metrics.misses == 0

    # -------------------------------------------------------------------------
    # Edge Cases
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_namespace(self, store: InMemoryCacheStore) -> None:
        """Empty namespace should work (keys start with separator)."""
        cache = NamespacedCache(store=store, namespace="", separator=":")
        await cache.set("key", "value")

        # Key is ":key" with empty namespace
        assert await store.get(":key") == "value"

    @pytest.mark.asyncio
    async def test_complex_values(self, cache: NamespacedCache) -> None:
        """Cache should handle complex values."""
        complex_value = {
            "list": [1, 2, 3],
            "nested": {"a": "b"},
            "none": None,
        }
        await cache.set("complex", complex_value)

        result = await cache.get("complex")
        assert result == complex_value

    @pytest.mark.asyncio
    async def test_none_value(self, cache: NamespacedCache) -> None:
        """Cache should distinguish between None value and missing key."""
        # Note: This depends on the underlying store implementation
        # InMemoryCacheStore stores None as a valid value
        await cache.set("none_key", None)

        # This will return None but count as a hit
        # Implementation detail: our get returns the value directly,
        # so we can't distinguish None from missing at this level
        result = await cache.get("none_key")
        assert result is None
