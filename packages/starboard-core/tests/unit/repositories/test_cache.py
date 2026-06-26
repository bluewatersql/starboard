# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for CacheManager repository.

Tests cover:
- Key generation (deterministic hashing)
- Cache get/set operations
- Cache miss handling with compute function
- TTL handling
- Invalidation
- Clear all functionality
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.repositories.cache import CacheManager


class TestCacheManagerKeyGeneration:
    """Tests for deterministic key generation."""

    def test_generate_key_simple(self):
        """Test generating key with simple params."""
        store = MagicMock()
        manager = CacheManager(store)

        key = manager.generate_key("tool:search", query="test")

        assert key.startswith("tool:search:")
        assert len(key) == len("tool:search:") + 16  # 16 hex chars

    def test_generate_key_deterministic(self):
        """Test that same params always generate same key."""
        store = MagicMock()
        manager = CacheManager(store)

        key1 = manager.generate_key("prefix", a=1, b="two")
        key2 = manager.generate_key("prefix", a=1, b="two")

        assert key1 == key2

    def test_generate_key_order_independent(self):
        """Test that key is independent of param order."""
        store = MagicMock()
        manager = CacheManager(store)

        key1 = manager.generate_key("prefix", a=1, b=2, c=3)
        key2 = manager.generate_key("prefix", c=3, a=1, b=2)

        assert key1 == key2

    def test_generate_key_different_prefixes(self):
        """Test that different prefixes generate different keys."""
        store = MagicMock()
        manager = CacheManager(store)

        key1 = manager.generate_key("prefix1", query="test")
        key2 = manager.generate_key("prefix2", query="test")

        assert key1 != key2

    def test_generate_key_different_params(self):
        """Test that different params generate different keys."""
        store = MagicMock()
        manager = CacheManager(store)

        key1 = manager.generate_key("prefix", query="test1")
        key2 = manager.generate_key("prefix", query="test2")

        assert key1 != key2

    def test_generate_key_complex_params(self):
        """Test key generation with complex nested params."""
        store = MagicMock()
        manager = CacheManager(store)

        key = manager.generate_key(
            "tool:analyze",
            filters={"type": "job", "status": "running"},
            options=["verbose", "detailed"],
        )

        assert key.startswith("tool:analyze:")
        assert len(key) == len("tool:analyze:") + 16


class TestCacheManagerGetOrCompute:
    """Tests for get_or_compute caching logic."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_value(self):
        """Test that cache hit returns value without calling compute."""
        store = AsyncMock()
        store.get.return_value = "cached_result"
        manager = CacheManager(store)

        compute_fn = AsyncMock(return_value="new_result")

        result = await manager.get_or_compute("key", compute_fn)

        assert result == "cached_result"
        store.get.assert_called_once_with("key")
        compute_fn.assert_not_called()
        store.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_computes_and_stores(self):
        """Test that cache miss calls compute and stores result."""
        store = AsyncMock()
        store.get.return_value = None
        manager = CacheManager(store, default_ttl=300)

        compute_fn = AsyncMock(return_value="computed_result")

        result = await manager.get_or_compute("key", compute_fn)

        assert result == "computed_result"
        store.get.assert_called_once_with("key")
        compute_fn.assert_called_once()
        store.set.assert_called_once_with("key", "computed_result", 300)

    @pytest.mark.asyncio
    async def test_cache_miss_with_custom_ttl(self):
        """Test that custom TTL overrides default."""
        store = AsyncMock()
        store.get.return_value = None
        manager = CacheManager(store, default_ttl=300)

        compute_fn = AsyncMock(return_value="result")

        await manager.get_or_compute("key", compute_fn, ttl=600)

        store.set.assert_called_once_with("key", "result", 600)

    @pytest.mark.asyncio
    async def test_cache_miss_with_zero_ttl(self):
        """Test that zero TTL is respected (no expiration override)."""
        store = AsyncMock()
        store.get.return_value = None
        manager = CacheManager(store, default_ttl=300)

        compute_fn = AsyncMock(return_value="result")

        await manager.get_or_compute("key", compute_fn, ttl=0)

        store.set.assert_called_once_with("key", "result", 0)

    @pytest.mark.asyncio
    async def test_compute_fn_receives_no_args(self):
        """Test that compute function is called with no arguments."""
        store = AsyncMock()
        store.get.return_value = None
        manager = CacheManager(store)

        async def compute():
            return {"data": "test"}

        compute_mock = AsyncMock(side_effect=compute)

        await manager.get_or_compute("key", compute_mock)

        compute_mock.assert_called_once_with()


class TestCacheManagerInvalidate:
    """Tests for cache invalidation."""

    @pytest.mark.asyncio
    async def test_invalidate_existing_key(self):
        """Test invalidating an existing key."""
        store = AsyncMock()
        store.delete.return_value = True
        manager = CacheManager(store)

        result = await manager.invalidate("key")

        assert result is True
        store.delete.assert_called_once_with("key")

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_key(self):
        """Test invalidating a non-existent key."""
        store = AsyncMock()
        store.delete.return_value = False
        manager = CacheManager(store)

        result = await manager.invalidate("nonexistent")

        assert result is False
        store.delete.assert_called_once_with("nonexistent")


class TestCacheManagerClearAll:
    """Tests for clearing all cache."""

    @pytest.mark.asyncio
    async def test_clear_all(self):
        """Test clearing all cached values."""
        store = AsyncMock()
        manager = CacheManager(store)

        await manager.clear_all()

        store.clear.assert_called_once()


class TestCacheManagerInitialization:
    """Tests for CacheManager initialization."""

    def test_default_ttl(self):
        """Test default TTL is 300 seconds."""
        store = MagicMock()
        manager = CacheManager(store)

        assert manager._default_ttl == 300

    def test_custom_default_ttl(self):
        """Test custom default TTL."""
        store = MagicMock()
        manager = CacheManager(store, default_ttl=600)

        assert manager._default_ttl == 600
