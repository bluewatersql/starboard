# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for Container cache factory integration.

Tests verify:
- CacheFactory initialization in Container
- Pre-configured namespaced caches (catalog, sql, data)
- Property access patterns
- Error handling for uninitialized container
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from starboard.adapters.state.inmemory.cache_store import InMemoryCacheStore
from starboard.infra.core.cache_factory import CacheFactory
from starboard.infra.core.config import EnvConfig
from starboard.infra.core.container import Container
from starboard.infra.core.namespaced_cache import NamespacedCache


def create_mock_store_without_connect() -> MagicMock:
    """Create a mock store without connect/close methods.

    The Container checks hasattr(store, 'connect') before calling it.
    We use spec to exclude those methods.
    """
    mock = MagicMock()
    # Remove connect/close to avoid hasattr checks triggering
    del mock.connect
    del mock.close
    return mock


class TestContainerCacheIntegration:
    """Test suite for Container cache factory integration."""

    @pytest.fixture
    def config(self) -> EnvConfig:
        """Create test configuration."""
        return EnvConfig(
            environment="test",
            database_backend="sqlite",
            cache_ttl=300,
            offline_mode=True,  # Skip validation for required API keys in tests
        )

    @pytest.fixture
    def container(self, config: EnvConfig) -> Container:
        """Create container instance (not initialized)."""
        return Container(config)

    @pytest.fixture
    def mock_stores(self) -> tuple[MagicMock, MagicMock, InMemoryCacheStore]:
        """Create mock stores for testing."""
        mock_state_store = create_mock_store_without_connect()
        mock_memory_store = create_mock_store_without_connect()
        cache_store = InMemoryCacheStore()
        return mock_state_store, mock_memory_store, cache_store

    # -------------------------------------------------------------------------
    # Uninitialized Container Tests
    # -------------------------------------------------------------------------

    def test_cache_factory_raises_before_init(self, container: Container) -> None:
        """cache_factory should raise RuntimeError before initialization."""
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = container.cache_factory

    def test_catalog_cache_raises_before_init(self, container: Container) -> None:
        """catalog_cache should raise RuntimeError before initialization."""
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = container.catalog_cache

    def test_sql_cache_raises_before_init(self, container: Container) -> None:
        """sql_cache should raise RuntimeError before initialization."""
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = container.sql_cache

    def test_data_cache_raises_before_init(self, container: Container) -> None:
        """data_cache should raise RuntimeError before initialization."""
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = container.data_cache

    # -------------------------------------------------------------------------
    # Initialized Container Tests (Mocked)
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cache_factory_created_on_init(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """CacheFactory should be created during initialization."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            factory = container.cache_factory
            assert isinstance(factory, CacheFactory)

    @pytest.mark.asyncio
    async def test_namespaces_precreated_on_init(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """Pre-configured namespaces should be created during initialization."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            factory = container.cache_factory
            namespaces = factory.list_namespaces()

            assert "catalog" in namespaces
            assert "sql" in namespaces
            assert "data" in namespaces

    @pytest.mark.asyncio
    async def test_catalog_cache_returns_namespaced_cache(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """catalog_cache should return NamespacedCache with 'catalog' namespace."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            cache = container.catalog_cache
            assert isinstance(cache, NamespacedCache)
            assert cache.namespace == "catalog"

    @pytest.mark.asyncio
    async def test_sql_cache_returns_namespaced_cache(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """sql_cache should return NamespacedCache with 'sql' namespace."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            cache = container.sql_cache
            assert isinstance(cache, NamespacedCache)
            assert cache.namespace == "sql"

    @pytest.mark.asyncio
    async def test_data_cache_returns_namespaced_cache(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """data_cache should return NamespacedCache with 'data' namespace."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            cache = container.data_cache
            assert isinstance(cache, NamespacedCache)
            assert cache.namespace == "data"

    @pytest.mark.asyncio
    async def test_caches_share_underlying_store(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """All namespaced caches should share the same underlying store."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            # Get the underlying store from all caches
            catalog_store = container.catalog_cache.store
            sql_store = container.sql_cache.store
            data_store = container.data_cache.store

            # All should be the same instance
            assert catalog_store is sql_store
            assert sql_store is data_store

    @pytest.mark.asyncio
    async def test_caches_are_isolated(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """Different namespace caches should have isolated keys."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            catalog = container.catalog_cache
            sql = container.sql_cache

            # Set same key in both namespaces
            await catalog.set("key", "catalog_value")
            await sql.set("key", "sql_value")

            # Values should be independent
            assert await catalog.get("key") == "catalog_value"
            assert await sql.get("key") == "sql_value"

    @pytest.mark.asyncio
    async def test_cache_factory_same_as_cache_stores_base(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """CacheFactory should use the same store as cache_store property."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            # Get base cache store
            base_store = container.cache_store

            # Get catalog cache's underlying store
            catalog_store = container.catalog_cache.store

            # Should be the same instance
            assert catalog_store is base_store

    # -------------------------------------------------------------------------
    # Custom Namespace Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_can_create_additional_namespaces(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """Should be able to create additional namespaces via factory."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            factory = container.cache_factory
            custom_cache = factory.create("custom")

            assert custom_cache.namespace == "custom"
            assert "custom" in factory.list_namespaces()

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing_cache(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """get_or_create should return existing pre-configured cache."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            factory = container.cache_factory

            # Get catalog cache via get_or_create
            cache = factory.get_or_create("catalog")

            # Should be the same as the property
            assert cache is container.catalog_cache

    # -------------------------------------------------------------------------
    # Metrics Tests
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # User Store Caching Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_user_store_returns_same_instance(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """user_store should return the same instance on repeated calls (singleton per container)."""
        mock_state, mock_memory, cache_store = mock_stores

        # Use InMemoryStateStore so we get InMemoryUserStore
        from starboard.adapters.state.inmemory.state_store import (
            InMemoryStateStore,
        )

        inmemory_state = InMemoryStateStore()

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=inmemory_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            store1 = container.user_store
            store2 = container.user_store

            assert store1 is store2

    @pytest.mark.asyncio
    async def test_aggregate_metrics_across_caches(
        self,
        container: Container,
        mock_stores: tuple[MagicMock, MagicMock, InMemoryCacheStore],
    ) -> None:
        """Factory should aggregate metrics from all namespaced caches."""
        mock_state, mock_memory, cache_store = mock_stores

        with (
            patch(
                "starboard.infra.core.container.create_state_store",
                return_value=mock_state,
            ),
            patch(
                "starboard.infra.core.container.create_memory_store",
                return_value=mock_memory,
            ),
            patch(
                "starboard.infra.core.container.create_cache_store",
                return_value=cache_store,
            ),
        ):
            await container.initialize()

            catalog = container.catalog_cache
            sql = container.sql_cache

            # Generate some activity
            await catalog.set("key", "value")
            await catalog.get("key")  # hit
            await sql.get("missing")  # miss

            # Get aggregate metrics
            metrics = container.cache_factory.get_aggregate_metrics()

            assert metrics.hits == 1
            assert metrics.misses == 1
            assert metrics.hit_rate == 0.5
