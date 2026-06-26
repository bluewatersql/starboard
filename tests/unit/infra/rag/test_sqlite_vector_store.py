# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for SQLite vector store (without sqlite-vec dependency).

These tests verify the logic without requiring the sqlite-vec extension.
Integration tests in tests/integration/infra/rag/ will test with the actual extension.
"""

from unittest.mock import AsyncMock, patch

import pytest
from starboard_core.foundations.models import VectorRecord
from starboard_server.infra.rag.adapters.storage.sqlite_vector_store import (
    SQLiteVectorStore,
)


class TestSQLiteVectorStoreUnit:
    """Unit tests for SQLiteVectorStore without sqlite-vec dependency."""

    def test_init(self):
        """Test initialization parameters."""
        store = SQLiteVectorStore("test.db", dimension=1536)

        assert store.db_path == "test.db"
        assert store.dimension == 1536
        assert not store._initialized

    def test_init_custom_dimension(self):
        """Test initialization with custom dimension."""
        store = SQLiteVectorStore("test.db", dimension=768)

        assert store.dimension == 768

    @pytest.mark.asyncio
    async def test_upsert_validates_empty_list(self):
        """Test that upsert raises ValueError for empty list."""
        store = SQLiteVectorStore("test.db")
        store._initialized = True  # Skip initialization

        with pytest.raises(ValueError, match="Cannot upsert empty vector list"):
            await store.upsert([])

    @pytest.mark.asyncio
    async def test_upsert_validates_dimension(self):
        """Test that upsert validates vector dimensions."""
        store = SQLiteVectorStore("test.db", dimension=3)
        store._initialized = True

        vector = VectorRecord(
            id="vec_1",
            embedding=[0.1, 0.2],  # Wrong dimension
            metadata={},
            content="test",
        )

        with pytest.raises(ValueError, match="wrong dimension"):
            await store.upsert([vector])

    @pytest.mark.asyncio
    async def test_search_validates_dimension(self):
        """Test that search validates query embedding dimension."""
        store = SQLiteVectorStore("test.db", dimension=1536)
        store._initialized = True

        with pytest.raises(ValueError, match="dimension mismatch"):
            await store.search([0.1, 0.2], top_k=5)  # Wrong dimension

    @pytest.mark.asyncio
    async def test_delete_empty_list_does_nothing(self):
        """Test that delete with empty list doesn't error."""
        store = SQLiteVectorStore("test.db")
        store._initialized = True

        # Mock the database connection
        with patch("aiosqlite.connect") as mock_connect:
            mock_db = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_db

            # Should return without attempting delete
            await store.delete([])

            # Should not have tried to execute any SQL
            mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_raises_on_missing_extension(self):
        """Test that initialization raises helpful error if sqlite-vec missing."""
        store = SQLiteVectorStore("test.db")

        # Mock _get_connection to raise RuntimeError
        async def mock_get_connection():
            raise RuntimeError(
                "Failed to load sqlite-vec extension. Extension not found"
            )

        store._get_connection = mock_get_connection

        with pytest.raises(RuntimeError, match="Failed to load sqlite-vec extension"):
            await store.initialize()


class TestSQLiteVectorStoreMetadata:
    """Tests for metadata handling in SQLite vector store."""

    def test_dimension_default(self):
        """Test that default dimension is 1536 (OpenAI)."""
        store = SQLiteVectorStore("test.db")

        assert store.dimension == 1536

    def test_db_path_stored(self):
        """Test that database path is stored correctly."""
        path = "/path/to/vectors.db"
        store = SQLiteVectorStore(path)

        assert store.db_path == path

    def test_not_initialized_by_default(self):
        """Test that store is not initialized on construction."""
        store = SQLiteVectorStore("test.db")

        assert not store._initialized
