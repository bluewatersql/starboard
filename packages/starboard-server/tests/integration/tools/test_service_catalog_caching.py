# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for ServiceCatalogTool caching.

Tests caching behavior, TTL, cache hits/misses, and performance.
Part of Phase 9: Service Catalog & Next-Step Suggestions
Updated in Phase 3 of caching abstraction for async support.
"""

import asyncio

import pytest
from starboard_server.adapters.state.inmemory.cache_store import InMemoryCacheStore
from starboard_server.domain.models.service_catalog import (
    ServiceCatalogEntry,
    ServiceStatus,
    ServiceType,
)
from starboard_server.infra.constraints.catalog_cache import CatalogCache
from starboard_server.tools.service_catalog_tool import ServiceCatalogTool


class TestCatalogCache:
    """Test CatalogCache functionality (async)."""

    @pytest.fixture
    def cache_store(self) -> InMemoryCacheStore:
        """Create a fresh in-memory cache store."""
        return InMemoryCacheStore()

    @pytest.fixture
    def cache(self, cache_store: InMemoryCacheStore) -> CatalogCache:
        """Create a CatalogCache with default TTL."""
        return CatalogCache(store=cache_store, ttl_seconds=300)

    @pytest.mark.asyncio
    async def test_cache_get_miss_returns_none(self, cache: CatalogCache) -> None:
        """Test that cache miss returns None."""
        result = await cache.get("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_set_and_get_hit(self, cache: CatalogCache) -> None:
        """Test setting and getting cached value."""
        test_data = [{"service_id": "test", "name": "Test Service"}]
        await cache.set("test_key", test_data)

        result = await cache.get("test_key")

        assert result == test_data

    @pytest.mark.asyncio
    async def test_cache_expiration_after_ttl(
        self, cache_store: InMemoryCacheStore
    ) -> None:
        """Test that cache entries expire after TTL."""
        cache = CatalogCache(store=cache_store, ttl_seconds=1)  # 1 second TTL

        test_data = [{"service_id": "test"}]
        await cache.set("test_key", test_data)

        # Immediately should return the value
        assert await cache.get("test_key") == test_data

        # Wait for TTL to expire
        await asyncio.sleep(1.1)

        # Now should return None (expired)
        assert await cache.get("test_key") is None

    @pytest.mark.asyncio
    async def test_cache_clear(self, cache: CatalogCache) -> None:
        """Test clearing the cache."""
        await cache.set("key1", ["data1"])
        await cache.set("key2", ["data2"])

        await cache.clear()

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    @pytest.mark.asyncio
    async def test_cache_hit_rate_tracking(self, cache: CatalogCache) -> None:
        """Test that cache tracks hit rate."""
        await cache.set("key1", ["data1"])

        await cache.get("nonexistent")  # Miss
        await cache.get("key1")  # Hit
        await cache.get("key1")  # Hit

        stats = cache.get_stats()

        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.666, rel=0.01)

    def test_cache_key_generation(self, cache: CatalogCache) -> None:
        """Test generating consistent cache keys."""
        key1 = cache.generate_key(domain="performance", service_type="agent")
        key2 = cache.generate_key(domain="performance", service_type="agent")
        key3 = cache.generate_key(domain="finops", service_type="agent")

        # Same params should generate same key
        assert key1 == key2

        # Different params should generate different key
        assert key1 != key3

    def test_cache_key_handles_none_values(self, cache: CatalogCache) -> None:
        """Test that cache key generation handles None values."""
        key1 = cache.generate_key(domain=None, service_type=None)
        key2 = cache.generate_key(domain=None, service_type=None)
        key3 = cache.generate_key(domain="performance", service_type=None)

        # Same None params should match
        assert key1 == key2

        # Different params (even with None) should differ
        assert key1 != key3

    @pytest.mark.asyncio
    async def test_cache_exists(self, cache: CatalogCache) -> None:
        """Test checking if key exists in cache."""
        await cache.set("key1", ["data1"])

        assert await cache.exists("key1") is True
        assert await cache.exists("nonexistent") is False

    @pytest.mark.asyncio
    async def test_cache_delete(self, cache: CatalogCache) -> None:
        """Test deleting a specific cache entry."""
        await cache.set("key1", ["data1"])
        assert await cache.get("key1") == ["data1"]

        deleted = await cache.delete("key1")
        assert deleted is True
        assert await cache.get("key1") is None

        # Deleting non-existent key returns False
        deleted = await cache.delete("nonexistent")
        assert deleted is False


class TestServiceCatalogToolWithCaching:
    """Test ServiceCatalogTool with caching enabled (async)."""

    def test_tool_with_cache_enabled(self) -> None:
        """Test creating tool with caching enabled."""
        tool = ServiceCatalogTool(enable_cache=True, cache_ttl=300)
        assert tool.cache is not None

    def test_tool_with_cache_disabled(self) -> None:
        """Test creating tool with caching disabled."""
        tool = ServiceCatalogTool(enable_cache=False)
        assert tool.cache is None

    def test_tool_default_has_cache_enabled(self) -> None:
        """Test that tool has caching enabled by default."""
        tool = ServiceCatalogTool()
        assert tool.cache is not None

    def test_tool_accepts_custom_cache_store(self) -> None:
        """Test that tool accepts a custom cache store."""
        store = InMemoryCacheStore()
        tool = ServiceCatalogTool(enable_cache=True, cache_store=store)

        assert tool.cache is not None
        # The cache should use our store
        assert tool.cache._store is store

    @pytest.mark.asyncio
    async def test_cache_hit_on_repeated_call(self) -> None:
        """Test that repeated calls hit the cache."""
        entries = [
            ServiceCatalogEntry(
                service_id="test_service",
                service_type=ServiceType.AGENT,
                name="Test Service",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
        ]

        tool = ServiceCatalogTool(initial_entries=entries, enable_cache=True)

        # First call - cache miss
        result1 = await tool.get_entries_cached(domain="test")

        # Second call - should be cache hit
        result2 = await tool.get_entries_cached(domain="test")

        assert result1 == result2
        assert tool.cache.get_stats()["hits"] >= 1

    @pytest.mark.asyncio
    async def test_cache_miss_on_first_call(self) -> None:
        """Test that first call is a cache miss."""
        entries = [
            ServiceCatalogEntry(
                service_id="test_service",
                service_type=ServiceType.AGENT,
                name="Test",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
        ]

        tool = ServiceCatalogTool(initial_entries=entries, enable_cache=True)

        # First call should be cache miss
        result = await tool.get_entries_cached(domain="test")

        assert len(result) == 1
        assert tool.cache.get_stats()["misses"] >= 1

    @pytest.mark.asyncio
    async def test_cache_different_keys_for_different_filters(self) -> None:
        """Test that different filter combinations use different cache keys."""
        entries = [
            ServiceCatalogEntry(
                service_id="perf_agent",
                service_type=ServiceType.AGENT,
                name="Performance Agent",
                domain="performance",
                description="Perf",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="finops_agent",
                service_type=ServiceType.AGENT,
                name="FinOps Agent",
                domain="finops",
                description="Cost",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]

        tool = ServiceCatalogTool(initial_entries=entries, enable_cache=True)

        # Call with different filters
        perf_result = await tool.get_entries_cached(domain="performance")
        finops_result = await tool.get_entries_cached(domain="finops")

        assert len(perf_result) == 1
        assert perf_result[0]["domain"] == "performance"
        assert len(finops_result) == 1
        assert finops_result[0]["domain"] == "finops"

    @pytest.mark.asyncio
    async def test_cache_hit_rate_exceeds_target(self) -> None:
        """Test that cache hit rate exceeds 80% after warmup."""
        entries = [
            ServiceCatalogEntry(
                service_id=f"service_{i}",
                service_type=ServiceType.AGENT,
                name=f"Service {i}",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
            for i in range(3)
        ]

        tool = ServiceCatalogTool(initial_entries=entries, enable_cache=True)

        # Make 10 calls with same filters (first is miss, rest are hits)
        for _ in range(10):
            await tool.get_entries_cached(domain="test")

        stats = tool.cache.get_stats()
        hit_rate = stats["hit_rate"]

        # After 10 calls (1 miss, 9 hits), hit rate should be 90%
        assert hit_rate > 0.8, f"Hit rate {hit_rate} should exceed 80%"

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_register(self) -> None:
        """Test that cache is invalidated when new entry is registered."""
        tool = ServiceCatalogTool(enable_cache=True)

        # Initial call
        result1 = await tool.get_entries_cached()
        assert len(result1) == 0

        # Register new entry
        new_entry = ServiceCatalogEntry(
            service_id="new_service",
            service_type=ServiceType.AGENT,
            name="New Service",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        tool.register_entry(new_entry)
        await tool.invalidate_cache()  # Async cache invalidation

        # Cache should be cleared, next call should reflect new entry
        result2 = await tool.get_entries_cached()
        assert len(result2) == 1

    @pytest.mark.asyncio
    async def test_cache_performance_improvement(self) -> None:
        """Test that cache provides consistent results."""
        # Create many entries
        entries = [
            ServiceCatalogEntry(
                service_id=f"service_{i}",
                service_type=ServiceType.AGENT,
                name=f"Service {i}",
                domain=f"domain_{i % 3}",  # 3 different domains
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
            for i in range(100)
        ]

        tool = ServiceCatalogTool(initial_entries=entries, enable_cache=True)

        # First call (cache miss)
        result1 = await tool.get_entries_cached(domain="domain_1")

        # Second call (cache hit)
        result2 = await tool.get_entries_cached(domain="domain_1")

        # Results should be identical
        assert result1 == result2
        assert len(result1) > 0

        # Verify cache was actually used
        stats = tool.cache.get_stats()
        assert stats["hits"] >= 1

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration_forces_refresh(self) -> None:
        """Test that expired cache entries are refreshed."""
        entries = [
            ServiceCatalogEntry(
                service_id="test_service",
                service_type=ServiceType.AGENT,
                name="Test",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
        ]

        # Very short TTL for testing
        tool = ServiceCatalogTool(
            initial_entries=entries, enable_cache=True, cache_ttl=1
        )

        # First call
        result1 = await tool.get_entries_cached(domain="test")
        assert len(result1) == 1

        # Wait for TTL to expire
        await asyncio.sleep(1.1)

        # Second call should refresh (cache miss due to expiration)
        result2 = await tool.get_entries_cached(domain="test")
        assert len(result2) == 1

        # Both results should have same content
        assert result1[0]["service_id"] == result2[0]["service_id"]

    @pytest.mark.asyncio
    async def test_get_entries_cached_without_cache(self) -> None:
        """Test that get_entries_cached works when cache is disabled."""
        entries = [
            ServiceCatalogEntry(
                service_id="test_service",
                service_type=ServiceType.AGENT,
                name="Test",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
        ]

        tool = ServiceCatalogTool(initial_entries=entries, enable_cache=False)

        # Should still work, just not use cache
        result = await tool.get_entries_cached(domain="test")
        assert len(result) == 1
