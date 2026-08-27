# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
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

from starboard.infra.core.cache_factory import CacheFactory
from starboard.infra.core.config import EnvConfig
from starboard.infra.core.namespaced_cache import NamespacedCache
from starboard.infra.core.state_factory import (
    create_cache_store,
    create_memory_store,
    create_state_store,
)
from starboard.infra.observability.logging import get_logger
from starboard.infra.rag.domain.protocols import (
    EmbeddingProvider,
    MultiCollectionStore,
)

logger = get_logger(__name__)

if TYPE_CHECKING:
    from starboard.adapters.state.inmemory.user_store import InMemoryUserStore
    from starboard.adapters.state.postgres.user_store import PostgresUserStore
    from starboard.adapters.state.sqlite.feedback_repository import (
        SQLiteFeedbackRepository,
    )
    from starboard.adapters.state.sqlite.user_store import SQLiteUserStore
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

    def _semantic_cache_uses_vector(self) -> bool:
        """Whether the similarity-based (vector) semantic cache is opted in.

        The default (``vector_backend="none"``) uses the dependency-free
        TTL-only exact-key cache. A real vector backend
        (``inmemory``/``sqlite``/``vectorsearch``/…) opts into the
        similarity-based :class:`SemanticCache` (Phase 2 C4, D-2.9).
        """
        return getattr(self._config, "vector_backend", "none") != "none"

    def _build_ttl_semantic_cache(self):
        """Build the default TTL-only exact-key semantic cache (no vector deps)."""
        from starboard.infra.cache import TTLSemanticCache

        return TTLSemanticCache(ttl=self._config.cache_ttl)

    @staticmethod
    def _require_reflexion_driver() -> None:
        """Ensure the reflexion vector-store driver is importable.

        Reflexion (episodic learning) is opt-in and needs a vector store. Guard
        the driver up front so a no-extras install surfaces an actionable
        install hint instead of silently degrading (Phase 2 C4, D-2.9).

        Raises:
            RuntimeError: naming the extra to install when ``sqlite_vec`` is
                absent.
        """
        import importlib

        try:
            importlib.import_module("sqlite_vec")
        except ImportError as e:
            raise RuntimeError(
                "enable_reflexion=True needs a vector-store driver for episodic "
                "learning, but 'sqlite_vec' is not installed. Install a vector "
                "extra: pip install 'starboard[sqlite]' (local sqlite-vec) or "
                "'starboard[vectorsearch]' (managed Databricks Vector Search)."
            ) from e

    async def _initialize_foundation_components(self) -> None:
        """Initialize foundation components (semantic cache; optional vector/reflexion).

        Default (lean) path — ``vector_backend="none"`` and
        ``enable_reflexion=False``: build only a TTL-only exact-key semantic
        cache. No embedding provider, no vector store, no reflexion store, and
        crucially **no sqlite-vec import**.

        Opt-in path — a real ``vector_backend`` and/or ``enable_reflexion=True``:
        lazily construct the embedding provider, vector store, reflexion store,
        and (when a vector backend is selected) a similarity-based semantic
        cache. All heavy imports are deferred so a no-extras /
        ``vector_backend="none"`` install never touches sqlite-vec /
        databricks-vectorsearch.
        """
        wants_vector = self._semantic_cache_uses_vector()
        wants_reflexion = self._config.enable_reflexion
        wants_semantic_cache = self._config.enable_semantic_cache

        # Reflexion is opt-in and needs a vector-store driver. Guard *before* any
        # heavy init so a missing extra raises an actionable error rather than
        # being swallowed by the degrade path below.
        if wants_reflexion:
            self._require_reflexion_driver()

        # --- Lean default path: TTL-only exact-key cache, nothing vector-backed. ---
        if not wants_vector and not wants_reflexion:
            if wants_semantic_cache:
                self._semantic_cache = self._build_ttl_semantic_cache()
                logger.info(
                    "semantic_cache_ttl_only_initialized",
                    ttl=self._config.cache_ttl,
                    reason="vector_backend=none, enable_reflexion=False",
                )
            return

        # --- Opt-in vector / reflexion path (behind [sqlite]/[vectorsearch]). ---
        from starboard.infra.rag.adapters.embedding import (
            LLMClientEmbeddingProvider,
        )
        from starboard.infra.rag.services.vector_store_factory import (
            create_vector_store,
        )

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

            # Reflexion store (opt-in): its own dedicated vector store on a
            # separate database. Lazy-imported so sqlite-vec is only touched here.
            if wants_reflexion:
                from starboard.infra.rag import SQLiteVectorStore
                from starboard.infra.reflexion import SQLiteReflexionStore

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

            # Semantic cache: similarity-based when a vector backend is opted in,
            # otherwise TTL-only exact-key (dependency-free).
            if wants_semantic_cache:
                if wants_vector:
                    from starboard.infra.cache import (
                        SemanticCache as SemanticCacheImpl,
                    )
                    from starboard.infra.rag import SQLiteVectorStore

                    cache_db_path = self._config.sqlite_reflexion_path or ":memory:"
                    cache_vector_store = SQLiteVectorStore(
                        db_path=cache_db_path,
                        collection_name="semantic_cache",
                        dimension=self._config.embedding_dimension,
                    )
                    await cache_vector_store.initialize()
                    self._semantic_cache = SemanticCacheImpl(
                        vector_store=cache_vector_store,
                        embedding_fn=embedding_fn,
                        ttl=self._config.cache_ttl,
                        similarity_threshold=self._config.semantic_cache_threshold,
                    )
                else:
                    # Reflexion is on but no vector backend selected: keep the
                    # semantic cache dependency-free (TTL-only exact-key).
                    self._semantic_cache = self._build_ttl_semantic_cache()
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
        await self._close_if_available(self._reflexion_store, "reflexion_store")
        await self._close_if_available(self._vector_store, "vector_store")
        await self._close_if_available(self._semantic_cache, "semantic_cache")

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
