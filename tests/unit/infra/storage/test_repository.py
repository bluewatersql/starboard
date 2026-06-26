# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for typed repository pattern.

Tests cover:
- Generic repository operations
- Model conversion (row to model, model to row)
- Dataclass and Pydantic model support
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.infra.storage.repository import UCRepository
from starboard_server.infra.storage.uc_adapter import UCStorageAdapter


@dataclass
class SampleModel:
    """Sample dataclass model for tests."""

    id: str
    name: str
    value: int
    created_at: datetime | None = None


class TestUCRepository:
    """Tests for UCRepository."""

    @pytest.fixture
    def mock_storage(self) -> MagicMock:
        """Create mock storage adapter."""
        storage = MagicMock(spec=UCStorageAdapter)
        storage.read = AsyncMock()
        storage.read_one = AsyncMock()
        storage.write = AsyncMock()
        storage.upsert = AsyncMock()
        storage.delete = AsyncMock()
        return storage

    @pytest.fixture
    def repository(self, mock_storage: MagicMock) -> UCRepository[SampleModel]:
        """Create repository with test model."""
        return UCRepository(
            storage=mock_storage,
            table_id="test_table",
            model_class=SampleModel,
        )

    @pytest.mark.asyncio
    async def test_get_returns_model(
        self,
        repository: UCRepository[SampleModel],
        mock_storage: MagicMock,
    ) -> None:
        """Test get returns typed model instance."""
        mock_storage.read_one.return_value = {
            "id": "test-id",
            "name": "Test Name",
            "value": 42,
            "created_at": None,
        }

        result = await repository.get(id="test-id")

        assert result is not None
        assert isinstance(result, SampleModel)
        assert result.id == "test-id"
        assert result.name == "Test Name"
        assert result.value == 42

        mock_storage.read_one.assert_called_once_with("test_table", {"id": "test-id"})

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(
        self,
        repository: UCRepository[SampleModel],
        mock_storage: MagicMock,
    ) -> None:
        """Test get returns None when row not found."""
        mock_storage.read_one.return_value = None

        result = await repository.get(id="nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_returns_models(
        self,
        repository: UCRepository[SampleModel],
        mock_storage: MagicMock,
    ) -> None:
        """Test list returns list of typed models."""
        mock_storage.read.return_value = [
            {"id": "a", "name": "A", "value": 1, "created_at": None},
            {"id": "b", "name": "B", "value": 2, "created_at": None},
        ]

        results = await repository.list()

        assert len(results) == 2
        assert all(isinstance(r, SampleModel) for r in results)
        assert results[0].id == "a"
        assert results[1].id == "b"

    @pytest.mark.asyncio
    async def test_list_with_filters(
        self,
        repository: UCRepository[SampleModel],
        mock_storage: MagicMock,
    ) -> None:
        """Test list with filters."""
        mock_storage.read.return_value = []

        await repository.list(
            filters={"name": "Test"}, order_by="created_at DESC", limit=10
        )

        mock_storage.read.assert_called_once_with(
            "test_table",
            filters={"name": "Test"},
            order_by="created_at DESC",
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_save_converts_model_to_row(
        self,
        repository: UCRepository[SampleModel],
        mock_storage: MagicMock,
    ) -> None:
        """Test save converts model to row dict."""
        model = SampleModel(id="new-id", name="New", value=100)

        await repository.save(model)

        mock_storage.upsert.assert_called_once()
        call_args = mock_storage.upsert.call_args
        assert call_args[0][0] == "test_table"
        row = call_args[0][1]
        assert row["id"] == "new-id"
        assert row["name"] == "New"
        assert row["value"] == 100

    @pytest.mark.asyncio
    async def test_delete_by_primary_key(
        self,
        repository: UCRepository[SampleModel],
        mock_storage: MagicMock,
    ) -> None:
        """Test delete by primary key."""
        await repository.delete(id="to-delete")

        mock_storage.delete.assert_called_once_with("test_table", {"id": "to-delete"})

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty_list(
        self,
        repository: UCRepository[SampleModel],
        mock_storage: MagicMock,
    ) -> None:
        """Test list returns empty list when no results."""
        mock_storage.read.return_value = []

        results = await repository.list()

        assert results == []

    def test_row_to_model_dataclass(
        self,
        repository: UCRepository[SampleModel],
    ) -> None:
        """Test converting row dict to dataclass model."""
        row = {"id": "test", "name": "Test", "value": 42, "created_at": None}

        model = repository._row_to_model(row)

        assert isinstance(model, SampleModel)
        assert model.id == "test"

    def test_model_to_row_dataclass(
        self,
        repository: UCRepository[SampleModel],
    ) -> None:
        """Test converting dataclass model to row dict."""
        model = SampleModel(id="test", name="Test", value=42)

        row = repository._model_to_row(model)

        assert row["id"] == "test"
        assert row["name"] == "Test"
        assert row["value"] == 42


class TestRepositoryWithPydantic:
    """Tests for repository with Pydantic models (if available)."""

    @pytest.mark.asyncio
    async def test_pydantic_model_conversion(self) -> None:
        """Test Pydantic model conversion if pydantic is available."""
        try:
            from pydantic import BaseModel

            class PydanticModel(BaseModel):
                id: str
                name: str
                value: int

            mock_storage = MagicMock(spec=UCStorageAdapter)
            mock_storage.read_one = AsyncMock(
                return_value={"id": "test", "name": "Test", "value": 42}
            )

            repo: UCRepository[PydanticModel] = UCRepository(
                storage=mock_storage,
                table_id="test",
                model_class=PydanticModel,
            )

            result = await repo.get(id="test")

            assert result is not None
            assert isinstance(result, PydanticModel)
            assert result.id == "test"

        except ImportError:
            pytest.skip("Pydantic not installed")
