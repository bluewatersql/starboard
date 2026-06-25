# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for StarboardMCPServer."""

import pytest
from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.models import MCPError
from starboard_server.mcp.server import StarboardMCPServer


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


@pytest.fixture()
def server(mcp_config: MCPServerConfig) -> StarboardMCPServer:
    """Create a StarboardMCPServer instance."""
    return StarboardMCPServer(config=mcp_config)


class TestStarboardMCPServer:
    """Tests for StarboardMCPServer."""

    def test_server_accepts_config(self, server: StarboardMCPServer) -> None:
        assert server.config.default_workspace_id == "test"

    def test_mcp_instance_created(self, server: StarboardMCPServer) -> None:
        assert server.mcp is not None
        assert server.mcp.name == "starboard-mcp"

    async def test_list_tools_includes_ping(self, server: StarboardMCPServer) -> None:
        tools = await server.mcp.list_tools()
        tool_names = [t.name for t in tools]
        assert "starboard_ping" in tool_names

    async def test_call_ping_tool(self, server: StarboardMCPServer) -> None:
        result = await server.mcp.call_tool("starboard_ping", {})
        # FastMCP returns a list of content objects
        assert len(result) > 0
        assert "pong" in str(result[0])

    def test_call_tool_not_implemented_returns_error(
        self, server: StarboardMCPServer
    ) -> None:
        error = server.call_tool_not_implemented("unknown_tool")
        assert isinstance(error, MCPError)
        assert error.code == "EXEC_NOT_IMPLEMENTED"
        assert "unknown_tool" in error.message


class TestStarboardMCPServerConfig:
    """Tests for server configuration handling."""

    def test_safe_mode_stored(self) -> None:
        config = MCPServerConfig(
            default_workspace_id="s",
            workspaces={
                "s": WorkspaceProfile(
                    host="https://s.databricks.com",
                    token_env="T",
                ),
            },
            safe_mode=True,
        )
        server = StarboardMCPServer(config=config)
        assert server.config.safe_mode is True

    def test_multiple_workspaces(self) -> None:
        config = MCPServerConfig(
            default_workspace_id="a",
            workspaces={
                "a": WorkspaceProfile(
                    host="https://a.databricks.com", token_env="A_TOK"
                ),
                "b": WorkspaceProfile(
                    host="https://b.databricks.com", token_env="B_TOK"
                ),
            },
        )
        server = StarboardMCPServer(config=config)
        assert len(server.config.workspaces) == 2
