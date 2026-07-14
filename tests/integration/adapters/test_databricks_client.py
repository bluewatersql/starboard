# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Integration tests for AsyncDatabricksClient.

Tests client initialization, authentication, service delegation,
and error handling.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from databricks.sdk import WorkspaceClient
from starboard.adapters.databricks.client import AsyncDatabricksClient
from starboard.infra.core.config import EnvConfig
from starboard.infra.reliability.exceptions import ConfigurationError


@pytest.fixture
def mock_env_config():
    """Mock EnvConfig with Databricks credentials."""
    config = Mock(spec=EnvConfig)
    config.databricks_host = "https://test.databricks.com"
    config.databricks_token = "test_token_123"
    config.databricks_warehouse_id = "test_warehouse_id"
    return config


@pytest.fixture
def mock_workspace_client():
    """Mock WorkspaceClient."""
    with patch(
        "starboard.adapters.databricks.client.WorkspaceClient"
    ) as mock_client_class:
        client = MagicMock(spec=WorkspaceClient)
        # Mock current user to simulate authentication (returns object with as_dict())
        mock_user = Mock()
        mock_user.as_dict.return_value = {
            "id": "test_user_123",
            "userName": "test@example.com",
            "displayName": "Test User",
        }
        client.current_user = Mock()
        client.current_user.me = Mock(return_value=mock_user)
        mock_client_class.return_value = client
        yield mock_client_class


class TestAsyncDatabricksClientInitialization:
    """Tests for AsyncDatabricksClient initialization."""

    @pytest.mark.asyncio
    async def test_initialization_with_config(
        self, mock_env_config, mock_workspace_client
    ):
        """Test successful initialization with config object."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert client is not None
        assert client._sdk_client is not None
        mock_workspace_client.assert_called_once_with(
            host="https://test.databricks.com", token="test_token_123"
        )
        await client.close()

    @pytest.mark.asyncio
    async def test_initialization_with_explicit_params(self, mock_workspace_client):
        """Test initialization with explicit host and token."""
        with patch.object(EnvConfig, "from_env") as mock_from_env:
            mock_config = Mock()
            mock_config.databricks_host = "https://default.databricks.com"
            mock_config.databricks_token = "default_token"
            mock_config.databricks_warehouse_id = "default_wh"
            mock_from_env.return_value = mock_config

            client = AsyncDatabricksClient(
                host="https://explicit.databricks.com", token="explicit_token"
            )
            await client._initialize()

            assert client is not None
            mock_workspace_client.assert_called_once_with(
                host="https://explicit.databricks.com", token="explicit_token"
            )
            await client.close()

    @pytest.mark.asyncio
    async def test_initialization_params_override_config(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that explicit params override config."""
        client = AsyncDatabricksClient(
            cfg=mock_env_config,
            host="https://override.databricks.com",
            token="override_token",
        )
        await client._initialize()

        # Should use explicit params, not config
        mock_workspace_client.assert_called_once_with(
            host="https://override.databricks.com", token="override_token"
        )
        await client.close()

    @pytest.mark.asyncio
    async def test_initialization_unauthenticated_raises_error(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that unauthenticated client raises ConfigurationError."""
        # Mock is_authenticated to return False
        mock_client = mock_workspace_client.return_value
        mock_client.current_user.me.side_effect = Exception("Auth failed")

        client = AsyncDatabricksClient(cfg=mock_env_config)
        with pytest.raises(ConfigurationError) as exc_info:
            await client._initialize()

        assert "Failed to authenticate" in str(exc_info.value)


class TestAsyncDatabricksClientAuthentication:
    """Tests for authentication verification."""

    @pytest.mark.asyncio
    async def test_is_authenticated_success(
        self, mock_env_config, mock_workspace_client
    ):
        """Test successful authentication check."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        # is_authenticated should work after initialization
        assert client.is_authenticated() is True
        await client.close()

    @pytest.mark.asyncio
    async def test_is_authenticated_failure(
        self, mock_env_config, mock_workspace_client
    ):
        """Test authentication failure."""
        mock_client = mock_workspace_client.return_value
        mock_client.current_user.me.side_effect = Exception("Unauthorized")

        client = AsyncDatabricksClient(cfg=mock_env_config)
        with pytest.raises(ConfigurationError):
            await client._initialize()


class TestAsyncDatabricksClientServices:
    """Tests for service delegation."""

    @pytest.mark.asyncio
    async def test_sql_service_initialized(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that SQL service is initialized."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert client._sql is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_job_service_initialized(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that job service is initialized."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert client._jobs is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_catalog_service_initialized(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that UC catalog service is initialized."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert client._catalog is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_cluster_service_initialized(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that cluster service is initialized."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert client._clusters is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_warehouse_service_initialized(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that warehouse service is initialized."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert client._warehouses is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_workspace_service_initialized(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that workspace service is initialized."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert client._workspace is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_sql_methods_available(self, mock_env_config, mock_workspace_client):
        """Test that SQL methods are available."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert hasattr(client, "execute_sql")
        assert hasattr(client, "get_query_history")
        await client.close()

    @pytest.mark.asyncio
    async def test_job_methods_available(self, mock_env_config, mock_workspace_client):
        """Test that job methods are available."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert hasattr(client, "run_job")
        assert hasattr(client, "create_job")
        assert hasattr(client, "get_job")
        assert hasattr(client, "list_jobs")
        await client.close()

    @pytest.mark.asyncio
    async def test_catalog_methods_available(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that catalog methods are available."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert hasattr(client, "get_table")
        assert hasattr(client, "get_table_lineage")
        await client.close()

    @pytest.mark.asyncio
    async def test_cluster_methods_available(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that cluster methods are available."""
        client = AsyncDatabricksClient(cfg=mock_env_config)
        await client._initialize()

        assert hasattr(client, "start_cluster")
        assert hasattr(client, "stop_cluster")
        assert hasattr(client, "get_cluster")
        await client.close()


class TestAsyncDatabricksClientIntegration:
    """Integration tests for complete client workflows."""

    @pytest.mark.asyncio
    async def test_client_initialization_and_service_access(
        self, mock_env_config, mock_workspace_client
    ):
        """Test complete workflow: init → access services."""
        async with AsyncDatabricksClient(cfg=mock_env_config) as client:
            # Verify client is initialized
            assert client._sdk_client is not None

            # Verify all services are accessible (as properties)
            assert client._sql is not None
            assert client._jobs is not None
            assert client._catalog is not None
            assert client._clusters is not None
            assert client._warehouses is not None
            assert client._workspace is not None

            # Verify public methods are available
            assert hasattr(client, "execute_sql")
            assert hasattr(client, "run_job")
            assert hasattr(client, "get_table")
            assert hasattr(client, "start_cluster")

    @pytest.mark.asyncio
    async def test_client_with_default_config(self, mock_workspace_client):
        """Test client initialization with default config."""
        with patch.object(EnvConfig, "from_env") as mock_from_env:
            mock_config = Mock()
            mock_config.databricks_host = "https://default.databricks.com"
            mock_config.databricks_token = "default_token"
            mock_config.databricks_warehouse_id = "default_warehouse"
            mock_from_env.return_value = mock_config

            async with AsyncDatabricksClient() as client:
                assert client._sdk_client is not None
                mock_workspace_client.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_cleanup(
        self, mock_env_config, mock_workspace_client
    ):
        """Test that context manager properly cleans up resources."""
        client = AsyncDatabricksClient(cfg=mock_env_config)

        async with client:
            assert client._initialized is True

        # After exiting context, client should be cleaned up
        assert client._initialized is False

    @pytest.mark.asyncio
    async def test_warehouse_id_resolution(
        self, mock_env_config, mock_workspace_client
    ):
        """Test warehouse ID is available after initialization."""
        async with AsyncDatabricksClient(cfg=mock_env_config) as client:
            assert client.warehouse_id == "test_warehouse_id"

    @pytest.mark.asyncio
    async def test_require_warehouse_id(self, mock_env_config, mock_workspace_client):
        """Test require_warehouse_id returns configured warehouse."""
        async with AsyncDatabricksClient(cfg=mock_env_config) as client:
            assert client.require_warehouse_id() == "test_warehouse_id"
