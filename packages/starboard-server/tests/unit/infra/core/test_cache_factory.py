# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for CacheFactory.

Tests verify:
- Namespace creation and uniqueness
- Cache retrieval methods
- Metrics aggregation across namespaces
- Store sharing between namespaces
"""

from __future__ import annotations

import pytest
from starboard_core.ports.cache_store import CacheMetrics
from starboard_server.adapters.state.inmemory.cache_store import InMemoryCacheStore
from starboard_server.infra.core.cache_factory import CacheFactory
from starboard_server.infra.core.namespaced_cache import NamespacedCache


class TestCacheFactory:
    """Test suite for CacheFactory."""

    @pytest.fixture
    def store(self) -> InMemoryCacheStore:
        """Create a fresh in-memory cache store."""
        return InMemoryCacheStore()

    @pytest.fixture
    def factory(self, store: InMemoryCacheStore) -> CacheFactory:
        """Create a cache factory with the store."""
        return CacheFactory(_base_store=store)

    # -------------------------------------------------------------------------
    # Namespace Creation Tests
    # -------------------------------------------------------------------------

    def test_create_returns_namespaced_cache(self, factory: CacheFactory) -> None:
        """create() should return NamespacedCache instance."""
        cache = factory.create("test")
        assert isinstance(cache, NamespacedCache)

    def test_create_sets_correct_namespace(self, factory: CacheFactory) -> None:
        """create() should set the correct namespace."""
        cache = factory.create("catalog")
        assert cache.namespace == "catalog"

    def test_create_duplicate_namespace_raises(self, factory: CacheFactory) -> None:
        """create() should raise ValueError for duplicate namespace."""
        factory.create("test")

        with pytest.raises(ValueError, match="already exists"):
            factory.create("test")

    def test_create_registers_namespace(self, factory: CacheFactory) -> None:
        """create() should register namespace in list."""
        factory.create("ns1")
        factory.create("ns2")

        namespaces = factory.list_namespaces()
        assert "ns1" in namespaces
        assert "ns2" in namespaces

    # -------------------------------------------------------------------------
    # Namespace Retrieval Tests
    # -------------------------------------------------------------------------

    def test_get_cache_returns_existing(self, factory: CacheFactory) -> None:
        """get_cache() should return existing cache."""
        created = factory.create("test")
        retrieved = factory.get_cache("test")

        assert retrieved is created

    def test_get_cache_returns_none_for_missing(self, factory: CacheFactory) -> None:
        """get_cache() should return None for missing namespace."""
        result = factory.get_cache("nonexistent")
        assert result is None

    def test_get_or_create_creates_new(self, factory: CacheFactory) -> None:
        """get_or_create() should create cache if not exists."""
        cache = factory.get_or_create("new_ns")

        assert cache is not None
        assert cache.namespace == "new_ns"
        assert "new_ns" in factory.list_namespaces()

    def test_get_or_create_returns_existing(self, factory: CacheFactory) -> None:
        """get_or_create() should return existing cache."""
        created = factory.create("test")
        retrieved = factory.get_or_create("test")

        assert retrieved is created

    def test_get_or_create_idempotent(self, factory: CacheFactory) -> None:
        """get_or_create() should be idempotent."""
        cache1 = factory.get_or_create("test")
        cache2 = factory.get_or_create("test")
        cache3 = factory.get_or_create("test")

        assert cache1 is cache2 is cache3

    # -------------------------------------------------------------------------
    # Namespace Listing Tests
    # -------------------------------------------------------------------------

    def test_list_namespaces_empty(self, factory: CacheFactory) -> None:
        """list_namespaces() should return empty list initially."""
        assert factory.list_namespaces() == []

    def test_list_namespaces_sorted(self, factory: CacheFactory) -> None:
        """list_namespaces() should return sorted list."""
        factory.create("z_last")
        factory.create("a_first")
        factory.create("m_middle")

        assert factory.list_namespaces() == ["a_first", "m_middle", "z_last"]

    # -------------------------------------------------------------------------
    # Store Sharing Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_caches_share_store(
        self, factory: CacheFactory, store: InMemoryCacheStore
    ) -> None:
        """All namespaced caches should share the same store."""
        cache1 = factory.create("ns1")
        cache2 = factory.create("ns2")

        await cache1.set("key", "from_ns1")
        await cache2.set("key", "from_ns2")

        # Both should be in the underlying store
        assert await store.get("ns1:key") == "from_ns1"
        assert await store.get("ns2:key") == "from_ns2"

    @pytest.mark.asyncio
    async def test_namespaces_isolated(self, factory: CacheFactory) -> None:
        """Namespaces should be isolated from each other."""
        cache1 = factory.create("ns1")
        cache2 = factory.create("ns2")

        await cache1.set("key", "value1")
        await cache2.set("key", "value2")

        assert await cache1.get("key") == "value1"
        assert await cache2.get("key") == "value2"

    # -------------------------------------------------------------------------
    # Metrics Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_all_metrics(self, factory: CacheFactory) -> None:
        """get_all_metrics() should return metrics for all namespaces."""
        cache1 = factory.create("ns1")
        cache2 = factory.create("ns2")

        await cache1.set("key", "value")
        await cache1.get("key")  # hit
        await cache2.get("missing")  # miss

        metrics = factory.get_all_metrics()

        assert "ns1" in metrics
        assert "ns2" in metrics
        assert metrics["ns1"].hits == 1
        assert metrics["ns2"].misses == 1

    @pytest.mark.asyncio
    async def test_get_all_metrics_returns_cache_metrics(
        self, factory: CacheFactory
    ) -> None:
        """get_all_metrics() should return CacheMetrics instances."""
        factory.create("test")
        metrics = factory.get_all_metrics()

        assert isinstance(metrics["test"], CacheMetrics)

    def test_get_aggregate_metrics_empty(self, factory: CacheFactory) -> None:
        """get_aggregate_metrics() should return empty metrics when no caches."""
        metrics = factory.get_aggregate_metrics()

        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.hit_rate == 0.0

    @pytest.mark.asyncio
    async def test_get_aggregate_metrics(self, factory: CacheFactory) -> None:
        """get_aggregate_metrics() should aggregate across all namespaces."""
        cache1 = factory.create("ns1")
        cache2 = factory.create("ns2")

        await cache1.set("key", "value")
        # ns1: 2 hits
        await cache1.get("key")
        await cache1.get("key")

        # ns2: 3 misses
        await cache2.get("missing1")
        await cache2.get("missing2")
        await cache2.get("missing3")

        metrics = factory.get_aggregate_metrics()

        assert metrics.hits == 2
        assert metrics.misses == 3
        assert metrics.hit_rate == 0.4  # 2 / 5

    # -------------------------------------------------------------------------
    # Clear All Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_clear_all(self, factory: CacheFactory) -> None:
        """clear_all() should clear entire store."""
        cache1 = factory.create("ns1")
        cache2 = factory.create("ns2")

        await cache1.set("key1", "value1")
        await cache2.set("key2", "value2")

        await factory.clear_all()

        assert await cache1.get("key1") is None
        assert await cache2.get("key2") is None

    @pytest.mark.asyncio
    async def test_clear_all_resets_metrics(self, factory: CacheFactory) -> None:
        """clear_all() should reset all cache metrics."""
        cache1 = factory.create("ns1")
        cache2 = factory.create("ns2")

        # Generate some metrics
        await cache1.set("key", "value")
        await cache1.get("key")
        await cache2.get("missing")

        await factory.clear_all()

        metrics = factory.get_aggregate_metrics()
        assert metrics.hits == 0
        assert metrics.misses == 0

    # -------------------------------------------------------------------------
    # Edge Cases
    # -------------------------------------------------------------------------

    def test_default_ttl_accepted(self, factory: CacheFactory) -> None:
        """create() should accept default_ttl parameter."""
        # default_ttl is reserved for future use but should not raise
        cache = factory.create("test", default_ttl=300)
        assert cache.namespace == "test"

    @pytest.mark.asyncio
    async def test_multiple_factories_same_store(
        self, store: InMemoryCacheStore
    ) -> None:
        """Multiple factories with same store should share data."""
        factory1 = CacheFactory(_base_store=store)
        factory2 = CacheFactory(_base_store=store)

        cache1 = factory1.create("ns")
        await cache1.set("key", "from_factory1")

        # factory2 creates same namespace (different factory, same store)
        cache2 = factory2.create("ns")

        # Should see the data (same underlying store)
        assert await cache2.get("key") == "from_factory1"
