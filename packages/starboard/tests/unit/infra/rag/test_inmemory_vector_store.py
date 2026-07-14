# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for in-memory vector store implementation."""

import numpy as np
import pytest
from starboard_core.rag.models import (
    RAGCodebookContext,
    RAGFacetContext,
    RAGNuanceContext,
    RAGTableContext,
)
from starboard.infra.rag.adapters.storage.inmemory_bootstrap import (
    InMemoryVectorStoreBootstrap,
)
from starboard.infra.rag.adapters.storage.inmemory_vector_store import (
    InMemoryMultiCollectionStore,
)


class MockEmbeddingProvider:
    """Mock embedding provider for testing."""

    def __init__(self, embedding_dim: int = 1024):
        self.embedding_dim = embedding_dim
        self._call_count = 0

    async def embed(self, text: str) -> list[float]:
        """Generate deterministic mock embedding based on text hash."""
        self._call_count += 1
        # Use hash to generate deterministic but varied embeddings
        seed = hash(text) % 10000
        np.random.seed(seed)
        embedding = np.random.randn(self.embedding_dim).astype(np.float32)
        # Normalize to unit vector
        embedding = embedding / np.linalg.norm(embedding)
        return embedding.tolist()


@pytest.fixture
def embedding_provider():
    """Create mock embedding provider."""
    return MockEmbeddingProvider(embedding_dim=1024)


@pytest.fixture
async def empty_store(embedding_provider):
    """Create empty initialized vector store."""
    store = InMemoryMultiCollectionStore(
        embedding_provider=embedding_provider,
        embedding_dim=1024,
        max_vectors=1000,
    )
    await store.initialize()
    return store


@pytest.fixture
async def populated_store(embedding_provider):
    """Create vector store populated with test data."""
    store = InMemoryMultiCollectionStore(
        embedding_provider=embedding_provider,
        embedding_dim=1024,
        max_vectors=1000,
    )
    await store.initialize()

    # Add test tables
    tables = [
        RAGTableContext(
            table_name="system.billing.usage",
            domain="finops_billing",
            description="Billing usage data with DBU consumption",
            table_columns="usage_date, sku_name, usage_quantity",
            relationships="",
            use_cases="Cost analysis",
            relevance_score=1.0,
        ),
        RAGTableContext(
            table_name="system.compute.warehouse_events",
            domain="compute_warehouses",
            description="SQL warehouse lifecycle events",
            table_columns="warehouse_id, timestamp",
            relationships="",
            use_cases="Warehouse monitoring",
            relevance_score=1.0,
        ),
        RAGTableContext(
            table_name="system.billing.list_prices",
            domain="finops_billing",
            description="List prices for SKUs",
            table_columns="sku_name, list_price",
            relationships="",
            use_cases="Cost calculation",
            relevance_score=1.0,
        ),
    ]
    await store.add_tables(tables)

    # Add test nuance
    nuance = [
        RAGNuanceContext(
            topic="performance",
            type="performance",
            content="Always filter by date range for performance",
            domain="finops_billing",
            relevance_score=1.0,
        ),
        RAGNuanceContext(
            topic="join_pattern",
            type="join_pattern",
            content="Join usage with list_prices on sku_name",
            domain="finops_billing",
            relevance_score=1.0,
        ),
        RAGNuanceContext(
            topic="analysis",
            type="analysis",
            content="Calculate warehouse uptime from events",
            domain="compute_warehouses",
            relevance_score=1.0,
        ),
    ]
    await store.add_nuance(nuance)

    return store


class TestInMemoryMultiCollectionStore:
    """Unit tests for InMemoryMultiCollectionStore."""

    @pytest.mark.asyncio
    async def test_initialize(self, embedding_provider):
        """Test store initialization."""
        store = InMemoryMultiCollectionStore(
            embedding_provider=embedding_provider,
            embedding_dim=1024,
            max_vectors=1000,
        )

        assert not store._initialized
        await store.initialize()
        assert store._initialized
        assert store._tables == []
        assert store._nuance == []
        assert store._codebook == []
        assert store._facets == []

    @pytest.mark.asyncio
    async def test_add_tables(self, empty_store):
        """Test adding tables to collection."""
        tables = [
            RAGTableContext(
                table_name="test.schema.table1",
                domain="test_domain",
                description="Test table",
                table_columns="col1",
                relationships="",
                use_cases="Testing",
                relevance_score=1.0,
            ),
        ]

        await empty_store.add_tables(tables)

        assert len(empty_store._tables) == 1
        assert empty_store._tables[0].id == "test.schema.table1"
        assert empty_store._tables[0].collection == "Tables"
        assert empty_store._embeddings["Tables"] is not None
        assert empty_store._embeddings["Tables"].shape == (1, 1024)

    @pytest.mark.asyncio
    async def test_add_nuance(self, empty_store):
        """Test adding nuance to collection."""
        nuance = [
            RAGNuanceContext(
                topic="test",
                type="test_category",
                content="Test best practice",
                domain="test_domain",
                relevance_score=1.0,
            ),
        ]

        await empty_store.add_nuance(nuance)

        assert len(empty_store._nuance) == 1
        assert empty_store._nuance[0].collection == "Nuance"
        assert empty_store._embeddings["Nuance"] is not None

    @pytest.mark.asyncio
    async def test_add_codebook(self, empty_store):
        """Test adding codebook entries."""
        codebook = [
            RAGCodebookContext(
                code="test.table.test_field",
                description="Test field description",
                sku_family="N/A",
                warehouse_type="ALL",
                time_validity="Always",
                involves_tags=False,
                domain="test_domain",
                relevance_score=1.0,
            ),
        ]

        await empty_store.add_codebook(codebook)

        assert len(empty_store._codebook) == 1
        assert empty_store._codebook[0].collection == "Codebook"
        assert empty_store._embeddings["Codebook"] is not None

    @pytest.mark.asyncio
    async def test_add_facets(self, empty_store):
        """Test adding facets."""
        facets = [
            RAGFacetContext(
                code="test.table.test_field",
                values=["value1", "value2", "value3"],
                domain="test_domain",
                relevance_score=1.0,
            ),
        ]

        await empty_store.add_facets(facets)

        assert len(empty_store._facets) == 1
        assert empty_store._facets[0].collection == "Facets"
        assert empty_store._embeddings["Facets"] is not None

    @pytest.mark.asyncio
    async def test_search_tables_collection(self, populated_store):
        """Test searching tables collection."""
        # Search for billing-related tables
        results = await populated_store._search_collection(
            collection="Tables",
            query_embedding=np.array(
                await populated_store.embedding_provider.embed("billing costs")
            ),
            n_results=5,
            domains=None,
        )

        assert len(results) > 0
        assert all(isinstance(r, RAGTableContext) for r in results)

    @pytest.mark.asyncio
    async def test_search_with_domain_filter(self, populated_store):
        """Test searching with domain filter."""
        # Create query embedding
        query_embedding = np.array(
            await populated_store.embedding_provider.embed("billing")
        )

        # Search with domain filter
        results = await populated_store._search_collection(
            collection="Tables",
            query_embedding=query_embedding,
            n_results=10,
            domains=["finops_billing"],
        )

        assert len(results) > 0
        # All results should be from billing domain
        assert all(r.domain == "finops_billing" for r in results)

    @pytest.mark.asyncio
    async def test_search_multi_collection(self, populated_store):
        """Test multi-collection search."""
        result = await populated_store.search_multi_collection(
            query="billing costs and usage patterns",
            collections=["Tables", "Nuance"],
            n_results_per_collection=5,
            domains=None,
        )

        assert isinstance(result.tables, list)
        assert isinstance(result.nuance, list)
        assert len(result.tables) > 0
        assert len(result.nuance) > 0

    @pytest.mark.asyncio
    async def test_search_empty_collection(self, empty_store):
        """Test searching empty collection returns empty results."""
        result = await empty_store.search_multi_collection(
            query="test query",
            collections=["Tables"],
            n_results_per_collection=5,
        )

        assert result.tables == []
        assert result.nuance == []

    @pytest.mark.asyncio
    async def test_capacity_limit(self, embedding_provider):
        """Test capacity limit enforcement."""
        store = InMemoryMultiCollectionStore(
            embedding_provider=embedding_provider,
            embedding_dim=1024,
            max_vectors=5,  # Very small limit
        )
        await store.initialize()

        # Add tables up to limit
        tables = [
            RAGTableContext(
                table_name=f"test.table{i}",
                domain="test",
                description=f"Table {i}",
                table_columns="",
                relationships="",
                use_cases="",
                relevance_score=1.0,
            )
            for i in range(5)
        ]

        await store.add_tables(tables)
        assert len(store._tables) == 5

        # Try to add one more (should fail)
        with pytest.raises(ValueError, match="exceed max_vectors limit"):
            await store.add_tables([tables[0]])

    @pytest.mark.asyncio
    async def test_domain_index_updated(self, empty_store):
        """Test domain index is updated when adding records."""
        tables = [
            RAGTableContext(
                table_name="test.table1",
                domain="domain1",
                description="Test",
                table_columns="",
                relationships="",
                use_cases="",
                relevance_score=1.0,
            ),
            RAGTableContext(
                table_name="test.table2",
                domain="domain2",
                description="Test",
                table_columns="",
                relationships="",
                use_cases="",
                relevance_score=1.0,
            ),
        ]

        await empty_store.add_tables(tables)

        assert "domain1" in empty_store._domain_index
        assert "domain2" in empty_store._domain_index
        assert "test.table1" in empty_store._domain_index["domain1"]
        assert "test.table2" in empty_store._domain_index["domain2"]

    def test_cosine_similarity_batch(self, empty_store):
        """Test cosine similarity computation."""
        query_embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        doc_embeddings = np.array(
            [
                [1.0, 0.0, 0.0],  # Perfect match
                [0.0, 1.0, 0.0],  # Orthogonal
                [0.5, 0.5, 0.0],  # Partial match
            ],
            dtype=np.float32,
        )

        similarities = empty_store._cosine_similarity_batch(
            query_embedding, doc_embeddings
        )

        # Perfect match should have similarity close to 1.0
        assert similarities[0] > 0.99
        # Orthogonal should have similarity close to 0.0
        assert abs(similarities[1]) < 0.01
        # Partial match should be between
        assert 0.0 < similarities[2] < 1.0

    @pytest.mark.asyncio
    async def test_get_stats(self, populated_store):
        """Test getting store statistics."""
        stats = populated_store.get_stats()

        assert stats["backend"] == "inmemory"
        assert stats["total_vectors"] > 0
        assert stats["max_vectors"] == 1000
        assert "collections" in stats
        assert stats["collections"]["tables"] == 3
        assert stats["collections"]["nuance"] == 3
        assert stats["initialized"] is True


class TestInMemoryVectorStoreBootstrap:
    """Unit tests for InMemoryVectorStoreBootstrap."""

    @pytest.mark.asyncio
    async def test_bootstrap_tables(self, empty_store):
        """Test bootstrapping with essential tables."""
        counts = await InMemoryVectorStoreBootstrap.bootstrap(
            empty_store,
            include_tables=True,
            include_nuance=False,
        )

        assert counts["tables"] > 0
        assert counts["nuance"] == 0
        assert len(empty_store._tables) > 0

        # Check that essential tables are present
        table_names = [t.id for t in empty_store._tables]
        assert "system.billing.usage" in table_names
        assert "system.billing.list_prices" in table_names

    @pytest.mark.asyncio
    async def test_bootstrap_nuance(self, empty_store):
        """Test bootstrapping with essential nuance."""
        counts = await InMemoryVectorStoreBootstrap.bootstrap(
            empty_store,
            include_tables=False,
            include_nuance=True,
        )

        assert counts["tables"] == 0
        assert counts["nuance"] > 0
        assert len(empty_store._nuance) > 0

    @pytest.mark.asyncio
    async def test_bootstrap_full(self, empty_store):
        """Test full bootstrap with tables and nuance."""
        counts = await InMemoryVectorStoreBootstrap.bootstrap(
            empty_store,
            include_tables=True,
            include_nuance=True,
        )

        assert counts["tables"] > 0
        assert counts["nuance"] > 0
        assert len(empty_store._tables) > 0
        assert len(empty_store._nuance) > 0

    @pytest.mark.asyncio
    async def test_bootstrap_uninitialized_store_fails(self, embedding_provider):
        """Test bootstrapping uninitialized store fails."""
        store = InMemoryMultiCollectionStore(
            embedding_provider=embedding_provider,
            embedding_dim=1024,
        )
        # Don't initialize

        with pytest.raises(ValueError, match="must be initialized"):
            await InMemoryVectorStoreBootstrap.bootstrap(store)

    @pytest.mark.asyncio
    async def test_bootstrap_essential_domains(self, empty_store):
        """Test that essential tables cover key domains."""
        await InMemoryVectorStoreBootstrap.bootstrap(empty_store)

        domains = {t.metadata.get("domain") for t in empty_store._tables}

        # Should have billing, warehouse, and jobs domains
        assert "finops_billing" in domains
        assert "compute_warehouses" in domains
        assert "compute_jobs" in domains
