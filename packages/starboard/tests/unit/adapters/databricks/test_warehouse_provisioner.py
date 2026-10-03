# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for WarehouseProvisioner."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starboard.adapters.databricks.warehouse_provisioner import (
    WarehouseProvisioner,
)
from starboard.exceptions import ConfigurationError


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock WorkspaceClient."""
    client = MagicMock()
    client.warehouses = MagicMock()
    return client


@pytest.fixture
def provisioner(mock_client: MagicMock) -> WarehouseProvisioner:
    """Create a WarehouseProvisioner with mock client."""
    return WarehouseProvisioner(
        client=mock_client,
        warehouse_name="TEST_DW",
        warehouse_size="X-Large",
    )


class TestProvision:
    """Tests for WarehouseProvisioner.provision()."""

    @pytest.mark.asyncio
    async def test_provision_creates_warehouse(
        self, provisioner: WarehouseProvisioner, mock_client: MagicMock
    ) -> None:
        """Successfully create a new warehouse when none exists."""
        mock_client.warehouses.list.return_value = []
        mock_response = MagicMock()
        mock_response.id = "abc123"
        mock_client.warehouses.create_and_wait.return_value = mock_response

        result = await provisioner.provision()

        assert result == "abc123"
        mock_client.warehouses.create_and_wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_provision_idempotent_existing_running(
        self, provisioner: WarehouseProvisioner, mock_client: MagicMock
    ) -> None:
        """Return existing warehouse ID when a running warehouse exists."""
        existing = MagicMock()
        existing.name = "TEST_DW"
        existing.id = "existing-123"
        existing.state = "RUNNING"
        mock_client.warehouses.list.return_value = [existing]

        result = await provisioner.provision()

        assert result == "existing-123"
        mock_client.warehouses.create_and_wait.assert_not_called()

    @pytest.mark.asyncio
    async def test_provision_idempotent_existing_stopped(
        self, provisioner: WarehouseProvisioner, mock_client: MagicMock
    ) -> None:
        """Return existing warehouse ID when a stopped warehouse exists."""
        existing = MagicMock()
        existing.name = "TEST_DW"
        existing.id = "stopped-456"
        existing.state = "STOPPED"
        mock_client.warehouses.list.return_value = [existing]

        result = await provisioner.provision()

        assert result == "stopped-456"
        mock_client.warehouses.create_and_wait.assert_not_called()

    @pytest.mark.asyncio
    async def test_provision_creates_when_existing_deleted(
        self, provisioner: WarehouseProvisioner, mock_client: MagicMock
    ) -> None:
        """Create new warehouse when existing one is deleted."""
        deleted = MagicMock()
        deleted.name = "TEST_DW"
        deleted.id = "deleted-789"
        deleted.state = "DELETED"
        mock_client.warehouses.list.return_value = [deleted]

        new_response = MagicMock()
        new_response.id = "new-abc"
        mock_client.warehouses.create_and_wait.return_value = new_response

        result = await provisioner.provision()

        assert result == "new-abc"
        mock_client.warehouses.create_and_wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_provision_raises_on_serverless_not_supported(
        self, provisioner: WarehouseProvisioner, mock_client: MagicMock
    ) -> None:
        """Raise ConfigurationError when serverless is not supported."""
        mock_client.warehouses.list.return_value = []
        mock_client.warehouses.create_and_wait.side_effect = Exception(
            "Serverless compute is not supported in this workspace"
        )

        with pytest.raises(ConfigurationError):
            await provisioner.provision()

    @pytest.mark.asyncio
    async def test_provision_raises_on_permission_denied(
        self, provisioner: WarehouseProvisioner, mock_client: MagicMock
    ) -> None:
        """Raise ConfigurationError on 403 permission denied."""
        mock_client.warehouses.list.return_value = []
        mock_client.warehouses.create_and_wait.side_effect = Exception(
            "403 permission denied: CREATE_WAREHOUSE"
        )

        with pytest.raises(ConfigurationError):
            await provisioner.provision()
