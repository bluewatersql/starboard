# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Vector store factory with automatic fallback.

Provides factory function to create vector stores with graceful degradation:
1. Try SQLite + vector extension (production)
2. Fallback to in-memory (development/CLI)
3. Return None if explicitly disabled

This enables the Analytics Agent to work in environments where SQLite
vector extensions are unavailable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from starboard.infra.observability.logging import get_logger
from starboard.infra.rag.domain.protocols import MultiCollectionStore

if TYPE_CHECKING:
    from starboard.infra.core.config import EnvConfig
    from starboard.infra.rag.domain.protocols import EmbeddingProvider

logger = get_logger(__name__)


async def create_vector_store(
    config: EnvConfig,
    embedding_provider: EmbeddingProvider,
    auto_bootstrap: bool = True,
) -> MultiCollectionStore | None:
    """Create vector store with automatic fallback.

    Priority order:
    1. SQLite + vector extension (if available and configured)
    2. In-memory store (fallback for development/CLI)
    3. None (if explicitly disabled)

    Args:
        config: Environment configuration
        embedding_provider: Embedding provider for generating vectors
        auto_bootstrap: Whether to auto-bootstrap in-memory store with essential data

    Returns:
        MultiCollectionStore instance or None if disabled

    Example:
        >>> embedding_provider = LLMClientEmbeddingProvider(...)
        >>> store = await create_vector_store(config, embedding_provider)
        >>> # Store is either SQLite or in-memory, depending on availability
    """
    # Check if vector store is explicitly disabled
    if getattr(config, "disable_vector_store", False):
        logger.info("vector_store_disabled_by_config")
        return None

    # Determine backend
    backend = getattr(config, "vector_backend", "sqlite")

    # Try SQLite vector store (production)
    if backend == "sqlite":
        try:
            from starboard.infra.rag.adapters.storage.sqlite_multi_collection_store import (
                SQLiteMultiCollectionStore,
            )

            db_path = getattr(config, "sqlite_vector_path", None) or ":memory:"
            embedding_dim = getattr(config, "embedding_dimension", 1024)

            store = SQLiteMultiCollectionStore(
                db_path=db_path,
                embedding_dim=embedding_dim,
                embedding_provider=embedding_provider,
            )
            await store.initialize()

            logger.info(
                "sqlite_vector_store_initialized",
                db_path=db_path,
                embedding_dim=embedding_dim,
            )
            return store

        except ImportError as e:
            logger.warning(
                "sqlite_vector_store_import_failed",
                error=str(e),
                error_type="ImportError",
                fallback="in_memory",
                suggestion="Install sqlite-vec extension or use in-memory backend",
            )
            # Fall through to in-memory

        except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
            logger.warning(
                "sqlite_vector_store_initialization_failed",
                error=str(e),
                error_type=type(e).__name__,
                fallback="in_memory",
            )
            # Fall through to in-memory

    # Fallback: In-memory vector store
    logger.info(
        "using_inmemory_vector_store",
        reason=(
            "sqlite_unavailable" if backend == "sqlite" else "inmemory_backend_selected"
        ),
        auto_bootstrap=auto_bootstrap,
        limitations="ephemeral, limited_scale (<10K vectors)",
    )

    from starboard.infra.rag.adapters.storage.inmemory_vector_store import (
        InMemoryMultiCollectionStore,
    )

    embedding_dim = getattr(config, "embedding_dimension", 1024)
    max_vectors = getattr(config, "inmemory_max_vectors", 10000)

    inmemory_store = InMemoryMultiCollectionStore(
        embedding_provider=embedding_provider,
        embedding_dim=embedding_dim,
        max_vectors=max_vectors,
    )
    await inmemory_store.initialize()

    # Auto-bootstrap with essential data
    if auto_bootstrap:
        try:
            from starboard.infra.rag.adapters.storage.bootstrap_loader import (
                load_bootstrap_data,
            )

            counts = await load_bootstrap_data(
                store=inmemory_store,
                use_exported=True,  # Try package-managed exports first
                use_hardcoded=True,  # Fall back to hardcoded data
            )
            logger.info(
                "inmemory_vector_store_bootstrapped",
                **counts,
            )
        except Exception as e:  # noqa: BLE001 - RAG infrastructure boundary
            logger.warning(
                "inmemory_vector_store_bootstrap_failed",
                error=str(e),
                error_type=type(e).__name__,
                impact="Analytics Agent may have limited context",
            )

    return cast(MultiCollectionStore, inmemory_store)


def get_vector_store_backend(config: EnvConfig) -> str:
    """Get the vector store backend that will be used.

    Args:
        config: Environment configuration

    Returns:
        Backend name: "sqlite", "inmemory", or "none"
    """
    if getattr(config, "disable_vector_store", False):
        return "none"

    backend = getattr(config, "vector_backend", "sqlite")

    # Check if SQLite backend is actually available
    if backend == "sqlite":
        try:
            from starboard.infra.rag.adapters.storage.sqlite_multi_collection_store import (  # noqa: F401
                SQLiteMultiCollectionStore,
            )

            return "sqlite"
        except ImportError:
            return "inmemory"  # Will fallback

    return backend
