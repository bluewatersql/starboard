# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Integration-style unit tests for MCP tool execution pipeline."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.agents.output.llm_responses import ToolResult
from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.exceptions import ExecutionError, RateLimitError
from starboard_server.mcp.server import StarboardMCPServer
from starboard_server.mcp.tool_bridge import PHASE_A_TOOLS


def _make_config(**overrides: object) -> MCPServerConfig:
    defaults: dict = {
        "default_workspace_id": "prod",
        "workspaces": {
            "prod": WorkspaceProfile(
                host="https://prod.databricks.com", token_env="PROD_TOKEN"
            ),
        },
    }
    defaults.update(overrides)
    return MCPServerConfig(**defaults)


def _make_server(
    *,
    safe_mode: bool = False,
    with_registry: bool = True,
) -> StarboardMCPServer:
    """Create a server with mocked dependencies."""
    config = _make_config(safe_mode=safe_mode)

    mock_resolver = MagicMock()
    mock_resolver.resolve.return_value = config.workspaces["prod"]

    mock_auth = MagicMock()
    mock_auth.get_credentials.return_value = MagicMock(
        host="https://prod.databricks.com", token="fake-token"
    )

    mock_rate_limiter = MagicMock()
    mock_rate_limiter.check = MagicMock()

    mock_sanitizer = MagicMock()
    mock_sanitizer.redact_output = MagicMock(side_effect=lambda d: d)

    mock_circuit_breakers = MagicMock()
    mock_breaker = MagicMock()

    async def _passthrough_call(fn, *a, **kw):
        return await fn(*a, **kw)

    mock_breaker.call = _passthrough_call
    mock_circuit_breakers.get.return_value = mock_breaker

    mock_registry = None
    if with_registry:
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(
            return_value=ToolResult(
                tool_call_id="",
                tool_name="resolve_query",
                content='{"sql": "SELECT 1"}',
            )
        )

    return StarboardMCPServer(
        config=config,
        workspace_resolver=mock_resolver,
        auth_provider=mock_auth,
        rate_limiter=mock_rate_limiter,
        sanitizer=mock_sanitizer,
        circuit_breakers=mock_circuit_breakers,
        tool_registry=mock_registry,
    )


class TestToolRegistration:
    """Tests for dynamic tool registration."""

    def test_list_tools_includes_phase_a(self) -> None:
        server = _make_server()
        tool_names = {t.name for t in server.mcp._tool_manager.list_tools()}
        for name in PHASE_A_TOOLS:
            assert name in tool_names, f"{name} not registered"

    def test_list_tools_includes_ping(self) -> None:
        server = _make_server()
        tool_names = {t.name for t in server.mcp._tool_manager.list_tools()}
        assert "starboard_ping" in tool_names

    def test_safe_mode_only_registers_safe_tools(self) -> None:
        server = _make_server(safe_mode=True)
        tool_names = {t.name for t in server.mcp._tool_manager.list_tools()}
        # Should not have Phase A online tools
        assert "resolve_query" not in tool_names
        # Should have safe tools
        assert "explore_artifact" in tool_names or "analyze_code_quality" in tool_names


class TestExecuteTool:
    """Tests for the _execute_tool pipeline."""

    @pytest.mark.asyncio()
    async def test_call_tool_executes_via_registry(self) -> None:
        server = _make_server()
        result_json = await server._execute_tool(
            "resolve_query", {"target": "SELECT 1"}
        )
        result = json.loads(result_json)
        assert result["status"] == "success"
        assert result["data"]["sql"] == "SELECT 1"

    @pytest.mark.asyncio()
    async def test_call_tool_resolves_workspace(self) -> None:
        server = _make_server()
        await server._execute_tool(
            "resolve_query", {"target": "SELECT 1", "workspace_id": "prod"}
        )
        server._workspace_resolver.resolve.assert_called_once_with("prod")

    @pytest.mark.asyncio()
    async def test_call_tool_default_workspace(self) -> None:
        server = _make_server()
        result_json = await server._execute_tool(
            "resolve_query", {"target": "SELECT 1"}
        )
        result = json.loads(result_json)
        assert result["workspace_id_used"] == "prod"

    @pytest.mark.asyncio()
    async def test_call_tool_sanitizes_output(self) -> None:
        server = _make_server()
        await server._execute_tool("resolve_query", {"target": "SELECT 1"})
        server._sanitizer.redact_output.assert_called_once()

    @pytest.mark.asyncio()
    async def test_call_tool_rate_limit_raises(self) -> None:
        server = _make_server()
        server._rate_limiter.check.side_effect = RateLimitError(
            "Too fast", code="RATE_SESSION_EXCEEDED", retry_after=5
        )
        with pytest.raises(RateLimitError):
            await server._execute_tool("resolve_query", {"target": "SELECT 1"})

    @pytest.mark.asyncio()
    async def test_call_tool_unknown_tool_raises(self) -> None:
        server = _make_server()
        with pytest.raises(ExecutionError) as exc_info:
            await server._execute_tool("nonexistent_tool", {"arg": "val"})
        assert exc_info.value.code == "EXEC_UNKNOWN_TOOL"

    @pytest.mark.asyncio()
    async def test_call_tool_safe_mode_rejects_online_tool(self) -> None:
        server = _make_server(safe_mode=True)
        with pytest.raises(ExecutionError) as exc_info:
            await server._execute_tool("resolve_query", {"target": "SELECT 1"})
        assert exc_info.value.code == "EXEC_SAFE_MODE_RESTRICTED"

    @pytest.mark.asyncio()
    async def test_call_tool_no_registry_raises(self) -> None:
        server = _make_server(with_registry=False)
        with pytest.raises(ExecutionError) as exc_info:
            await server._execute_tool("resolve_query", {"target": "SELECT 1"})
        assert exc_info.value.code == "EXEC_NO_REGISTRY"

    @pytest.mark.asyncio()
    async def test_call_tool_returns_mcp_response(self) -> None:
        server = _make_server()
        result_json = await server._execute_tool(
            "resolve_query", {"target": "SELECT 1"}
        )
        result = json.loads(result_json)
        assert "status" in result
        assert "workspace_id_used" in result
        assert "data" in result
        assert "duration_ms" in result
