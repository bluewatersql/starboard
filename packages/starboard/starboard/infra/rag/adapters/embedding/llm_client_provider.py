# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""LLM client embedding provider.

Wraps BaseLLMClient implementations to provide embeddings via the
EmbeddingProvider protocol.  Uses the configured LLM client factory to load
the appropriate provider.

Since the OpenAI adapter now uses ``AsyncOpenAI``, the ``embed()`` method on
``BaseLLMClient`` is async-native — no ``run_in_executor`` bridge is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starboard.adapters.llm import BaseLLMClient, create_llm_client
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.infra.core.config import EnvConfig

logger = get_logger(__name__)


class LLMClientEmbeddingProvider:
    """
    Embedding provider that uses BaseLLMClient for embeddings.

    Loads the configured LLM client using the factory pattern and delegates
    embedding calls to the client's embed() method.

    Args:
        llm_client: Optional LLM client instance. If None, creates one from config.
        cfg: Optional configuration. If None, loads from environment.

    Example:
        from starboard.infra.rag import LLMClientEmbeddingProvider, SQLiteMultiCollectionStore
        from starboard.infra.core.config import EnvConfig, get_config

        # Use default LLM client from config
        provider = LLMClientEmbeddingProvider()

        # Or provide explicit config
        config = get_config()
        provider = LLMClientEmbeddingProvider(cfg=config)

        # Or provide existing LLM client
        from starboard.adapters.llm import create_llm_client
        llm_client = create_llm_client(cfg=config)
        provider = LLMClientEmbeddingProvider(llm_client=llm_client)

        # Use with vector store
        store = SQLiteMultiCollectionStore(
            db_path="vectors.db",
            embedding_provider=provider,
        )

        # Generate embeddings
        embedding = await provider.embed("test query")
        embeddings = await provider.embed_batch(["text1", "text2"])
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        cfg: EnvConfig | None = None,
    ) -> None:
        """
        Initialize LLM client embedding provider.

        Args:
            llm_client: Optional LLM client instance. If None, creates one from config.
            cfg: Optional configuration. If None, loads from environment.

        Raises:
            ValueError: If LLM client cannot be created or is missing embed() method.
        """
        if llm_client is not None:
            self.llm_client = llm_client
        else:
            self.llm_client = create_llm_client(cfg=cfg)
            logger.debug(
                "llm_client_embedding_provider_initialized",
                llm_client=type(self.llm_client).__name__,
            )

        # Verify client has embed method
        if not hasattr(self.llm_client, "embed"):
            raise ValueError(
                f"LLM client {type(self.llm_client).__name__} does not implement embed() method"
            )

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for text using LLM client.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.

        Example:
            embedding = await provider.embed("test query")
        """
        if not text:
            return []

        embeddings = await self.llm_client.embed([text])
        return embeddings[0] if embeddings else []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using LLM client.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Example:
            embeddings = await provider.embed_batch(["text1", "text2"])
        """
        if not texts:
            return []

        return await self.llm_client.embed(texts)
