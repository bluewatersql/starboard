"""
Unit tests for S3: Make DATABRICKS_WAREHOUSE_ID optional.

Tests the warehouse ID resolution logic that automatically fetches
the default workspace warehouse when not explicitly configured.
"""

from unittest.mock import MagicMock, patch

import pytest
from starboard_server.adapters.databricks.client import AsyncDatabricksClient
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.reliability.exceptions import ConfigurationError


class TestWarehouseIdResolution:
    """Tests for AsyncDatabricksClient warehouse ID resolution."""

    @pytest.fixture
    def mock_workspace_client(self):
        """Create a mock WorkspaceClient."""
        with patch(
            "starboard_server.adapters.databricks.client.WorkspaceClient"
        ) as mock:
            client = MagicMock()
            # Mock authentication check
            client.current_user.me.return_value = MagicMock(
                as_dict=lambda: {"userName": "test@example.com"}
            )
            # Mock token creation
            client.tokens.create.return_value = MagicMock(token_value="test-token")
            client.config.host = "https://test.databricks.com"
            mock.return_value = client
            yield client

    @pytest.fixture
    def mock_config_with_warehouse(self):
        """Create mock config with warehouse ID."""
        config = MagicMock(spec=EnvConfig)
        config.databricks_host = "https://test.databricks.com"
        config.databricks_token = "test-token"
        config.databricks_warehouse_id = "configured-warehouse-id"
        return config

    @pytest.fixture
    def mock_config_without_warehouse(self):
        """Create mock config without warehouse ID."""
        config = MagicMock(spec=EnvConfig)
        config.databricks_host = "https://test.databricks.com"
        config.databricks_token = "test-token"
        config.databricks_warehouse_id = None
        return config

    @pytest.mark.asyncio
    async def test_uses_configured_warehouse_id(
        self, mock_workspace_client, mock_config_with_warehouse
    ):
        """When warehouse ID is configured, it should be used directly."""
        client = AsyncDatabricksClient(cfg=mock_config_with_warehouse)
        await client._initialize()

        assert client.warehouse_id == "configured-warehouse-id"
        # Should not call settings API when configured
        mock_workspace_client.settings.default_warehouse_id.get.assert_not_called()
        await client.close()

    @pytest.mark.asyncio
    async def test_uses_default_warehouse_when_not_configured(
        self, mock_workspace_client, mock_config_without_warehouse
    ):
        """When warehouse ID is not configured, should get default from workspace."""
        # Mock the default warehouse setting (matches actual SDK structure)
        mock_string_val = MagicMock()
        mock_string_val.value = "default-workspace-warehouse"
        mock_setting = MagicMock()
        mock_setting.string_val = mock_string_val
        mock_workspace_client.settings.default_warehouse_id.get.return_value = (
            mock_setting
        )

        client = AsyncDatabricksClient(cfg=mock_config_without_warehouse)
        await client._initialize()

        assert client.warehouse_id == "default-workspace-warehouse"
        mock_workspace_client.settings.default_warehouse_id.get.assert_called_once()
        await client.close()

    @pytest.mark.asyncio
    async def test_none_warehouse_when_no_default_configured(
        self, mock_workspace_client, mock_config_without_warehouse
    ):
        """When no default warehouse is configured, warehouse_id should be None."""
        # Mock no default warehouse configured (string_val is None)
        mock_setting = MagicMock()
        mock_setting.string_val = None
        mock_workspace_client.settings.default_warehouse_id.get.return_value = (
            mock_setting
        )

        client = AsyncDatabricksClient(cfg=mock_config_without_warehouse)
        await client._initialize()

        assert client.warehouse_id is None
        await client.close()

    @pytest.mark.asyncio
    async def test_none_warehouse_when_sdk_call_fails(
        self, mock_workspace_client, mock_config_without_warehouse
    ):
        """When SDK call fails, should gracefully return None."""
        # Mock SDK call failure
        mock_workspace_client.settings.default_warehouse_id.get.side_effect = Exception(
            "SDK error"
        )

        client = AsyncDatabricksClient(cfg=mock_config_without_warehouse)
        await client._initialize()

        assert client.warehouse_id is None
        await client.close()

    @pytest.mark.asyncio
    async def test_require_warehouse_id_returns_configured(
        self, mock_workspace_client, mock_config_with_warehouse
    ):
        """require_warehouse_id should return configured warehouse ID."""
        client = AsyncDatabricksClient(cfg=mock_config_with_warehouse)
        await client._initialize()

        assert client.require_warehouse_id() == "configured-warehouse-id"
        await client.close()

    @pytest.mark.asyncio
    async def test_require_warehouse_id_returns_default(
        self, mock_workspace_client, mock_config_without_warehouse
    ):
        """require_warehouse_id should return default warehouse ID."""
        # Mock the default warehouse setting (matches actual SDK structure)
        mock_string_val = MagicMock()
        mock_string_val.value = "default-workspace-warehouse"
        mock_setting = MagicMock()
        mock_setting.string_val = mock_string_val
        mock_workspace_client.settings.default_warehouse_id.get.return_value = (
            mock_setting
        )

        client = AsyncDatabricksClient(cfg=mock_config_without_warehouse)
        await client._initialize()

        assert client.require_warehouse_id() == "default-workspace-warehouse"
        await client.close()

    @pytest.mark.asyncio
    async def test_require_warehouse_id_raises_when_none(
        self, mock_workspace_client, mock_config_without_warehouse
    ):
        """require_warehouse_id should raise ConfigurationError when None."""
        # Mock no default warehouse configured (string_val is None)
        mock_setting = MagicMock()
        mock_setting.string_val = None
        mock_workspace_client.settings.default_warehouse_id.get.return_value = (
            mock_setting
        )

        client = AsyncDatabricksClient(cfg=mock_config_without_warehouse)
        await client._initialize()

        with pytest.raises(ConfigurationError) as exc_info:
            client.require_warehouse_id()

        assert "databricks_warehouse_id" in str(exc_info.value)
        assert "hint" in str(exc_info.value).lower()
        await client.close()
