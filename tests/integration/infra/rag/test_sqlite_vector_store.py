# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for SQLite vector store."""

import tempfile
from pathlib import Path

import pytest
from starboard_core.foundations.models import VectorRecord
from starboard.infra.rag.adapters.storage.sqlite_vector_store import (
    SQLiteVectorStore,
)


# Check if sqlite-vec is available
def sqlite_vec_available():
    """Check if sqlite-vec extension is available."""
    import sqlite3
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            conn = sqlite3.connect(f.name)
            # Check if enable_load_extension is available
            if not hasattr(conn, "enable_load_extension"):
                return False
            conn.enable_load_extension(True)
            conn.load_extension("vec0")
            conn.close()
            return True
    except (AttributeError, Exception):
        return False


requires_sqlite_vec = pytest.mark.skipif(
    not sqlite_vec_available(),
    reason="sqlite-vec extension not installed. Install from https://github.com/asg017/sqlite-vec",
)


@pytest.fixture
async def vector_store():
    """Create a temporary SQLite vector store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_vectors.db"
        store = SQLiteVectorStore(
            str(db_path), dimension=3
        )  # Small dimension for testing
        await store.initialize()
        yield store
        await store.clear()


@requires_sqlite_vec
@pytest.mark.asyncio
class TestSQLiteVectorStore:
    """Tests for SQLite vector store."""

    async def test_initialize_creates_tables(self, vector_store):
        """Test that initialization creates required tables."""
        # Store should be initialized by fixture
        assert vector_store._initialized

        # Can query count without error
        count = await vector_store.count()
        assert count == 0

    async def test_upsert_single_vector(self, vector_store):
        """Test inserting a single vector."""
        vector = VectorRecord(
            id="vec_1",
            embedding=[0.1, 0.2, 0.3],
            metadata={"source": "test"},
            content="Test content",
        )

        await vector_store.upsert([vector])

        count = await vector_store.count()
        assert count == 1

    async def test_upsert_multiple_vectors(self, vector_store):
        """Test batch inserting multiple vectors."""
        vectors = [
            VectorRecord(
                id=f"vec_{i}",
                embedding=[float(i), float(i + 1), float(i + 2)],
                metadata={"source": "test", "index": i},
                content=f"Content {i}",
            )
            for i in range(10)
        ]

        await vector_store.upsert(vectors)

        count = await vector_store.count()
        assert count == 10

    async def test_upsert_replaces_existing_vector(self, vector_store):
        """Test that upsert replaces existing vectors with same ID."""
        # Insert original
        original = VectorRecord(
            id="vec_1",
            embedding=[0.1, 0.2, 0.3],
            metadata={"version": "1"},
            content="Original content",
        )
        await vector_store.upsert([original])

        # Update with same ID
        updated = VectorRecord(
            id="vec_1",
            embedding=[0.4, 0.5, 0.6],
            metadata={"version": "2"},
            content="Updated content",
        )
        await vector_store.upsert([updated])

        # Should still have only 1 vector
        count = await vector_store.count()
        assert count == 1

        # Search should return updated version
        results = await vector_store.search([0.4, 0.5, 0.6], top_k=1)
        assert len(results) == 1
        assert results[0].id == "vec_1"
        assert results[0].content == "Updated content"
        assert results[0].metadata["version"] == "2"

    async def test_search_returns_similar_vectors(self, vector_store):
        """Test that search returns vectors by similarity."""
        vectors = [
            VectorRecord(
                id="vec_1",
                embedding=[1.0, 0.0, 0.0],
                metadata={},
                content="Content 1",
            ),
            VectorRecord(
                id="vec_2",
                embedding=[0.9, 0.1, 0.0],
                metadata={},
                content="Content 2",
            ),
            VectorRecord(
                id="vec_3",
                embedding=[0.0, 1.0, 0.0],
                metadata={},
                content="Content 3",
            ),
        ]
        await vector_store.upsert(vectors)

        # Search for vector similar to vec_1
        results = await vector_store.search([1.0, 0.0, 0.0], top_k=2)

        assert len(results) == 2
        # Should return vec_1 first (exact match)
        assert results[0].id == "vec_1"
        assert results[0].score > 0.9  # High similarity
        # Then vec_2 (somewhat similar)
        assert results[1].id == "vec_2"

    async def test_search_with_filters(self, vector_store):
        """Test search with metadata filters."""
        vectors = [
            VectorRecord(
                id="vec_1",
                embedding=[1.0, 0.0, 0.0],
                metadata={"source": "docs", "type": "guide"},
                content="Documentation guide",
            ),
            VectorRecord(
                id="vec_2",
                embedding=[1.0, 0.0, 0.0],  # Same embedding
                metadata={"source": "blog", "type": "post"},
                content="Blog post",
            ),
        ]
        await vector_store.upsert(vectors)

        # Search with source filter
        results = await vector_store.search(
            [1.0, 0.0, 0.0], top_k=10, filters={"source": "docs"}
        )

        assert len(results) == 1
        assert results[0].id == "vec_1"
        assert results[0].metadata["source"] == "docs"

    async def test_search_respects_top_k(self, vector_store):
        """Test that search limits results to top_k."""
        vectors = [
            VectorRecord(
                id=f"vec_{i}",
                embedding=[float(i), 0.0, 0.0],
                metadata={},
                content=f"Content {i}",
            )
            for i in range(20)
        ]
        await vector_store.upsert(vectors)

        results = await vector_store.search([0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 5

    async def test_delete_vectors(self, vector_store):
        """Test deleting vectors by ID."""
        vectors = [
            VectorRecord(
                id=f"vec_{i}",
                embedding=[float(i), 0.0, 0.0],
                metadata={},
                content=f"Content {i}",
            )
            for i in range(5)
        ]
        await vector_store.upsert(vectors)

        # Delete some vectors
        await vector_store.delete(["vec_1", "vec_3"])

        count = await vector_store.count()
        assert count == 3

        # Deleted vectors should not appear in search
        results = await vector_store.search([1.0, 0.0, 0.0], top_k=10)
        result_ids = {r.id for r in results}
        assert "vec_1" not in result_ids
        assert "vec_3" not in result_ids
        assert "vec_0" in result_ids
        assert "vec_2" in result_ids
        assert "vec_4" in result_ids

    async def test_delete_nonexistent_vectors(self, vector_store):
        """Test that deleting nonexistent vectors doesn't error."""
        # Should not raise error
        await vector_store.delete(["nonexistent_1", "nonexistent_2"])

        count = await vector_store.count()
        assert count == 0

    async def test_clear_removes_all_vectors(self, vector_store):
        """Test that clear removes all vectors."""
        vectors = [
            VectorRecord(
                id=f"vec_{i}",
                embedding=[float(i), 0.0, 0.0],
                metadata={},
                content=f"Content {i}",
            )
            for i in range(10)
        ]
        await vector_store.upsert(vectors)

        await vector_store.clear()

        count = await vector_store.count()
        assert count == 0

    async def test_empty_search_returns_empty(self):
        """Test searching empty store returns empty results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "empty.db"
            store = SQLiteVectorStore(str(db_path), dimension=3)
            await store.initialize()

            results = await store.search([1.0, 0.0, 0.0], top_k=10)

            assert len(results) == 0

    async def test_upsert_empty_list_raises_error(self, vector_store):
        """Test that upserting empty list raises ValueError."""
        with pytest.raises(ValueError, match="Cannot upsert empty vector list"):
            await vector_store.upsert([])

    async def test_upsert_wrong_dimension_raises_error(self, vector_store):
        """Test that wrong embedding dimension raises ValueError."""
        vector = VectorRecord(
            id="vec_bad",
            embedding=[0.1, 0.2],  # Wrong dimension (expected 3)
            metadata={},
            content="Bad vector",
        )

        with pytest.raises(ValueError, match="wrong dimension"):
            await vector_store.upsert([vector])

    async def test_search_wrong_dimension_raises_error(self, vector_store):
        """Test that searching with wrong dimension raises ValueError."""
        with pytest.raises(ValueError, match="dimension mismatch"):
            await vector_store.search([0.1, 0.2], top_k=5)  # Wrong dimension

    async def test_similarity_scores_in_valid_range(self, vector_store):
        """Test that similarity scores are between 0 and 1."""
        vectors = [
            VectorRecord(
                id=f"vec_{i}",
                embedding=[float(i), float(i + 1), float(i + 2)],
                metadata={},
                content=f"Content {i}",
            )
            for i in range(10)
        ]
        await vector_store.upsert(vectors)

        results = await vector_store.search([5.0, 6.0, 7.0], top_k=10)

        for result in results:
            assert 0.0 <= result.score <= 1.0

    async def test_multiple_searches(self, vector_store):
        """Test performing multiple searches."""
        vectors = [
            VectorRecord(
                id=f"vec_{i}",
                embedding=[float(i), 0.0, 0.0],
                metadata={},
                content=f"Content {i}",
            )
            for i in range(10)
        ]
        await vector_store.upsert(vectors)

        # Multiple searches should all work
        for i in range(5):
            results = await vector_store.search([float(i), 0.0, 0.0], top_k=3)
            assert len(results) > 0
            # Closest result should be the one we searched for
            assert results[0].id == f"vec_{i}"
