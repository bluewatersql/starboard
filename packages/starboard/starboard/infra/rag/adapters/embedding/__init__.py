# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Embedding provider adapters.

Provides implementations of the EmbeddingProvider protocol for various backends.
"""

from starboard.infra.rag.adapters.embedding.helpers import (
    create_mock_provider,
    get_default_embedding_provider,
)
from starboard.infra.rag.adapters.embedding.llm_client_provider import (
    LLMClientEmbeddingProvider,
)
from starboard.infra.rag.adapters.embedding.mock_provider import (
    MockEmbeddingProvider,
)

__all__ = [
    "LLMClientEmbeddingProvider",
    "MockEmbeddingProvider",
    "create_mock_provider",
    "get_default_embedding_provider",
]
