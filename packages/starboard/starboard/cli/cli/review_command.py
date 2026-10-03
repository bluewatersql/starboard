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
                     [--lookback-days N] [--json] [--out F]
    starboard review --internal-workspace-id ID | --internal-account ACCT
                     [--lookback-days N] [--json] [--since F] [--manifest-out F]
    starboard review --from-discovery <run-dir>/discovery [--json] [--out F]
                     [--manifest-out F]

The ``--internal-*`` form runs the same review over the gated internal fleet
mirror (no customer-workspace connection) via the ``starboard.port_adapters``
discovery-source seam, exactly as ``starboard --discover --internal-*`` does.

``--from-discovery`` evaluates the rules on a saved discovery run's results
(``raw/<pack>.json``, fallback ``discovery.json``) instead of re-running the
evidence queries: fully offline (no workspace connection, no auth), inheriting
the discovery run's scope and lookback, so discovery and review agree.

Emits the Phase-0 JSON envelope (``{ok, domain, command, data|error, meta}``)
on ``--json`` (``--out F`` writes it to ``F`` instead and prints only a one-line
``{ok, out, finding_count, degraded}`` summary JSON on stdout) — shared with ``python -m starboard_x.review`` via
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
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from starboard_x.contract import (
    EXIT_API,
    EXIT_ARG,
    EXIT_AUTH,
    EXIT_NOT_FOUND,
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
    parser.add_argument(
        "--internal",
        action="store_true",
        help=(
            "Internal no-workspace mode: analyze from internal telemetry WITHOUT "
            "connecting to the customer workspace. Requires the gated internal "
            "path to be enabled and wired; errors clearly otherwise. --workspace "
            "is used only to SCOPE the query, not to connect."
        ),
    )
    parser.add_argument(
        "--internal-workspace-id",
        default=None,
        help=(
            "Review this workspace id on the INTERNAL fleet mirror (no "
            "customer-workspace connection; takes precedence over "
            "--internal-account). Requires the gated internal source."
        ),
    )
    parser.add_argument(
        "--internal-account",
        default=None,
        help=(
            "Review this Databricks account id on the INTERNAL fleet mirror (no "
            "customer-workspace connection). Requires the gated internal source."
        ),
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help=(
            "Evidence-query time window in days (default 30). With "
            "--from-discovery the discovery run's lookback is used; a differing "
            "value only warns."
        ),
    )
    parser.add_argument(
        "--from-discovery",
        default=None,
        metavar="DIR",
        help=(
            "Evaluate the rules on a saved discovery run (the --out-dir "
            "discovery directory, or its discovery.json) instead of re-running "
            "the evidence queries. Fully offline: no workspace connection or "
            "auth. Workspace scope and lookback come from the discovery output. "
            "Run AFTER discovery finishes, never concurrently."
        ),
    )
    parser.add_argument("--max-parallelism", type=int, default=4)
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the discovery scan cache (re-run every evidence query).",
    )
    # --- severity gate (opt-in) -------------------------------------------- #
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
            "Path to a prior review snapshot (v1) OR findings-manifest (v2) JSON; "
            "report the delta vs. this run (read-only, never writes the workspace). "
            "A v2 manifest yields the cost-aware run-over-run comparison "
            "(newly-expensive / regressed / improved / persisting)."
        ),
    )
    parser.add_argument(
        "--snapshot-out",
        default=None,
        help="Write a review snapshot JSON to this local path for a later --since.",
    )
    parser.add_argument(
        "--manifest-out",
        default=None,
        help=(
            "Write a findings-manifest (v2) JSON to this local path: per-finding "
            "entity/rule/severity/score/DBU estimate, for a later cost-aware "
            "--since comparison. Local file only; never written to the workspace."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the JSON envelope to stdout instead of a table.",
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help=(
            "Write the JSON envelope to PATH (implies --json); stdout then "
            "carries only a one-line summary JSON {ok, out, finding_count, "
            "degraded}. Use this instead of redirecting stdout."
        ),
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
    if getattr(args, "internal", False):
        # Internal no-workspace mode. Whether this actually opens the gate is
        # governed by ``EnvConfig.internal_mode_active`` (fail-closed: needs
        # ENABLE_INTERNAL_ADAPTERS + the installed starboard-internal package),
        # so setting the flag is a safe no-op in a public wheel.
        overrides["internal_mode"] = True
    if overrides:
        config = config.model_copy(update=overrides)
    return config


def _internal_preflight(config) -> tuple[bool, str]:
    """Resolve the internal-data gate for an ``--internal`` run (no live client).

    Returns ``(gate_open, message)``:

    * ``(False, msg)`` — the gate could NOT open (public wheel, adapters
      disabled, or no ``STARBOARD_INTERNAL_*`` deployment env). ``msg`` is an
      actionable error. No customer workspace is ever contacted.
    * ``(True, msg)`` — the gate is open, but a bare ``--internal`` names no
      mirror scope; ``msg`` tells the caller to pass ``--internal-workspace-id``
      or ``--internal-account`` (the flags that run the no-connect review).

    Uses :func:`detect_gate_open` with ``client=None`` so the gate opens (or not)
    without resolving a workspace credential — the whole point of ``--internal``.
    """
    from starboard import detect_gate_open

    ctx = detect_gate_open(config, client=None)
    if not ctx.gate_open:
        return (
            False,
            "Internal mode (--internal) could not open the internal-data gate. "
            "It requires the gated internal path: set ENABLE_INTERNAL_ADAPTERS=true, "
            "install the starboard-internal package, and wire at least one "
            "STARBOARD_INTERNAL_* deployment env var. No customer workspace was "
            "contacted.",
        )
    return (
        True,
        "Internal mode active — the internal-data gate is open. Pass "
        "--internal-workspace-id <id> or --internal-account <acct> to run the "
        "review on the internal fleet mirror (no customer-workspace connection).",
    )


class _InternalUnusedExecutor:
    """Base ``SQLExecutor`` guard for an internal-mirror review.

    Every evidence query runs through the gated ``MirrorSource`` (which carries
    its own internal executor), so this must never be called — raising upholds
    the no-customer-connection invariant of an internal review.
    """

    async def execute_sql(self, sql: str):  # noqa: ANN201, ARG002
        raise RuntimeError(
            "internal review must not use the customer SQL executor — all "
            "queries run via the gated MirrorSource"
        )


class _OfflineUnusedExecutor:
    """Base ``SQLExecutor`` guard for a ``--from-discovery`` review.

    Evidence rows come from the saved discovery output, so this must never be
    called — raising upholds the offline (no-connection) invariant.
    """

    async def execute_sql(self, sql: str):  # noqa: ANN201, ARG002
        raise RuntimeError(
            "--from-discovery review must not execute queries — evidence comes "
            "from the saved discovery output"
        )


class DiscoveryScopeMismatchError(ValueError):
    """``--from-discovery`` output is scoped to a different workspace/account."""


def _discovery_scope(
    args: argparse.Namespace, evidence
) -> tuple[str | None, str | None]:
    """Return ``(workspace_label, workspace_id)`` for a ``--from-discovery`` run.

    The scope comes from the discovery envelope (``scope.workspace_ids`` /
    ``scope.account``). An explicit ``--internal-workspace-id`` /
    ``--internal-account`` that disagrees with it is a hard error; with no
    discovery scope (public path) the ``--workspace``/``--profile`` label or the
    explicit internal flags are used as given.
    """
    ws_arg = getattr(args, "internal_workspace_id", None)
    acct_arg = getattr(args, "internal_account", None)
    disc_ws = evidence.workspace_ids
    disc_acct = evidence.account

    if ws_arg and disc_ws and str(ws_arg) not in disc_ws:
        raise DiscoveryScopeMismatchError(
            f"--internal-workspace-id {ws_arg} does not match the discovery "
            f"output scope (workspace_ids={list(disc_ws)}) at {evidence.path}"
        )
    # A --workspace/--profile given as a workspace id (``123`` / ``ws-123``) is
    # checked too; a profile NAME cannot be compared offline and is only a label.
    label_arg = args.workspace or args.profile
    label_id = str(label_arg).removeprefix("ws-") if label_arg else ""
    if label_id.isdigit() and disc_ws and label_id not in disc_ws:
        raise DiscoveryScopeMismatchError(
            f"--workspace {label_arg} does not match the discovery output scope "
            f"(workspace_ids={list(disc_ws)}) at {evidence.path}"
        )
    if acct_arg and disc_acct and str(acct_arg) != disc_acct:
        raise DiscoveryScopeMismatchError(
            f"--internal-account {acct_arg} does not match the discovery output "
            f"scope (account={disc_acct}) at {evidence.path}"
        )

    workspace_ids: tuple[str, ...] = disc_ws or ((str(ws_arg),) if ws_arg else ())
    account = disc_acct or (str(acct_arg) if acct_arg else None)
    if len(workspace_ids) == 1:
        return f"ws-{workspace_ids[0]}", workspace_ids[0]
    if account:
        return f"acct-{account}", None
    return args.workspace or args.profile, None


class InternalSourceUnavailableError(RuntimeError):
    """The gated internal discovery source could not be resolved."""


def _internal_scope(
    args: argparse.Namespace,
) -> tuple[tuple[str, ...] | None, str | None] | None:
    """Return ``(workspace_ids, account)`` for an internal-mirror review, or None.

    ``--internal-workspace-id`` takes precedence over ``--internal-account``
    (same rule as ``starboard --discover``).
    """
    ws_id = getattr(args, "internal_workspace_id", None)
    if ws_id:
        return (str(ws_id),), None
    account = getattr(args, "internal_account", None)
    if account:
        return None, str(account)
    return None


def _internal_label(scope: tuple[tuple[str, ...] | None, str | None]) -> str:
    """Workspace label for an internal review: ``ws-<id>`` (or ``acct-<acct>``)."""
    workspace_ids, account = scope
    if workspace_ids:
        return f"ws-{workspace_ids[0]}"
    return f"acct-{account}"


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


async def _run_review(
    args: argparse.Namespace,
    workspace_label: str | None,
    progress: Callable[[str], None] | None = None,
    evidence=None,
):
    """Run the review; returns ``(review, gate_outcome, products_dbu, evidence_report)``.

    With ``evidence`` (``--from-discovery``) no query runs and nothing is
    connected: rows come from the saved discovery output (the base executor is
    a raising guard). With an ``--internal-*`` scope the evidence queries run
    through the gated ``MirrorSource`` resolved via the port-adapter seam; no
    customer client is built or entered (the base executor is a raising guard).
    """
    from starboard import WorkloadReviewService

    gate = _build_gate(args)
    domains = _parse_domains(args.domains)
    scope = _internal_scope(args)

    async def _execute(service):
        if gate is None:
            review = await service.run(domains, progress=progress)
            return review, None, dict(service.products_dbu), service.evidence_report
        validated = await service.run_validated(domains, gate=gate, progress=progress)
        return (
            validated.review,
            validated.gate,
            dict(service.products_dbu),
            service.evidence_report,
        )

    def _service(sql_executor, source=None, evidence=None):
        return WorkloadReviewService(
            sql_executor,
            lookback_days=args.lookback_days,
            max_parallelism=args.max_parallelism,
            enable_cache=not args.no_cache,
            workspace=workspace_label,
            source=source,
            evidence=evidence,
        )

    if evidence is not None:
        return await _execute(_service(_OfflineUnusedExecutor(), evidence=evidence))

    if scope is not None:
        from starboard.bootstrap import resolve_internal_source

        workspace_ids, account = scope
        try:
            source = resolve_internal_source(workspace_ids, account=account)
        except RuntimeError as exc:
            raise InternalSourceUnavailableError(str(exc)) from exc
        return await _execute(_service(_InternalUnusedExecutor(), source))

    from starboard.bootstrap import AsyncDatabricksClient, AsyncSQLExecutor

    client = AsyncDatabricksClient(cfg=_resolve_config(args))
    async with client:
        return await _execute(_service(AsyncSQLExecutor(client)))


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


def _load_since(path: str):
    """Load a prior ``--since`` file, discriminating v1 snapshot from v2 manifest.

    Returns a :class:`ReviewSnapshot` (v1, finding ids only) or a
    :class:`FindingsManifest` (v2, per-finding DBU/entity records). The version
    is read from the JSON ``snapshot_version`` field; anything that is not the v2
    manifest version is treated as a v1 snapshot for backward compatibility.
    """
    import json

    from starboard_core.domain.rules.action_rate import (
        MANIFEST_VERSION,
        FindingsManifest,
        ReviewSnapshot,
    )

    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if str(payload.get("snapshot_version")) == MANIFEST_VERSION:
        return FindingsManifest.model_validate(payload)
    return ReviewSnapshot.model_validate(payload)


def _write_manifest(
    review,
    path: str,
    *,
    lookback_days: int | None,
    workspace: str | None,
    workspace_id: str | None = None,
    products_dbu: dict[str, float] | None = None,
    evidence_source: dict | None = None,
    discovery_skipped: list[str] | None = None,
) -> None:
    """Write a v2 :class:`FindingsManifest` of ``review`` to a local JSON file.

    The manifest carries the review's ``degraded`` / ``unavailable_queries`` /
    ``unavailable_domains`` / ``cost_basis`` / ``coverage_note`` and, for
    ``--from-discovery``, the ``evidence_source`` provenance plus
    ``discovery_skipped`` (every query the discovery input skipped).

    Read-only w.r.t. the customer workspace: the manifest is a local per-run
    record (the recurrence keystone), never written back to Databricks. DBU
    figures are list-price estimates extracted from the verified evidence rows.
    """
    import json
    from datetime import datetime

    from starboard_core.domain.rules.action_rate import FindingsManifest

    manifest = FindingsManifest.from_review(
        review,
        run_date=datetime.now(UTC).date().isoformat(),
        lookback_days=lookback_days,
        workspace_id=workspace_id,
        products_dbu=products_dbu,
        evidence_source=evidence_source,
        discovery_skipped=discovery_skipped,
    )
    # ``workspace`` on the manifest comes from the review; keep it if the review
    # carried none but the CLI knew the profile label.
    if manifest.workspace is None and workspace is not None:
        manifest = manifest.model_copy(update={"workspace": workspace})
    payload = manifest.model_dump(mode="json")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


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
    Path(path).parent.mkdir(parents=True, exist_ok=True)
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

    if args.out:
        args.json = True

    def _emit(**kwargs) -> bool:
        return _emit_json(out=args.out, **kwargs)

    def _fail(message: str, code: int) -> int:
        if args.json:
            _emit(ok=False, command="run", error=message)
        else:
            err.print(f"\n[bold red]{message}[/bold red]")
        return code

    requested_lookback = args.lookback_days
    if args.lookback_days is None:
        args.lookback_days = 30

    workspace_label = args.workspace or args.profile
    internal_scope = _internal_scope(args)
    internal_workspace_id: str | None = None
    if internal_scope is not None:
        workspace_label = _internal_label(internal_scope)
        if internal_scope[0]:
            internal_workspace_id = internal_scope[0][0]

    # --from-discovery: offline evidence from a saved discovery run. Scope and
    # lookback are inherited from the discovery output; nothing is connected.
    evidence = None
    evidence_source: dict | None = None
    # Every query the discovery input skipped (None = live review, no input).
    discovery_skipped: list[str] | None = None
    if args.from_discovery:
        from starboard import DiscoveryEvidenceError, load_discovery_evidence

        try:
            evidence = load_discovery_evidence(args.from_discovery)
            workspace_label, internal_workspace_id = _discovery_scope(args, evidence)
        except DiscoveryEvidenceError as exc:
            return _fail(f"--from-discovery: {exc}", EXIT_NOT_FOUND)
        except DiscoveryScopeMismatchError as exc:
            return _fail(f"--from-discovery: {exc}", EXIT_ARG)
        evidence_source = evidence.provenance()
        discovery_skipped = list(evidence.skipped_query_ids)
        if evidence.lookback_days is not None:
            if (
                requested_lookback is not None
                and requested_lookback != evidence.lookback_days
            ):
                err.print(
                    f"[yellow]! --lookback-days {requested_lookback} differs from "
                    f"the discovery run's lookback ({evidence.lookback_days} days); "
                    f"using the discovery lookback.[/yellow]"
                )
                evidence_source["requested_lookback_days"] = requested_lookback
            args.lookback_days = evidence.lookback_days

    # Bare --internal (no mirror scope) preflight, before any client build: the
    # gate opens via detect_gate_open with NO live workspace client. Closed gate
    # (public wheel / adapters unwired) => clear auth error; open gate => arg
    # error naming the --internal-workspace-id / --internal-account flags. Never
    # falls through to the workspace-connecting public flow.
    if getattr(args, "internal", False) and internal_scope is None and evidence is None:
        config = _resolve_config(args)
        gate_open, message = _internal_preflight(config)
        if not gate_open:
            if args.json:
                _emit(ok=False, command="run", error=message)
            else:
                err.print(f"\n[bold red]{message}[/bold red]")
            return EXIT_AUTH
        if args.json:
            _emit(ok=False, command="run", error=message)
        else:
            err.print(f"\n[yellow]{message}[/yellow]")
        return EXIT_ARG

    # Immediate, unconditional startup line so the command never looks dead while
    # it scans (a full multi-domain scan + council pass can run for minutes). The
    # live spinner below updates per phase; both go to stderr so --json stdout
    # stays a clean envelope.
    scope = ", ".join(_parse_domains(args.domains))
    target = f" ({workspace_label})" if workspace_label else ""
    err.print(f"[dim]Workload Review{target} — domains: {scope}…[/dim]")
    if evidence is not None:
        err.print(
            f"[dim]Evidence: discovery output at {evidence.path} "
            f"(offline; no queries executed)[/dim]"
        )

    try:
        with err.status("Starting review…", spinner="dots") as status:

            def _progress(message: str) -> None:
                status.update(message)

            review, gate_outcome, products_dbu, evidence_report = asyncio.run(
                _run_review(
                    args, workspace_label, progress=_progress, evidence=evidence
                )
            )
    except KeyboardInterrupt:
        err.print("\n[yellow]Interrupted by user[/yellow]")
        return EXIT_API
    except InternalSourceUnavailableError as exc:
        message = (
            f"Internal review could not resolve the gated internal source ({exc}). "
            "It requires the starboard-internal package and its configured fleet "
            "source. No customer workspace was contacted."
        )
        if args.json:
            _emit(ok=False, command="run", error=message)
        else:
            err.print(f"\n[bold red]{message}[/bold red]")
        return EXIT_AUTH
    except ConnectionError as exc:
        # InternalPreflightError (starboard-internal) subclasses ConnectionError,
        # so the internal fleet preflight surfaces as one clean line, no traceback.
        message = f"Connection failed: {exc}"
        if args.json:
            _emit(ok=False, command="run", error=message)
        else:
            err.print(f"\n[bold red]{message}[/bold red]")
        return EXIT_API
    except Exception as exc:  # noqa: BLE001 - map to the envelope exit codes
        message = str(exc)
        exit_code = EXIT_API
        lowered = message.lower()
        if any(k in lowered for k in ("auth", "credential", "token", "unauthor")):
            exit_code = EXIT_AUTH
        logger.warning("workload_review_failed", error=message)
        if args.json:
            _emit(ok=False, command="run", error=message)
        else:
            err.print(f"\n[bold red]Review failed:[/bold red] {message}")
        return exit_code

    # Run-over-run delta (read-only): compare against a prior snapshot/manifest.
    # A v1 snapshot yields the presence/absence Action-Rate; a v2 manifest yields
    # the cost-aware CostDelta (newly-expensive / regressed / improved / persisting).
    delta = None
    cost_delta = None
    if args.since:
        try:
            from starboard_core.domain.rules.action_rate import (
                FindingsManifest,
                compute_action_rate,
                compute_cost_delta,
            )

            prior = _load_since(args.since)
            if isinstance(prior, FindingsManifest):
                curr = FindingsManifest.from_review(
                    review,
                    # Same date the written manifest gets, so the delta's
                    # current_run_date is populated (not null).
                    run_date=datetime.now(UTC).date().isoformat(),
                    lookback_days=args.lookback_days,
                    workspace_id=internal_workspace_id,
                    products_dbu=products_dbu,
                    evidence_source=evidence_source,
                    discovery_skipped=discovery_skipped,
                )
                cost_delta = compute_cost_delta(prior, curr)
            else:
                delta = compute_action_rate(prior, review)
        except Exception as exc:  # noqa: BLE001 - bad snapshot is an arg error
            message = f"could not read --since snapshot: {exc}"
            if args.json:
                _emit(ok=False, command="run", error=message)
            else:
                err.print(f"\n[bold red]{message}[/bold red]")
            return EXIT_ARG

    # Persist a snapshot for a future --since (local file, not the workspace).
    if args.snapshot_out:
        try:
            _write_snapshot(review, args.snapshot_out)
        except Exception as exc:  # noqa: BLE001 - surface but don't fail the review
            err.print(f"[yellow]! could not write snapshot: {exc}[/yellow]")

    # Persist a v2 findings-manifest for a future cost-aware --since comparison.
    if args.manifest_out:
        try:
            _write_manifest(
                review,
                args.manifest_out,
                lookback_days=args.lookback_days,
                workspace=workspace_label,
                workspace_id=internal_workspace_id,
                products_dbu=products_dbu,
                evidence_source=evidence_source,
                discovery_skipped=discovery_skipped,
            )
        except Exception as exc:  # noqa: BLE001 - surface but don't fail the review
            err.print(f"[yellow]! could not write manifest: {exc}[/yellow]")

    if args.json:
        data = review.model_dump(mode="json")
        # Manifest field names on each finding (``FindingRecord.entity_id`` /
        # ``composite_key``), so a consumer can key review.json like the manifest.
        for rf in data.get("findings") or []:
            f = rf.get("finding") or {}
            entity_id = (f.get("location") or {}).get("entity")
            rf["entity_id"] = entity_id
            rf["composite_key"] = (
                f"{f['rule_id']}::{entity_id}"
                if f.get("rule_id") and entity_id
                else f.get("id")
            )
        # List-price DBU per product (DBU only, trailing 30 full days; F-01).
        data["products_dbu"] = products_dbu
        # Per-query evidence detail: unavailable reasons, row-capped queries,
        # effective lookbacks, and retry attempts when a result carries them.
        data["evidence_report"] = evidence_report
        # Coverage scope: unavailable_queries = evidence the rules consumed but
        # lacked; discovery_skipped = everything the discovery input skipped.
        from starboard_core.domain.rules.action_rate import coverage_note

        data["discovery_skipped"] = discovery_skipped or []
        data["coverage_note"] = coverage_note(
            review.unavailable_queries, discovery_skipped
        )
        if evidence_source is not None:
            data["evidence_source"] = evidence_source
        if gate_outcome is not None:
            data["validation"] = {"gate_suppressed": gate_outcome.suppressed_count}
        if delta is not None:
            data["action_rate"] = delta.model_dump(mode="json")
        if cost_delta is not None:
            data["cost_delta"] = cost_delta.model_dump(mode="json")
        if not _emit(ok=True, command="run", data=data):
            return EXIT_API
    else:
        _render_table(review, out)
        if evidence_source is not None:
            out.print(
                f"[dim]Evidence: discovery output {evidence_source['path']} "
                f"(lookback {evidence_source.get('lookback_days')} days; "
                f"{len(evidence_report.get('unavailable') or {})} evidence "
                f"queries unavailable).[/dim]\n"
            )
        _render_validation(gate_outcome, out)
        _render_action_rate(delta, out)
        _render_cost_delta(cost_delta, out)
    return EXIT_OK


def _render_validation(gate_outcome, console: Console) -> None:
    """Print a short severity-gate summary when the gate ran."""
    if gate_outcome is None:
        return
    console.print(
        f"[dim]Validation: severity gate suppressed "
        f"{gate_outcome.suppressed_count}.[/dim]\n"
    )


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


def _render_cost_delta(cost_delta, console: Console) -> None:
    """Print the cost-aware run-over-run comparison when a v2 --since was given."""
    if cost_delta is None:
        return
    console.print(
        f"[bold]Cost delta[/bold] (vs. prior manifest): "
        f"[red]{cost_delta.newly_expensive_count} newly-expensive[/red], "
        f"[yellow]{cost_delta.regressed_count} regressed[/yellow], "
        f"[green]{cost_delta.improved_count} improved[/green], "
        f"{cost_delta.persisting_count} persisting, "
        f"{len(cost_delta.new_low_cost)} new (low-cost). "
        f"[dim](DBU = list-price estimate)[/dim]\n"
    )


def _emit_json(
    *,
    ok: bool,
    command: str,
    data=None,
    error: str | None = None,
    out: str | None = None,
) -> bool:
    """Print the JSON envelope, or write it to ``out`` and print a summary line.

    With ``out`` stdout carries exactly one compact JSON line
    ``{ok, out, finding_count, degraded}`` (plus ``error`` on failure), so a
    caller never has to redirect (and risk mixing stderr into) the envelope.
    Returns ``False`` only when ``out`` could not be written (reported as an
    ``ok: false`` summary line).
    """
    import json

    payload = envelope(
        ok=ok,
        domain=_DOMAIN,
        command=command,
        data=data,
        error=error,
        meta=build_meta("json"),
    )
    if out is None:
        print(json.dumps(payload, indent=2, default=str))
        return True
    target = Path(out).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print(
            json.dumps(
                {"ok": False, "out": str(target), "error": f"could not write: {exc}"}
            )
        )
        return False
    summary: dict = {
        "ok": ok,
        "out": str(target),
        "finding_count": (data or {}).get("finding_count") if ok else None,
        "degraded": (data or {}).get("degraded") if ok else None,
    }
    if not ok:
        summary["error"] = error
    print(json.dumps(summary, default=str))
    return True


__all__ = ["run_review"]
