"""RAG domain layer - Pure logic, protocols, and models (NO I/O)."""

from starboard_server.infra.rag.domain.protocols import (
    CollectionType,
    EmbeddingProvider,
    MultiCollectionStore,
    VectorQuery,
    VectorQueryResult,
)

__all__ = [
    "CollectionType",
    "EmbeddingProvider",
    "MultiCollectionStore",
    "VectorQuery",
    "VectorQueryResult",
]
