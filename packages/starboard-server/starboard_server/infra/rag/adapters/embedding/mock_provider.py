# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Mock embedding provider for testing and development.

Provides deterministic embeddings without API calls.
"""

from __future__ import annotations

import hashlib


class MockEmbeddingProvider:
    """
    Mock embedding provider for testing without API calls.

    Generates deterministic embeddings based on text hash.
    Useful for development, testing, and offline mode.

    Args:
        embedding_dim: Dimension of embeddings (default: 1024)

    Example:
        from starboard_server.infra.rag import MockEmbeddingProvider, SQLiteMultiCollectionStore

        # Use for testing
        mock_provider = MockEmbeddingProvider(embedding_dim=1024)

        store = SQLiteMultiCollectionStore(
            db_path="test_vectors.db",
            embedding_provider=mock_provider,
        )

        # Test search without API calls
        results = await store.search_tables("test query", n_results=5)

    Note:
        Mock embeddings are deterministic but not semantically meaningful.
        Use only for testing, not production.
    """

    def __init__(self, embedding_dim: int = 1024):
        """
        Initialize mock embedding provider.

        Args:
            embedding_dim: Dimension of embeddings (default: 1024)
        """
        self.embedding_dim = embedding_dim

    async def embed(self, text: str) -> list[float]:
        """
        Generate deterministic mock embedding based on text hash.

        Args:
            text: Text to embed

        Returns:
            Mock embedding vector (deterministic)

        Example:
            embedding = await provider.embed("hello world")
            # Returns same vector every time for "hello world"
        """
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        return [((hash_val + i) % 1000) / 1000.0 for i in range(self.embedding_dim)]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of mock embedding vectors

        Example:
            embeddings = await provider.embed_batch(["text1", "text2"])
        """
        return [await self.embed(text) for text in texts]
