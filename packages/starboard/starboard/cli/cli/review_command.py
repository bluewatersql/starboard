# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard review`` command — the Workload Review flagship CLI (Phase-3 D1b).

Reviews a workspace's jobs / queries / warehouses the way Isaac ``/review``
reviews code, on **public ``system.*`` data only**: it runs the relevant query
packs, scores the rows against the seed :class:`RuleRegistry`, and prints a
ranked, evidence-cited set of findings.

Invocation::

    starboard review [--domains jobs,sql,warehouse] [--workspace NAME | --profile NAME]
                     [--lookback-days N] [--json]

Emits the Phase-0 JSON envelope (``{ok, domain, command, data|error, meta}``)
on ``--json`` — shared with ``python -m starboard_x.review`` via
:mod:`starboard_x.contract` — and the Phase-0 exit-code contract
(``0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error``).
"""

from __future__ import annotations

import argparse
import asyncio
import os

from rich.console import Console
from rich.table import Table
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

_DOMAIN = "review"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starboard review",
        description="Workload Review — ranked, evidence-cited findings over public system.* data.",
    )
    parser.add_argument(
        "--domains",
        default=None,
        help="Comma-separated review domains (default: jobs,sql,warehouse).",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace to review (a ~/.databrickscfg profile name).",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Databricks config profile (alias of --workspace).",
    )
    parser.add_argument("--host", default=None, help="Databricks workspace URL.")
    parser.add_argument("--token", default=None, help="Databricks personal access token.")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--max-parallelism", type=int, default=4)
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the discovery scan cache (re-run every evidence query).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the JSON envelope to stdout instead of a table.",
    )
    return parser


def _parse_domains(raw: str | None) -> list[str]:
    from starboard_core.domain.rules.evaluator import DEFAULT_DOMAINS

    if not raw:
        return list(DEFAULT_DOMAINS)
    return [d.strip() for d in raw.split(",") if d.strip()]


def _resolve_config(args: argparse.Namespace):
    """Build an ``EnvConfig`` honoring --workspace/--profile/--host/--token.

    Mirrors the main CLI's auth-by-subtraction: profile flows through the SDK
    credential chain via ``DATABRICKS_CONFIG_PROFILE``; inline host/token
    override the resolved config.
    """
    from starboard.bootstrap import get_config

    profile = args.workspace or args.profile
    if profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile

    config = get_config()
    overrides = {}
    if args.host:
        overrides["databricks_host"] = args.host
    if args.token:
        overrides["databricks_token"] = args.token
    if overrides:
        config = config.model_copy(update=overrides)
    return config


async def _run_review(args: argparse.Namespace, workspace_label: str | None):
    from starboard.bootstrap import AsyncDatabricksClient, AsyncSQLExecutor
    from starboard.tools.services.workload_review_service import (
        WorkloadReviewService,
    )

    config = _resolve_config(args)
    client = AsyncDatabricksClient(cfg=config)
    sql_executor = AsyncSQLExecutor(client)
    service = WorkloadReviewService(
        sql_executor,
        lookback_days=args.lookback_days,
        max_parallelism=args.max_parallelism,
        enable_cache=not args.no_cache,
        workspace=workspace_label,
    )
    async with client:
        return await service.run(_parse_domains(args.domains))


def _render_table(review, console: Console) -> None:
    """Print a human-readable ranked findings table."""
    console.print(
        f"\n[bold blue]Workload Review[/bold blue] — "
        f"{', '.join(review.requested_domains)}"
        + (f"  [dim]({review.workspace})[/dim]" if review.workspace else "")
    )
    if review.degraded:
        degraded = [r.domain for r in review.domain_reports if r.degraded]
        console.print(
            f"[yellow]! partial results[/yellow] — degraded domains: "
            f"{', '.join(degraded)}"
        )

    if not review.findings:
        console.print("\n[green]No findings.[/green] "
                      "(No rules fired, or evidence returned nothing to flag.)\n")
        console.print(f"[dim]{review.cost_basis}[/dim]\n")
        return

    table = Table(title="Findings (ranked)", show_header=True, padding=(0, 1))
    table.add_column("#", justify="right", width=3)
    table.add_column("Severity", width=9)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Domain", width=10)
    table.add_column("Finding", ratio=2)
    table.add_column("Evidence", ratio=1)

    sev_color = {
        "critical": "red",
        "high": "yellow",
        "medium": "cyan",
        "low": "dim",
    }
    for i, rf in enumerate(review.findings, 1):
        f = rf.finding
        color = sev_color.get(f.severity.value, "white")
        evidence = ", ".join(
            f"{ref.query_id}[{ref.row_index}]" for ref in rf.evidence
        )
        table.add_row(
            str(i),
            f"[{color}]{f.severity.value}[/{color}]",
            f"{f.score:.1f}",
            f.category,
            f.summary,
            evidence,
        )
    console.print()
    console.print(table)
    console.print(f"\n[dim]{review.cost_basis}[/dim]\n")


def run_review(argv: list[str]) -> int:
    """Entry point for ``starboard review`` (returns a process exit code)."""
    out = Console()
    err = Console(stderr=True)

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already printed help (code 0) or a usage error (code 2) to
        # the console; map anything non-zero to the Phase-0 arg-error code.
        code = exc.code if isinstance(exc.code, int) else EXIT_ARG
        return EXIT_OK if code == 0 else EXIT_ARG

    workspace_label = args.workspace or args.profile

    try:
        review = asyncio.run(_run_review(args, workspace_label))
    except KeyboardInterrupt:
        err.print("\n[yellow]Interrupted by user[/yellow]")
        return EXIT_API
    except Exception as exc:  # noqa: BLE001 - map to the envelope exit codes
        message = str(exc)
        exit_code = EXIT_API
        lowered = message.lower()
        if any(k in lowered for k in ("auth", "credential", "token", "unauthor")):
            exit_code = EXIT_AUTH
        logger.warning("workload_review_failed", error=message)
        if args.json:
            _emit_json(ok=False, command="run", error=message)
        else:
            err.print(f"\n[bold red]Review failed:[/bold red] {message}")
        return exit_code

    if args.json:
        _emit_json(ok=True, command="run", data=review.model_dump(mode="json"))
    else:
        _render_table(review, out)
    return EXIT_OK


def _emit_json(*, ok: bool, command: str, data=None, error: str | None = None) -> None:
    import json

    payload = envelope(
        ok=ok,
        domain=_DOMAIN,
        command=command,
        data=data,
        error=error,
        meta=build_meta("json"),
    )
    print(json.dumps(payload, indent=2, default=str))


__all__ = ["run_review"]
