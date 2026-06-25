# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""MCP transport adapters for stdio and Streamable HTTP.

Provides factory functions that create and run the MCP server with
different transports:

- **stdio**: For local CLI integration (Claude Desktop, Cursor, etc.)
- **Streamable HTTP (ASGI)**: For embedding in a FastAPI application
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from starboard_server.infra.core.config import get_config
from starboard_server.infra.observability.logging import get_logger
from starboard_server.mcp.auth_context import EnvTokenAuthProvider
from starboard_server.mcp.circuit_breaker_registry import MCPCircuitBreakerRegistry
from starboard_server.mcp.config import MCPServerConfig
from starboard_server.mcp.rate_limiter import MCPRateLimiter
from starboard_server.mcp.sanitizer import MCPSanitizer
from starboard_server.mcp.server import StarboardMCPServer
from starboard_server.mcp.workspace_registry import DefaultWorkspaceRegistry

if TYPE_CHECKING:
    from starboard_server.agents.agent_factory import AgentFactory
    from starboard_server.agents.routing.intent_router import IntentRouter
    from starboard_server.agents.tools.tool_registry import ToolRegistry

logger = get_logger(__name__)


def create_starboard_mcp_server(
    config: MCPServerConfig,
    api_key: str | None = None,
) -> StarboardMCPServer:
    """Create a fully configured ``StarboardMCPServer`` with all dependencies.

    Args:
        config: Validated MCP server configuration.
        api_key: Optional API key for HTTP transport authentication.
            When set, all HTTP requests must supply this key via the
            ``Authorization: Bearer <api_key>`` header.

    Returns:
        Configured server instance ready to serve via any transport.
    """
    workspace_resolver = DefaultWorkspaceRegistry(config)
    auth_provider = EnvTokenAuthProvider()
    rate_limiter = MCPRateLimiter(
        per_session_limit=config.rate_limit_per_minute,
    )
    circuit_breakers = MCPCircuitBreakerRegistry()

    env_cfg = get_config()
    sanitizer = MCPSanitizer() if env_cfg.enable_pii_redaction else None

    return StarboardMCPServer(
        config=config,
        workspace_resolver=workspace_resolver,
        auth_provider=auth_provider,
        rate_limiter=rate_limiter,
        sanitizer=sanitizer,
        circuit_breakers=circuit_breakers,
        api_key=api_key,
    )


async def bootstrap_mcp_server(
    config: MCPServerConfig,
    api_key: str | None = None,
) -> StarboardMCPServer:
    """Create a fully bootstrapped MCP server with working tool execution.

    Initializes ``AsyncDatabricksClient``, ``SharedContextProvider``,
    ``ToolRegistry``, ``AgentFactory``, and ``IntentRouter`` — then
    injects them alongside MCP cross-cutting concerns into the server.

    This is the **production** factory.  Use
    ``create_starboard_mcp_server()`` when you need a lightweight
    instance and will inject your own dependencies (e.g. in tests).

    Args:
        config: Validated MCP server configuration.
        api_key: Optional API key for HTTP transport authentication.

    Returns:
        Configured server with tool and agent execution capability.
    """
    from starboard_server.adapters.databricks import AsyncDatabricksClient
    from starboard_server.adapters.llm import create_llm_client
    from starboard_server.agents.agent_factory import AgentFactory as _AgentFactory
    from starboard_server.agents.config.agent_config import AgentConfig
    from starboard_server.agents.routing.intent_router import (
        IntentRouter as _IntentRouter,
    )
    from starboard_server.agents.tools.tool_factory import create_tool_registry
    from starboard_server.services.context.provider import SharedContextProvider

    env_cfg = get_config()

    # --- Databricks client from default workspace profile ---------------
    # NOTE: Uses _initialize() directly (not context manager) to match the
    # existing pattern in dependencies.py and main.py.  The client lives for
    # the lifetime of the MCP server process, so cleanup happens at exit.
    api = AsyncDatabricksClient(cfg=env_cfg)
    await api._initialize()  # noqa: SLF001 - follows codebase convention

    # --- Shared context provider ----------------------------------------
    provider = SharedContextProvider(api)

    # --- LLM client -----------------------------------------------------
    llm_client = create_llm_client(cfg=env_cfg)

    # --- Tool registry --------------------------------------------------
    tool_registry, _ = create_tool_registry(
        api=api,
        provider=provider,
        llm_client=llm_client,
    )

    # --- Agent factory --------------------------------------------------
    base_agent_config = AgentConfig(
        model=env_cfg.llm_model,
        max_tokens=env_cfg.llm_max_tokens,
        temperature=env_cfg.llm_temperature,
        domain_model_overrides=env_cfg.domain_model_overrides or {},
        domain_temperature_overrides=env_cfg.domain_temperature_overrides or {},
    )
    agent_factory = _AgentFactory(
        llm_client=llm_client,
        tool_registry=tool_registry,
        base_config=base_agent_config,
    )

    # --- Intent router --------------------------------------------------
    intent_router = _IntentRouter(
        llm_client=llm_client,
        disabled_domains=env_cfg.disabled_agent_domains,
    )

    # --- MCP cross-cutting concerns -------------------------------------
    workspace_resolver = DefaultWorkspaceRegistry(config)
    auth_provider = EnvTokenAuthProvider()
    rate_limiter = MCPRateLimiter(
        per_session_limit=config.rate_limit_per_minute,
    )
    circuit_breakers = MCPCircuitBreakerRegistry()
    sanitizer = MCPSanitizer() if env_cfg.enable_pii_redaction else None

    server = StarboardMCPServer(
        config=config,
        workspace_resolver=workspace_resolver,
        auth_provider=auth_provider,
        rate_limiter=rate_limiter,
        sanitizer=sanitizer,
        circuit_breakers=circuit_breakers,
        tool_registry=tool_registry,
        agent_factory=agent_factory,
        intent_router=intent_router,
        api_key=api_key,
    )

    logger.info(
        "mcp_server_bootstrapped",
        default_workspace=config.default_workspace_id,
        tool_count=len(tool_registry.list_tools()),
        agent_tools_enabled=True,
    )

    return server


async def run_stdio_server(
    config: MCPServerConfig,
    *,
    bootstrap: bool = True,
) -> None:
    """Run the MCP server with stdio transport.

    This blocks until the stdio connection is closed (typically when the
    client process exits).

    Args:
        config: Validated MCP server configuration.
        bootstrap: When ``True`` (default), use ``bootstrap_mcp_server``
            for full tool/agent execution.  ``False`` creates a
            lightweight server (useful for tests).
    """
    if bootstrap:
        server = await bootstrap_mcp_server(config)
    else:
        server = create_starboard_mcp_server(config)
    logger.info("mcp_stdio_starting", bootstrap=bootstrap)
    await server.mcp.run_stdio_async()


def create_stdio_server(
    config: MCPServerConfig,
    *,
    bootstrap: bool = True,
) -> None:
    """Run the MCP server with stdio transport (sync entry point).

    Args:
        config: Validated MCP server configuration.
        bootstrap: When ``True`` (default), use ``bootstrap_mcp_server``
            for full tool/agent execution.
    """
    asyncio.run(run_stdio_server(config, bootstrap=bootstrap))


def create_mcp_app(
    config: MCPServerConfig,
    api_key: str | None = None,
    *,
    tool_registry: ToolRegistry | None = None,
    agent_factory: AgentFactory | None = None,
    intent_router: IntentRouter | None = None,
) -> Any:
    """Create an ASGI app for Streamable HTTP transport.

    The returned app can be mounted into a FastAPI application::

        mcp_app = create_mcp_app(config)
        fastapi_app.mount("/mcp", mcp_app)

    When ``tool_registry``, ``agent_factory``, and ``intent_router`` are
    provided (e.g. from the FastAPI lifespan container) they are forwarded
    to the server so that ``call_tool`` and agent tools work without the
    ``EXEC_NO_REGISTRY`` error.

    When ``api_key`` is provided, the ASGI app is wrapped with a lightweight
    authentication middleware that validates the ``Authorization: Bearer``
    header on every incoming request.

    Args:
        config: Validated MCP server configuration.
        api_key: Optional API key for HTTP transport authentication.
        tool_registry: Optional pre-built tool registry.
        agent_factory: Optional pre-built agent factory.
        intent_router: Optional pre-built intent router.

    Returns:
        ASGI application suitable for mounting in FastAPI.
    """
    server = create_starboard_mcp_server(config, api_key=api_key)

    # If pre-built dependencies are provided, inject them via public API
    if tool_registry is not None or agent_factory is not None or intent_router is not None:
        server.inject_runtime_deps(
            tool_registry=tool_registry,
            agent_factory=agent_factory,
            intent_router=intent_router,
        )

    base_app = server.mcp.streamable_http_app()

    if api_key:
        base_app = _wrap_with_api_key_auth(base_app, api_key)
        logger.info("mcp_http_app_created", auth="api_key")
    else:
        logger.info("mcp_http_app_created", auth="none")

    return base_app


def _wrap_with_api_key_auth(app: Any, api_key: str) -> Any:
    """Wrap an ASGI app with API-key bearer-token authentication.

    Requests that supply ``Authorization: Bearer <api_key>`` pass through.
    All others receive a ``401 Unauthorized`` JSON response.

    Args:
        app: The inner ASGI application to protect.
        api_key: The expected bearer token value.

    Returns:
        An ASGI application with authentication enforced.
    """
    import json as _json

    expected_header = f"Bearer {api_key}".encode()

    async def _auth_middleware(scope: Any, receive: Any, send: Any) -> None:
        # Only enforce auth on HTTP requests; pass-through for lifespan events
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"")
            if auth_header != expected_header:
                response_body = _json.dumps(
                    {"error": "Unauthorized", "message": "Invalid or missing API key."}
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(response_body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": response_body})
                return
        await app(scope, receive, send)

    return _auth_middleware
