# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard review`` command — the Workload Review flagship CLI (Phase-3 D1b).

Reviews a workspace's jobs / queries / warehouses the way Isaac ``/review``
reviews code, on **public ``system.*`` data only**: it runs the relevant query
packs, scores the rows against the seed :class:`RuleRegistry`, and prints a
ranked, evidence-cited set of findings. The default scope is jobs/sql/warehouse;
Phase-2 adds opt-in ``--domains`` surfaces — ``uc``, ``dlt`` (alias
``pipelines``), ``ml``, ``vector-search`` (D-a), and ``portfolio-readiness`` (X4,
a public-safe workload-maturity review) — over the same rule engine.

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
import logging
import os
import sys
from collections.abc import Callable
from datetime import UTC

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

from starboard import get_logger

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
        help=(
            "Comma-separated review domains (default: jobs,sql,warehouse). "
            "Opt-in surfaces: uc, dlt (alias: pipelines), ml, vector-search, "
            "portfolio-readiness."
        ),
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
    parser.add_argument(
        "--token", default=None, help="Databricks personal access token."
    )
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--max-parallelism", type=int, default=4)
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the discovery scan cache (re-run every evidence query).",
    )
    # --- D1c: validator council + severity gate (opt-in) ------------------- #
    parser.add_argument(
        "--validate",
        action="store_true",
        help=(
            "Gate findings through the bounded validator council before "
            "surfacing them (model ids + max passes come from config)."
        ),
    )
    parser.add_argument(
        "--min-severity",
        default=None,
        choices=["low", "medium", "high", "critical"],
        help="Suppress findings below this severity (severity gate floor).",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Suppress findings below this priority score (severity gate floor).",
    )
    # --- D1c: Action-Rate re-scan loop (read-only, local snapshots) -------- #
    parser.add_argument(
        "--since",
        default=None,
        help=(
            "Path to a prior review snapshot JSON; report the resolved-rate "
            "delta vs. this run (read-only, never writes the workspace)."
        ),
    )
    parser.add_argument(
        "--snapshot-out",
        default=None,
        help="Write a review snapshot JSON to this local path for a later --since.",
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


def _build_gate(args: argparse.Namespace):
    """Build a severity gate from --min-severity/--min-score, or None."""
    if args.min_severity is None and args.min_score is None:
        return None
    from starboard_core.domain.models.finding import Severity
    from starboard_core.domain.rules.gate import SeverityGate

    kwargs: dict = {}
    if args.min_severity is not None:
        kwargs["min_severity"] = Severity(args.min_severity)
    if args.min_score is not None:
        kwargs["min_score"] = args.min_score
    return SeverityGate(**kwargs)


def _build_validator(args: argparse.Namespace, config, err: Console):
    """Build the validator council from config, or None (degrades on failure).

    Model ids + bounded max-passes come from :class:`CouncilConfig` (env/config),
    never hard-coded. If no LLM client can be built (e.g. offline), the council
    is skipped with a warning rather than failing the review.
    """
    if not args.validate:
        return None
    from starboard import CouncilConfig, build_council, create_llm_client

    try:
        llm_client = create_llm_client(config)
    except Exception as exc:  # noqa: BLE001 - degrade to no-council, keep the review
        err.print(
            f"[yellow]! --validate requested but no model client is available "
            f"({exc}); surfacing findings without council validation.[/yellow]"
        )
        return None
    council_config = CouncilConfig.from_env(default_model=config.llm_model)
    return build_council(llm_client, council_config)


async def _run_review(
    args: argparse.Namespace,
    workspace_label: str | None,
    err: Console,
    progress: Callable[[str], None] | None = None,
):
    from starboard import WorkloadReviewService
    from starboard.bootstrap import AsyncDatabricksClient, AsyncSQLExecutor

    config = _resolve_config(args)
    gate = _build_gate(args)
    validator = _build_validator(args, config, err)

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
        if gate is None and validator is None:
            review = await service.run(_parse_domains(args.domains), progress=progress)
            return review, None, None
        validated = await service.run_validated(
            _parse_domains(args.domains),
            gate=gate,
            validator=validator,
            progress=progress,
        )
        return validated.review, validated.gate, validated.council


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
        console.print(
            "\n[green]No findings.[/green] "
            "(No rules fired, or evidence returned nothing to flag.)\n"
        )
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
        evidence = ", ".join(f"{ref.query_id}[{ref.row_index}]" for ref in rf.evidence)
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


def _load_snapshot(path: str):
    """Load a prior :class:`ReviewSnapshot` from a local JSON file."""
    import json

    from starboard_core.domain.rules.action_rate import ReviewSnapshot

    with open(path, encoding="utf-8") as fh:
        return ReviewSnapshot.model_validate(json.load(fh))


def _write_snapshot(review, path: str) -> None:
    """Write a :class:`ReviewSnapshot` of ``review`` to a local JSON file.

    Read-only w.r.t. the customer workspace (D-3.3): the snapshot is a local
    diff key, never written back to Databricks.
    """
    import json
    from datetime import datetime

    from starboard_core.domain.rules.action_rate import ReviewSnapshot

    snapshot = ReviewSnapshot.from_review(
        review, created_at=datetime.now(UTC).isoformat()
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot.model_dump(mode="json"), fh, indent=2, default=str)


def _route_logs_to_stderr() -> None:
    """Send all logs to stderr so stdout carries only the review's own output.

    ``starboard review`` is dispatched (``cli.cli.main.main``) *before* the agent
    CLI's ``setup_cli_logging`` runs, so it inherits the ambient import-time
    structlog config whose default ``PrintLoggerFactory`` writes to **stdout**.
    Left unrouted, any WARNING/ERROR emitted mid-run (e.g. a dead council model)
    lands on stdout and corrupts the ``--json`` envelope. Pinning the factory and
    the stdlib stream to ``sys.stderr`` here keeps stdout reserved for the ranked
    table or the JSON envelope.
    """
    import structlog

    logging.basicConfig(
        level=logging.WARNING, stream=sys.stderr, format="%(message)s", force=True
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def run_review(argv: list[str]) -> int:
    """Entry point for ``starboard review`` (returns a process exit code)."""
    _route_logs_to_stderr()
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

    # Immediate, unconditional startup line so the command never looks dead while
    # it scans (a full multi-domain scan + council pass can run for minutes). The
    # live spinner below updates per phase; both go to stderr so --json stdout
    # stays a clean envelope.
    scope = ", ".join(_parse_domains(args.domains))
    target = f" ({workspace_label})" if workspace_label else ""
    err.print(
        f"[dim]Workload Review{target} — domains: {scope}"
        + ("; validating findings" if args.validate else "")
        + "…[/dim]"
    )

    try:
        with err.status("Starting review…", spinner="dots") as status:

            def _progress(message: str) -> None:
                status.update(message)

            review, gate_outcome, council = asyncio.run(
                _run_review(args, workspace_label, err, progress=_progress)
            )
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

    # Action-Rate re-scan delta (read-only): compare against a prior snapshot.
    delta = None
    if args.since:
        try:
            from starboard_core.domain.rules.action_rate import (
                compute_action_rate,
            )

            delta = compute_action_rate(_load_snapshot(args.since), review)
        except Exception as exc:  # noqa: BLE001 - bad snapshot is an arg error
            message = f"could not read --since snapshot: {exc}"
            if args.json:
                _emit_json(ok=False, command="run", error=message)
            else:
                err.print(f"\n[bold red]{message}[/bold red]")
            return EXIT_ARG

    # Persist a snapshot for a future --since (local file, not the workspace).
    if args.snapshot_out:
        try:
            _write_snapshot(review, args.snapshot_out)
        except Exception as exc:  # noqa: BLE001 - surface but don't fail the review
            err.print(f"[yellow]! could not write snapshot: {exc}[/yellow]")

    if args.json:
        data = review.model_dump(mode="json")
        if gate_outcome is not None or council is not None:
            data["validation"] = {
                "gate_suppressed": (
                    gate_outcome.suppressed_count if gate_outcome else 0
                ),
                "council_suppressed": (council.suppressed_count if council else 0),
                "council_model_calls": (council.total_model_calls if council else 0),
                "council_max_possible_calls": (
                    council.max_possible_calls if council else 0
                ),
                "council_disabled_models": (
                    list(council.disabled_model_ids) if council else []
                ),
            }
        if delta is not None:
            data["action_rate"] = delta.model_dump(mode="json")
        _emit_json(ok=True, command="run", data=data)
    else:
        _render_table(review, out)
        _render_validation(gate_outcome, council, out)
        _render_action_rate(delta, out)
    return EXIT_OK


def _render_validation(gate_outcome, council, console: Console) -> None:
    """Print a short validation summary when the D1c pipeline ran."""
    if gate_outcome is None and council is None:
        return
    if council is not None and council.disabled_model_ids:
        console.print(
            "[yellow]! council models unreachable and skipped for this run: "
            f"{', '.join(council.disabled_model_ids)}[/yellow] "
            "[dim](check the endpoint names in "
            "STARBOARD_REVIEW_COUNCIL_MODELS)[/dim]"
        )
    parts: list[str] = []
    if gate_outcome is not None:
        parts.append(f"severity gate suppressed {gate_outcome.suppressed_count}")
    if council is not None:
        parts.append(
            f"council suppressed {council.suppressed_count} "
            f"({council.total_model_calls}/{council.max_possible_calls} model calls)"
        )
    console.print(f"[dim]Validation: {'; '.join(parts)}.[/dim]\n")


def _render_action_rate(delta, console: Console) -> None:
    """Print the Action-Rate resolved-rate delta when --since was given."""
    if delta is None:
        return
    console.print(
        f"[bold]Action-Rate[/bold] (vs. snapshot): "
        f"resolved {delta.resolved_count}/{delta.prior_count} "
        f"([green]{delta.resolved_rate:.0%}[/green]), "
        f"{len(delta.persisting_ids)} persisting, {len(delta.new_ids)} new.\n"
    )


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
