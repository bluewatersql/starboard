"""Embedding generation service."""

from __future__ import annotations

from starboard_server.infra.core.container import Container
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    """

    Service for generating text embeddings.

    Features:
    - Async embedding generation
    - Automatic caching (24 hour TTL)
    - Batch embedding support
    - Configurable model

    Example:
        service = EmbeddingService(api_key="<your-llm-api-key>", container=container)
        embedding = await service.embed("Hello world")
        # Returns 1536-dimensional vector

    Note:
        Requires LLM_API_KEY in environment or passed explicitly.
        Falls back to mock embeddings if API key not available.
    """

    def __init__(self, api_key: str | None, container: Container):
        """
        Initialize embedding service.

        Args:
            api_key: OpenAI API key (None to use mock embeddings)
            container: DI container for caching
        """
        self._api_key = api_key
        self._cache_manager = container.cache_manager
        self._config = container.config
        self._client = None

        # Initialize OpenAI client if API key available
        if api_key:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=self._config.llm_base_url,
                )
                logger.debug(
                    "embedding_service_initialized",
                    model=self._config.embedding_model,
                    cache_ttl=self._config.embedding_cache_ttl,
                )
            except ImportError:
                logger.warning(
                    "openai_not_installed",
                    message="OpenAI package not found. Install with: pip install openai",
                )
                self._client = None
        else:
            logger.debug(
                "embedding_service_mock_mode",
                message="No API key provided, using mock embeddings",
            )

    async def embed(self, text: str) -> list[float]:
        """
        Generate embedding for text.

        Args:
            text: Text to embed (truncated to 8000 chars)

        Returns:
            Embedding vector (dimensions depend on configured model)

        Note:
            Results are cached for 24 hours by default.
        """
        # Truncate text
        truncated_text = text[:8000]

        # Check cache
        cache_key = self._cache_manager.generate_key(
            "embedding",
            text_hash=hash(truncated_text),
            model=self._config.embedding_model,
        )

        cached = await self._cache_manager._store.get(cache_key)
        if cached:
            logger.debug(
                "embedding_cache_hit",
                text_length=len(text),
                cache_key=cache_key,
            )
            return cached

        # Generate embedding
        logger.debug(
            "embedding_cache_miss",
            text_length=len(text),
            cache_key=cache_key,
        )

        if self._client:
            embedding = await self._generate_real_embedding(truncated_text)
        else:
            embedding = self._generate_mock_embedding(truncated_text)

        # Cache for configured TTL
        await self._cache_manager._store.set(
            cache_key,
            embedding,
            ttl=self._config.embedding_cache_ttl,
        )

        logger.debug(
            "embedding_generated",
            text_length=len(text),
            embedding_dim=len(embedding),
            cached=True,
        )

        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors

        Note:
            Uses batch API call if OpenAI client available,
            otherwise generates mock embeddings sequentially.
        """
        if not texts:
            return []

        # Truncate texts
        truncated = [text[:8000] for text in texts]

        if self._client:
            # Batch API call
            embeddings = await self._generate_real_embeddings_batch(truncated)
        else:
            # Generate mock embeddings
            embeddings = [self._generate_mock_embedding(text) for text in truncated]

        logger.debug(
            "batch_embeddings_generated",
            count=len(texts),
            total_length=sum(len(t) for t in texts),
        )

        return embeddings

    async def _generate_real_embedding(self, text: str) -> list[float]:
        """
        Generate real embedding using OpenAI API.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        response = await self._client.embeddings.create(  # type: ignore[union-attr]
            model=self._config.embedding_model,
            input=text,
        )

        return response.data[0].embedding

    async def _generate_real_embeddings_batch(
        self, texts: list[str]
    ) -> list[list[float]]:
        """
        Generate real embeddings using OpenAI batch API.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        response = await self._client.embeddings.create(  # type: ignore[union-attr]
            model=self._config.embedding_model,
            input=texts,
        )

        return [data.embedding for data in response.data]

    def _generate_mock_embedding(self, text: str) -> list[float]:
        """
        Generate mock embedding for testing.

        Args:
            text: Text to embed

        Returns:
            Mock embedding vector (1536 dimensions, deterministic)

        Note:
            Uses hash of text to generate deterministic mock embedding.
            Not suitable for production use.
        """
        # Generate deterministic mock embedding based on text hash
        text_hash = hash(text)

        # Create 1536-dimensional mock vector
        embedding = []
        for i in range(1536):
            # Use hash to generate pseudo-random but deterministic values
            value = ((text_hash + i) % 1000) / 1000.0 - 0.5
            embedding.append(value)

        return embedding
