"""Dependency injection container."""

from typing import TYPE_CHECKING, Union

from starboard_core.foundations.protocols import (
    ReflexionStore,
    SemanticCache,
)
from starboard_core.ports.cache_store import CacheStore
from starboard_core.ports.memory_store import MemoryStore
from starboard_core.ports.state_store import StateStore
from starboard_core.repositories import (
    CacheManager,
    ConversationRepository,
    MemoryRepository,
)

from starboard_server.infra.core.cache_factory import CacheFactory
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.core.namespaced_cache import NamespacedCache
from starboard_server.infra.core.state_factory import (
    create_cache_store,
    create_memory_store,
    create_state_store,
)
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.rag.domain.protocols import (
    EmbeddingProvider,
    MultiCollectionStore,
)

logger = get_logger(__name__)

if TYPE_CHECKING:
    from starboard_server.adapters.state.inmemory.user_store import InMemoryUserStore
    from starboard_server.adapters.state.postgres.user_store import PostgresUserStore
    from starboard_server.adapters.state.sqlite.feedback_repository import (
        SQLiteFeedbackRepository,
    )
    from starboard_server.adapters.state.sqlite.user_store import SQLiteUserStore
    from starboard_server.repositories.feedback_repository import (
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
    - Foundation components (vector store, reflexion, semantic cache)

    Usage:
        config = get_config()
        config.validate_config()
        container = Container(config)
        await container.initialize()

        # Access repositories
        conv_repo = container.conversation_repo

        # Access foundation components
        vector_store = container.vector_store
        semantic_cache = container.semantic_cache

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
            InMemoryUserStore | SQLiteUserStore | PostgresUserStore | None
        ) = None

        # Foundation components
        self._vector_store: MultiCollectionStore | None = None
        self._reflexion_store: ReflexionStore | None = None
        self._semantic_cache: SemanticCache | None = None
        self._embedding_provider: EmbeddingProvider | None = None

    async def initialize(self) -> None:
        """
        Initialize all providers (call on app startup).

        Creates provider instances and establishes connections
        for stores that require it (Postgres, Redis).

        Also initializes foundation components:
        - Vector store for RAG
        - Reflexion store for agent learnings
        - Semantic cache for LLM response caching

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

        # Initialize foundation components
        # Only initialize if not in test environment (skip if using in-memory backends)
        if self._config.environment != "test":
            await self._initialize_foundation_components()

    async def _initialize_foundation_components(self) -> None:
        """Initialize vector store, reflexion store, and semantic cache.

        This is optional and can be skipped in test environments.
        Uses factory pattern with automatic fallback to in-memory store.
        """
        from starboard_server.infra.cache import SemanticCache as SemanticCacheImpl
        from starboard_server.infra.rag import SQLiteVectorStore
        from starboard_server.infra.rag.adapters.embedding import (
            LLMClientEmbeddingProvider,
        )
        from starboard_server.infra.rag.services.vector_store_factory import (
            create_vector_store,
        )
        from starboard_server.infra.reflexion import SQLiteReflexionStore

        try:
            # Initialize embedding provider (used by RAG tools, reflexion, semantic cache)
            self._embedding_provider = LLMClientEmbeddingProvider(cfg=self._config)

            # Create vector store with automatic fallback
            # Priority: SQLite (if available) -> In-memory (fallback) -> None (if disabled)
            self._vector_store = await create_vector_store(
                config=self._config,
                embedding_provider=self._embedding_provider,
                auto_bootstrap=True,  # Auto-populate in-memory store with essential data
            )

            # Create embedding function for reflexion and semantic cache.
            # Uses real LLM embeddings via the provider; falls back to
            # deterministic hash-based fakes only in offline/mock mode.
            embedding_fn = self._create_embedding_function(self._embedding_provider)

            # Create reflexion store (uses its own dedicated vector store on separate database)
            reflexion_db_path = self._config.sqlite_reflexion_path or ":memory:"
            reflexion_vector_store = SQLiteVectorStore(
                db_path=reflexion_db_path,
                collection_name="learnings",  # Reflexion learnings collection
                dimension=self._config.embedding_dimension,
            )
            await reflexion_vector_store.initialize()

            self._reflexion_store = SQLiteReflexionStore(  # type: ignore[assignment]
                db_path=reflexion_db_path,
                vector_store=reflexion_vector_store,
                embedding_fn=embedding_fn,
            )
            await self._reflexion_store.initialize()  # type: ignore[union-attr]

            # Create semantic cache WITHOUT vector store (use in-memory cache only)
            # Vector-based semantic cache requires additional vector store which can
            # cause connection issues. For now, use simple TTL-based caching.
            # TODO(BACKLOG-003): Reuse multi-collection store for semantic cache vectors
            self._semantic_cache = SemanticCacheImpl(
                vector_store=reflexion_vector_store,  # Reuse reflexion vector store
                embedding_fn=embedding_fn,
                ttl=self._config.cache_ttl,
                similarity_threshold=self._config.semantic_cache_threshold,
            )
        except Exception as e:  # noqa: BLE001 - DI container boundary
            # Log warning but don't fail initialization
            # Foundation components are optional features
            error_msg = str(e)
            is_sqlite_extension_error = (
                "extension loading" in error_msg.lower()
                or "enable_load_extension" in error_msg
            )

            if is_sqlite_extension_error:
                logger.warning(
                    "foundation_components_init_failed",
                    error_type=type(e).__name__,
                    error=error_msg,
                    msg="Foundation components (vector store, reflexion, semantic cache) failed to initialize due to SQLite extension support. "
                    "These are optional features and the system will continue to work without them. "
                    "To enable vector search capabilities, rebuild Python with loadable extension support. "
                    "On macOS with pyenv: PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' pyenv install <version>",
                )
            else:
                logger.warning(
                    "foundation_components_init_failed",
                    error_type=type(e).__name__,
                    error=error_msg,
                    msg="Foundation components (vector store, reflexion, semantic cache) failed to initialize. "
                    "These are optional features and the system will continue to work without them.",
                )

    def _create_embedding_function(
        self,
        provider: EmbeddingProvider | None = None,
    ):
        """Create async embedding function for vector operations.

        In normal mode, returns an async function that directly awaits
        the embedding provider. In offline/mock mode, returns a deterministic
        hash-based async function that produces fake embeddings.

        Args:
            provider: Embedding provider to wrap. If None or offline/mock
                      mode, falls back to hash-based fake embeddings.
        """
        use_fake = (
            self._config.offline_mode or self._config.mock_llm or provider is None
        )

        if use_fake:
            import hashlib

            dimension = self._config.embedding_dimension
            logger.info(
                "using_fake_embeddings",
                reason="offline_mode"
                if self._config.offline_mode
                else ("mock_llm" if self._config.mock_llm else "no_provider"),
            )

            async def fake_embedding(text: str) -> list[float]:
                """Generate deterministic fake embedding from text hash."""
                hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)  # noqa: S324
                return [((hash_val + i) % 1000) / 1000.0 for i in range(dimension)]

            return fake_embedding

        assert provider is not None

        # Real embeddings: async-native — directly await the provider
        async def real_embedding(text: str) -> list[float]:
            """Generate real embedding via LLM provider."""
            return await provider.embed(text)

        return real_embedding

    async def shutdown(self) -> None:
        """
        Shutdown all providers (call on app shutdown).

        Closes connections and releases resources for all
        providers that require cleanup.
        """
        if self._state_store and hasattr(self._state_store, "close"):
            await self._state_store.close()

        if self._cache_store and hasattr(self._cache_store, "close"):
            await self._cache_store.close()

        if self._memory_store and hasattr(self._memory_store, "close"):
            await self._memory_store.close()

        # Close foundation components
        if self._reflexion_store is not None and hasattr(
            self._reflexion_store, "close"
        ):
            await self._reflexion_store.close()  # type: ignore[union-attr]

        if self._vector_store is not None and hasattr(self._vector_store, "close"):
            await self._vector_store.close()  # type: ignore[union-attr]

        if self._semantic_cache is not None and hasattr(
            self._semantic_cache, "close"
        ):
            await self._semantic_cache.close()  # type: ignore[union-attr]

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
    ) -> Union["SQLiteFeedbackRepository", "PostgresFeedbackRepository"]:
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

        # Detect state store type and return appropriate repository
        from starboard_server.adapters.state.sqlite.state_store import SQLiteStateStore

        if isinstance(self._state_store, SQLiteStateStore):
            # SQLite implementation
            from starboard_server.adapters.state.sqlite.feedback_repository import (
                SQLiteFeedbackRepository,
            )

            return SQLiteFeedbackRepository(db_conn=self._state_store.conn)
        else:
            # PostgreSQL implementation (future)
            from starboard_server.repositories.feedback_repository import (
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
    ) -> Union["InMemoryUserStore", "SQLiteUserStore", "PostgresUserStore"]:
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

        # Detect state store type and return appropriate repository
        from starboard_server.adapters.state.inmemory.state_store import (
            InMemoryStateStore,
        )
        from starboard_server.adapters.state.sqlite.state_store import SQLiteStateStore

        if isinstance(self._state_store, InMemoryStateStore):
            # In-memory implementation for dev/testing
            from starboard_server.adapters.state.inmemory.user_store import (
                InMemoryUserStore,
            )

            self._user_store = InMemoryUserStore()
        elif isinstance(self._state_store, SQLiteStateStore):
            # SQLite implementation
            from starboard_server.adapters.state.sqlite.user_store import (
                SQLiteUserStore,
            )

            self._user_store = SQLiteUserStore(conn=self._state_store.conn)
        else:
            # PostgreSQL implementation
            from starboard_server.adapters.state.postgres.user_store import (
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

    @property
    def vector_store(self) -> MultiCollectionStore | None:
        """
        Get vector store for RAG.

        Returns:
            VectorStore instance if foundation components initialized, None otherwise

        Note:
            Returns None if foundation components failed to initialize (e.g., SQLite
            extension support not available). Consumers should handle None gracefully.
        """
        return self._vector_store

    @property
    def reflexion_store(self) -> ReflexionStore | None:
        """
        Get reflexion store for agent learnings.

        Returns:
            ReflexionStore instance if foundation components initialized, None otherwise

        Note:
            Returns None if foundation components failed to initialize (e.g., SQLite
            extension support not available). Consumers should handle None gracefully.
        """
        return self._reflexion_store

    @property
    def semantic_cache(self) -> SemanticCache | None:
        """
        Get semantic cache for LLM response caching.

        Returns:
            SemanticCache instance if foundation components initialized, None otherwise

        Note:
            Returns None if foundation components failed to initialize (e.g., SQLite
            extension support not available). Consumers should handle None gracefully.
        """
        return self._semantic_cache

    @property
    def embedding_provider(self) -> EmbeddingProvider | None:
        """
        Get embedding provider for generating vector embeddings.

        Returns:
            EmbeddingProvider instance if foundation components initialized, None otherwise

        Note:
            Returns None if foundation components failed to initialize (e.g., SQLite
            extension support not available). Consumers should handle None gracefully.
        """
        return self._embedding_provider
