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
) -> StarboardMCPServer:
    """Create a fully configured ``StarboardMCPServer`` with all dependencies.

    Args:
        config: Validated MCP server configuration.

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


def create_mcp_app(config: MCPServerConfig) -> Any:
    """Create an ASGI app for Streamable HTTP transport.

    The returned app can be mounted into a FastAPI application::

        mcp_app = create_mcp_app(config)
        fastapi_app.mount("/mcp", mcp_app)

    Args:
        config: Validated MCP server configuration.

    Returns:
        ASGI application suitable for mounting in FastAPI.
    """
    server = create_starboard_mcp_server(config)
    logger.info("mcp_http_app_created")
    return server.mcp.streamable_http_app()
