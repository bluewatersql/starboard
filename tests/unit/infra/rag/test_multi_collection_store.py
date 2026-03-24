"""
Unit tests for multi-collection store protocol and models.

Tests collection types, query models, and protocol validation.
"""

import pytest
from starboard_core.foundations.models import VectorRecord, VectorSearchResult
from starboard_server.infra.rag.domain.protocols import (
    CollectionType,
    MultiCollectionStore,
    VectorQuery,
    VectorQueryResult,
)


class TestCollectionType:
    """Test CollectionType enum."""

    def test_collection_types(self):
        """Should have all expected collection types."""
        assert CollectionType.TABLES == "tables"
        assert CollectionType.NUANCE == "nuance"
        assert CollectionType.FACETS == "facets"
        assert CollectionType.LEARNINGS == "learnings"

    def test_collection_type_values(self):
        """Should enumerate all values."""
        types = list(CollectionType)
        assert len(types) == 4
        assert CollectionType.TABLES in types
        assert CollectionType.NUANCE in types
        assert CollectionType.FACETS in types
        assert CollectionType.LEARNINGS in types

    def test_collection_type_string_comparison(self):
        """Should compare with strings."""
        assert CollectionType.TABLES == "tables"
        assert CollectionType.TABLES.value == "tables"


class TestVectorQuery:
    """Test VectorQuery model."""

    def test_vector_query_basic(self):
        """Should create query with required fields."""
        query = VectorQuery(
            query_embedding=[0.1, 0.2, 0.3],
            collection=CollectionType.TABLES,
        )

        assert query.query_embedding == [0.1, 0.2, 0.3]
        assert query.collection == CollectionType.TABLES
        assert query.domains is None
        assert query.n_results == 20
        assert query.agent_domain is None

    def test_vector_query_with_domains(self):
        """Should support domain filtering."""
        query = VectorQuery(
            query_embedding=[0.1, 0.2],
            collection=CollectionType.TABLES,
            domains=["finops_billing", "compute_warehouses"],
        )

        assert query.domains == ["finops_billing", "compute_warehouses"]

    def test_vector_query_with_custom_n_results(self):
        """Should support custom result count."""
        query = VectorQuery(
            query_embedding=[0.1],
            collection=CollectionType.NUANCE,
            n_results=50,
        )

        assert query.n_results == 50

    def test_vector_query_with_agent_domain(self):
        """Should support agent domain for learnings."""
        query = VectorQuery(
            query_embedding=[0.1],
            collection=CollectionType.LEARNINGS,
            agent_domain="analytics",
        )

        assert query.agent_domain == "analytics"

    def test_vector_query_immutable(self):
        """Should be immutable (frozen dataclass)."""
        query = VectorQuery(
            query_embedding=[0.1],
            collection=CollectionType.TABLES,
        )

        with pytest.raises(AttributeError):
            query.collection = CollectionType.NUANCE  # type: ignore


class TestVectorQueryResult:
    """Test VectorQueryResult model."""

    def test_vector_query_result_basic(self):
        """Should create result with required fields."""
        results = [
            VectorSearchResult(
                id="test1",
                score=0.9,
                content="Test content",
                metadata={"domain": "test"},
            )
        ]

        result = VectorQueryResult(
            results=results,
            collection=CollectionType.TABLES,
            domains_queried=["finops_billing"],
            total_results=10,
        )

        assert len(result.results) == 1
        assert result.collection == CollectionType.TABLES
        assert result.domains_queried == ["finops_billing"]
        assert result.total_results == 10
        assert result.deduplicated is False

    def test_vector_query_result_empty(self):
        """Should handle empty results."""
        result = VectorQueryResult(
            results=[],
            collection=CollectionType.NUANCE,
            domains_queried=None,
            total_results=0,
        )

        assert result.results == []
        assert result.domains_queried is None
        assert result.total_results == 0

    def test_vector_query_result_deduplicated(self):
        """Should track deduplication status."""
        result = VectorQueryResult(
            results=[],
            collection=CollectionType.TABLES,
            domains_queried=["test"],
            total_results=20,
            deduplicated=True,
        )

        assert result.deduplicated is True
        assert result.total_results == 20  # Total before deduplication

    def test_vector_query_result_multiple_domains(self):
        """Should support multiple domain filters."""
        result = VectorQueryResult(
            results=[],
            collection=CollectionType.FACETS,
            domains_queried=[
                "finops_billing",
                "compute_warehouses",
                "query_optimization",
            ],
            total_results=50,
        )

        assert len(result.domains_queried) == 3


class TestMultiCollectionStoreProtocol:
    """Test MultiCollectionStore protocol."""

    def test_protocol_can_be_implemented(self):
        """Should be able to implement the protocol."""

        class MockStore:
            """Mock implementation of MultiCollectionStore."""

            async def initialize(self) -> None:
                pass

            async def query_tables(
                self,
                query_embedding: list[float],
                *,
                domains: list[str] | None = None,
                n_results: int = 20,
                deduplicate: bool = True,
            ) -> list[VectorSearchResult]:
                return []

            async def query_nuance(
                self,
                query_embedding: list[float],
                *,
                domains: list[str] | None = None,
                n_results: int = 25,
            ) -> list[VectorSearchResult]:
                return []

            async def query_facets(
                self,
                query_embedding: list[float],
                *,
                domains: list[str] | None = None,
                n_results: int = 50,
            ) -> list[VectorSearchResult]:
                return []

            async def query_learnings(
                self,
                query_embedding: list[float],
                *,
                agent_domain: str,
                n_results: int = 10,
            ) -> list[VectorSearchResult]:
                return []

            async def upsert_tables(self, records: list[VectorRecord]) -> None:
                pass

            async def upsert_nuance(self, records: list[VectorRecord]) -> None:
                pass

            async def upsert_facets(self, records: list[VectorRecord]) -> None:
                pass

            async def upsert_learnings(self, records: list[VectorRecord]) -> None:
                pass

            async def close(self) -> None:
                pass

        # Should be compatible with protocol
        store: MultiCollectionStore = MockStore()
        assert store is not None

    @pytest.mark.asyncio
    async def test_protocol_query_methods(self):
        """Should have all query methods."""

        class MockStore:
            async def initialize(self) -> None:
                pass

            async def query_tables(
                self,
                query_embedding: list[float],
                *,
                domains: list[str] | None = None,
                n_results: int = 20,
                deduplicate: bool = True,
            ) -> list[VectorSearchResult]:
                return [
                    VectorSearchResult(
                        id="test",
                        score=0.9,
                        content="Test",
                        metadata={},
                    )
                ]

            async def query_nuance(
                self,
                query_embedding: list[float],
                *,
                domains: list[str] | None = None,
                n_results: int = 25,
            ) -> list[VectorSearchResult]:
                return []

            async def query_facets(
                self,
                query_embedding: list[float],
                *,
                domains: list[str] | None = None,
                n_results: int = 50,
            ) -> list[VectorSearchResult]:
                return []

            async def query_learnings(
                self,
                query_embedding: list[float],
                *,
                agent_domain: str,
                n_results: int = 10,
            ) -> list[VectorSearchResult]:
                return []

            async def upsert_tables(self, records: list[VectorRecord]) -> None:
                pass

            async def upsert_nuance(self, records: list[VectorRecord]) -> None:
                pass

            async def upsert_facets(self, records: list[VectorRecord]) -> None:
                pass

            async def upsert_learnings(self, records: list[VectorRecord]) -> None:
                pass

            async def close(self) -> None:
                pass

        store: MultiCollectionStore = MockStore()

        # Test query methods
        results = await store.query_tables([0.1, 0.2])
        assert len(results) == 1

        results = await store.query_nuance([0.1, 0.2])
        assert len(results) == 0

        results = await store.query_facets([0.1, 0.2])
        assert len(results) == 0

        results = await store.query_learnings([0.1, 0.2], agent_domain="analytics")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_protocol_upsert_methods(self):
        """Should have all upsert methods."""

        class MockStore:
            def __init__(self):
                self.tables_records = []
                self.nuance_records = []
                self.facets_records = []
                self.learnings_records = []

            async def initialize(self) -> None:
                pass

            async def query_tables(
                self,
                query_embedding: list[float],
                *,
                domains: list[str] | None = None,
                n_results: int = 20,
                deduplicate: bool = True,
            ) -> list[VectorSearchResult]:
                return []

            async def query_nuance(
                self,
                query_embedding: list[float],
                *,
                domains: list[str] | None = None,
                n_results: int = 25,
            ) -> list[VectorSearchResult]:
                return []

            async def query_facets(
                self,
                query_embedding: list[float],
                *,
                domains: list[str] | None = None,
                n_results: int = 50,
            ) -> list[VectorSearchResult]:
                return []

            async def query_learnings(
                self,
                query_embedding: list[float],
                *,
                agent_domain: str,
                n_results: int = 10,
            ) -> list[VectorSearchResult]:
                return []

            async def upsert_tables(self, records: list[VectorRecord]) -> None:
                self.tables_records.extend(records)

            async def upsert_nuance(self, records: list[VectorRecord]) -> None:
                self.nuance_records.extend(records)

            async def upsert_facets(self, records: list[VectorRecord]) -> None:
                self.facets_records.extend(records)

            async def upsert_learnings(self, records: list[VectorRecord]) -> None:
                self.learnings_records.extend(records)

            async def close(self) -> None:
                pass

        store: MultiCollectionStore = MockStore()

        # Test upsert methods
        table_record = VectorRecord(
            id="table1",
            embedding=[0.1, 0.2],
            content="Table content",
            metadata={"type": "table"},
        )
        await store.upsert_tables([table_record])
        assert len(store.tables_records) == 1  # type: ignore

        nuance_record = VectorRecord(
            id="nuance1",
            embedding=[0.1, 0.2],
            content="Nuance content",
            metadata={"type": "nuance"},
        )
        await store.upsert_nuance([nuance_record])
        assert len(store.nuance_records) == 1  # type: ignore
