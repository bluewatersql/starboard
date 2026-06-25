# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCP transport adapters."""

import pytest
from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.transports import create_mcp_app, create_starboard_mcp_server


@pytest.fixture()
def mcp_config() -> MCPServerConfig:
    """Create a minimal valid MCP config for testing."""
    return MCPServerConfig(
        default_workspace_id="test",
        workspaces={
            "test": WorkspaceProfile(
                host="https://test.databricks.com",
                token_env="TEST_TOKEN",
            ),
        },
    )


class TestTransports:
    """Tests for transport factory functions."""

    def test_create_starboard_mcp_server(self, mcp_config: MCPServerConfig) -> None:
        server = create_starboard_mcp_server(mcp_config)
        assert server.config == mcp_config
        assert server.mcp is not None

    def test_create_mcp_app_returns_asgi(self, mcp_config: MCPServerConfig) -> None:
        app = create_mcp_app(mcp_config)
        # ASGI app must be callable
        assert callable(app)

    def test_create_mcp_app_is_starlette(self, mcp_config: MCPServerConfig) -> None:
        app = create_mcp_app(mcp_config)
        # The streamable_http_app returns a Starlette app
        from starlette.applications import Starlette

        assert isinstance(app, Starlette)
