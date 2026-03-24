"""
Helper functions for embedding providers.

Utilities to create and configure embedding providers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starboard_server.infra.rag.adapters.embedding.mock_provider import (
    MockEmbeddingProvider,
)
from starboard_server.infra.rag.domain.protocols import EmbeddingProvider

if TYPE_CHECKING:
    from starboard_server.infra.core.container import Container


def get_default_embedding_provider(
    api_key: str | None = None,
    container: Container | None = None,
    embedding_dim: int = 1024,
    use_mock: bool = False,
) -> EmbeddingProvider:
    """
    Get a default embedding provider based on available configuration.

    Priority:
    1. If use_mock=True: Returns MockEmbeddingProvider
    2. If api_key + container: Returns EmbeddingService
    3. Otherwise: Returns MockEmbeddingProvider (fallback)

    Args:
        api_key: Optional OpenAI API key
        container: Optional DI container (required for EmbeddingService)
        embedding_dim: Embedding dimension for mock provider (default: 1024)
        use_mock: Force use of mock provider (default: False)

    Returns:
        EmbeddingProvider instance

    Example:
        # Get default provider (tries EmbeddingService, falls back to mock)
        from starboard_server.infra.rag import get_default_embedding_provider

        provider = get_default_embedding_provider(
            api_key=config.llm_api_key,
            container=container,
        )

        store = SQLiteMultiCollectionStore(
            db_path="vectors.db",
            embedding_provider=provider,
        )

        # Force mock provider
        mock_provider = get_default_embedding_provider(use_mock=True)

        # Get mock with custom dimension
        mock_1536 = get_default_embedding_provider(
            use_mock=True,
            embedding_dim=1536,
        )
    """
    # Force mock if requested
    if use_mock:
        return MockEmbeddingProvider(embedding_dim=embedding_dim)

    # Try to create EmbeddingService if we have dependencies
    if api_key and container:
        try:
            from starboard_server.services.memory.embedding_service import (
                EmbeddingService,
            )

            return EmbeddingService(api_key=api_key, container=container)
        except ImportError:
            # Fall back to mock if EmbeddingService not available
            pass

    # Fallback to mock provider
    return MockEmbeddingProvider(embedding_dim=embedding_dim)


def create_mock_provider(embedding_dim: int = 1024) -> MockEmbeddingProvider:
    """
    Create a mock embedding provider for testing.

    Convenience function for creating mock providers.

    Args:
        embedding_dim: Embedding dimension (default: 1024)

    Returns:
        MockEmbeddingProvider instance

    Example:
        from starboard_server.infra.rag import create_mock_provider

        # Create mock with default dimension (1024)
        mock = create_mock_provider()

        # Create mock with custom dimension
        mock_1536 = create_mock_provider(embedding_dim=1536)

        # Use with vector store
        store = SQLiteMultiCollectionStore(
            db_path="test.db",
            embedding_provider=mock,
        )
    """
    return MockEmbeddingProvider(embedding_dim=embedding_dim)
