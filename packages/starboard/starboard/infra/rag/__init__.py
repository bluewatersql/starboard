# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
RAG (Retrieval-Augmented Generation) infrastructure for Analytics Agent.

Organized in three architectural layers:
- domain/: Pure logic, protocols (no I/O)
- services/: Orchestration, business logic
- adapters/: I/O boundaries (storage, embedding providers)
"""

# Domain layer (protocols and pure logic)
# Adapter layer (I/O implementations)
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
from starboard.infra.rag.adapters.storage.sqlite_multi_collection_store import (
    SQLiteMultiCollectionStore,
)
from starboard.infra.rag.adapters.storage.sqlite_vector_store import (
    SQLiteVectorStore,
)

# Legacy imports (for backward compatibility - will be deprecated)
from starboard.infra.rag.checkpoint import (
    is_file_fresh as is_file_fresh_advanced,
)
from starboard.infra.rag.checkpoint import (
    read_checkpoint as read_checkpoint_advanced,
)
from starboard.infra.rag.checkpoint import (
    validate_checkpoint,
)
from starboard.infra.rag.checkpoint import (
    write_checkpoint as write_checkpoint_advanced,
)
from starboard.infra.rag.domain import (
    CollectionType,
    EmbeddingProvider,
    MultiCollectionStore,
    VectorQuery,
    VectorQueryResult,
)
from starboard.infra.rag.domain.query_analyzer import QueryAnalyzer
from starboard.infra.rag.domain.sql_parser import analyze_dataframe

# Service layer (orchestration)
from starboard.infra.rag.services.checkpoint_service import (
    is_file_fresh,
    read_checkpoint,
    write_checkpoint,
)
from starboard.infra.rag.services.chunking_service import (
    ChunkingService,
    TableChunk,
)
from starboard.infra.rag.services.domain_service import (
    DomainChunk,
    DomainService,
)
from starboard.infra.rag.services.enrichment_service import (
    EnrichmentService,
)
from starboard.infra.rag.services.metadata_service import (
    DatabricksClient,
    MetadataExtractor,
)

__all__ = [
    # Domain layer
    "CollectionType",
    "EmbeddingProvider",
    "MultiCollectionStore",
    "QueryAnalyzer",
    "VectorQuery",
    "VectorQueryResult",
    "analyze_dataframe",
    # Service layer
    "ChunkingService",
    "DOMAIN_MAPPINGS",
    "DatabricksClient",
    "DomainChunk",
    "DomainService",
    "EnrichmentService",
    "MetadataExtractor",
    "TableChunk",
    "is_file_fresh",
    "read_checkpoint",
    "write_checkpoint",
    # Adapter layer
    "LLMClientEmbeddingProvider",
    "MockEmbeddingProvider",
    "SQLiteMultiCollectionStore",
    "SQLiteVectorStore",
    "create_mock_provider",
    "get_default_embedding_provider",
    # Legacy (backward compatibility)
    "is_file_fresh_advanced",
    "read_checkpoint_advanced",
    "validate_checkpoint",
    "write_checkpoint_advanced",
]
