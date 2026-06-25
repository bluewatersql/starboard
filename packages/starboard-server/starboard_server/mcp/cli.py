# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""CLI entry point for the Starboard MCP server.

Usage::

    # stdio transport (default — for Claude Desktop, Cursor, etc.)
    starboard-mcp

    # Streamable HTTP transport
    starboard-mcp --transport http --port 8100

    # With explicit config file
    starboard-mcp --config /path/to/mcp.json

    # Workspace management (credentials stay outside AI assistants)
    starboard-mcp workspace add
    starboard-mcp workspace list
    starboard-mcp workspace remove <id>
    starboard-mcp workspace set-default <id>
"""

from __future__ import annotations

import argparse
import getpass
import sys

from starboard_server.infra.observability.logging import get_logger
from starboard_server.mcp.config import load_mcp_config
from starboard_server.mcp.exceptions import ConfigurationError

logger = get_logger(__name__)


# ------------------------------------------------------------------
# Workspace subcommand handlers
# ------------------------------------------------------------------


def _workspace_add(args: argparse.Namespace) -> None:
    """Interactive workspace profile creation."""
    from starboard_server.mcp.workspace_manager import add_workspace

    ws_id = args.id or input("Workspace ID (e.g. production, staging): ").strip()
    if not ws_id:
        print("Workspace ID is required.", file=sys.stderr)
        sys.exit(1)

    host = args.host or input("Databricks host URL: ").strip()
    if not host:
        print("Host URL is required.", file=sys.stderr)
        sys.exit(1)

    token = args.token or getpass.getpass("Databricks API token: ").strip()
    if not token:
        print("Token is required.", file=sys.stderr)
        sys.exit(1)

    warehouse_id = (
        args.warehouse_id
        or input("Default SQL warehouse ID (optional, press Enter to skip): ").strip()
        or None
    )

    catalog = (
        args.catalog
        or input("Default catalog (optional, press Enter to skip): ").strip()
        or None
    )

    add_workspace(
        workspace_id=ws_id,
        host=host,
        token=token,
        set_default=args.set_default,
        warehouse_id=warehouse_id,
        default_catalog=catalog,
    )
    print(f"Workspace '{ws_id}' added to ~/.starboard/config.json")
    print("Token stored in ~/.starboard/.env (mode 0600)")


def _workspace_list(_args: argparse.Namespace) -> None:
    """List configured workspaces."""
    from starboard_server.mcp.workspace_manager import list_workspaces

    workspaces = list_workspaces()
    if not workspaces:
        print("No workspaces configured. Run: starboard-mcp workspace add")
        return

    for ws in workspaces:
        default_marker = " (default)" if ws["is_default"] else ""
        token_status = "token set" if ws["token_configured"] else "TOKEN MISSING"
        print(f"  {ws['workspace_id']}{default_marker}")
        print(f"    host: {ws['host']}")
        print(f"    credentials: {token_status}")
        if ws.get("warehouse_id"):
            print(f"    warehouse: {ws['warehouse_id']}")
        if ws.get("default_catalog"):
            print(f"    catalog: {ws['default_catalog']}")


def _workspace_remove(args: argparse.Namespace) -> None:
    """Remove a workspace profile."""
    from starboard_server.mcp.workspace_manager import remove_workspace

    if remove_workspace(args.id):
        print(f"Workspace '{args.id}' removed.")
    else:
        print(f"Workspace '{args.id}' not found.", file=sys.stderr)
        sys.exit(1)


def _workspace_set_default(args: argparse.Namespace) -> None:
    """Set the default workspace."""
    from starboard_server.mcp.workspace_manager import set_default

    if set_default(args.id):
        print(f"Default workspace set to '{args.id}'.")
    else:
        print(f"Workspace '{args.id}' not found.", file=sys.stderr)
        sys.exit(1)


# ------------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------------


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

    subparsers = parser.add_subparsers(dest="command")

    # -- Server mode (default when no subcommand) ---------------------
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

    # -- Workspace management -----------------------------------------
    ws_parser = subparsers.add_parser(
        "workspace", help="Manage Databricks workspace profiles"
    )
    ws_sub = ws_parser.add_subparsers(dest="ws_action")

    add_p = ws_sub.add_parser("add", help="Add a workspace profile")
    add_p.add_argument("--id", type=str, help="Workspace identifier")
    add_p.add_argument("--host", type=str, help="Databricks host URL")
    add_p.add_argument("--token", type=str, help="API token (prompted if omitted)")
    add_p.add_argument("--warehouse-id", type=str, help="Default SQL warehouse ID")
    add_p.add_argument("--catalog", type=str, help="Default Unity Catalog name")
    add_p.add_argument(
        "--set-default", action="store_true", help="Set as default workspace"
    )

    list_p = ws_sub.add_parser("list", help="List configured workspaces")  # noqa: F841

    rm_p = ws_sub.add_parser("remove", help="Remove a workspace profile")
    rm_p.add_argument("id", type=str, help="Workspace ID to remove")

    sd_p = ws_sub.add_parser("set-default", help="Set the default workspace")
    sd_p.add_argument("id", type=str, help="Workspace ID to set as default")

    return parser.parse_args(argv)


def _run_server(args: argparse.Namespace) -> None:
    """Start the MCP server."""
    try:
        config = load_mcp_config(config_path=args.config)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc.message}", file=sys.stderr)
        sys.exit(1)

    if config is None:
        print(
            "No MCP configuration found. Set STARBOARD_MCP_CONFIG, "
            "DATABRICKS_HOST+DATABRICKS_TOKEN, or use --config.\n"
            "Or run: starboard-mcp workspace add",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.transport == "stdio":
        from starboard_server.mcp.transports import create_stdio_server

        logger.info("mcp_cli_starting", transport="stdio")
        create_stdio_server(config, bootstrap=True)
    else:
        import asyncio

        import uvicorn

        from starboard_server.mcp.transports import bootstrap_mcp_server

        logger.info(
            "mcp_cli_starting",
            transport="http",
            host=args.host,
            port=args.port,
        )
        server = asyncio.run(bootstrap_mcp_server(config))
        app = server.mcp.streamable_http_app()
        uvicorn.run(app, host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    """Run the Starboard MCP server or manage workspaces.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).
    """
    args = parse_args(argv)

    if args.command == "workspace":
        handlers = {
            "add": _workspace_add,
            "list": _workspace_list,
            "remove": _workspace_remove,
            "set-default": _workspace_set_default,
        }
        handler = handlers.get(args.ws_action)
        if handler is None:
            print(
                "Usage: starboard-mcp workspace {add|list|remove|set-default}",
                file=sys.stderr,
            )
            sys.exit(1)
        handler(args)
    else:
        _run_server(args)


if __name__ == "__main__":
    main()
