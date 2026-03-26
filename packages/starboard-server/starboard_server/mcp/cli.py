# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""CLI entry point for the Starboard MCP server.

Usage::

    # stdio transport (default — for Claude Desktop, Cursor, etc.)
    python -m starboard_server.mcp

    # Streamable HTTP transport
    python -m starboard_server.mcp --transport http --port 8100

    # With explicit config file
    python -m starboard_server.mcp --config /path/to/mcp.json
"""

from __future__ import annotations

import argparse
import sys

from starboard_server.infra.observability.logging import get_logger
from starboard_server.mcp.config import load_mcp_config
from starboard_server.mcp.exceptions import ConfigurationError

logger = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse MCP CLI arguments.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        prog="starboard-mcp",
        description="Starboard MCP Server — Databricks workload analysis via MCP",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8100,
        help="Port for HTTP transport (default: 8100)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to MCP config JSON file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run the Starboard MCP server.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).
    """
    args = parse_args(argv)

    try:
        config = load_mcp_config(config_path=args.config)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc.message}", file=sys.stderr)
        sys.exit(1)

    if config is None:
        print(
            "No MCP configuration found. Set STARBOARD_MCP_CONFIG, "
            "DATABRICKS_HOST+DATABRICKS_TOKEN, or use --config.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.transport == "stdio":
        from starboard_server.mcp.transports import create_stdio_server

        logger.info("mcp_cli_starting", transport="stdio")
        create_stdio_server(config)
    else:
        import uvicorn

        from starboard_server.mcp.transports import create_mcp_app

        logger.info(
            "mcp_cli_starting",
            transport="http",
            host=args.host,
            port=args.port,
        )
        app = create_mcp_app(config)
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
