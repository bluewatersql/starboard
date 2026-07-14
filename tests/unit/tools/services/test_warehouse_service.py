# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for WarehouseService."""

from __future__ import annotations

from typing import Any

import pytest
from starboard.tools.exceptions import WarehouseNotFoundError
from starboard.tools.services.warehouse_service import WarehouseService


class MockWarehouseProvider:
    """Mock WarehouseDataProvider for testing."""

    def __init__(self):
        self.warehouse_configs: dict[str, dict] = {}
        self.warehouse_metrics: dict[str, dict] = {}
        self.warehouse_history: dict[str, dict] = {}
        self.warehouses_list: list[dict] = []

    async def get_warehouse_config(self, warehouse_id: str) -> dict[str, Any] | None:
        return self.warehouse_configs.get(warehouse_id)

    async def get_warehouse_metrics(
        self, warehouse_id: str, days_history: int = 7
    ) -> dict[str, Any] | None:
        return self.warehouse_metrics.get(warehouse_id)

    async def get_warehouse_query_history(
        self, warehouse_id: str, days_history: int = 30
    ) -> dict[str, Any] | None:
        return self.warehouse_history.get(warehouse_id)

    async def list_warehouses(self) -> list[dict[str, Any]]:
        return self.warehouses_list


class TestWarehouseService:
    """Tests for WarehouseService."""

    @pytest.fixture
    def mock_provider(self) -> MockWarehouseProvider:
        """Create mock provider."""
        return MockWarehouseProvider()

    @pytest.fixture
    def service(self, mock_provider: MockWarehouseProvider) -> WarehouseService:
        """Create service with mock provider."""
        return WarehouseService(warehouse_data=mock_provider)

    # =========================================================================
    # get_warehouse_config tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_warehouse_config_found(
        self, service: WarehouseService, mock_provider: MockWarehouseProvider
    ):
        """Test getting warehouse config when found."""
        mock_provider.warehouse_configs["wh-123"] = {
            "id": "wh-123",
            "name": "analytics-warehouse",
            "cluster_size": "Large",
        }

        result = await service.get_warehouse_config("wh-123")

        assert result is not None
        assert result["id"] == "wh-123"
        assert result["name"] == "analytics-warehouse"

    @pytest.mark.asyncio
    async def test_get_warehouse_config_not_found_raises(
        self, service: WarehouseService
    ):
        """Test getting warehouse config raises when not found."""
        with pytest.raises(WarehouseNotFoundError) as exc_info:
            await service.get_warehouse_config("nonexistent")

        assert exc_info.value.warehouse_id == "nonexistent"

    @pytest.mark.asyncio
    async def test_get_warehouse_config_or_none(self, service: WarehouseService):
        """Test getting warehouse config returns None when not found."""
        result = await service.get_warehouse_config_or_none("nonexistent")
        assert result is None

    # =========================================================================
    # get_warehouse_metrics tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_warehouse_metrics_found(
        self, service: WarehouseService, mock_provider: MockWarehouseProvider
    ):
        """Test getting warehouse metrics when found."""
        mock_provider.warehouse_metrics["wh-123"] = {
            "query_count": 100,
            "avg_duration_ms": 500,
        }

        result = await service.get_warehouse_metrics("wh-123")

        assert result is not None
        assert result["query_count"] == 100

    @pytest.mark.asyncio
    async def test_get_warehouse_metrics_not_found_returns_none(
        self, service: WarehouseService
    ):
        """Test getting warehouse metrics returns None when not found."""
        result = await service.get_warehouse_metrics("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_warehouse_metrics_with_days(
        self, service: WarehouseService, mock_provider: MockWarehouseProvider
    ):
        """Test getting warehouse metrics with custom days parameter."""
        mock_provider.warehouse_metrics["wh-123"] = {"metrics": {}}

        result = await service.get_warehouse_metrics("wh-123", days_history=30)
        assert result is not None

    # =========================================================================
    # get_warehouse_query_history tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_warehouse_query_history_found(
        self, service: WarehouseService, mock_provider: MockWarehouseProvider
    ):
        """Test getting warehouse query history when found."""
        mock_provider.warehouse_history["wh-123"] = {
            "queries": [{"id": "q1"}, {"id": "q2"}],
            "summary": {"total_queries": 2},
        }

        result = await service.get_warehouse_query_history("wh-123")

        assert result is not None
        assert "queries" in result
        assert len(result["queries"]) == 2

    @pytest.mark.asyncio
    async def test_get_warehouse_query_history_not_found_returns_none(
        self, service: WarehouseService
    ):
        """Test getting warehouse query history returns None when not found."""
        result = await service.get_warehouse_query_history("nonexistent")
        assert result is None

    # =========================================================================
    # list_warehouses tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_warehouses_with_data(
        self, service: WarehouseService, mock_provider: MockWarehouseProvider
    ):
        """Test listing warehouses when data exists."""
        mock_provider.warehouses_list = [
            {"id": "wh-1", "name": "warehouse-1"},
            {"id": "wh-2", "name": "warehouse-2"},
        ]

        result = await service.list_warehouses()

        assert len(result) == 2
        assert result[0]["id"] == "wh-1"

    @pytest.mark.asyncio
    async def test_list_warehouses_empty(self, service: WarehouseService):
        """Test listing warehouses when none exist."""
        result = await service.list_warehouses()
        assert result == []


class TestWarehouseServiceProtocol:
    """Test that WarehouseService uses WarehouseDataProvider protocol."""

    def test_service_accepts_protocol(self):
        """Verify service constructor accepts WarehouseDataProvider."""

        # MockWarehouseProvider should satisfy WarehouseDataProvider
        mock = MockWarehouseProvider()

        # Type checker would catch if MockWarehouseProvider doesn't match
        service = WarehouseService(warehouse_data=mock)
        assert service is not None
