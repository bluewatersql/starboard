"""
Embedding provider adapters.

Provides implementations of the EmbeddingProvider protocol for various backends.
"""

from starboard_server.infra.rag.adapters.embedding.helpers import (
    create_mock_provider,
    get_default_embedding_provider,
)
from starboard_server.infra.rag.adapters.embedding.llm_client_provider import (
    LLMClientEmbeddingProvider,
)
from starboard_server.infra.rag.adapters.embedding.mock_provider import (
    MockEmbeddingProvider,
)

__all__ = [
    "LLMClientEmbeddingProvider",
    "MockEmbeddingProvider",
    "create_mock_provider",
    "get_default_embedding_provider",
]
