# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
SQLite-based multi-collection vector store implementation.

Implements MultiCollectionStore protocol using SQLite with sqlite-vec extension.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
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

from starboard_server.infra.rag.adapters.storage.sqlite_vector_store import (
    SQLiteVectorStore,
)
from starboard_server.infra.rag.domain.protocols import (
    CollectionType,
    EmbeddingProvider,
    MultiCollectionStore,
)

logger = structlog.get_logger(__name__)


class SQLiteMultiCollectionStore(MultiCollectionStore):
    """
    SQLite-based multi-collection vector store.

    Uses SQLiteVectorStore as backend with separate collections for:
    - Tables: Table metadata chunks
    - Nuance: Platform concepts and best practices
    - Facets: Exploded categorical values
    - Learnings: Reflexion feedback and patterns

    Supports both low-level (embedding-based) and high-level (text-based) queries:
    - Low-level: query_tables(query_embedding=[...], ...)
    - High-level: search_tables(query="billing costs", ...)

    Example:
        # With EmbeddingService
        from starboard_server.services.memory import EmbeddingService

        embedding_service = EmbeddingService(api_key="<your-llm-api-key>", container=container)
        store = SQLiteMultiCollectionStore(
            db_path="vectors.db",
            embedding_provider=embedding_service,
        )
        await store.initialize()

        # High-level search (generates embedding automatically)
        results = await store.search_tables("show me billing costs", n_results=10)

        # Low-level query (provide embedding directly)
        embedding = await embedding_service.embed("billing costs")
        results = await store.query_tables(query_embedding=embedding, n_results=10)
    """

    def __init__(
        self,
        db_path: str,
        embedding_dim: int = 1024,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        """
        Initialize multi-collection store.

        Args:
            db_path: Path to SQLite database
            embedding_dim: Dimension of embeddings (default: 1024 for OpenAI)
            embedding_provider: Optional embedding provider for text-based searches.
                If not provided, only low-level query_* methods are available.
                High-level search_* methods will raise ValueError.

        Example:
            # With embedding provider (supports both query_* and search_* methods)
            store = SQLiteMultiCollectionStore(
                db_path="vectors.db",
                embedding_provider=embedding_service,
            )

            # Without provider (only query_* methods available)
            store = SQLiteMultiCollectionStore(db_path="vectors.db")
        """
        super().__init__(
            embedding_provider=embedding_provider, embedding_dim=embedding_dim
        )
        self.db_path = db_path

        # Create separate vector stores for each collection
        self._tables_store = SQLiteVectorStore(
            db_path=db_path,
            collection_name=CollectionType.TABLES.value,
            dimension=embedding_dim,
        )
        self._nuance_store = SQLiteVectorStore(
            db_path=db_path,
            collection_name=CollectionType.NUANCE.value,
            dimension=embedding_dim,
        )
        self._codebook_store = SQLiteVectorStore(
            db_path=db_path,
            collection_name=CollectionType.CODEBOOK.value,
            dimension=embedding_dim,
        )
        self._facets_store = SQLiteVectorStore(
            db_path=db_path,
            collection_name=CollectionType.FACETS.value,
            dimension=embedding_dim,
        )

    async def initialize(self) -> None:
        """
        Initialize all collections.

        Creates tables for each collection if they don't exist.

        Raises:
            Exception: If initialization fails
        """
        await self._tables_store.initialize()
        await self._nuance_store.initialize()
        await self._codebook_store.initialize()
        await self._facets_store.initialize()

        logger.debug(
            "multi_collection_store_initialized",
            db_path=self.db_path,
            collections=[c.value for c in CollectionType],
        )

    async def query_tables(
        self,
        query_embedding: list[float],
        *,
        domains: list[str] | None = None,
        n_results: int = 20,
    ) -> list[RAGTableContext]:
        """
        Query Tables collection.

        Searches table metadata chunks with optional domain filtering
        and deduplication by base_id.

        Args:
            query_embedding: Query vector
            domains: Optional domain filter (e.g., ["finops_billing"])
            n_results: Number of results (before deduplication)
            deduplicate: Whether to deduplicate by base_id (default: True)

        Returns:
            List of search results, optionally deduplicated
        """
        # Query semantic table search first
        semantic_results = await self.query_semantic_table_search(
            query_embedding=query_embedding,
            domains=domains,
            n_results=5,
        )

        # Build list of table names from semantic results
        table_names = [result.metadata.get("table_name") for result in semantic_results]

        # Build filter conditions
        # doc_types = ["columns", "relationships", "use_cases"]
        doc_types = ["table_columns"]
        filter_conditions = self._build_filter(
            domains=domains,
            doc_types=doc_types,
            tables=[t for t in table_names if t is not None] if table_names else None,
        )

        # Execute search
        results = await self._tables_store.search_by_metadata(
            top_k=n_results,
            filters=filter_conditions if filter_conditions else {},
        )

        def _strip_rag_headers(tbl: str, doc_type: str, content: str) -> str:
            return content.replace(
                f"TABLE: {tbl}\nDOC_TYPE: {doc_type}\n",
                "",
            )

        search_results = {
            r.metadata.get("table_name"): {
                "table_name": r.metadata.get("table_name"),
                "description": _strip_rag_headers(
                    r.metadata.get("table_name") or "",
                    r.metadata.get("doc_type") or "",
                    r.content,
                ),
                "domain": r.metadata.get("rag_resource_domain"),
                "relevance_score": r.score,
            }
            for r in semantic_results
        }

        for r in results:
            table_name = r.metadata.get("table_name")
            doc_type = r.metadata.get("doc_type")
            if table_name and doc_type:
                search_results[table_name][doc_type] = _strip_rag_headers(
                    table_name, doc_type, r.content
                )

        logger.debug(
            "tables_query_complete",
            domains=domains,
            n_results=n_results,
            results_count=len(semantic_results),
        )

        return [RAGTableContext(**r) for r in search_results.values()]

    async def query_semantic_table_search(
        self,
        query_embedding: list[float],
        *,
        domains: list[str] | None = None,
        n_results: int = 5,
    ) -> list[VectorSearchResult]:
        """
        Query semantic table search.

        Searches table metadata chunks with optional domain filtering.

        Args:
            query_embedding: Query vector
            domains: Optional domain filter
            n_results: Number of results

        Returns:
            List of search results
        """
        # Build filter conditions
        doc_types = ["table_summary"]
        filter_conditions = self._build_filter(domains=domains, doc_types=doc_types)

        # Execute search
        results = await self._tables_store.search(
            query_embedding=query_embedding,
            top_k=n_results,
            filters=filter_conditions,
        )

        return results

    async def query_nuance(
        self,
        query_embedding: list[float],
        *,
        domains: list[str] | None = None,
        n_results: int = 25,
    ) -> list[RAGNuanceContext]:
        """
        Query Nuance collection.

        Searches platform concepts, rules, and best practices.

        Args:
            query_embedding: Query vector
            domains: Optional domain filter
            n_results: Number of results

        Returns:
            List of search results
        """
        filter_conditions = self._build_filter(domains=domains)

        results = await self._nuance_store.search(
            query_embedding=query_embedding,
            top_k=n_results,
            filters=filter_conditions,
        )

        logger.debug(
            "nuance_query_complete",
            domains=domains,
            n_results=n_results,
            results_count=len(results),
        )

        def _strip_rag_headers(doc_type: str, topic: str, content: str) -> str:
            return content.replace(
                f"DOC_TYPE: {doc_type}\nTOPIC: {topic}\n",
                "",
            )

        nuances = []

        for r in results:
            doc_type = r.metadata.get("doc_type") or ""
            topic_id = r.metadata.get("topic_id") or ""
            nuances.append(
                RAGNuanceContext(
                    type=r.metadata.get("doc_type"),
                    topic=r.metadata.get("topic_id"),
                    content=_strip_rag_headers(
                        doc_type,
                        topic_id,
                        r.content,
                    ),
                    relevance_score=r.score,
                    domain=r.metadata.get("rag_resource_domain"),
                )
            )

        return nuances

    async def query_facets(
        self,
        query_embedding: list[float],
        *,
        domains: list[str] | None = None,
        n_results: int = 50,
    ) -> list[RAGFacetContext]:
        """
        Query Facets collection.

        Searches exploded categorical values for exact matching.

        Args:
            query_embedding: Query vector
            domains: Optional domain filter
            n_results: Number of results

        Returns:
            List of search results
        """
        filter_conditions = self._build_filter(domains=domains)

        results = await self._facets_store.search(
            query_embedding=query_embedding,
            top_k=n_results,
            filters=filter_conditions,
        )

        logger.debug(
            "facets_query_complete",
            domains=domains,
            n_results=n_results,
            results_count=len(results),
        )

        facets = {}
        for r in results:
            field_value = r.metadata.get("field_value")
            code_key = r.metadata.get("code_key")
            if field_value != "null" and code_key:
                if code_key not in facets:
                    facets[code_key] = {
                        "code": code_key,
                        "values": [field_value],
                        "relevance_score": r.score,
                        "domain": r.metadata.get("rag_resource_domain"),
                    }
                else:
                    values = facets[code_key].get("values")
                    if isinstance(values, list):
                        values.append(field_value)

        return [RAGFacetContext(**f) for f in facets.values()]

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
        filter_conditions = self._build_filter(domains=domains)

        results = await self._codebook_store.search(
            query_embedding=query_embedding,
            top_k=n_results,
            filters=filter_conditions,
        )

        logger.debug(
            "codebook_query_complete",
            domains=domains,
            n_results=n_results,
            results_count=len(results),
        )

        def _strip_rag_headers(code_key: str, content: str) -> str:
            return content.replace(
                f"DOC_TYPE: codebook\nCODE_KEY: {code_key}\n",
                "",
            )

        codebooks = []
        for r in results:
            code_key = r.metadata.get("code_key") or ""
            codebooks.append(
                RAGCodebookContext(
                    code=r.metadata.get("code_key"),
                    description=_strip_rag_headers(code_key, r.content),
                    relevance_score=r.score,
                    domain=r.metadata.get("rag_resource_domain"),
                    sku_family=r.metadata.get("sku_family", "all"),
                    warehouse_type=r.metadata.get("warehouse_type", "both"),
                    time_validity=r.metadata.get("time_validity", "none"),
                    involves_tags=r.metadata.get("involves_tags", False),
                )
            )

        return codebooks

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
            n_results_per_collection: Results per collection
            domains: Optional domain filter (applied to all collections)

        Returns:
            Dict mapping collection name to results

        Raises:
            ValueError: If no embedding provider configured
            ValueError: If unknown collection name provided
        """
        # Build coroutines for parallel execution.
        # NOTE: Must store coroutines (not Tasks) so TaskGroup can schedule them.
        # Calling asyncio.create_task() here would pre-schedule tasks and then
        # passing them to tg.create_task() would raise TypeError (expects coroutine).
        coroutines: list[tuple[str, Any]] = []

        for collection in collections:
            collection_lower = collection.lower()

            if collection_lower == "tables":
                coroutines.append(
                    (
                        collection,
                        self.query_tables(
                            query_embedding=query_embedding,
                            domains=domains,
                            n_results=n_results_per_collection,
                        ),
                    )
                )

            elif collection_lower == "nuance":
                coroutines.append(
                    (
                        collection,
                        self.query_nuance(
                            query_embedding=query_embedding,
                            domains=domains,
                            n_results=n_results_per_collection,
                        ),
                    )
                )

            elif collection_lower == "facets":
                coroutines.append(
                    (
                        collection,
                        self.query_facets(
                            query_embedding=query_embedding,
                            domains=domains,
                            n_results=n_results_per_collection,
                        ),
                    )
                )

            elif collection_lower == "codebook":
                coroutines.append(
                    (
                        collection,
                        self.query_codebook(
                            query_embedding=query_embedding,
                            domains=domains,
                            n_results=n_results_per_collection,
                        ),
                    )
                )

            else:
                raise ValueError(
                    f"Unknown collection: {collection}. "
                    f"Valid collections: Tables, Nuance, Facets, Learnings"
                )

        # Execute all coroutines in parallel using TaskGroup for structured concurrency.
        async with asyncio.TaskGroup() as tg:
            tg_tasks = [tg.create_task(coro) for _, coro in coroutines]
        task_results = [t.result() for t in tg_tasks]

        # Build results dict
        results = {
            collection.lower(): result
            for (collection, _), result in zip(coroutines, task_results)
        }

        logger.debug(
            "multi_collection_query_complete",
            # query_embedding=query_embedding,
            collections=list(results.keys()),
            total_results=sum(len(r) for r in results.values()),
        )

        return RAGContext(
            tables=results.get("tables", []),
            nuance=results.get("nuance", []),
            codebook=results.get("codebook", []),
            facets=results.get("facets", []),
            learnings=results.get("learnings", []),
        )

    async def upsert_tables(self, records: list[VectorRecord]) -> None:
        """
        Upsert records to Tables collection.

        Args:
            records: Vector records with table chunk data
        """
        await self._tables_store.upsert(records)
        logger.debug("tables_upsert_complete", records_count=len(records))

    async def upsert_nuance(self, records: list[VectorRecord]) -> None:
        """
        Upsert records to Nuance collection.

        Args:
            records: Vector records with nuance data
        """
        await self._nuance_store.upsert(records)
        logger.debug("nuance_upsert_complete", records_count=len(records))

    async def upsert_facets(self, records: list[VectorRecord]) -> None:
        """
        Upsert records to Facets collection.

        Args:
            records: Vector records with facet data
        """
        await self._facets_store.upsert(records)
        logger.debug("facets_upsert_complete", records_count=len(records))

    async def upsert_codebook(self, records: list[VectorRecord]) -> None:
        """
        Upsert records to Codebook collection.

        Args:
            records: Vector records with codebook data
        """
        await self._codebook_store.upsert(records)
        logger.debug("codebook_upsert_complete", records_count=len(records))

    async def close(self) -> None:
        """Close all vector stores and release resources."""
        await self._tables_store.close()
        await self._nuance_store.close()
        await self._facets_store.close()
        await self._codebook_store.close()
        logger.debug("multi_collection_store_closed", db_path=self.db_path)

    def _build_filter(
        self,
        *,
        domains: list[str] | None = None,
        doc_types: list[str] | None = None,
        tables: list[str] | None = None,
    ) -> dict[str, str | list[str]] | None:
        """
        Build filter conditions for RAG resource-domain filtering.

        Args:
            domains: RAG resource domains to filter by
            doc_types: RAG resource doc types to filter by
            tables: RAG resource tables to filter by
        Returns:
            Filter dict for SQLiteVectorStore.search(), or None if no filter
        """
        filter_conditions: dict[str, str | list[str]] = {}

        if domains:
            if len(domains) == 1:
                filter_conditions["rag_resource_domain"] = domains[0]
            else:
                filter_conditions["rag_resource_domain"] = domains

        if doc_types:
            if len(doc_types) == 1:
                filter_conditions["doc_type"] = doc_types[0]
            else:
                filter_conditions["doc_type"] = doc_types

        if tables:
            if len(tables) == 1:
                filter_conditions["table_name"] = tables[0]
            else:
                filter_conditions["table_name"] = tables

        return filter_conditions if filter_conditions else None

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
