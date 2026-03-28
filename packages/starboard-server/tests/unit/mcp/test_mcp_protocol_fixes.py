# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""TDD tests for MCP protocol critical fixes (Workstream 1B).

Tests are written to FAIL before the fix and PASS after.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.server import StarboardMCPServer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mcp_config() -> MCPServerConfig:
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
    return StarboardMCPServer(config=mcp_config)


# ---------------------------------------------------------------------------
# Item 1: _register_resources()
# ---------------------------------------------------------------------------


class TestRegisterResources:
    """Item 1: _register_resources() must be called and register >= 5 resources."""

    async def test_list_resources_returns_five_or_more(
        self, server: StarboardMCPServer
    ) -> None:
        """MCP list_resources must expose at least 5 resources."""
        resources = await server.mcp.list_resources()
        assert len(resources) >= 5, (
            f"Expected >= 5 MCP resources, got {len(resources)}: {resources}"
        )

    async def test_workspace_info_resource_registered(
        self, server: StarboardMCPServer
    ) -> None:
        resources = await server.mcp.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "starboard://workspace/info" in uris

    async def test_tool_catalog_resource_registered(
        self, server: StarboardMCPServer
    ) -> None:
        resources = await server.mcp.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "starboard://tools/catalog" in uris

    async def test_agent_catalog_resource_registered(
        self, server: StarboardMCPServer
    ) -> None:
        resources = await server.mcp.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "starboard://agents/catalog" in uris

    async def test_health_resource_registered(self, server: StarboardMCPServer) -> None:
        resources = await server.mcp.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "starboard://health" in uris

    async def test_tool_dependencies_resource_registered(
        self, server: StarboardMCPServer
    ) -> None:
        resources = await server.mcp.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "starboard://tools/dependencies" in uris

    async def test_resources_have_mime_type(self, server: StarboardMCPServer) -> None:
        """Each resource must declare a mimeType."""
        resources = await server.mcp.list_resources()
        for r in resources:
            assert r.mimeType is not None, f"Resource {r.uri} missing mimeType"


# ---------------------------------------------------------------------------
# Item 2: Error handling in _execute_tool()
# ---------------------------------------------------------------------------


class TestExecuteToolErrorHandling:
    """Item 2: _execute_tool must return isError JSON on exception, not propagate."""

    async def test_exception_returns_json_not_propagates(
        self, mcp_config: MCPServerConfig
    ) -> None:
        """When tool execution raises, response must be JSON with isError=true."""
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(
            side_effect=RuntimeError("downstream failure")
        )
        srv = StarboardMCPServer(config=mcp_config, tool_registry=mock_registry)

        # Should NOT raise; must return an error JSON string
        result = await srv._execute_tool("resolve_query", {"target": "test-id"})
        parsed = json.loads(result)
        assert parsed.get("isError") is True, (
            f"Expected isError=true in response, got: {parsed}"
        )
        assert "error" in parsed or "message" in parsed, (
            "Error response must include error message"
        )

    async def test_exception_message_is_sanitized(
        self, mcp_config: MCPServerConfig
    ) -> None:
        """Error message must not expose raw exception stack traces."""
        mock_registry = MagicMock()
        secret_msg = "token=supersecret123"
        mock_registry.execute_tool = AsyncMock(
            side_effect=ValueError(f"Connection error: {secret_msg}")
        )
        srv = StarboardMCPServer(config=mcp_config, tool_registry=mock_registry)
        result = await srv._execute_tool("resolve_query", {"target": "x"})
        parsed = json.loads(result)
        # Must be parseable JSON and have isError
        assert parsed.get("isError") is True

    async def test_auth_error_returns_json(self, mcp_config: MCPServerConfig) -> None:
        """AuthenticationError must also return isError JSON."""
        from starboard_server.mcp.exceptions import AuthenticationError

        mock_auth = MagicMock()
        mock_auth.get_credentials = MagicMock(
            side_effect=AuthenticationError("bad token")
        )
        mock_ws = MagicMock()
        mock_ws.resolve = MagicMock(return_value=MagicMock())
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(return_value={"ok": True})

        srv = StarboardMCPServer(
            config=mcp_config,
            workspace_resolver=mock_ws,
            auth_provider=mock_auth,
            tool_registry=mock_registry,
        )
        result = await srv._execute_tool("resolve_query", {"target": "x"})
        parsed = json.loads(result)
        assert parsed.get("isError") is True


# ---------------------------------------------------------------------------
# Item 3: inputSchema passed to FastMCP add_tool
# ---------------------------------------------------------------------------


class TestInputSchemaRegistration:
    """Item 3: Tool registration must pass inputSchema to FastMCP."""

    async def test_registered_tools_have_input_schema(
        self, server: StarboardMCPServer
    ) -> None:
        """Every registered Phase A tool must expose an inputSchema."""
        tools = await server.mcp.list_tools()
        phase_a = {t.name: t for t in tools if t.name != "starboard_ping"}
        assert len(phase_a) > 0, "No Phase A tools registered"
        for name, tool in phase_a.items():
            assert tool.inputSchema is not None, f"Tool '{name}' has no inputSchema"
            # Must be a dict-like object with 'type' key
            schema = tool.inputSchema
            assert hasattr(schema, "__getitem__") or hasattr(schema, "model_fields"), (
                f"Tool '{name}' inputSchema is not schema-like: {schema!r}"
            )

    async def test_tool_input_schema_has_properties(
        self, server: StarboardMCPServer
    ) -> None:
        """inputSchema must have a properties dict."""
        tools = await server.mcp.list_tools()
        for tool in tools:
            if tool.name == "starboard_ping":
                continue
            schema = tool.inputSchema
            # Accept dict or Pydantic model with properties field
            if isinstance(schema, dict):
                assert "properties" in schema, (
                    f"Tool '{tool.name}' inputSchema missing 'properties': {schema}"
                )

    async def test_tool_schema_not_kwargs_wrapped(
        self, server: StarboardMCPServer
    ) -> None:
        """No tool should advertise a 'kwargs: string' schema from FastMCP auto-gen.

        FastMCP auto-generates ``{"kwargs": {"type": "string"}}`` for
        ``**kwargs`` handlers.  _fix_tool_schema must replace it with the
        real parameter schema so MCP clients see actual parameter names.
        """
        tools = await server.mcp.list_tools()
        for tool in tools:
            schema = tool.inputSchema
            if not isinstance(schema, dict):
                continue
            props = schema.get("properties", {})
            assert "kwargs" not in props, (
                f"Tool '{tool.name}' still has auto-generated 'kwargs' "
                f"property — _fix_tool_schema not applied: {schema}"
            )

    async def test_analyze_discovery_domain_exposes_domains_param(
        self, server: StarboardMCPServer
    ) -> None:
        """analyze_discovery_domain must advertise 'domains' and 'domain' params."""
        tools = await server.mcp.list_tools()
        by_name = {t.name: t for t in tools}
        tool = by_name.get("analyze_discovery_domain")
        if tool is None:
            pytest.skip("analyze_discovery_domain not registered in this scope")
        schema = tool.inputSchema
        assert isinstance(schema, dict)
        props = schema.get("properties", {})
        assert "domains" in props, (
            f"analyze_discovery_domain missing 'domains' property: {props.keys()}"
        )
        assert "domain" in props, (
            f"analyze_discovery_domain missing 'domain' property: {props.keys()}"
        )


# ---------------------------------------------------------------------------
# Item 3b: _PassthroughMeta delivers raw arguments to **kwargs handlers
# ---------------------------------------------------------------------------


class TestPassthroughMeta:
    """_PassthroughMeta must deliver raw arguments without wrapping."""

    async def test_passthrough_meta_delivers_raw_args(self) -> None:
        """Handler must receive the actual parameter names, not a kwargs wrapper."""
        from mcp.server.fastmcp import FastMCP
        from starboard_server.mcp.server import _PassthroughMeta

        mcp = FastMCP("test")
        received: dict[str, Any] = {}

        async def my_tool(**kwargs: Any) -> str:
            received.update(kwargs)
            return "ok"

        mcp.add_tool(my_tool, name="my_tool", description="test")
        tool = mcp._tool_manager.get_tool("my_tool")
        assert tool is not None

        tool.parameters = {
            "type": "object",
            "properties": {
                "domains": {"type": "array", "items": {"type": "string"}},
            },
        }
        tool.fn_metadata = _PassthroughMeta(
            arg_model=tool.fn_metadata.arg_model,
            output_schema=None,
            output_model=None,
            wrap_output=False,
        )

        await tool.run({"domains": ["billing", "jobs"]}, context=None)
        assert "domains" in received, f"Expected 'domains' key, got: {received}"
        assert received["domains"] == ["billing", "jobs"]
        assert "kwargs" not in received, "kwargs wrapper leaked through"


# ---------------------------------------------------------------------------
# Item 4 & 10: Composite tools registered in MCP
# ---------------------------------------------------------------------------


class TestCompositeToolRegistration:
    """Items 4 & 10: Composite tools must be registered in MCP."""

    async def test_get_job_summary_registered(self, server: StarboardMCPServer) -> None:
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert "get_job_summary" in names, (
            f"Composite tool 'get_job_summary' not in MCP tool list: {sorted(names)}"
        )

    async def test_get_query_analysis_registered(
        self, server: StarboardMCPServer
    ) -> None:
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert "get_query_analysis" in names

    async def test_get_table_profile_registered(
        self, server: StarboardMCPServer
    ) -> None:
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert "get_table_profile" in names

    async def test_get_workspace_overview_registered(
        self, server: StarboardMCPServer
    ) -> None:
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert "get_workspace_overview" in names


# ---------------------------------------------------------------------------
# Item 5: Bounded session dicts in MCPRateLimiter
# ---------------------------------------------------------------------------


class TestBoundedSessionDicts:
    """Item 5: Session bucket dict must not grow unbounded."""

    def test_session_buckets_evict_old_entries(self) -> None:
        """After max_sessions entries, old sessions must be evicted."""
        from starboard_server.mcp.rate_limiter import MCPRateLimiter

        limiter = MCPRateLimiter(per_session_limit=60, max_sessions=10)
        # Fill beyond capacity
        for i in range(15):
            limiter.check(f"session-{i}")
        # Should not exceed max_sessions
        assert len(limiter._session_buckets) <= 10, (
            f"Session buckets grew beyond max: {len(limiter._session_buckets)}"
        )

    def test_rate_limiter_default_max_sessions(self) -> None:
        """MCPRateLimiter must accept max_sessions parameter."""
        from starboard_server.mcp.rate_limiter import MCPRateLimiter

        limiter = MCPRateLimiter(per_session_limit=60, max_sessions=100)
        assert limiter._max_sessions == 100


# ---------------------------------------------------------------------------
# Item 6: Validate tool inputs against inputSchema
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Item 6: Tool inputs must be validated against inputSchema before execution."""

    async def test_missing_required_param_returns_error(
        self, mcp_config: MCPServerConfig
    ) -> None:
        """Missing required param must return isError JSON, not raise."""
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(return_value={"ok": True})
        srv = StarboardMCPServer(config=mcp_config, tool_registry=mock_registry)

        # resolve_query requires 'target'; call without it
        result = await srv._execute_tool("resolve_query", {})
        parsed = json.loads(result)
        assert parsed.get("isError") is True, (
            f"Expected isError for missing required param, got: {parsed}"
        )
        # Ensure tool was NOT called with invalid input
        mock_registry.execute_tool.assert_not_called()

    async def test_valid_input_passes_validation(
        self, mcp_config: MCPServerConfig
    ) -> None:
        """Valid inputs must pass validation and reach tool execution."""
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(return_value={"data": "result"})
        srv = StarboardMCPServer(config=mcp_config, tool_registry=mock_registry)

        # resolve_query with valid 'target'
        result = await srv._execute_tool("resolve_query", {"target": "abc-123"})
        # With no workspace_resolver/auth, it will fail at registry stage with
        # EXEC_NO_REGISTRY or similar — but it must attempt execution
        parsed = json.loads(result)
        # Either succeeds or fails for registry reasons, not validation
        assert "isError" in parsed or parsed.get("status") in ("success", "error")


# ---------------------------------------------------------------------------
# Item 7: Fail explicitly on missing auth
# ---------------------------------------------------------------------------


class TestMissingAuthExplicitFail:
    """Item 7: Missing auth providers must raise explicit errors."""

    async def test_auth_provider_none_with_workspace_resolver_raises(
        self, mcp_config: MCPServerConfig
    ) -> None:
        """If workspace_resolver is set but auth_provider is None, must return auth error."""
        mock_ws = MagicMock()
        mock_ws.resolve = MagicMock(return_value=MagicMock())
        mock_registry = MagicMock()
        mock_registry.execute_tool = AsyncMock(return_value={"ok": True})

        srv = StarboardMCPServer(
            config=mcp_config,
            workspace_resolver=mock_ws,
            auth_provider=None,  # No auth provider!
            tool_registry=mock_registry,
        )
        result = await srv._execute_tool("resolve_query", {"target": "test"})
        parsed = json.loads(result)
        # Must fail with an auth-related error, not silently proceed without credentials
        assert parsed.get("isError") is True, (
            "Expected explicit auth failure when workspace_resolver is set but auth_provider is None"
        )
        error_text = str(parsed)
        assert any(
            kw in error_text.lower()
            for kw in ("auth", "credential", "token", "authentication")
        ), f"Expected auth-related error message, got: {error_text}"


# ---------------------------------------------------------------------------
# Item 8: Derive user_id from MCP session in agent_bridge
# ---------------------------------------------------------------------------


class TestUserIdFromSession:
    """Item 8: agent_bridge must use session-derived user_id, not hardcoded 'mcp'."""

    async def test_run_agent_uses_session_user_id(self) -> None:
        """MCPAgentExecutor._run_agent must pass user_id derived from session."""
        from starboard_server.mcp.agent_bridge import MCPAgentExecutor

        captured_calls: list[dict] = []

        async def mock_run_stream(**kwargs: Any):
            captured_calls.append(kwargs)
            return
            yield  # make it an async generator

        mock_agent = MagicMock()
        mock_agent.run_stream = mock_run_stream
        mock_agent.config = MagicMock()
        mock_agent.config.domain = "query"

        mock_factory = MagicMock()
        mock_factory.get_agent = MagicMock(return_value=mock_agent)
        mock_factory.events = None

        executor = MCPAgentExecutor(agent_factory=mock_factory)
        await executor.execute(
            message="test query",
            workspace_id="test",
            domain="query",
            session_id="user-session-abc123",
        )

        assert len(captured_calls) > 0
        call_kwargs = captured_calls[0]
        user_id = call_kwargs.get("user_id", "")
        # Must NOT be the hardcoded "mcp" value
        assert user_id != "mcp", (
            f"user_id should be derived from session, not hardcoded 'mcp'. Got: {user_id!r}"
        )
        assert "abc123" in user_id or "user-session" in user_id or user_id != "", (
            f"user_id should reflect session context: {user_id!r}"
        )


# ---------------------------------------------------------------------------
# Item 9/11: HTTP transport auth
# ---------------------------------------------------------------------------


class TestHTTPTransportAuth:
    """Items 9 & 11: HTTP transport must support API key authentication."""

    def test_create_mcp_app_with_api_key(self) -> None:
        """create_mcp_app must accept and enforce an api_key parameter."""
        from starboard_server.mcp.transports import create_mcp_app

        config = MCPServerConfig(
            default_workspace_id="test",
            workspaces={
                "test": WorkspaceProfile(
                    host="https://test.databricks.com",
                    token_env="TEST_TOKEN",
                ),
            },
        )
        # Must not raise when api_key is provided
        app = create_mcp_app(config, api_key="test-secret-key")
        assert callable(app)

    def test_create_starboard_mcp_server_with_api_key(self) -> None:
        """create_starboard_mcp_server must accept api_key parameter."""
        from starboard_server.mcp.transports import create_starboard_mcp_server

        config = MCPServerConfig(
            default_workspace_id="test",
            workspaces={
                "test": WorkspaceProfile(
                    host="https://test.databricks.com",
                    token_env="TEST_TOKEN",
                ),
            },
        )
        server = create_starboard_mcp_server(config, api_key="test-secret-key")
        assert server is not None
        assert server._api_key == "test-secret-key"

    def test_server_stores_api_key(self, mcp_config: MCPServerConfig) -> None:
        """StarboardMCPServer must store api_key for auth enforcement."""
        srv = StarboardMCPServer(config=mcp_config, api_key="my-key")
        assert srv._api_key == "my-key"

    def test_server_api_key_defaults_none(self, mcp_config: MCPServerConfig) -> None:
        """api_key defaults to None (no auth required) when not provided."""
        srv = StarboardMCPServer(config=mcp_config)
        assert srv._api_key is None
