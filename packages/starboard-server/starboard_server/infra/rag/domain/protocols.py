# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
RAG domain protocols and interfaces.

Defines abstract interfaces for:
- Embedding generation (EmbeddingProvider)
- Multi-collection vector storage (MultiCollectionStore)
- Domain models for queries and results

These protocols enable dependency inversion and flexible implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from starboard_core.foundations.models import (
    VectorRecord,
    VectorSearchResult,
)
from starboard_core.rag.models import (
    RAGCodebookContext,
    RAGContext,
    RAGFacetContext,
    RAGNuanceContext,
    RAGTableContext,
)

# ============================================================================
# Embedding Provider Protocol
# ============================================================================


@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Protocol for embedding generation.

    Implementations must provide async methods for single and batch embedding.
    This allows the vector store to work with any embedding provider
    (OpenAI, Databricks, Azure, mock, etc.).

    Example Implementations:
        - EmbeddingService (starboard_server.services.memory.embedding_service)
        - BaseLLMClient providers (OpenAI, Anthropic, etc.)
        - Custom providers (Databricks, Cohere, etc.)
        - Mock providers for testing

    Example:
        # Using existing EmbeddingService
        from starboard_server.services.memory import EmbeddingService
        from starboard_server.infra.rag.adapters.storage import SQLiteMultiCollectionStore

        embedding_service = EmbeddingService(api_key="<your-llm-api-key>", container=container)
        store = SQLiteMultiCollectionStore(
            db_path="vectors.db",
            embedding_provider=embedding_service,
        )

        # Using mock for testing
        from starboard_server.infra.rag.adapters.embedding import MockEmbeddingProvider

        store = SQLiteMultiCollectionStore(
            db_path="test.db",
            embedding_provider=MockEmbeddingProvider(),
        )
    """

    async def embed(self, text: str) -> list[float]:
        """
        Generate embedding for text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        ...


# ============================================================================
# Multi-Collection Vector Store Protocol
# ============================================================================


class CollectionType(StrEnum):
    """Collection types for multi-collection vector store."""

    TABLES = "tables"
    NUANCE = "nuance"
    FACETS = "facets"
    CODEBOOK = "codebook"
    LEARNINGS = "learnings"


@dataclass(frozen=True)
class VectorQuery:
    """
    Query parameters for vector search.

    Attributes:
        query_embedding: Query vector embedding
        collection: Collection to search
        domains: Domain filter (e.g., ["finops_billing"])
        n_results: Number of results to return
        agent_domain: Agent domain for learnings (e.g., "analytics")
    """

    query_embedding: list[float]
    collection: CollectionType
    domains: list[str] | None = None
    n_results: int = 20
    agent_domain: str | None = None  # For learnings collection


@dataclass
class VectorQueryResult:
    """
    Result from vector search.

    Attributes:
        results: List of search results
        collection: Collection queried
        domains_queried: Domains that were filtered
        total_results: Total results before deduplication
        deduplicated: Whether results were deduplicated
    """

    results: list[VectorSearchResult]
    collection: CollectionType
    domains_queried: list[str] | None
    total_results: int
    deduplicated: bool = False


@runtime_checkable
class MultiCollectionStore(Protocol):
    """
    Protocol for multi-collection vector stores.

    Supports separate collections for Tables, Nuance, Facets, and Learnings
    with collection-specific query methods and domain filtering.

    Pattern:
        store = SQLiteMultiCollectionStore("vectors.db")
        await store.initialize()

        # Query specific collections
        tables = await store.query_tables(embedding, domains=["finops_billing"])
        nuance = await store.query_nuance(embedding, domains=["finops_billing"])
        facets = await store.query_facets(embedding, domains=["compute_warehouses"])
    """

    embedding_provider: EmbeddingProvider | None = None
    embedding_dim: int = 1024

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_dim: int = 1024,
    ):
        """
        Initialize the vector store.

        Args:
            embedding_provider: Embedding provider
            embedding_dim: Embedding dimension
        """
        self.embedding_provider = embedding_provider
        self.embedding_dim = embedding_dim

    async def initialize(self) -> None:
        """
        Initialize the vector store.

        Creates collections/tables if they don't exist.

        Raises:
            Exception: If initialization fails
        """
        ...

    async def generate_embedding(self, text: str) -> list[float]:
        """
        Generate embedding for text query using configured provider.

        Args:
            text: Query text

        Returns:
            Embedding vector

        Raises:
            ValueError: If no embedding provider configured
        """
        if not self.embedding_provider:
            raise ValueError(
                "No embedding provider configured. "
                "Pass embedding_provider to __init__() to use text-based search methods, "
                "or use query_* methods with pre-computed embeddings."
            )

        return await self.embedding_provider.embed(text)

    async def search_tables(
        self,
        query: str,
        *,
        domains: list[str] | None = None,
        n_results: int = 20,
    ) -> list[RAGTableContext]:
        """
        Search Tables collection using text query.

        Convenience method that generates embedding and calls query_tables().

        Args:
            query: Text query (e.g., "billing usage and costs")
            domains: Optional domain filter (e.g., ["finops_billing"])
            n_results: Number of results (before deduplication)
            deduplicate: Whether to deduplicate by base_id

        Returns:
            List of search results

        Raises:
            ValueError: If no embedding provider configured
        """
        query_embedding = await self.generate_embedding(query)

        return await self.query_tables(
            query_embedding=query_embedding,
            domains=domains,
            n_results=n_results,
        )

    async def search_nuance(
        self,
        query: str,
        *,
        domains: list[str] | None = None,
        n_results: int = 25,
    ) -> list[RAGNuanceContext]:
        """
        Search Nuance collection using text query.

        Searches platform concepts, rules, and best practices.

        Args:
            query: Text query
            domains: Optional domain filter
            n_results: Number of results

        Returns:
            List of search results

        Raises:
            ValueError: If no embedding provider configured
        """
        query_embedding = await self.generate_embedding(query)

        return await self.query_nuance(
            query_embedding=query_embedding,
            domains=domains,
            n_results=n_results,
        )

    async def search_codebook(
        self,
        query: str,
        *,
        domains: list[str] | None = None,
        n_results: int = 50,
    ) -> list[RAGCodebookContext]:
        """
        Search Codebook collection using text query.

        Searches codebook entries for exact matching.

        Args:
            query: Text query
            domains: Optional domain filter
            n_results: Number of results

        Returns:
            List of search results
        """
        query_embedding = await self.generate_embedding(query)

        return await self.query_codebook(
            query_embedding=query_embedding,
            domains=domains,
            n_results=n_results,
        )

    async def search_facets(
        self,
        query: str,
        *,
        domains: list[str] | None = None,
        n_results: int = 50,
    ) -> list[RAGFacetContext]:
        """
        Search Facets collection using text query.

        Searches exploded categorical values for exact matching.

        Args:
            query: Text query (e.g., "warehouse sizes")
            domains: Optional domain filter
            n_results: Number of results

        Returns:
            List of search results

        Raises:
            ValueError: If no embedding provider configured
        """
        query_embedding = await self.generate_embedding(query)

        return await self.query_facets(
            query_embedding=query_embedding,
            domains=domains,
            n_results=n_results,
        )

    async def search_multi_collection(
        self,
        query: str,
        *,
        collections: list[str],
        n_results_per_collection: int = 10,
        domains: list[str] | None = None,
    ) -> RAGContext:
        """
        Search multiple collections with single text query.

        Args:
            query: Text query
            collections: List of collection names
            n_results_per_collection: Number of results per collection
            domains: Optional domain filter

        Returns:
            RAGContext
        """
        query_embedding = await self.generate_embedding(query)

        return await self.query_multi_collection(
            query_embedding=query_embedding,
            collections=collections,
            n_results_per_collection=n_results_per_collection,
            domains=domains,
        )

    async def query_multi_collection(
        self,
        query_embedding: list[float],
        *,
        collections: list[str],
        n_results_per_collection: int = 10,
        domains: list[str] | None = None,
    ) -> RAGContext:
        """
        Query multiple collections with single text query.

        Generates embedding once and queries multiple collections in parallel.
        Efficient when you need results from multiple collections.

        Args:
            query_embedding: Query embedding
            collections: Collection names (e.g., ["Tables", "Nuance", "Facets"])
            n_results_per_collection: Number of results per collection (default: 10)
            domains: Optional domain filter

        Returns:
            RAGContext
        """
        ...

    async def query_tables(
        self,
        query_embedding: list[float],
        *,
        domains: list[str] | None = None,
        n_results: int = 20,
    ) -> list[RAGTableContext]:
        """
        Query Tables collection.

        Searches table metadata chunks (summary, use_cases, relationships, columns)
        with optional domain filtering and deduplication by base_id.

        Args:
            query_embedding: Query vector
            domains: Optional domain filter (e.g., ["finops_billing"])
            n_results: Number of results (before deduplication)

        Returns:
            List of search results, optionally deduplicated
        """
        ...

    async def query_codebook(
        self,
        query_embedding: list[float],
        *,
        domains: list[str] | None = None,
        n_results: int = 50,
    ) -> list[RAGCodebookContext]:
        """
        Query Codebook collection.

        Searches codebook entries for exact matching.

        Args:
            query_embedding: Query vector
            domains: Optional domain filter
            n_results: Number of results

        Returns:
            List of search results
        """
        ...

    async def query_nuance(
        self,
        query_embedding: list[float],
        *,
        domains: list[str] | None = None,
        n_results: int = 25,
    ) -> list[RAGNuanceContext]:
        """
        Query Nuance collection.

        Searches platform concepts, rules, best practices, and contextual information.

        Args:
            query_embedding: Query vector
            domains: Optional domain filter
            n_results: Number of results

        Returns:
            List of search results
        """
        ...

    async def query_facets(
        self,
        query_embedding: list[float],
        *,
        domains: list[str] | None = None,
        n_results: int = 50,
    ) -> list[RAGFacetContext]:
        """
        Query Facets collection.

        Searches exploded categorical values for exact matching
        (e.g., warehouse_size, sku_name, etc.).

        Args:
            query_embedding: Query vector
            domains: Optional domain filter
            n_results: Number of results

        Returns:
            List of search results
        """
        ...

    async def upsert_tables(self, records: list[VectorRecord]) -> None:
        """Upsert records to Tables collection."""
        ...

    async def upsert_nuance(self, records: list[VectorRecord]) -> None:
        """Upsert records to Nuance collection."""
        ...

    async def upsert_facets(self, records: list[VectorRecord]) -> None:
        """Upsert records to Facets collection."""
        ...

    async def close(self) -> None:
        """Close the vector store and release resources."""

    async def connect(self) -> None:
        """Initialize connection to the backing store."""
        ...

    async def delete(self, key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        ...

    async def get(self, key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        ...

    async def set(self, key: str, value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
        ...

        ...
