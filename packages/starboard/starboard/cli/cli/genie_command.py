# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard genie ask`` command — NL→SQL over the public ``NLQueryPort`` (Phase-3 D8).

Answers a natural-language question about the resolved workspace with generated
SQL, using the **public** ``AnalyticsSqlAdapter`` (native ``LLMSQLGenerator``) — no
internal data, no MCP. When the internal-data enablement gate is open and the
``starboard-internal`` package is installed, the gated curated-Genie-room adapter
supersedes this public path (D8-internal); the public path here is the universal
default.

Invocation::

    starboard genie ask "why is my bill so high?" [--workspace NAME | --profile NAME]
                        [--warehouse-id ID] [--json]

Emits the Phase-0 JSON envelope (``{ok, domain, command, data|error, meta}``) on
``--json`` and the Phase-0 exit-code contract
(``0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error``).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

from rich.console import Console
from starboard_x.contract import (
    EXIT_API,
    EXIT_ARG,
    EXIT_AUTH,
    EXIT_OK,
    build_meta,
    envelope,
)

from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

_DOMAIN = "genie"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starboard genie",
        description="Natural-language → SQL over public workspace data (NLQueryPort).",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)
    ask = sub.add_parser("ask", help="Answer an NL question with generated SQL.")
    ask.add_argument("question", help="The natural-language question.")
    ask.add_argument(
        "--workspace",
        default=None,
        help="Workspace to target (a ~/.databrickscfg profile name).",
    )
    ask.add_argument(
        "--profile", default=None, help="Databricks config profile (alias of --workspace)."
    )
    ask.add_argument("--host", default=None, help="Databricks workspace URL.")
    ask.add_argument("--token", default=None, help="Databricks personal access token.")
    ask.add_argument(
        "--warehouse-id", default=None, help="SQL warehouse id for query context."
    )
    ask.add_argument(
        "--json",
        action="store_true",
        help="Emit the JSON envelope to stdout instead of formatted text.",
    )
    return parser


def _resolve_config(args: argparse.Namespace):
    """Build an ``EnvConfig`` honoring --workspace/--profile/--host/--token.

    Mirrors the main CLI's auth-by-subtraction (see ``review_command``): a profile
    flows through the SDK credential chain via ``DATABRICKS_CONFIG_PROFILE``; inline
    host/token override the resolved config.
    """
    from starboard.bootstrap import get_config

    profile = args.workspace or args.profile
    if profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile

    config = get_config()
    overrides: dict[str, Any] = {}
    if args.host:
        overrides["databricks_host"] = args.host
    if args.token:
        overrides["databricks_token"] = args.token
    if overrides:
        config = config.model_copy(update=overrides)
    return config


def _default_adapter(config: Any) -> Any:
    """Build the public ``AnalyticsSqlAdapter`` over the native ``LLMSQLGenerator``."""
    from starboard.adapters.llm import create_llm_client
    from starboard.adapters.ports.analytics_sql import AnalyticsSqlAdapter
    from starboard.tools.domain.analytics_sql.llm_sql_generator import LLMSQLGenerator

    llm_client = create_llm_client(config)
    generator = LLMSQLGenerator(llm_client=llm_client)  # type: ignore[arg-type]
    return AnalyticsSqlAdapter(generator)


def run_genie(argv: list[str], *, adapter_factory: Any = None) -> int:
    """Run ``starboard genie …``; return a Phase-0 exit code.

    Args:
        argv: Arguments after the ``genie`` token.
        adapter_factory: Optional ``(config) -> NLQueryPort`` used instead of the
            default public adapter — injected by tests to avoid a live LLM client.
    """
    out = Console()
    err = Console(stderr=True)
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_ARG

    if not str(args.question).strip():
        err.print("[red]genie ask: question must be non-empty[/red]")
        return EXIT_ARG

    factory = adapter_factory or _default_adapter
    try:
        config = _resolve_config(args)
        adapter = factory(config)
    except Exception as exc:  # noqa: BLE001 - map to the auth/arg contract
        msg = str(exc)
        code = EXIT_AUTH if "auth" in msg.lower() or "credential" in msg.lower() else EXIT_API
        if args.json:
            out.print_json(
                data=envelope(
                    ok=False, domain=_DOMAIN, command="ask", error=msg, meta=build_meta()
                )
            )
        else:
            err.print(f"[red]genie ask failed: {msg}[/red]")
        return code

    from starboard_core.ports.nl_query import WorkspaceCtx

    ctx = WorkspaceCtx(
        host=getattr(config, "databricks_host", None),
        warehouse_id=args.warehouse_id
        or getattr(config, "databricks_warehouse_id", None),
    )

    try:
        answer = asyncio.run(adapter.ask(args.question, ctx))
    except Exception as exc:  # noqa: BLE001
        if args.json:
            out.print_json(
                data=envelope(
                    ok=False, domain=_DOMAIN, command="ask", error=str(exc), meta=build_meta()
                )
            )
        else:
            err.print(f"[red]genie ask failed: {exc}[/red]")
        return EXIT_API

    data = {
        "question": args.question,
        "sql": answer.sql,
        "explanation": answer.explanation,
        "success": answer.success,
        "metadata": answer.metadata,
    }
    if args.json:
        out.print_json(
            data=envelope(
                ok=bool(answer.success),
                domain=_DOMAIN,
                command="ask",
                data=data,
                meta=build_meta(),
            )
        )
    else:
        if answer.success:
            out.print("[bold]Generated SQL[/bold]:")
            out.print(answer.sql or "(no SQL generated)")
            if answer.explanation:
                out.print(f"\n[dim]{answer.explanation}[/dim]")
        else:
            err.print("[yellow]No SQL generated for this question.[/yellow]")

    return EXIT_OK if answer.success else EXIT_API
