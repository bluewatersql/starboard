# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for SQLiteMultiCollectionStore.

Tests multi-collection vector store with domain filtering and deduplication.
"""

from unittest.mock import AsyncMock

import pytest
from starboard_core.foundations.models import VectorRecord, VectorSearchResult
from starboard_server.infra.rag.adapters.storage.sqlite_multi_collection_store import (
    SQLiteMultiCollectionStore,
)


class TestInit:
    """Test initialization."""

    def test_init(self):
        """Should initialize with db_path and embedding_dim."""
        store = SQLiteMultiCollectionStore(db_path="test.db", embedding_dim=1536)

        assert store.db_path == "test.db"
        assert store.embedding_dim == 1536
        assert store._tables_store is not None
        assert store._nuance_store is not None
        assert store._codebook_store is not None
        assert store._facets_store is not None
        assert store._learnings_store is not None

    def test_init_default_embedding_dim(self):
        """Should use default embedding_dim of 1536."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        assert store.embedding_dim == 1024


@pytest.mark.asyncio
class TestInitialize:
    """Test initialize method."""

    async def test_initialize(self):
        """Should initialize all collections."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        # Mock all store initialize methods
        store._tables_store.initialize = AsyncMock()
        store._nuance_store.initialize = AsyncMock()
        store._codebook_store.initialize = AsyncMock()
        store._facets_store.initialize = AsyncMock()
        store._learnings_store.initialize = AsyncMock()

        await store.initialize()

        store._tables_store.initialize.assert_awaited_once()
        store._nuance_store.initialize.assert_awaited_once()
        store._codebook_store.initialize.assert_awaited_once()
        store._facets_store.initialize.assert_awaited_once()
        store._learnings_store.initialize.assert_awaited_once()


@pytest.mark.asyncio
class TestQueryTables:
    """Test query_tables method."""

    async def test_query_tables_basic(self):
        """Should query tables collection."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        mock_results = [
            VectorSearchResult(
                id="1",
                content="Table 1",
                score=0.9,
                metadata={"base_id": "table1"},
            ),
        ]
        store._tables_store.search = AsyncMock(return_value=mock_results)

        results = await store.query_tables([0.1, 0.2, 0.3])

        assert len(results) == 1
        assert results[0].content == "Table 1"
        store._tables_store.search.assert_awaited_once()

    async def test_query_tables_with_domains(self):
        """Should apply domain filter."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._tables_store.search = AsyncMock(return_value=[])

        await store.query_tables(
            [0.1, 0.2, 0.3], domains=["finops_billing"], n_results=10
        )

        # Check filter was built correctly
        call_args = store._tables_store.search.call_args
        assert call_args.kwargs["filters"] == {"domain": "finops_billing"}

    async def test_query_tables_with_multiple_domains(self):
        """Should handle multiple domains."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._tables_store.search = AsyncMock(return_value=[])

        await store.query_tables(
            [0.1, 0.2, 0.3], domains=["finops_billing", "finops_usage"]
        )

        call_args = store._tables_store.search.call_args
        assert call_args.kwargs["filters"] == {
            "domain": ["finops_billing", "finops_usage"]
        }

    async def test_query_tables_no_deduplication(self):
        """Should skip deduplication if requested."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        mock_results = [
            VectorSearchResult(
                id="1",
                content="Table 1",
                score=0.9,
                metadata={"base_id": "table1"},
            ),
            VectorSearchResult(
                id="2",
                content="Table 1 duplicate",
                score=0.8,
                metadata={"base_id": "table1"},
            ),
        ]
        store._tables_store.search = AsyncMock(return_value=mock_results)

        results = await store.query_tables([0.1, 0.2, 0.3], deduplicate=False)

        # Should return both results without deduplication
        assert len(results) == 2

    async def test_query_tables_with_deduplication(self):
        """Should deduplicate by base_id."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        mock_results = [
            VectorSearchResult(
                id="1",
                content="Table 1",
                score=0.9,
                metadata={"base_id": "table1"},
            ),
            VectorSearchResult(
                id="2",
                content="Table 1 duplicate",
                score=0.8,
                metadata={"base_id": "table1"},
            ),
        ]
        store._tables_store.search = AsyncMock(return_value=mock_results)

        results = await store.query_tables([0.1, 0.2, 0.3], deduplicate=True)

        # Should return only highest scoring result
        assert len(results) == 1
        assert results[0].score == 0.9


@pytest.mark.asyncio
class TestQueryNuance:
    """Test query_nuance method."""

    async def test_query_nuance_basic(self):
        """Should query nuance collection."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        mock_results = [
            VectorSearchResult(id="1", content="Nuance 1", score=0.9, metadata={}),
        ]
        store._nuance_store.search = AsyncMock(return_value=mock_results)

        results = await store.query_nuance([0.1, 0.2, 0.3])

        assert len(results) == 1
        store._nuance_store.search.assert_awaited_once()

    async def test_query_nuance_with_domains(self):
        """Should apply domain filter."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._nuance_store.search = AsyncMock(return_value=[])

        await store.query_nuance([0.1, 0.2, 0.3], domains=["finops_billing"])

        call_args = store._nuance_store.search.call_args
        assert call_args.kwargs["filters"] == {"domain": "finops_billing"}


@pytest.mark.asyncio
class TestQueryFacets:
    """Test query_facets method."""

    async def test_query_facets_basic(self):
        """Should query facets collection."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        mock_results = [
            VectorSearchResult(id="1", content="Facet 1", score=0.9, metadata={}),
        ]
        store._facets_store.search = AsyncMock(return_value=mock_results)

        results = await store.query_facets([0.1, 0.2, 0.3])

        assert len(results) == 1
        store._facets_store.search.assert_awaited_once()

    async def test_query_facets_with_domains(self):
        """Should apply domain filter."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._facets_store.search = AsyncMock(return_value=[])

        await store.query_facets([0.1, 0.2, 0.3], domains=["compute_warehouses"])

        call_args = store._facets_store.search.call_args
        assert call_args.kwargs["filters"] == {"domain": "compute_warehouses"}


@pytest.mark.asyncio
class TestQueryCodebook:
    """Test query_codebook method."""

    async def test_query_codebook_basic(self):
        """Should query codebook collection."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        mock_results = [
            VectorSearchResult(id="1", content="Codebook 1", score=0.9, metadata={}),
        ]
        store._codebook_store.search = AsyncMock(return_value=mock_results)

        results = await store.query_codebook([0.1, 0.2, 0.3])

        assert len(results) == 1
        store._codebook_store.search.assert_awaited_once()

    async def test_query_codebook_with_domains(self):
        """Should apply domain filter."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._codebook_store.search = AsyncMock(return_value=[])

        await store.query_codebook([0.1, 0.2, 0.3], domains=["finops_billing"])

        call_args = store._codebook_store.search.call_args
        assert call_args.kwargs["filters"] == {"domain": "finops_billing"}


@pytest.mark.asyncio
class TestQueryLearnings:
    """Test query_learnings method."""

    async def test_query_learnings_basic(self):
        """Should query learnings collection with agent_domain filter."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        mock_results = [
            VectorSearchResult(id="1", content="Learning 1", score=0.9, metadata={}),
        ]
        store._learnings_store.search = AsyncMock(return_value=mock_results)

        results = await store.query_learnings([0.1, 0.2, 0.3], agent_domain="analytics")

        assert len(results) == 1
        call_args = store._learnings_store.search.call_args
        assert call_args.kwargs["filters"] == {"agent_domain": "analytics"}


@pytest.mark.asyncio
class TestUpsertMethods:
    """Test upsert methods."""

    async def test_upsert_tables(self):
        """Should upsert to tables collection."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._tables_store.upsert = AsyncMock()

        records = [
            VectorRecord(id="1", content="Table 1", embedding=[0.1], metadata={}),
        ]

        await store.upsert_tables(records)
        store._tables_store.upsert.assert_awaited_once_with(records)

    async def test_upsert_nuance(self):
        """Should upsert to nuance collection."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._nuance_store.upsert = AsyncMock()

        records = [
            VectorRecord(id="1", content="Nuance 1", embedding=[0.1], metadata={}),
        ]

        await store.upsert_nuance(records)
        store._nuance_store.upsert.assert_awaited_once_with(records)

    async def test_upsert_facets(self):
        """Should upsert to facets collection."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._facets_store.upsert = AsyncMock()

        records = [
            VectorRecord(id="1", content="Facet 1", embedding=[0.1], metadata={}),
        ]

        await store.upsert_facets(records)
        store._facets_store.upsert.assert_awaited_once_with(records)

    async def test_upsert_codebook(self):
        """Should upsert to codebook collection."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._codebook_store.upsert = AsyncMock()

        records = [
            VectorRecord(id="1", content="Codebook 1", embedding=[0.1], metadata={}),
        ]

        await store.upsert_codebook(records)
        store._codebook_store.upsert.assert_awaited_once_with(records)

    async def test_upsert_learnings(self):
        """Should upsert to learnings collection."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        store._learnings_store.upsert = AsyncMock()

        records = [
            VectorRecord(id="1", content="Learning 1", embedding=[0.1], metadata={}),
        ]

        await store.upsert_learnings(records)
        store._learnings_store.upsert.assert_awaited_once_with(records)


@pytest.mark.asyncio
class TestClose:
    """Test close method."""

    async def test_close(self):
        """Should close all collections."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        store._tables_store.close = AsyncMock()
        store._nuance_store.close = AsyncMock()
        store._codebook_store.close = AsyncMock()
        store._facets_store.close = AsyncMock()
        store._learnings_store.close = AsyncMock()

        await store.close()

        store._tables_store.close.assert_awaited_once()
        store._nuance_store.close.assert_awaited_once()
        store._codebook_store.close.assert_awaited_once()
        store._facets_store.close.assert_awaited_once()
        store._learnings_store.close.assert_awaited_once()


class TestBuildDomainFilter:
    """Test _build_domain_filter method."""

    def test_no_domains(self):
        """Should return None if no domains."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        result = store._build_domain_filter(None)
        assert result is None

    def test_single_domain(self):
        """Should return dict with single domain."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        result = store._build_domain_filter(["finops_billing"])
        assert result == {"domain": "finops_billing"}

    def test_multiple_domains(self):
        """Should return dict with domain list."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        result = store._build_domain_filter(["finops_billing", "finops_usage"])
        assert result == {"domain": ["finops_billing", "finops_usage"]}


class TestDeduplicateByBaseId:
    """Test _deduplicate_by_base_id method."""

    def test_empty_results(self):
        """Should handle empty results."""
        store = SQLiteMultiCollectionStore(db_path="test.db")
        result = store._deduplicate_by_base_id([])
        assert result == []

    def test_no_duplicates(self):
        """Should return all results if no duplicates."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        results = [
            VectorSearchResult(
                id="1",
                content="Table 1",
                score=0.9,
                metadata={"base_id": "table1"},
            ),
            VectorSearchResult(
                id="2",
                content="Table 2",
                score=0.8,
                metadata={"base_id": "table2"},
            ),
        ]

        deduplicated = store._deduplicate_by_base_id(results)
        assert len(deduplicated) == 2

    def test_with_duplicates(self):
        """Should keep highest scoring result per base_id."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        results = [
            VectorSearchResult(
                id="1",
                content="Table 1 - finops_billing",
                score=0.9,
                metadata={"base_id": "table1"},
            ),
            VectorSearchResult(
                id="2",
                content="Table 1 - finops_usage",
                score=0.85,
                metadata={"base_id": "table1"},
            ),
            VectorSearchResult(
                id="3",
                content="Table 2",
                score=0.8,
                metadata={"base_id": "table2"},
            ),
        ]

        deduplicated = store._deduplicate_by_base_id(results)

        assert len(deduplicated) == 2
        # Should keep highest scoring result for table1
        assert deduplicated[0].score == 0.9
        assert deduplicated[1].score == 0.8

    def test_no_base_id(self):
        """Should keep results without base_id."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        results = [
            VectorSearchResult(id="1", content="Result 1", score=0.9, metadata={}),
            VectorSearchResult(id="2", content="Result 2", score=0.8, metadata={}),
        ]

        deduplicated = store._deduplicate_by_base_id(results)
        assert len(deduplicated) == 2

    def test_sorted_by_score(self):
        """Should sort deduplicated results by score descending."""
        store = SQLiteMultiCollectionStore(db_path="test.db")

        results = [
            VectorSearchResult(
                id="1",
                content="Table 1",
                score=0.7,
                metadata={"base_id": "table1"},
            ),
            VectorSearchResult(
                id="2",
                content="Table 2",
                score=0.9,
                metadata={"base_id": "table2"},
            ),
            VectorSearchResult(
                id="3",
                content="Table 3",
                score=0.8,
                metadata={"base_id": "table3"},
            ),
        ]

        deduplicated = store._deduplicate_by_base_id(results)

        assert deduplicated[0].score == 0.9
        assert deduplicated[1].score == 0.8
        assert deduplicated[2].score == 0.7
