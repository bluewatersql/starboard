# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""MCP transport adapters for stdio and Streamable HTTP.

Provides factory functions that create and run the MCP server with
different transports:

- **stdio**: For local CLI integration (Claude Desktop, Cursor, etc.)
- **Streamable HTTP (ASGI)**: For embedding in a FastAPI application
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from starboard_server.infra.core.config import get_config
from starboard_server.mcp.auth_context import EnvTokenAuthProvider
from starboard_server.mcp.circuit_breaker_registry import MCPCircuitBreakerRegistry
from starboard_server.mcp.config import MCPServerConfig
from starboard_server.mcp.rate_limiter import MCPRateLimiter
from starboard_server.mcp.sanitizer import MCPSanitizer
from starboard_server.mcp.server import StarboardMCPServer
from starboard_server.mcp.workspace_registry import DefaultWorkspaceRegistry

logger = structlog.get_logger(__name__)


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


async def run_stdio_server(config: MCPServerConfig) -> None:
    """Run the MCP server with stdio transport.

    This blocks until the stdio connection is closed (typically when the
    client process exits).

    Args:
        config: Validated MCP server configuration.
    """
    server = create_starboard_mcp_server(config)
    logger.info("mcp_stdio_starting")
    await server.mcp.run_stdio_async()


def create_stdio_server(config: MCPServerConfig) -> None:
    """Run the MCP server with stdio transport (sync entry point).

    Args:
        config: Validated MCP server configuration.
    """
    asyncio.run(run_stdio_server(config))


def create_mcp_app(config: MCPServerConfig, api_key: str | None = None) -> Any:
    """Create an ASGI app for Streamable HTTP transport.

    The returned app can be mounted into a FastAPI application::

        mcp_app = create_mcp_app(config)
        fastapi_app.mount("/mcp", mcp_app)

    When ``api_key`` is provided, the ASGI app is wrapped with a lightweight
    authentication middleware that validates the ``Authorization: Bearer``
    header on every incoming request.

    Args:
        config: Validated MCP server configuration.
        api_key: Optional API key for HTTP transport authentication.

    Returns:
        ASGI application suitable for mounting in FastAPI.
    """
    server = create_starboard_mcp_server(config, api_key=api_key)
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
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(response_body)).encode()),
                    ],
                })
                await send({"type": "http.response.body", "body": response_body})
                return
        await app(scope, receive, send)

    return _auth_middleware
