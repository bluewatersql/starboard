# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for SharedContextProvider."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from starboard.services.context.provider import (
    ContextCache,
    SharedContextProvider,
)


class TestContextCache:
    """Tests for ContextCache class."""

    def test_cache_get_miss(self):
        """Test cache miss increments miss counter."""
        cache = ContextCache()
        result, found = cache.get("nonexistent")

        assert result is None
        assert not found
        assert cache.misses == 1
        assert cache.hits == 0

    def test_cache_get_hit(self):
        """Test cache hit increments hit counter."""
        cache = ContextCache()
        cache.put("key", "value")
        result, found = cache.get("key")

        assert result == "value"
        assert found
        assert cache.hits == 1
        assert cache.misses == 0

    def test_cache_put(self):
        """Test putting values in cache."""
        cache = ContextCache()
        cache.put("key", {"data": "test"})

        result, found = cache.get("key")
        assert result == {"data": "test"}
        assert found

    def test_cache_clear(self):
        """Test clearing cache."""
        cache = ContextCache()
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.get("key1")  # Hit
        cache.get("nonexistent")  # Miss

        cache.clear()

        result, found = cache.get("key1")
        assert result is None
        assert not found
        assert cache.hits == 0
        assert cache.misses == 1  # From the get after clear
        assert len(cache.data) == 0

    def test_cache_stats(self):
        """Test cache statistics."""
        cache = ContextCache()
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.get("key1")  # Hit
        cache.get("key2")  # Hit
        cache.get("nonexistent")  # Miss

        stats = cache.stats()

        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["total"] == 3
        assert stats["hit_rate"] == pytest.approx(66.67, rel=0.01)
        assert stats["size"] == 2

    def test_cache_stats_empty(self):
        """Test cache statistics when empty."""
        cache = ContextCache()
        stats = cache.stats()

        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["total"] == 0
        assert stats["hit_rate"] == 0
        assert stats["size"] == 0


class TestSharedContextProvider:
    """Tests for SharedContextProvider class."""

    @pytest.fixture
    def mock_api(self) -> MagicMock:
        """Create a mock Databricks API."""
        return MagicMock()

    @pytest.fixture
    def provider(self, mock_api: MagicMock) -> SharedContextProvider:
        """Create SharedContextProvider with mock API."""
        return SharedContextProvider(mock_api)

    @pytest.mark.asyncio
    async def test_get_cached_value(self, provider: SharedContextProvider):
        """Test getting a cached value."""
        # Pre-populate cache
        provider.cache.put("table_metadata::my_table", {"columns": ["id", "name"]})

        result = await provider.get("table_metadata", "my_table")

        assert result == {"columns": ["id", "name"]}
        assert provider.cache.hits == 1

    @pytest.mark.asyncio
    async def test_get_from_fetcher(
        self, provider: SharedContextProvider, mock_api: MagicMock
    ):
        """Test getting value from fetcher on cache miss."""
        # Mock the fetcher
        fetcher_result = {"table_name": "my_table", "columns": ["id"]}

        async def mock_fetcher(api: Any, resource_id: str, **kwargs: Any) -> dict:
            return fetcher_result

        provider.register_fetcher("test_resource", mock_fetcher)

        result = await provider.get("test_resource", "resource-123")

        assert result == fetcher_result
        # Should be cached now
        cached_result, found = provider.cache.get("test_resource::resource-123")
        assert cached_result == fetcher_result
        assert found

    @pytest.mark.asyncio
    async def test_get_unknown_fetcher(self, provider: SharedContextProvider):
        """Test getting value with unknown fetcher type."""
        result = await provider.get("unknown_type", "resource-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_fetcher_returns_none(
        self, provider: SharedContextProvider, mock_api: MagicMock
    ):
        """Test when fetcher returns None."""

        async def mock_fetcher(api: Any, resource_id: str, **kwargs: Any) -> None:
            return None

        provider.register_fetcher("nullable_resource", mock_fetcher)

        result = await provider.get("nullable_resource", "resource-123")

        assert result is None
        # None values should not be cached
        cached_result, found = provider.cache.get("nullable_resource::resource-123")
        assert cached_result is None
        assert not found

    @pytest.mark.asyncio
    async def test_get_fetcher_raises_exception(
        self, provider: SharedContextProvider, mock_api: MagicMock
    ):
        """Test when fetcher raises exception."""

        async def mock_fetcher(api: Any, resource_id: str, **kwargs: Any) -> dict:
            raise ValueError("Fetch failed")

        provider.register_fetcher("failing_resource", mock_fetcher)

        result = await provider.get("failing_resource", "resource-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_many(self, provider: SharedContextProvider):
        """Test getting multiple resources."""
        # Pre-populate cache
        provider.cache.put("table_metadata::table1", {"name": "table1"})
        provider.cache.put("table_metadata::table2", {"name": "table2"})

        results = await provider.get_many(
            "table_metadata", ["table1", "table2", "table3"]
        )

        assert len(results) == 2
        assert results["table1"] == {"name": "table1"}
        assert results["table2"] == {"name": "table2"}
        assert "table3" not in results

    def test_put(self, provider: SharedContextProvider):
        """Test putting data directly into cache."""
        provider.put("custom_type", "custom-id", {"custom": "data"})

        result, found = provider.cache.get("custom_type::custom-id")

        assert result == {"custom": "data"}
        assert found

    def test_put_with_kwargs(self, provider: SharedContextProvider):
        """Test putting data with additional kwargs for cache key."""
        provider.put("resource", "id", {"data": "test"}, version="v2")

        result, found = provider.cache.get("resource::id::version=v2")

        assert result == {"data": "test"}
        assert found

    def test_register_fetcher(self, provider: SharedContextProvider):
        """Test registering a custom fetcher."""

        def custom_fetcher(api: Any, resource_id: str, **kwargs: Any) -> dict:
            return {"custom": resource_id}

        provider.register_fetcher("custom_type", custom_fetcher)

        assert "custom_type" in provider.fetchers
        assert provider.fetchers["custom_type"] == custom_fetcher

    def test_clear_cache(self, provider: SharedContextProvider):
        """Test clearing the cache."""
        provider.cache.put("key1", "value1")
        provider.cache.put("key2", "value2")

        provider.clear_cache()

        assert len(provider.cache.data) == 0

    def test_cache_stats(self, provider: SharedContextProvider):
        """Test getting cache statistics."""
        provider.cache.put("key", "value")
        provider.cache.get("key")
        provider.cache.get("nonexistent")

        stats = provider.cache_stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1

    def test_build_cache_key_simple(self, provider: SharedContextProvider):
        """Test building simple cache key."""
        key = provider._build_cache_key("resource_type", "resource_id", {})

        assert key == "resource_type::resource_id"

    def test_build_cache_key_with_params(self, provider: SharedContextProvider):
        """Test building cache key with parameters."""
        key = provider._build_cache_key(
            "resource_type", "resource_id", {"param1": "value1", "param2": "value2"}
        )

        # Params should be sorted
        assert key == "resource_type::resource_id::param1=value1::param2=value2"

    def test_build_cache_key_ignores_none_params(self, provider: SharedContextProvider):
        """Test that None params are ignored in cache key."""
        key = provider._build_cache_key(
            "resource_type", "resource_id", {"param1": "value1", "param2": None}
        )

        assert key == "resource_type::resource_id::param1=value1"


class TestSharedContextProviderAsync:
    """Tests for SharedContextProvider async methods."""

    @pytest.fixture
    def mock_api(self) -> MagicMock:
        """Create a mock Databricks API."""
        return MagicMock()

    @pytest.fixture
    def provider(self, mock_api: MagicMock) -> SharedContextProvider:
        """Create SharedContextProvider with mock API."""
        return SharedContextProvider(mock_api)

    @pytest.mark.asyncio
    async def test_get_async_cached_value(self, provider: SharedContextProvider):
        """Test getting a cached value asynchronously."""
        provider.cache.put("table_metadata::my_table", {"columns": ["id", "name"]})

        result = await provider.get("table_metadata", "my_table")

        assert result == {"columns": ["id", "name"]}
        assert provider.cache.hits == 1

    @pytest.mark.asyncio
    async def test_get_async_from_fetcher(
        self, provider: SharedContextProvider, mock_api: MagicMock
    ):
        """Test getting value from fetcher asynchronously on cache miss."""
        fetcher_result = {"table_name": "my_table", "columns": ["id"]}

        async def mock_fetcher(api: Any, resource_id: str, **kwargs: Any) -> dict:
            return fetcher_result

        provider.register_fetcher("test_resource", mock_fetcher)

        result = await provider.get("test_resource", "resource-123")

        assert result == fetcher_result
        # Should be cached now
        cached_result, found = provider.cache.get("test_resource::resource-123")
        assert cached_result == fetcher_result
        assert found

    @pytest.mark.asyncio
    async def test_get_async_unknown_fetcher(self, provider: SharedContextProvider):
        """Test getting value with unknown fetcher type asynchronously."""
        result = await provider.get("unknown_type", "resource-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_async_fetcher_returns_none(
        self, provider: SharedContextProvider, mock_api: MagicMock
    ):
        """Test when async fetcher returns None."""

        async def mock_fetcher(api: Any, resource_id: str, **kwargs: Any) -> None:
            return None

        provider.register_fetcher("nullable_resource", mock_fetcher)

        result = await provider.get("nullable_resource", "resource-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_async_fetcher_raises_exception(
        self, provider: SharedContextProvider, mock_api: MagicMock
    ):
        """Test when async fetcher raises exception."""

        async def mock_fetcher(api: Any, resource_id: str, **kwargs: Any) -> dict:
            raise ValueError("Fetch failed")

        provider.register_fetcher("failing_resource", mock_fetcher)

        result = await provider.get("failing_resource", "resource-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_async_with_kwargs(
        self, provider: SharedContextProvider, mock_api: MagicMock
    ):
        """Test async get with additional kwargs."""

        async def mock_fetcher(
            api: Any, resource_id: str, max_items: int = 10, **kwargs: Any
        ) -> dict:
            return {"data": "test", "max_items": max_items}

        provider.register_fetcher("parameterized_resource", mock_fetcher)

        result = await provider.get(
            "parameterized_resource", "resource-123", max_items=5
        )

        assert result is not None
        assert result["max_items"] == 5
