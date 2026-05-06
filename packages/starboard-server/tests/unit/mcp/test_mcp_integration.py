# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Integration tests for StarboardMCPServer — full pipeline wiring.

These tests verify that the MCP server correctly wires tools, agent tools,
prompts, and the execution pipeline using real internal components with
mocked external dependencies (ToolRegistry, AgentFactory).
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from starboard_server.mcp.agent_bridge import (
    AGENT_DOMAINS,
    AGENT_TOOL_METADATA,
    _MCP_EXCLUDED_AGENT_DOMAINS,
)
from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.prompt_bridge import PROMPT_METADATA
from starboard_server.mcp.server import StarboardMCPServer


@pytest.fixture()
def mcp_config() -> MCPServerConfig:
    return MCPServerConfig(
        default_workspace_id="ws-test",
        workspaces={
            "ws-test": WorkspaceProfile(
                host="https://test.databricks.com",
                token_env="TEST_TOKEN",
            ),
        },
    )


@pytest.fixture()
def mock_agent_factory() -> MagicMock:
    """Create a mock AgentFactory with a minimal agent."""
    factory = MagicMock()
    factory.events = None

    mock_agent = MagicMock()
    mock_agent.config.domain = "query"

    async def _empty_stream(**_kwargs: object) -> Any:
        return
        yield  # type: ignore[misc]  # noqa: RET503

    mock_agent.run_stream = _empty_stream
    factory.get_agent.return_value = mock_agent
    return factory


@pytest.fixture()
def server_with_agents(
    mcp_config: MCPServerConfig,
    mock_agent_factory: MagicMock,
) -> StarboardMCPServer:
    """Create a server with agent tools enabled."""
    return StarboardMCPServer(
        config=mcp_config,
        agent_factory=mock_agent_factory,
    )


@pytest.fixture()
def server_minimal(mcp_config: MCPServerConfig) -> StarboardMCPServer:
    """Create a minimal server without agent tools."""
    return StarboardMCPServer(config=mcp_config)


class TestServerToolRegistration:
    """Integration: verify all tool types are registered on the FastMCP instance."""

    async def test_ping_tool_registered(
        self, server_minimal: StarboardMCPServer
    ) -> None:
        tools = await server_minimal.mcp.list_tools()
        names = {t.name for t in tools}
        assert "starboard_ping" in names

    async def test_phase_a_tools_registered(
        self, server_minimal: StarboardMCPServer
    ) -> None:
        from starboard_server.mcp.tool_bridge import PHASE_A_TOOLS

        tools = await server_minimal.mcp.list_tools()
        names = {t.name for t in tools}
        for tool_name in PHASE_A_TOOLS:
            assert tool_name in names, f"Phase A tool {tool_name!r} not registered"

    async def test_agent_tools_not_registered_without_factory(
        self, server_minimal: StarboardMCPServer
    ) -> None:
        tools = await server_minimal.mcp.list_tools()
        names = {t.name for t in tools}
        assert "query_agent" not in names

    async def test_agent_tools_registered_with_factory(
        self, server_with_agents: StarboardMCPServer
    ) -> None:
        tools = await server_with_agents.mcp.list_tools()
        names = {t.name for t in tools}
        for domain in AGENT_DOMAINS:
            if domain in _MCP_EXCLUDED_AGENT_DOMAINS:
                assert f"{domain}_agent" not in names, (
                    f"Excluded agent tool '{domain}_agent' should not be registered"
                )
            else:
                assert f"{domain}_agent" in names, (
                    f"Agent tool '{domain}_agent' not registered"
                )

    async def test_total_tool_count_with_agents(
        self, server_with_agents: StarboardMCPServer
    ) -> None:
        from starboard_server.mcp.tool_bridge import PHASE_A_TOOLS

        tools = await server_with_agents.mcp.list_tools()
        # ping + Phase A + MCP-exposed agent tools (excludes discovery)
        expected_min = 1 + len(PHASE_A_TOOLS) + len(AGENT_TOOL_METADATA)
        assert len(tools) >= expected_min


class TestServerPromptRegistration:
    """Integration: verify prompts are registered and callable."""

    async def test_prompts_registered(self, server_minimal: StarboardMCPServer) -> None:
        prompts = await server_minimal.mcp.list_prompts()
        names = {p.name for p in prompts}
        for prompt_def in PROMPT_METADATA:
            assert prompt_def["name"] in names, (
                f"Prompt {prompt_def['name']!r} not registered"
            )

    async def test_prompt_count(self, server_minimal: StarboardMCPServer) -> None:
        prompts = await server_minimal.mcp.list_prompts()
        assert len(prompts) >= 8

    @patch("starboard_server.prompts.factories.get_system_prompt")
    async def test_prompt_returns_messages(
        self,
        mock_get: MagicMock,
        server_minimal: StarboardMCPServer,
    ) -> None:
        mock_get.return_value = "You are the query agent."
        result = await server_minimal.mcp.get_prompt(
            "query_agent_prompt",
            arguments={"goal": "optimize", "workspace_id": "ws-1"},
        )
        assert result is not None
        assert len(result.messages) >= 1


class TestAgentToolExecution:
    """Integration: agent tool execution via _execute_agent_tool pipeline."""

    async def test_agent_tool_returns_json(
        self, server_with_agents: StarboardMCPServer
    ) -> None:
        result_json = await server_with_agents._execute_agent_tool(
            "query_agent",
            {"message": "Analyze my query"},
        )
        data = json.loads(result_json)
        assert "status" in data
        assert data["agent_domain"] == "query"
        assert data["workspace_id_used"] == "ws-test"

    async def test_agent_tool_includes_conversation_id(
        self, server_with_agents: StarboardMCPServer
    ) -> None:
        result_json = await server_with_agents._execute_agent_tool(
            "query_agent",
            {"message": "test", "conversation_id": "my-conv-123"},
        )
        data = json.loads(result_json)
        assert data["mcp_metadata"]["conversation_id"] == "my-conv-123"

    async def test_agent_tool_auto_generates_conversation_id(
        self, server_with_agents: StarboardMCPServer
    ) -> None:
        result_json = await server_with_agents._execute_agent_tool(
            "query_agent",
            {"message": "test"},
        )
        data = json.loads(result_json)
        assert data["mcp_metadata"]["conversation_id"].startswith("mcp-conv-")

    async def test_agent_tool_uses_default_workspace(
        self, server_with_agents: StarboardMCPServer
    ) -> None:
        result_json = await server_with_agents._execute_agent_tool(
            "query_agent",
            {"message": "test"},
        )
        data = json.loads(result_json)
        assert data["workspace_id_used"] == "ws-test"

    async def test_agent_tool_with_workspace_override(
        self, server_with_agents: StarboardMCPServer
    ) -> None:
        result_json = await server_with_agents._execute_agent_tool(
            "query_agent",
            {"message": "test", "workspace_id": "ws-override"},
        )
        data = json.loads(result_json)
        assert data["workspace_id_used"] == "ws-override"


class TestAgentToolErrorPaths:
    """Integration: error propagation through the agent tool pipeline."""

    async def test_unknown_agent_tool_returns_error(
        self, server_with_agents: StarboardMCPServer
    ) -> None:
        # Register a fake tool that routes through _execute_agent_tool
        # but with an unknown name
        result_json = await server_with_agents._execute_agent_tool(
            "nonexistent_agent", {"message": "test"}
        )
        data = json.loads(result_json)
        assert data["code"] == "EXEC_UNKNOWN_AGENT"

    async def test_no_agent_factory_returns_error(
        self, server_minimal: StarboardMCPServer
    ) -> None:
        result_json = await server_minimal._execute_agent_tool(
            "query_agent", {"message": "test"}
        )
        data = json.loads(result_json)
        assert data["code"] == "EXEC_NO_AGENT_FACTORY"


class TestServerProperties:
    """Integration: verify server properties are wired correctly."""

    def test_agent_executor_none_without_factory(
        self, server_minimal: StarboardMCPServer
    ) -> None:
        assert server_minimal.agent_executor is None

    def test_agent_executor_created_with_factory(
        self, server_with_agents: StarboardMCPServer
    ) -> None:
        assert server_with_agents.agent_executor is not None

    def test_config_accessible(self, server_minimal: StarboardMCPServer) -> None:
        assert server_minimal.config.default_workspace_id == "ws-test"

    def test_sanitizer_applied_when_set(
        self,
        mcp_config: MCPServerConfig,
        mock_agent_factory: MagicMock,
    ) -> None:
        sanitizer = MagicMock()
        sanitizer.redact_output.side_effect = lambda x: x
        server = StarboardMCPServer(
            config=mcp_config,
            agent_factory=mock_agent_factory,
            sanitizer=sanitizer,
        )
        assert server.sanitizer is sanitizer
