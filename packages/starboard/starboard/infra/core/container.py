# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Dependency injection container."""

from typing import TYPE_CHECKING, Union

from starboard_core.ports.cache_store import CacheStore
from starboard_core.ports.memory_store import MemoryStore
from starboard_core.ports.state_store import StateStore
from starboard_core.repositories import (
    CacheManager,
    ConversationRepository,
    MemoryRepository,
)

from starboard.infra.core.cache_factory import CacheFactory
from starboard.infra.core.config import EnvConfig
from starboard.infra.core.namespaced_cache import NamespacedCache
from starboard.infra.core.state_factory import (
    create_cache_store,
    create_memory_store,
    create_state_store,
)
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from starboard.adapters.state.inmemory.user_store import InMemoryUserStore
    from starboard.adapters.state.postgres.user_store import PostgresUserStore
    from starboard.adapters.state.sqlite.feedback_repository import (
        SQLiteFeedbackRepository,
    )
    from starboard.adapters.state.sqlite.user_store import SQLiteUserStore
    from starboard.adapters.state.uc.feedback_repository import UCFeedbackRepository
    from starboard.adapters.state.uc.user_store import UCUserStore
    from starboard.repositories.feedback_repository import (
        PostgresFeedbackRepository,
    )


class Container:
    """
    Dependency injection container for application dependencies.

    Manages lifecycle of all state management components:
    - State stores (conversation persistence)
    - Memory stores (long-term memory)
    - Cache stores (key-value caching)
    - Repositories (business logic)

    Usage:
        config = get_config()
        config.validate_config()
        container = Container(config)
        await container.initialize()

        # Access repositories
        conv_repo = container.conversation_repo

        # Cleanup on shutdown
        await container.shutdown()
    """

    def __init__(self, config: EnvConfig):
        """
        Initialize container with configuration.

        Args:
            config: Environment configuration
        """
        self._config = config
        self._state_store: StateStore | None = None
        self._memory_store: MemoryStore | None = None
        self._cache_store: CacheStore | None = None
        self._cache_factory: CacheFactory | None = None

        # User store (cached per container instance)
        self._user_store: (
            InMemoryUserStore | SQLiteUserStore | PostgresUserStore | UCUserStore | None
        ) = None

    async def initialize(self) -> None:
        """
        Initialize all providers (call on app startup).

        Creates provider instances and establishes connections
        for stores that require it (Postgres, Redis).

        Raises:
            ValueError: If configuration is invalid
            ConnectionError: If unable to connect to external services
        """
        # Validate configuration first
        self._config.validate_config()

        # Create providers
        self._state_store = create_state_store(self._config)
        self._cache_store = create_cache_store(self._config)
        self._memory_store = create_memory_store(self._config)

        # Create cache factory with namespaced caches
        self._cache_factory = CacheFactory(_base_store=self._cache_store)

        # Pre-create common namespaced caches
        # These can be accessed via cache_factory.get_cache() or dedicated properties
        self._cache_factory.create("catalog")  # Service catalog entries
        self._cache_factory.create("sql")  # SQL query results
        self._cache_factory.create("data")  # Query result DataFrames
        self._cache_factory.create(
            "attachments", default_ttl=3600
        )  # Large file attachments (1hr TTL)

        # Connect providers that need initialization
        for store in (self._state_store, self._cache_store, self._memory_store):
            if store is not None and hasattr(store, "connect"):
                await store.connect()

    async def _close_if_available(self, store: object, name: str) -> None:
        """Close a store if it exists and has a close method.

        Args:
            store: Store instance to close (may be ``None``).
            name: Human-readable name for logging on failure.
        """
        if store is not None and hasattr(store, "close"):
            try:
                await store.close()  # type: ignore[union-attr]
            except Exception:
                logger.warning(f"Failed to close {name}", exc_info=True)

    async def shutdown(self) -> None:
        """
        Shutdown all providers (call on app shutdown).

        Closes connections and releases resources for all
        providers that require cleanup.
        """
        await self._close_if_available(self._state_store, "state_store")
        await self._close_if_available(self._cache_store, "cache_store")
        await self._close_if_available(self._memory_store, "memory_store")

    @property
    def conversation_repo(self) -> ConversationRepository:
        """
        Get conversation repository.

        Returns:
            ConversationRepository instance

        Raises:
            RuntimeError: If container not initialized
        """
        if self._state_store is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        return ConversationRepository(self._state_store)

    @property
    def memory_repo(self) -> MemoryRepository:
        """
        Get memory repository.

        Returns:
            MemoryRepository instance

        Raises:
            RuntimeError: If container not initialized
        """
        if self._memory_store is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        return MemoryRepository(self._memory_store)

    @property
    def cache_manager(self) -> CacheManager:
        """
        Get cache manager.

        Returns:
            CacheManager instance

        Raises:
            RuntimeError: If container not initialized
        """
        if self._cache_store is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        return CacheManager(
            self._cache_store,
            default_ttl=self._config.cache_ttl,
        )

    @property
    def config(self) -> EnvConfig:
        """Get environment configuration."""
        return self._config

    @property
    def state_store(self) -> StateStore:
        """
        Get state store instance.

        Returns:
            StateStore instance

        Raises:
            RuntimeError: If container not initialized
        """
        if self._state_store is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        return self._state_store

    @property
    def memory_store(self) -> MemoryStore:
        """
        Get memory store instance.

        Returns:
            MemoryStore instance

        Raises:
            RuntimeError: If container not initialized
        """
        if self._memory_store is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        return self._memory_store

    @property
    def cache_store(self) -> CacheStore:
        """
        Get cache store instance.

        Returns:
            CacheStore instance

        Raises:
            RuntimeError: If container not initialized
        """
        if self._cache_store is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        return self._cache_store

    @property
    def cache_factory(self) -> CacheFactory:
        """
        Get cache factory for creating namespaced caches.

        The factory provides namespace isolation and unified metrics
        across all cache consumers sharing the same underlying store.

        Returns:
            CacheFactory instance

        Raises:
            RuntimeError: If container not initialized

        Example:
            factory = container.cache_factory
            my_cache = factory.get_or_create("my_namespace")
            await my_cache.set("key", "value", ttl=300)
        """
        if self._cache_factory is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        return self._cache_factory

    @property
    def catalog_cache(self) -> NamespacedCache:
        """
        Get namespaced cache for service catalog entries.

        Pre-configured namespace: "catalog"
        Recommended TTL: 300s (5 minutes)

        Returns:
            NamespacedCache for catalog data

        Raises:
            RuntimeError: If container not initialized
        """
        if self._cache_factory is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        cache = self._cache_factory.get_cache("catalog")
        if cache is None:
            raise RuntimeError("Catalog cache not initialized")
        return cache

    @property
    def sql_cache(self) -> NamespacedCache:
        """
        Get namespaced cache for SQL query results.

        Pre-configured namespace: "sql"
        Recommended TTL: 300s (5 minutes)

        Returns:
            NamespacedCache for SQL results

        Raises:
            RuntimeError: If container not initialized
        """
        if self._cache_factory is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        cache = self._cache_factory.get_cache("sql")
        if cache is None:
            raise RuntimeError("SQL cache not initialized")
        return cache

    @property
    def data_cache(self) -> NamespacedCache:
        """
        Get namespaced cache for query result DataFrames.

        Pre-configured namespace: "data"
        Recommended TTL: 3600s (1 hour)

        Returns:
            NamespacedCache for DataFrame results

        Raises:
            RuntimeError: If container not initialized
        """
        if self._cache_factory is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")
        cache = self._cache_factory.get_cache("data")
        if cache is None:
            raise RuntimeError("Data cache not initialized")
        return cache

    @property
    def feedback_repo(
        self,
    ) -> Union[
        "SQLiteFeedbackRepository", "PostgresFeedbackRepository", "UCFeedbackRepository"
    ]:
        """
        Get feedback repository (database-specific).

        Returns the appropriate feedback repository implementation
        based on the configured state store type:
        - SQLite: SQLiteFeedbackRepository
        - PostgreSQL: PostgresFeedbackRepository

        Returns:
            Feedback repository instance

        Raises:
            RuntimeError: If container not initialized
            ValueError: If state store type doesn't support feedback
        """
        if self._state_store is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")

        # Capability dispatch (native_simplification §1): a state store may supply
        # its own feedback repository (e.g. UCStateStore) rather than requiring an
        # isinstance ladder here. Prefer that hook when present.
        get_feedback_repo = getattr(self._state_store, "get_feedback_repo", None)
        if callable(get_feedback_repo):
            return get_feedback_repo()

        # Detect state store type and return appropriate repository
        from starboard.adapters.state.sqlite.state_store import SQLiteStateStore

        if isinstance(self._state_store, SQLiteStateStore):
            # SQLite implementation
            from starboard.adapters.state.sqlite.feedback_repository import (
                SQLiteFeedbackRepository,
            )

            return SQLiteFeedbackRepository(db_conn=self._state_store.conn)
        else:
            # PostgreSQL implementation (future)
            from starboard.repositories.feedback_repository import (
                PostgresFeedbackRepository,
            )

            # PostgreSQL state store should provide a db_client property
            if not hasattr(self._state_store, "db_client"):
                raise ValueError(
                    f"State store type {type(self._state_store).__name__} "
                    "does not support feedback repository"
                )

            return PostgresFeedbackRepository(db_client=self._state_store.db_client)  # type: ignore[attr-defined]

    @property
    def user_store(
        self,
    ) -> Union[
        "InMemoryUserStore", "SQLiteUserStore", "PostgresUserStore", "UCUserStore"
    ]:
        """
        Get user repository (database-specific).

        Returns the appropriate user repository implementation
        based on the configured state store type:
        - SQLite: SQLiteUserStore
        - PostgreSQL: PostgresUserStore

        Returns:
            User repository instance

        Raises:
            RuntimeError: If container not initialized
            ValueError: If state store type doesn't support users
        """
        if self._user_store is not None:
            return self._user_store

        if self._state_store is None:
            raise RuntimeError("Container not initialized. Call initialize() first.")

        # Capability dispatch (native_simplification §1): a state store may supply
        # its own user store (e.g. UCStateStore) rather than requiring an
        # isinstance ladder here. Prefer that hook when present.
        get_user_store = getattr(self._state_store, "get_user_store", None)
        if callable(get_user_store):
            self._user_store = get_user_store()
            return self._user_store

        # Detect state store type and return appropriate repository
        from starboard.adapters.state.inmemory.state_store import (
            InMemoryStateStore,
        )
        from starboard.adapters.state.sqlite.state_store import SQLiteStateStore

        if isinstance(self._state_store, InMemoryStateStore):
            # In-memory implementation for dev/testing
            from starboard.adapters.state.inmemory.user_store import (
                InMemoryUserStore,
            )

            self._user_store = InMemoryUserStore()
        elif isinstance(self._state_store, SQLiteStateStore):
            # SQLite implementation
            from starboard.adapters.state.sqlite.user_store import (
                SQLiteUserStore,
            )

            self._user_store = SQLiteUserStore(conn=self._state_store.conn)
        else:
            # PostgreSQL implementation
            from starboard.adapters.state.postgres.user_store import (
                PostgresUserStore,
            )

            # PostgreSQL state store should provide a pool property
            if not hasattr(self._state_store, "pool"):
                raise ValueError(
                    f"State store type {type(self._state_store).__name__} "
                    "does not support user repository"
                )

            self._user_store = PostgresUserStore(pool=self._state_store.pool)  # type: ignore[attr-defined]

        return self._user_store
