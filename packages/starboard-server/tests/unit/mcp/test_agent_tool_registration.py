# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for agent tool registration in StarboardMCPServer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starboard_server.mcp.agent_bridge import AGENT_TOOL_METADATA
from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.models import MCPAgentResponse, MCPResponseMetadata
from starboard_server.mcp.server import StarboardMCPServer


def _make_config() -> MCPServerConfig:
    return MCPServerConfig(
        default_workspace_id="prod",
        workspaces={
            "prod": WorkspaceProfile(
                host="https://prod.databricks.com",
                token_env="PROD_TOKEN",
            ),
        },
    )


class TestAgentToolRegistration:
    """Tests for agent tool registration in StarboardMCPServer."""

    def test_agent_tools_registered_when_factory_provided(self) -> None:
        factory = MagicMock()
        factory.events = None
        server = StarboardMCPServer(
            config=_make_config(),
            agent_factory=factory,
        )
        assert server.agent_executor is not None
        # Agent tools should be registered in FastMCP
        tool_names = [t.name for t in server.mcp._tool_manager.list_tools()]
        for tool_def in AGENT_TOOL_METADATA:
            assert tool_def["name"] in tool_names

    def test_agent_tools_skipped_when_no_factory(self) -> None:
        server = StarboardMCPServer(config=_make_config())
        assert server.agent_executor is None

    def test_agent_executor_uses_config_timeout(self) -> None:
        config = MCPServerConfig(
            default_workspace_id="prod",
            workspaces={
                "prod": WorkspaceProfile(
                    host="https://prod.databricks.com",
                    token_env="PROD_TOKEN",
                ),
            },
            agent_timeout=60,
        )
        factory = MagicMock()
        factory.events = None
        server = StarboardMCPServer(config=config, agent_factory=factory)
        assert server.agent_executor is not None
        assert server.agent_executor._default_timeout == 60


class TestExecuteAgentTool:
    """Tests for _execute_agent_tool pipeline."""

    @pytest.mark.asyncio
    async def test_execute_agent_tool_returns_json(self) -> None:
        factory = MagicMock()
        factory.events = None
        server = StarboardMCPServer(config=_make_config(), agent_factory=factory)

        mock_response = MCPAgentResponse(
            status="success",
            workspace_id_used="prod",
            agent_domain="query",
            response_text="Done",
            mcp_metadata=MCPResponseMetadata(
                workspace_id_used="prod",
                domain_selected="query",
                confidence=1.0,
            ),
        )

        with patch.object(
            server._agent_executor, "execute", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = mock_response

            result = await server._execute_agent_tool(
                "query_agent", {"message": "Test query"}
            )

        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["agent_domain"] == "query"

    @pytest.mark.asyncio
    async def test_execute_agent_tool_unknown_returns_error(self) -> None:
        factory = MagicMock()
        factory.events = None
        server = StarboardMCPServer(config=_make_config(), agent_factory=factory)

        result = await server._execute_agent_tool(
            "nonexistent_agent", {"message": "test"}
        )

        parsed = json.loads(result)
        assert parsed["code"] == "EXEC_UNKNOWN_AGENT"

    @pytest.mark.asyncio
    async def test_execute_agent_tool_no_executor_returns_error(self) -> None:
        server = StarboardMCPServer(config=_make_config())

        result = await server._execute_agent_tool("query_agent", {"message": "test"})

        parsed = json.loads(result)
        assert parsed["code"] == "EXEC_NO_AGENT_FACTORY"

    @pytest.mark.asyncio
    async def test_execute_agent_tool_uses_default_workspace(self) -> None:
        factory = MagicMock()
        factory.events = None
        server = StarboardMCPServer(config=_make_config(), agent_factory=factory)

        mock_response = MCPAgentResponse(
            status="success",
            workspace_id_used="prod",
            agent_domain="job",
            response_text="ok",
        )

        with patch.object(
            server._agent_executor, "execute", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = mock_response

            await server._execute_agent_tool("job_agent", {"message": "Check job"})

            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["workspace_id"] == "prod"
            assert call_kwargs["domain"] == "job"

    @pytest.mark.asyncio
    async def test_execute_agent_tool_sanitizes_output(self) -> None:
        factory = MagicMock()
        factory.events = None
        sanitizer = MagicMock()
        sanitizer.redact_output = MagicMock(
            side_effect=lambda d: {**d, "response_text": "[REDACTED]"}
        )

        server = StarboardMCPServer(
            config=_make_config(),
            agent_factory=factory,
            sanitizer=sanitizer,
        )

        mock_response = MCPAgentResponse(
            status="success",
            workspace_id_used="prod",
            agent_domain="query",
            response_text="user@example.com has a slow query",
        )

        with patch.object(
            server._agent_executor, "execute", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = mock_response

            result = await server._execute_agent_tool(
                "query_agent", {"message": "test"}
            )

        parsed = json.loads(result)
        assert parsed["response_text"] == "[REDACTED]"
        sanitizer.redact_output.assert_called_once()
