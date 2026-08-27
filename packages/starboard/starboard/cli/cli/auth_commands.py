# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard auth`` command group (Phase 2 Task A0).

Thin, guided wrapper over the shared auth resolver (``infra/auth/resolver.py``)
so the no-MCP path gets a one-time login without the user hand-rolling
``databricks auth login`` invocations.

Subcommands:

* ``auth login [--host URL] [--profile NAME]`` — prefer the Databricks CLI
  (``shutil.which("databricks")`` → ``databricks auth login``); fall back to the
  SDK in-process ``external-browser`` U2M flow when the CLI is absent
  (decision D-2.11).
* ``auth status`` — resolve a ``WorkspaceClient`` and print the redacted auth
  description (host / auth_type / profile / user). Never prints a token.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from rich.console import Console

from starboard import describe_auth, resolve_workspace_client
from starboard.cli.cli.exit_codes import AUTH_ERROR, SUCCESS, USAGE_ERROR

# Cached at ~/.databricks/token-cache.json by the SDK's external-browser flow.
_TOKEN_CACHE_HINT = "~/.databricks/token-cache.json"


def cmd_auth_login(
    host: str | None = None,
    profile: str | None = None,
) -> int:
    """Run a one-time Databricks OAuth/U2M login (decision D-2.11).

    Prefers the Databricks CLI when it is on ``PATH``; otherwise triggers the
    SDK's in-process ``external-browser`` strategy (opens a browser and caches
    the token at ``~/.databricks/token-cache.json``).

    Args:
        host: Workspace URL. Required for the in-process fallback; optional for
            the CLI path when a profile already carries a host.
        profile: ``~/.databrickscfg`` profile name to write / use.

    Returns:
        A process exit code (``0`` on success, nonzero on failure).
    """
    out = Console()
    err = Console(stderr=True)

    if shutil.which("databricks"):
        cmd = ["databricks", "auth", "login"]
        if host:
            cmd += ["--host", host]
        if profile:
            cmd += ["--profile", profile]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            err.print(
                "[bold red]Databricks CLI login failed[/bold red] "
                f"(exit {e.returncode}).\n"
                "Verify the host URL and that you completed the browser prompt, "
                "then re-run [cyan]starboard auth login[/cyan]."
            )
            return AUTH_ERROR
        except OSError as e:  # pragma: no cover - defensive
            err.print(f"[bold red]Could not launch the Databricks CLI:[/bold red] {e}")
            return AUTH_ERROR
    else:
        # No CLI on PATH — use the SDK external-browser U2M strategy in-process.
        if not host:
            err.print(
                "[bold red]A workspace --host is required[/bold red] for "
                "browser-based login when the Databricks CLI is not installed.\n"
                "Run [cyan]starboard auth login --host <workspace-url>[/cyan]."
            )
            return USAGE_ERROR
        try:
            client = WorkspaceClient(
                config=Config(host=host, auth_type="external-browser")
            )
            # Resolving the current user triggers the browser flow + token cache.
            client.current_user.me()
        except Exception as e:  # noqa: BLE001 - surface any SDK/browser failure
            err.print(
                "[bold red]Browser login failed[/bold red]: "
                f"{e}\n"
                "Re-run [cyan]starboard auth login --host <workspace-url>[/cyan] "
                "and complete the browser prompt."
            )
            return AUTH_ERROR

    out.print(
        "[bold green]Login complete.[/bold green] "
        f"Token cached at [dim]{_TOKEN_CACHE_HINT}[/dim].\n"
        "Verify with [cyan]starboard auth status[/cyan]."
    )
    return SUCCESS


def cmd_auth_status(*, as_json: bool = False) -> int:
    """Resolve the current auth and print a redacted description.

    Uses the shared resolver so it reflects exactly what the agent path will
    use. Only host / auth_type / profile / user are shown — never a token.

    Args:
        as_json: Emit a JSON object on stdout instead of a table.

    Returns:
        A process exit code (``0`` on success, nonzero on failure).
    """
    err = Console(stderr=True)

    try:
        client = resolve_workspace_client()
        info = describe_auth(client)
    except Exception as e:  # noqa: BLE001 - any resolution/identity failure
        err.print(
            "[bold red]Could not resolve Databricks auth[/bold red]: "
            f"{e}\n"
            "Run [cyan]starboard auth login --host <workspace-url> "
            "--profile <name>[/cyan], set DATABRICKS_CONFIG_PROFILE, or provide "
            "DATABRICKS_HOST + DATABRICKS_TOKEN."
        )
        return AUTH_ERROR

    if as_json:
        # Plain stdout so the payload stays machine-parseable.
        print(json.dumps(info, indent=2, default=str))
        return SUCCESS

    out = Console()
    from rich.table import Table

    table = Table(title="Databricks Auth", show_header=True, padding=(0, 1))
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for field in ("host", "auth_type", "profile", "user"):
        value = info.get(field)
        table.add_row(field, str(value) if value is not None else "[dim]—[/dim]")
    out.print(table)
    return SUCCESS


def build_parser() -> argparse.ArgumentParser:
    """Build the ``starboard auth`` argument parser (login / status)."""
    parser = argparse.ArgumentParser(
        prog="starboard auth",
        description="Databricks authentication for Starboard.",
    )
    sub = parser.add_subparsers(dest="auth_command")

    login = sub.add_parser(
        "login",
        help="Log in to a Databricks workspace (CLI or in-process browser flow).",
    )
    login.add_argument(
        "--host",
        type=str,
        default=None,
        help="Databricks workspace URL (e.g. https://<workspace>.databricks.com).",
    )
    login.add_argument(
        "--profile",
        type=str,
        default=None,
        help="~/.databrickscfg profile name to write / use.",
    )

    status = sub.add_parser(
        "status",
        help="Show the resolved Databricks identity (no secrets).",
    )
    status.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Emit the auth description as JSON.",
    )

    return parser


def run_auth(argv: list[str]) -> int:
    """Parse ``auth`` subcommand args and dispatch to the handler.

    Args:
        argv: Arguments following the ``auth`` verb (e.g. ``["status", "--json"]``).

    Returns:
        A process exit code.
    """
    parser = build_parser()
    ns = parser.parse_args(argv)

    if ns.auth_command == "login":
        return cmd_auth_login(host=ns.host, profile=ns.profile)
    if ns.auth_command == "status":
        return cmd_auth_status(as_json=ns.json)

    parser.print_help(sys.stderr)
    return USAGE_ERROR
