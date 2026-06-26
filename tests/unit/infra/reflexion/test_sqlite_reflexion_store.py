# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for SQLiteReflexionStore (mocked dependencies)."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starboard_core.foundations.models import ReflexionLearning, VectorSearchResult
from starboard_server.infra.reflexion import SQLiteReflexionStore


class TestSQLiteReflexionStoreInit:
    """Tests for store initialization."""

    @pytest.fixture
    def mock_vector_store(self):
        """Create mock vector store."""
        store = AsyncMock()
        store.initialize = AsyncMock()
        return store

    @pytest.fixture
    def mock_embedding_fn(self):
        """Create mock embedding function."""
        return AsyncMock(return_value=[0.1] * 1536)

    def test_init(self, mock_vector_store, mock_embedding_fn):
        """Test store initialization."""
        store = SQLiteReflexionStore(
            db_path=":memory:",
            vector_store=mock_vector_store,
            embedding_fn=mock_embedding_fn,
        )

        assert store.db_path == ":memory:"
        assert store.vector_store == mock_vector_store
        assert store.embedding_fn == mock_embedding_fn
        assert not store._initialized


class TestSQLiteReflexionStoreSaveLearning:
    """Tests for saving learnings."""

    @pytest.fixture
    async def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            db_path = f.name
        yield db_path
        # Cleanup
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    def mock_vector_store(self):
        """Create mock vector store."""
        store = AsyncMock()
        store.initialize = AsyncMock()
        store.upsert = AsyncMock()
        return store

    @pytest.fixture
    def mock_embedding_fn(self):
        """Create mock embedding function."""
        return AsyncMock(return_value=[0.1] * 1536)

    @pytest.fixture
    async def store(self, temp_db, mock_vector_store, mock_embedding_fn):
        """Create reflexion store."""
        store = SQLiteReflexionStore(
            db_path=temp_db,
            vector_store=mock_vector_store,
            embedding_fn=mock_embedding_fn,
        )
        await store.initialize()
        return store

    async def test_save_learning_basic(self, store, mock_vector_store):
        """Test saving a basic learning."""
        learning = ReflexionLearning(
            id="learn_1",
            problem="Query timeout",
            solution="Use partition pruning",
            feedback="Worked well",
            success_score=0.85,
            tags=["query", "performance"],
        )

        await store.save_learning(learning)

        # Verify SQLite storage
        count = await store.count()
        assert count == 1

        # Verify vector store upsert was called
        mock_vector_store.upsert.assert_called_once()
        vectors = mock_vector_store.upsert.call_args[0][0]
        assert len(vectors) == 1
        assert vectors[0].id == "learn_1"
        assert "Query timeout" in vectors[0].content
        assert "Use partition pruning" in vectors[0].content

    async def test_save_learning_updates_existing(self, store):
        """Test updating an existing learning."""
        learning1 = ReflexionLearning(
            id="learn_1",
            problem="Query timeout",
            solution="Use partition pruning",
            feedback="Worked well",
            success_score=0.85,
            tags=["query"],
        )
        await store.save_learning(learning1)

        # Update with new solution
        learning2 = ReflexionLearning(
            id="learn_1",
            problem="Query timeout",
            solution="Use better indexes",
            feedback="Even better",
            success_score=0.95,
            tags=["query", "index"],
        )
        await store.save_learning(learning2)

        # Should still have only 1 learning
        count = await store.count()
        assert count == 1

    async def test_save_multiple_learnings(self, store):
        """Test saving multiple learnings."""
        learning1 = ReflexionLearning(
            id="learn_1",
            problem="Problem 1",
            solution="Solution 1",
            feedback="Feedback 1",
            success_score=0.8,
            tags=["tag1"],
        )
        learning2 = ReflexionLearning(
            id="learn_2",
            problem="Problem 2",
            solution="Solution 2",
            feedback="Feedback 2",
            success_score=0.9,
            tags=["tag2"],
        )

        await store.save_learning(learning1)
        await store.save_learning(learning2)

        count = await store.count()
        assert count == 2


class TestSQLiteReflexionStoreSearchLearnings:
    """Tests for searching learnings."""

    @pytest.fixture
    async def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            db_path = f.name
        yield db_path
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    def mock_vector_store(self):
        """Create mock vector store."""
        store = AsyncMock()
        store.initialize = AsyncMock()
        store.upsert = AsyncMock()
        store.search = AsyncMock()
        return store

    @pytest.fixture
    def mock_embedding_fn(self):
        """Create mock embedding function."""
        return AsyncMock(return_value=[0.1] * 1536)

    @pytest.fixture
    async def store(self, temp_db, mock_vector_store, mock_embedding_fn):
        """Create reflexion store with sample data."""
        store = SQLiteReflexionStore(
            db_path=temp_db,
            vector_store=mock_vector_store,
            embedding_fn=mock_embedding_fn,
        )
        await store.initialize()

        # Add sample learnings
        learning1 = ReflexionLearning(
            id="learn_1",
            problem="Query timeout on large table",
            solution="Use partition pruning",
            feedback="Reduced query time by 80%",
            success_score=0.85,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            tags=["query", "performance"],
        )
        learning2 = ReflexionLearning(
            id="learn_2",
            problem="High cluster costs",
            solution="Enable autoscaling",
            feedback="Reduced costs by 40%",
            success_score=0.75,
            created_at=datetime(2024, 1, 2, tzinfo=UTC),
            tags=["cluster", "cost"],
        )

        await store.save_learning(learning1)
        await store.save_learning(learning2)

        return store

    async def test_search_learnings_basic(self, store, mock_vector_store):
        """Test basic learning search."""
        # Mock vector search results
        mock_vector_store.search.return_value = [
            VectorSearchResult(
                id="learn_1",
                score=0.95,
                metadata={},
                content="",
            )
        ]

        results = await store.search_learnings("optimize query", top_k=5)

        assert len(results) == 1
        assert results[0].id == "learn_1"
        assert results[0].problem == "Query timeout on large table"

    async def test_search_learnings_with_min_score(self, store, mock_vector_store):
        """Test search with minimum success score filter."""
        # Mock returns both learnings
        mock_vector_store.search.return_value = [
            VectorSearchResult(id="learn_1", score=0.95, metadata={}, content=""),
            VectorSearchResult(id="learn_2", score=0.90, metadata={}, content=""),
        ]

        # Only learn_1 has success_score >= 0.8
        results = await store.search_learnings("optimize", top_k=5, min_score=0.8)

        assert len(results) == 1
        assert results[0].id == "learn_1"
        assert results[0].success_score >= 0.8

    async def test_search_learnings_respects_top_k(self, store, mock_vector_store):
        """Test search respects top_k limit."""
        # Mock returns 2 learnings
        mock_vector_store.search.return_value = [
            VectorSearchResult(id="learn_1", score=0.95, metadata={}, content=""),
            VectorSearchResult(id="learn_2", score=0.90, metadata={}, content=""),
        ]

        results = await store.search_learnings("optimize", top_k=1)

        assert len(results) == 1

    async def test_search_learnings_no_results(self, store, mock_vector_store):
        """Test search with no matching results."""
        mock_vector_store.search.return_value = []

        results = await store.search_learnings("nonexistent", top_k=5)

        assert len(results) == 0


class TestSQLiteReflexionStoreGetByTags:
    """Tests for tag-based retrieval."""

    @pytest.fixture
    async def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            db_path = f.name
        yield db_path
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    async def store(self, temp_db):
        """Create reflexion store with sample data."""
        mock_vector_store = AsyncMock()
        mock_vector_store.initialize = AsyncMock()
        mock_vector_store.upsert = AsyncMock()

        store = SQLiteReflexionStore(
            db_path=temp_db,
            vector_store=mock_vector_store,
            embedding_fn=AsyncMock(return_value=[0.1] * 1536),
        )
        await store.initialize()

        # Add learnings with different tags
        learning1 = ReflexionLearning(
            id="learn_1",
            problem="Problem 1",
            solution="Solution 1",
            feedback="Feedback 1",
            success_score=0.8,
            tags=["query", "performance"],
        )
        learning2 = ReflexionLearning(
            id="learn_2",
            problem="Problem 2",
            solution="Solution 2",
            feedback="Feedback 2",
            success_score=0.9,
            tags=["cluster", "cost"],
        )
        learning3 = ReflexionLearning(
            id="learn_3",
            problem="Problem 3",
            solution="Solution 3",
            feedback="Feedback 3",
            success_score=0.85,
            tags=["query", "cost"],
        )

        await store.save_learning(learning1)
        await store.save_learning(learning2)
        await store.save_learning(learning3)

        return store

    async def test_get_by_single_tag(self, store):
        """Test retrieval by single tag."""
        results = await store.get_by_tags(["query"])

        assert len(results) == 2
        ids = {r.id for r in results}
        assert ids == {"learn_1", "learn_3"}

    async def test_get_by_multiple_tags_and_logic(self, store):
        """Test retrieval by multiple tags (AND logic)."""
        results = await store.get_by_tags(["query", "performance"])

        assert len(results) == 1
        assert results[0].id == "learn_1"

    async def test_get_by_tags_no_match(self, store):
        """Test retrieval with no matching tags."""
        results = await store.get_by_tags(["nonexistent"])

        assert len(results) == 0

    async def test_get_by_empty_tags(self, store):
        """Test retrieval with empty tag list."""
        results = await store.get_by_tags([])

        assert len(results) == 0


class TestSQLiteReflexionStoreUtilities:
    """Tests for utility methods."""

    @pytest.fixture
    async def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            db_path = f.name
        yield db_path
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    async def store(self, temp_db):
        """Create reflexion store."""
        mock_vector_store = AsyncMock()
        mock_vector_store.initialize = AsyncMock()
        mock_vector_store.upsert = AsyncMock()
        mock_vector_store.clear = AsyncMock()

        store = SQLiteReflexionStore(
            db_path=temp_db,
            vector_store=mock_vector_store,
            embedding_fn=AsyncMock(return_value=[0.1] * 1536),
        )
        await store.initialize()
        return store

    async def test_count_empty(self, store):
        """Test count on empty store."""
        count = await store.count()

        assert count == 0

    async def test_count_with_learnings(self, store):
        """Test count with learnings."""
        learning1 = ReflexionLearning(
            id="learn_1",
            problem="Problem 1",
            solution="Solution 1",
            feedback="Feedback 1",
            success_score=0.8,
            tags=["tag1"],
        )
        learning2 = ReflexionLearning(
            id="learn_2",
            problem="Problem 2",
            solution="Solution 2",
            feedback="Feedback 2",
            success_score=0.9,
            tags=["tag2"],
        )

        await store.save_learning(learning1)
        await store.save_learning(learning2)

        count = await store.count()
        assert count == 2

    async def test_clear(self, store):
        """Test clearing all learnings."""
        learning = ReflexionLearning(
            id="learn_1",
            problem="Problem",
            solution="Solution",
            feedback="Feedback",
            success_score=0.8,
            tags=["tag"],
        )
        await store.save_learning(learning)

        await store.clear()

        count = await store.count()
        assert count == 0
        # Verify vector store was cleared
        store.vector_store.clear.assert_called_once()


class TestSQLiteReflexionStoreAsyncEmbedding:
    """Tests for async embedding function support."""

    @pytest.fixture
    async def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            db_path = f.name
        yield db_path
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    def async_embedding_fn(self):
        """Create async embedding function."""

        async def embed(text):
            return [0.1] * 1536

        return embed

    @pytest.fixture
    async def store(self, temp_db, async_embedding_fn):
        """Create store with async embedding function."""
        mock_vector_store = AsyncMock()
        mock_vector_store.initialize = AsyncMock()
        mock_vector_store.upsert = AsyncMock()
        mock_vector_store.search = AsyncMock(return_value=[])

        store = SQLiteReflexionStore(
            db_path=temp_db,
            vector_store=mock_vector_store,
            embedding_fn=async_embedding_fn,
        )
        await store.initialize()
        return store

    async def test_save_with_async_embedding(self, store):
        """Test saving with async embedding function."""
        learning = ReflexionLearning(
            id="learn_1",
            problem="Problem",
            solution="Solution",
            feedback="Feedback",
            success_score=0.8,
            tags=["tag"],
        )

        await store.save_learning(learning)

        # Should not raise, embedding generated async
        count = await store.count()
        assert count == 1

    async def test_search_with_async_embedding(self, store):
        """Test searching with async embedding function."""
        results = await store.search_learnings("test query", top_k=5)

        # Should not raise, embedding generated async
        assert isinstance(results, list)
