"""Tests for embedding provider wiring in Container.

Tests cover:
- Fake provider used in offline mode
- Fake provider used in mock_llm mode
- Fake provider used when no provider given
- Real provider wraps LLMClientEmbeddingProvider when available
- All embedding functions are async
"""

from unittest.mock import AsyncMock, MagicMock

from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.core.container import Container


class TestEmbeddingWiring:
    """Tests for _create_embedding_function behavior."""

    async def test_fake_embeddings_in_offline_mode(self):
        """Offline mode uses hash-based async fake embeddings."""
        config = EnvConfig(offline_mode=True)
        container = Container(config)

        fn = container._create_embedding_function(provider=None)
        result = await fn("hello world")

        assert isinstance(result, list)
        assert len(result) == config.embedding_dimension
        assert all(isinstance(v, float) for v in result)

        # Deterministic: same input -> same output
        assert await fn("hello world") == result

    async def test_fake_embeddings_in_mock_llm_mode(self):
        """mock_llm mode uses hash-based async fake embeddings."""
        config = EnvConfig(mock_llm=True)
        container = Container(config)

        fn = container._create_embedding_function(provider=None)
        result = await fn("test")

        assert isinstance(result, list)
        assert len(result) == config.embedding_dimension

    async def test_fake_embeddings_when_no_provider(self):
        """No provider falls back to hash-based async fake embeddings."""
        config = EnvConfig()
        container = Container(config)

        fn = container._create_embedding_function(provider=None)
        result = await fn("test")

        assert isinstance(result, list)
        assert len(result) == config.embedding_dimension

    async def test_real_embeddings_wraps_provider(self):
        """Normal mode wraps async provider directly."""
        config = EnvConfig(offline_mode=False, mock_llm=False)
        container = Container(config)

        # Mock an embedding provider
        mock_provider = MagicMock()
        mock_provider.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        fn = container._create_embedding_function(provider=mock_provider)

        # The function should call the provider
        result = await fn("test query")
        assert result == [0.1, 0.2, 0.3]
        mock_provider.embed.assert_called_once_with("test query")

    async def test_different_inputs_produce_different_fake_embeddings(self):
        """Hash-based fakes produce different vectors for different inputs."""
        config = EnvConfig(offline_mode=True)
        container = Container(config)

        fn = container._create_embedding_function(provider=None)
        vec1 = await fn("hello")
        vec2 = await fn("world")

        assert vec1 != vec2
