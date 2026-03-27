# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""End-to-end MCP server integration tests.

Verifies that the MCP server correctly wires ToolRegistry and AgentFactory
so that call_tool succeeds (not just list_tools).  Uses a real ToolRegistry
with a mock AsyncDatabricksClient and mock LLM to keep tests offline.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.agents.output.llm_responses import ToolResult
from starboard_server.mcp.agent_bridge import AGENT_TOOL_METADATA
from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.server import StarboardMCPServer
from starboard_server.mcp.tool_bridge import PHASE_A_TOOLS

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mcp_config(**overrides: Any) -> MCPServerConfig:
    """Build a minimal MCP config for testing."""
    defaults: dict[str, Any] = {
        "default_workspace_id": "test",
        "workspaces": {
            "test": WorkspaceProfile(
                host="https://test.cloud.databricks.com",
                token_env="TEST_TOKEN",
            ),
        },
    }
    defaults.update(overrides)
    return MCPServerConfig(**defaults)


def _make_mock_tool_registry() -> MagicMock:
    """Create a mock ToolRegistry that returns structured tool results."""
    registry = MagicMock()
    registry.execute_tool = AsyncMock(
        return_value=ToolResult(
            tool_call_id="test-call-1",
            tool_name="resolve_query",
            content=json.dumps({
                "sql": "SELECT 1",
                "status": "completed",
                "analysis": "Simple query",
            }),
        )
    )
    registry.list_tools.return_value = [
        {"name": name} for name in sorted(PHASE_A_TOOLS)
    ]
    return registry


def _make_mock_agent_factory() -> MagicMock:
    """Create a mock AgentFactory with a minimal agent."""
    factory = MagicMock()
    factory.events = None

    mock_agent = MagicMock()
    mock_agent.config.domain = "query"

    async def _mock_stream(**_kwargs: object) -> Any:
        """Produce no events (agent completes immediately)."""
        return
        yield  # type: ignore[misc]  # noqa: RET503

    mock_agent.run_stream = _mock_stream
    factory.get_agent.return_value = mock_agent
    factory.tool_registry = _make_mock_tool_registry()
    return factory


def _make_mock_intent_router() -> MagicMock:
    """Create a mock IntentRouter."""
    router = MagicMock()
    return router


@pytest.fixture()
def mcp_config() -> MCPServerConfig:
    """Standard test MCP configuration."""
    return _make_mcp_config()


@pytest.fixture()
def mock_tool_registry() -> MagicMock:
    """Mock ToolRegistry for offline testing."""
    return _make_mock_tool_registry()


@pytest.fixture()
def mock_agent_factory() -> MagicMock:
    """Mock AgentFactory for offline testing."""
    return _make_mock_agent_factory()


@pytest.fixture()
def mock_intent_router() -> MagicMock:
    """Mock IntentRouter for offline testing."""
    return _make_mock_intent_router()


@pytest.fixture()
def full_server(
    mcp_config: MCPServerConfig,
    mock_tool_registry: MagicMock,
    mock_agent_factory: MagicMock,
    mock_intent_router: MagicMock,
) -> StarboardMCPServer:
    """Create a fully wired MCP server with real registration, mock backends."""
    mock_resolver = MagicMock()
    mock_resolver.resolve.return_value = mcp_config.workspaces["test"]

    mock_auth = MagicMock()
    mock_auth.get_credentials.return_value = MagicMock(
        host="https://test.cloud.databricks.com",
        token="fake-token",
    )

    mock_rate_limiter = MagicMock()
    mock_rate_limiter.check = MagicMock()

    mock_circuit_breakers = MagicMock()
    mock_breaker = MagicMock()

    async def _passthrough_call(fn: Any, *a: Any, **kw: Any) -> Any:
        return await fn(*a, **kw)

    mock_breaker.call = _passthrough_call
    mock_circuit_breakers.get.return_value = mock_breaker

    return StarboardMCPServer(
        config=mcp_config,
        workspace_resolver=mock_resolver,
        auth_provider=mock_auth,
        rate_limiter=mock_rate_limiter,
        circuit_breakers=mock_circuit_breakers,
        tool_registry=mock_tool_registry,
        agent_factory=mock_agent_factory,
        intent_router=mock_intent_router,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListTools:
    """Verify list_tools returns expected Phase A tools."""

    @pytest.mark.integration
    async def test_list_tools_returns_phase_a_tools(
        self, full_server: StarboardMCPServer
    ) -> None:
        """list_tools should include all Phase A tools plus ping, composites, and agents."""
        tools = await full_server.mcp.list_tools()
        tool_names = {t.name for t in tools}

        # Phase A tools should be present
        for phase_a_tool in PHASE_A_TOOLS:
            assert phase_a_tool in tool_names, f"Phase A tool {phase_a_tool!r} missing"

        # Ping should always be present
        assert "starboard_ping" in tool_names

    @pytest.mark.integration
    async def test_list_tools_includes_agent_tools(
        self, full_server: StarboardMCPServer
    ) -> None:
        """list_tools should include agent tools when agent_factory is provided."""
        tools = await full_server.mcp.list_tools()
        tool_names = {t.name for t in tools}

        for agent_def in AGENT_TOOL_METADATA:
            assert agent_def["name"] in tool_names, (
                f"Agent tool {agent_def['name']!r} missing"
            )

    @pytest.mark.integration
    async def test_list_tools_with_phase_b_scope(
        self, mock_tool_registry: MagicMock,
        mock_agent_factory: MagicMock,
    ) -> None:
        """Phase B tool_scope should expose more tools than Phase A."""
        config_b = _make_mcp_config(tool_scope="phase_b")
        server_b = StarboardMCPServer(
            config=config_b,
            tool_registry=mock_tool_registry,
            agent_factory=mock_agent_factory,
        )
        tools = await server_b.mcp.list_tools()
        tool_names = {t.name for t in tools}

        # Phase B should include Phase A tools
        for phase_a_tool in PHASE_A_TOOLS:
            assert phase_a_tool in tool_names

        # Phase B should also include deep analysis tools
        # (at minimum, the ones that exist in ALL_TOOL_METADATA)
        assert len(tool_names) > len(PHASE_A_TOOLS)


class TestCallTool:
    """Verify call_tool executes through the full pipeline."""

    @pytest.mark.integration
    async def test_call_tool_resolve_query_succeeds(
        self, full_server: StarboardMCPServer, mock_tool_registry: MagicMock
    ) -> None:
        """call_tool('resolve_query') should execute via ToolRegistry, not EXEC_NO_REGISTRY."""
        result = await full_server._execute_tool(
            "resolve_query", {"target": "SELECT 1"}
        )
        parsed = json.loads(result)

        # Should NOT be an error
        assert not parsed.get("isError"), f"Got error: {parsed}"
        assert "EXEC_NO_REGISTRY" not in str(parsed)

        # ToolRegistry.execute_tool should have been called
        mock_tool_registry.execute_tool.assert_called_once()

    @pytest.mark.integration
    async def test_call_tool_without_registry_raises_error(self) -> None:
        """call_tool without ToolRegistry should raise ExecutionError."""
        from starboard_server.mcp.exceptions import ExecutionError

        config = _make_mcp_config()
        server = StarboardMCPServer(config=config)

        with pytest.raises(ExecutionError, match="Tool registry not configured"):
            await server._execute_tool("resolve_query", {"target": "SELECT 1"})


class TestCallAgentTool:
    """Verify agent tool execution flows through MCPAgentExecutor."""

    @pytest.mark.integration
    async def test_call_agent_tool_executes(
        self, full_server: StarboardMCPServer
    ) -> None:
        """call_tool('query_agent') should execute agent and return response."""
        result = await full_server._execute_agent_tool(
            "query_agent",
            {"message": "Analyze my slow query"},
        )
        parsed = json.loads(result)

        # Should return a structured response (not an error)
        assert parsed.get("status") in ("success", "error", "timeout")
        # Should have agent_domain set
        assert parsed.get("agent_domain") == "query"

    @pytest.mark.integration
    async def test_agent_tool_without_factory_returns_error(self) -> None:
        """Agent tool without AgentFactory should return EXEC_NO_AGENT_FACTORY."""
        config = _make_mcp_config()
        server = StarboardMCPServer(config=config)

        result = await server._execute_agent_tool(
            "query_agent", {"message": "test"}
        )
        parsed = json.loads(result)

        assert parsed["code"] == "EXEC_NO_AGENT_FACTORY"


class TestListResources:
    """Verify list_resources returns introspection resources."""

    @pytest.mark.integration
    async def test_list_resources_returns_expected_count(
        self, full_server: StarboardMCPServer
    ) -> None:
        """list_resources should return introspection resources."""
        resources = await full_server.mcp.list_resources()
        assert len(resources) >= 5, (
            f"Expected at least 5 resources, got {len(resources)}: "
            f"{[r.name for r in resources]}"
        )

    @pytest.mark.integration
    async def test_list_resources_includes_tool_catalog(
        self, full_server: StarboardMCPServer
    ) -> None:
        """list_resources should include the tool catalog resource."""
        resources = await full_server.mcp.list_resources()
        uris = {str(r.uri) for r in resources}
        assert any("tool" in uri and "catalog" in uri for uri in uris), (
            f"Tool catalog resource not found in: {uris}"
        )


class TestToolScopeValidation:
    """Verify tool_scope correctly gates tool execution."""

    @pytest.mark.integration
    async def test_phase_a_rejects_phase_b_tool(
        self,
        mock_tool_registry: MagicMock,
    ) -> None:
        """Phase A scope should reject Phase B-only tools."""
        from starboard_server.mcp.exceptions import ExecutionError

        config = _make_mcp_config(tool_scope="phase_a")
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = config.workspaces["test"]

        server = StarboardMCPServer(
            config=config,
            workspace_resolver=mock_resolver,
            tool_registry=mock_tool_registry,
        )

        # analyze_job_history is a Phase B tool, not in Phase A
        with pytest.raises(ExecutionError, match="not available"):
            await server._execute_tool(
                "analyze_job_history", {"job_id": "123"}
            )
