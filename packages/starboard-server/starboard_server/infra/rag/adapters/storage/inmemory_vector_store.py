# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""In-memory vector store implementation for development and CLI usage.

This module provides a pure Python + NumPy implementation of the MultiCollectionStore
protocol, enabling RAG functionality without external dependencies (SQLite vector extensions).

Key Features:
- Zero external dependencies (only NumPy)
- Fast startup and search for small-to-medium corpora (<10K vectors)
- Protocol-compliant with MultiCollectionStore
- Domain-based filtering
- Vectorized cosine similarity search

Limitations:
- Ephemeral storage (no persistence across sessions)
- Brute-force search O(n*d) - acceptable for <10K vectors
- Single-process only
- Memory footprint: ~5KB per vector

Use Cases:
- CLI one-shot executions
- Development/testing environments
- CI/CD pipelines
- Fallback when SQLite vector extensions unavailable
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from starboard_core.rag.models import (
    RAGCodebookContext,
    RAGContext,
    RAGFacetContext,
    RAGNuanceContext,
    RAGTableContext,
)

from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_server.infra.rag.domain.protocols import EmbeddingProvider

logger = get_logger(__name__)


@dataclass
class VectorRecord:
    """Single vector entry in a collection.

    Stores the original RAG object, its text representation, embedding,
    and metadata for filtering and retrieval.
    """

    id: str  # Unique ID within collection
    collection: str  # Collection name (Tables, Nuance, Codebook, Facets)
    content: str  # Text content used for embedding
    embedding: np.ndarray  # Vector embedding (shape: (embedding_dim,))
    metadata: dict[str, Any]  # Domain, source, timestamps, etc.
    rag_object: (
        RAGTableContext | RAGNuanceContext | RAGCodebookContext | RAGFacetContext
    )  # Original object


class InMemoryMultiCollectionStore:
    """In-memory implementation of MultiCollectionStore protocol.

    Provides RAG context retrieval using pure Python + NumPy cosine similarity.
    Designed for CLI and development environments where SQLite vector extensions
    are unavailable or undesirable.

    Example:
        >>> embedding_provider = LLMClientEmbeddingProvider(...)
        >>> store = InMemoryMultiCollectionStore(
        ...     embedding_provider=embedding_provider,
        ...     embedding_dim=1024,
        ... )
        >>> await store.initialize()
        >>> await store.add_tables([table1, table2, ...])
        >>> results = await store.search_multi_collection(
        ...     query="warehouse costs",
        ...     collections=["Tables", "Nuance"],
        ...     n_results_per_collection=5,
        ... )
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        embedding_dim: int = 1024,
        max_vectors: int = 10000,
    ):
        """Initialize in-memory vector store.

        Args:
            embedding_provider: Provider for generating embeddings
            embedding_dim: Dimension of embeddings (must match provider)
            max_vectors: Maximum total vectors across all collections (safety limit)
        """
        self.embedding_provider = embedding_provider
        self.embedding_dim = embedding_dim
        self._max_vectors = max_vectors

        # Collections (separate namespaces)
        self._tables: list[VectorRecord] = []
        self._nuance: list[VectorRecord] = []
        self._codebook: list[VectorRecord] = []
        self._facets: list[VectorRecord] = []

        # Domain index for fast filtering (domain -> set of record IDs)
        self._domain_index: dict[str, set[str]] = {}

        # Embeddings matrices (NumPy arrays for vectorized operations)
        # Shape: (n_vectors, embedding_dim)
        self._embeddings: dict[str, np.ndarray | None] = {
            "Tables": None,
            "Nuance": None,
            "Codebook": None,
            "Facets": None,
        }

        # Metadata
        self._initialized = False
        self._creation_time = time.time()

        logger.debug(
            "inmemory_vector_store_created",
            embedding_dim=embedding_dim,
            max_vectors=max_vectors,
        )

    async def initialize(self) -> None:
        """Initialize vector store.

        For in-memory store, this is a no-op (initialization happens during add_* calls).
        Method exists for protocol compliance.
        """
        self._initialized = True
        logger.info(
            "inmemory_vector_store_initialized",
            embedding_dim=self.embedding_dim,
            max_vectors=self._max_vectors,
        )

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text query.

        Args:
            text: Query text

        Returns:
            Embedding vector

        Raises:
            ValueError: If no embedding provider configured
        """
        if not self.embedding_provider:
            raise ValueError("No embedding provider configured")

        return await self.embedding_provider.embed(text)

    async def search_multi_collection(
        self,
        query: str,
        collections: list[str],
        n_results_per_collection: int = 20,
        domains: list[str] | None = None,
    ) -> RAGContext:
        """Search multiple collections for relevant context.

        Args:
            query: Natural language query
            collections: List of collection names to search
            n_results_per_collection: Max results per collection
            domains: Optional list of domains to filter by

        Returns:
            RAGContext with results from all collections
        """
        start_time = time.time()

        # Generate query embedding
        query_embedding = await self.embedding_provider.embed(query)
        query_embedding_np = np.array(query_embedding, dtype=np.float32)

        # Search each collection
        results = RAGContext(
            tables=(
                await self._search_collection(
                    "Tables", query_embedding_np, n_results_per_collection, domains
                )
                if "Tables" in collections
                else []
            ),
            nuance=(
                await self._search_collection(
                    "Nuance", query_embedding_np, n_results_per_collection, domains
                )
                if "Nuance" in collections
                else []
            ),
            codebook=(
                await self._search_collection(
                    "Codebook", query_embedding_np, n_results_per_collection, domains
                )
                if "Codebook" in collections
                else []
            ),
            facets=(
                await self._search_collection(
                    "Facets", query_embedding_np, n_results_per_collection, domains
                )
                if "Facets" in collections
                else []
            ),
            learnings=[],  # Not implemented yet
        )

        elapsed_ms = (time.time() - start_time) * 1000

        logger.debug(
            "inmemory_vector_store_search",
            query_length=len(query),
            collections=collections,
            n_results_per_collection=n_results_per_collection,
            domains=domains,
            elapsed_ms=elapsed_ms,
            result_tables=len(results.tables),
            result_nuance=len(results.nuance),
            result_codebook=len(results.codebook),
            result_facets=len(results.facets),
        )

        # Warn if search is slow
        if elapsed_ms > 500:
            total_vectors = sum(
                len(self._get_collection_records(c)) for c in collections
            )
            logger.warning(
                "inmemory_vector_store_slow_search",
                elapsed_ms=elapsed_ms,
                threshold_ms=500,
                total_vectors=total_vectors,
                suggestion="consider using SQLite backend for better performance",
            )

        return results

    async def add_tables(
        self,
        tables: list[RAGTableContext],
        precomputed_embeddings: dict[int, np.ndarray] | None = None,
    ) -> None:
        """Add table metadata to Tables collection.

        Args:
            tables: List of RAGTableContext objects to add
            precomputed_embeddings: Optional dict of precomputed embeddings keyed by table index

        Raises:
            ValueError: If adding would exceed max_vectors limit
        """
        await self._check_capacity(len(tables))

        for idx, table in enumerate(tables):
            # Build searchable content
            content = self._build_table_content(table)

            # Use precomputed embedding if available (by index), otherwise generate
            if precomputed_embeddings and idx in precomputed_embeddings:
                embedding_np = precomputed_embeddings[idx]
            else:
                # Generate embedding
                embedding = await self.embedding_provider.embed(content)
                embedding_np = np.array(embedding, dtype=np.float32)

            # Create record
            record = VectorRecord(
                id=table.table_name or f"table_{hash(content) % 100000}",
                collection="Tables",
                content=content,
                embedding=embedding_np,
                metadata={
                    "domain": table.domain or "",
                },
                rag_object=table,
            )

            self._tables.append(record)

            # Update domain index
            if table.domain:
                if table.domain not in self._domain_index:
                    self._domain_index[table.domain] = set()
                self._domain_index[table.domain].add(record.id)

        # Rebuild embeddings matrix for vectorized search
        self._rebuild_embeddings_matrix("Tables")

        logger.debug(
            "inmemory_vector_store_tables_added",
            count=len(tables),
            total_tables=len(self._tables),
        )

    async def add_nuance(
        self,
        nuance: list[RAGNuanceContext],
        precomputed_embeddings: dict[int, np.ndarray] | None = None,
    ) -> None:
        """Add nuance/best practices to Nuance collection.

        Args:
            nuance: List of RAGNuanceContext objects to add
            precomputed_embeddings: Optional dict of precomputed embeddings keyed by nuance index

        Raises:
            ValueError: If adding would exceed max_vectors limit
        """
        await self._check_capacity(len(nuance))

        for idx, item in enumerate(nuance):
            # Use content directly as searchable text
            content = item.content

            # Use precomputed embedding if available, otherwise generate
            if precomputed_embeddings and idx in precomputed_embeddings:
                embedding_np = precomputed_embeddings[idx]
            else:
                # Generate embedding
                embedding = await self.embedding_provider.embed(content)
                embedding_np = np.array(embedding, dtype=np.float32)

            # Create unique ID
            item_id = f"nuance_{hash(content) % 100000}"

            # Create record
            record = VectorRecord(
                id=item_id,
                collection="Nuance",
                content=content,
                embedding=embedding_np,
                metadata={
                    "domain": item.domain or "",
                    "category": item.type or "",
                },
                rag_object=item,
            )

            self._nuance.append(record)

            # Update domain index
            if item.domain:
                if item.domain not in self._domain_index:
                    self._domain_index[item.domain] = set()
                self._domain_index[item.domain].add(record.id)

        # Rebuild embeddings matrix
        self._rebuild_embeddings_matrix("Nuance")

        logger.debug(
            "inmemory_vector_store_nuance_added",
            count=len(nuance),
            total_nuance=len(self._nuance),
        )

    async def add_codebook(
        self,
        codebook: list[RAGCodebookContext],
        precomputed_embeddings: dict[int, np.ndarray] | None = None,
    ) -> None:
        """Add codebook entries to Codebook collection.

        Args:
            codebook: List of RAGCodebookContext objects to add
            precomputed_embeddings: Optional dict of precomputed embeddings keyed by codebook index

        Raises:
            ValueError: If adding would exceed max_vectors limit
        """
        await self._check_capacity(len(codebook))

        for idx, entry in enumerate(codebook):
            # Build searchable content
            content = f"{entry.code}: {entry.description}"

            # Use precomputed embedding if available, otherwise generate
            if precomputed_embeddings and idx in precomputed_embeddings:
                embedding_np = precomputed_embeddings[idx]
            else:
                # Generate embedding
                embedding = await self.embedding_provider.embed(content)
                embedding_np = np.array(embedding, dtype=np.float32)

            # Create unique ID
            entry_id = entry.code

            # Create record
            record = VectorRecord(
                id=entry_id,
                collection="Codebook",
                content=content,
                embedding=embedding_np,
                metadata={
                    "domain": entry.domain or "",
                    "code": entry.code,
                },
                rag_object=entry,
            )

            self._codebook.append(record)

            # Update domain index
            if entry.domain:
                if entry.domain not in self._domain_index:
                    self._domain_index[entry.domain] = set()
                self._domain_index[entry.domain].add(record.id)

        # Rebuild embeddings matrix
        self._rebuild_embeddings_matrix("Codebook")

        logger.debug(
            "inmemory_vector_store_codebook_added",
            count=len(codebook),
            total_codebook=len(self._codebook),
        )

    async def add_facets(
        self,
        facets: list[RAGFacetContext],
    ) -> None:
        """Add facets to Facets collection.

        Args:
            facets: List of RAGFacetContext objects to add

        Raises:
            ValueError: If adding would exceed max_vectors limit
        """
        await self._check_capacity(len(facets))

        for facet in facets:
            # Build searchable content
            content = f"{facet.code}: {', '.join(facet.values[:10])}"  # First 10 values

            # Generate embedding
            embedding = await self.embedding_provider.embed(content)
            embedding_np = np.array(embedding, dtype=np.float32)

            # Create unique ID
            facet_id = facet.code

            # Create record
            record = VectorRecord(
                id=facet_id,
                collection="Facets",
                content=content,
                embedding=embedding_np,
                metadata={
                    "domain": facet.domain or "",
                    "code": facet.code,
                },
                rag_object=facet,
            )

            self._facets.append(record)

            # Update domain index
            if facet.domain:
                if facet.domain not in self._domain_index:
                    self._domain_index[facet.domain] = set()
                self._domain_index[facet.domain].add(record.id)

        # Rebuild embeddings matrix
        self._rebuild_embeddings_matrix("Facets")

        logger.debug(
            "inmemory_vector_store_facets_added",
            count=len(facets),
            total_facets=len(self._facets),
        )

    async def _search_collection(
        self,
        collection: str,
        query_embedding: np.ndarray,
        n_results: int,
        domains: list[str] | None,
    ) -> list[Any]:
        """Search a single collection using cosine similarity.

        Args:
            collection: Collection name
            query_embedding: Query embedding vector
            n_results: Max results to return
            domains: Optional domain filter

        Returns:
            List of RAG objects (RAGTableContext, RAGNuance, etc.)
        """
        records = self._get_collection_records(collection)

        if not records:
            return []

        # Filter by domains
        if domains:
            records = [r for r in records if r.metadata.get("domain") in domains]

        if not records:
            return []

        # Get embeddings matrix for this collection
        embeddings_matrix = self._get_embeddings_for_records(collection, records)

        if embeddings_matrix is None or len(embeddings_matrix) == 0:
            return []

        # Compute cosine similarities
        similarities = self._cosine_similarity_batch(query_embedding, embeddings_matrix)

        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1][:n_results]

        # Return RAG objects
        return [records[i].rag_object for i in top_indices]

    def _cosine_similarity_batch(
        self,
        query_embedding: np.ndarray,  # Shape: (d,)
        doc_embeddings: np.ndarray,  # Shape: (n, d)
    ) -> np.ndarray:  # Shape: (n,)
        """Compute cosine similarity between query and all documents.

        Uses vectorized NumPy operations for efficiency.

        Args:
            query_embedding: Query embedding vector
            doc_embeddings: Document embeddings matrix

        Returns:
            Similarity scores for each document
        """
        # Normalize query
        query_norm = np.linalg.norm(query_embedding)
        if query_norm == 0:
            return np.zeros(len(doc_embeddings))
        query_normalized = query_embedding / query_norm

        # Normalize documents (row-wise)
        doc_norms = np.linalg.norm(doc_embeddings, axis=1, keepdims=True)
        # Avoid division by zero
        doc_norms = np.where(doc_norms == 0, 1, doc_norms)
        doc_embeddings_normalized = doc_embeddings / doc_norms

        # Compute dot products (cosine similarity)
        similarities = doc_embeddings_normalized @ query_normalized

        return similarities

    def _rebuild_embeddings_matrix(self, collection: str) -> None:
        """Rebuild embeddings matrix for a collection.

        Called after adding new records to enable vectorized search.

        Args:
            collection: Collection name
        """
        records = self._get_collection_records(collection)

        if not records:
            self._embeddings[collection] = None
            return

        # Stack embeddings into matrix
        embeddings_list = [r.embedding for r in records]
        self._embeddings[collection] = np.vstack(embeddings_list)

        emb_matrix = self._embeddings[collection]
        assert emb_matrix is not None
        logger.debug(
            "inmemory_embeddings_matrix_rebuilt",
            collection=collection,
            shape=emb_matrix.shape,
        )

    def _get_collection_records(self, collection: str) -> list[VectorRecord]:
        """Get all records for a collection.

        Args:
            collection: Collection name

        Returns:
            List of VectorRecord objects
        """
        return {
            "Tables": self._tables,
            "Nuance": self._nuance,
            "Codebook": self._codebook,
            "Facets": self._facets,
        }.get(collection, [])

    def _get_embeddings_for_records(
        self,
        collection: str,
        records: list[VectorRecord],
    ) -> np.ndarray | None:
        """Get embeddings matrix for specific records (with domain filtering).

        Args:
            collection: Collection name
            records: Filtered list of records

        Returns:
            Embeddings matrix or None
        """
        all_records = self._get_collection_records(collection)
        full_matrix = self._embeddings.get(collection)

        if full_matrix is None or len(all_records) == 0:
            return None

        # If no filtering, return full matrix
        if len(records) == len(all_records):
            return full_matrix

        # Find indices of filtered records
        record_ids = {r.id for r in records}
        indices = [i for i, r in enumerate(all_records) if r.id in record_ids]

        # Return filtered embeddings
        return full_matrix[indices]

    def _build_table_content(self, table: RAGTableContext) -> str:
        """Build searchable text content for a table.

        Args:
            table: RAGTableContext object

        Returns:
            Searchable text representation
        """
        parts = [
            f"Table: {table.table_name}",
        ]

        if table.description:
            parts.append(f"Description: {table.description}")

        if table.table_columns:
            parts.append(f"Columns: {table.table_columns}")

        if table.use_cases:
            parts.append(f"Use cases: {table.use_cases}")

        return " | ".join(parts)

    async def _check_capacity(self, adding: int) -> None:
        """Check if adding vectors would exceed capacity.

        Args:
            adding: Number of vectors to add

        Raises:
            ValueError: If adding would exceed max_vectors limit
        """
        total = (
            len(self._tables)
            + len(self._nuance)
            + len(self._codebook)
            + len(self._facets)
        )
        new_total = total + adding

        if new_total > self._max_vectors:
            raise ValueError(
                f"Cannot add {adding} vectors: would exceed max_vectors limit "
                f"({self._max_vectors}). Current: {total}, New total: {new_total}"
            )

        # Warn at 80% capacity
        if new_total > self._max_vectors * 0.8 and total <= self._max_vectors * 0.8:
            logger.warning(
                "inmemory_vector_store_near_capacity",
                current=total,
                adding=adding,
                max_vectors=self._max_vectors,
                utilization=new_total / self._max_vectors,
            )

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the vector store.

        Returns:
            Dictionary with store statistics
        """
        total_vectors = (
            len(self._tables)
            + len(self._nuance)
            + len(self._codebook)
            + len(self._facets)
        )

        return {
            "backend": "inmemory",
            "total_vectors": total_vectors,
            "max_vectors": self._max_vectors,
            "utilization": total_vectors / self._max_vectors,
            "collections": {
                "tables": len(self._tables),
                "nuance": len(self._nuance),
                "codebook": len(self._codebook),
                "facets": len(self._facets),
            },
            "domains": list(self._domain_index.keys()),
            "memory_estimate_mb": (total_vectors * self.embedding_dim * 4)
            / (1024 * 1024),
            "initialized": self._initialized,
            "uptime_seconds": time.time() - self._creation_time,
        }

    async def close(self) -> None:
        """Release resources (no-op for this store)."""

    async def connect(self) -> None:
        """Initialize connection (no-op for this store)."""

    async def delete(self, _key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, _key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, _key: str, _value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
