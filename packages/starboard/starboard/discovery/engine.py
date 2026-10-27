# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery engine — orchestrates the full 4-phase pipeline.

Phase 1: Audit — run P-AUDIT01 to discover active products
Phase 2: Query — execute conditional query packs in parallel
Phase 3: Analyze — heuristics + LLM per domain
Phase 4: Synthesize — aggregate into DiscoveryReport + output

Supports partial failures, data-only mode (skip LLM), and configurable
parallelism. Emits structured log events at each phase boundary.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from starboard_core.domain.models.discovery.analysis import DomainAnalysis
from starboard_core.domain.models.discovery.capture import CaptureIncomplete
from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    PackResult,
    QueryResult,
)
from starboard_core.domain.models.discovery.report import (
    AnalysisContext,
    DiscoveryReport,
)
from starboard_core.engagement.row_scope import WorkspaceAuthorizationError
from starboard_core.engagement.sink import LocalStorageRefused
from starboard_core.engagement.write_guard import LocalWriteRefused
from starboard_core.ports.engagement_storage import StorageError

from starboard.discovery.analyzer import DomainAnalyzer
from starboard.discovery.capture import CaptureLog, sql_digest
from starboard.discovery.executor import (
    DEFAULT_TIMEOUT_RETRIES,
    MAX_IN_FLIGHT_IDS_SHOWN,
    QueryPackExecutor,
    SQLExecutor,
)
from starboard.discovery.heuristics import create_default_heuristic_registry
from starboard.discovery.output.formatters import OutputFormatter
from starboard.discovery.prompts.domain_analysis import PromptBuilder
from starboard.discovery.query_packs.registry import (
    PlanSelection,
    QueryPackRegistry,
    create_default_registry,
)
from starboard.discovery.sources import ScopedSystemTablesSource
from starboard.discovery.synthesizer import ReportAssembler
from starboard.infra.observability.logging import get_logger
from starboard.ports.discovery import install_entry_point_adapters
from starboard.ports.registry import Port, PortRegistry

if TYPE_CHECKING:
    from starboard_core.engagement.sink import ArtifactSink

    from starboard.discovery.sources import QuerySource

logger = get_logger(__name__)

ProgressCallback = Callable[[str, dict[str, Any]], None]

_T = TypeVar("_T")

#: Returns the connected workspace's server-reported ID (SDK ``get_workspace_id()``).
WorkspaceIdProbe = Callable[[], Awaitable[str]]


def resolve_internal_source(
    workspace_ids: tuple[str, ...] | None,
    account: str | None = None,
    *,
    entry_points: Any = None,
    gate_open: bool = True,
) -> QuerySource:
    """Resolve the gated internal discovery source via the port-adapter registry.

    Reuses the existing ``starboard.port_adapters`` entry-point seam + gate rather
    than a parallel mechanism: the internal provider registers as ``INTERNAL_TIER``
    against :attr:`Port.DISCOVERY_SOURCE` and is selected only when the gate is
    open. **No PUBLIC adapter is ever registered for this port**, so a closed gate
    or an absent internal package leaves the registry with nothing to return and we
    raise — never a silent fallback to a customer workspace.

    The provider's ``create()`` yields a zero-arg *builder*; we call
    ``build(workspace_ids=...)`` so the per-run scope reaches the ``MirrorSource``.

    Args:
        workspace_ids: The run's workspace scope, threaded into the built source.
        entry_points: Optional pre-collected entry points (tests inject these);
            when ``None`` they are read from installed distributions.
        gate_open: Whether the internal-data gate is open (default ``True`` —
            ``source="internal"`` is itself the explicit internal-run request).

    Raises:
        RuntimeError: When no internal ``DISCOVERY_SOURCE`` provider is selectable.
    """
    registry = PortRegistry()
    install_entry_point_adapters(registry, entry_points=entry_points)
    try:
        builder = registry.select_adapter(Port.DISCOVERY_SOURCE, gate_open=gate_open)
    except KeyError:
        raise RuntimeError("internal source not available") from None
    return builder.build(workspace_ids=workspace_ids or (), account=account)


def resolve_scheduled_source(
    *,
    internal_source_account: str | None,
    internal_source_workspace_id: str | None,
) -> tuple[str, str | None, tuple[str, ...] | None]:
    """Resolve an unattended/scheduled run's ``EngineConfig`` source fields.

    Auto-run wiring (Task 9): a cron/scheduled discovery run has no user to
    prompt, so a preset target (set as config, not asked interactively) is
    itself the fully-resolved, no-prompt scope — unlike
    :func:`starboard.discovery.scope_resolver.resolve_scope`, which models an
    *interactive* routing decision and may return a prompt when no target is
    supplied. Here, "unset" simply means "stay external" (today's behavior,
    byte-identical).

    Per the spec (one account or one workspace_id per run), a preset
    ``internal_source_workspace_id`` takes precedence over
    ``internal_source_account`` when both are set.

    Args:
        internal_source_account: Preset account-scope target, if any.
        internal_source_workspace_id: Preset workspace-scope target, if any.

    Returns:
        ``(source, internal_account, internal_workspace_ids)`` ready to pass
        straight into :class:`EngineConfig`. ``source="external"`` with both
        targets ``None`` when neither preset is set.
    """
    if internal_source_workspace_id:
        return "internal", None, (internal_source_workspace_id,)
    if internal_source_account:
        return "internal", internal_source_account, None
    return "external", None, None


#: Failures the pipeline boundary re-raises instead of recording: storage refusals
#: and refused local writes on a covered run.
_STORAGE_REFUSALS = (LocalWriteRefused, LocalStorageRefused, StorageError)


class _BudgetSpent(Exception):
    """The capture's wall-clock deadline passed (internal to :meth:`DiscoveryEngine.run`)."""


def _storage_refusal(exc: BaseException) -> BaseException | None:
    """The first storage refusal in ``exc`` (task-group leaves included), else ``None``."""
    if isinstance(exc, _STORAGE_REFUSALS):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            found = _storage_refusal(inner)
            if found is not None:
                return found
    return None


@dataclass(frozen=True)
class EngineConfig:
    """Configuration for the discovery engine.

    Args:
        lookback_days: Time window for queries (7, 30, 60, or 90).
        max_parallelism: Max concurrent SQL/LLM operations.
        domains: Specific domains to analyze (None = all active).
        data_only: Skip LLM analysis and synthesis.
        output_dir: Directory for report output.
        llm_model: Optional LLM model override.
        llm_temperature: LLM temperature for analysis/synthesis.
        min_dbu_threshold: Minimum DBUs for a product to be considered active.
        enable_cache: Dedupe identical hot-table scans within/across runs.
            Set False for ``--no-cache``.
        cache_freshness_floor_s: Max age (seconds) a cached scan may be served.
        source: Discovery source selector. ``"external"`` (default) runs the
            rendered ``system.*`` SQL on the customer executor — byte-identical to
            today. ``"internal"`` resolves the gated ``MirrorSource`` through the
            ``starboard.port_adapters`` registry/gate (hard-errors when the
            internal package/provider is absent — never a customer fallback).
        internal_workspace_ids: Per-run workspace scope for the internal source
            (threaded into the ``MirrorSource``). Only used when
            ``source="internal"``.
        internal_account: Optional account-scope target for internal runs
            (reserved for account-wide scoping; workspace scoping is the wired
            path today).
        discovery_mode: Controls which queries run. ``GENERAL`` (default) runs
            only standard profiling queries; ``DEEP_DIVE`` also enables the
            deeper detail queries (enabled via ``--include-deep-dive``).
        timeout_retries: Bounded re-submissions after a statement poll-deadline
            timeout (internal fleet path). ``--timeout-retries`` on the CLI.
        authorized_workspace_ids: The run's authorized workspace scope on the
            public customer source. When set, the engine refuses to run unless the
            connected workspace's server ID is in the set, and every
            workspace-grained ``system.*`` reference is limited to these IDs
            (:class:`~starboard.discovery.sources.ScopedSystemTablesSource`).
            Ignored for ``source="internal"``, which scopes itself.
        sink: Artifact sink for the report on a ``--run-folder`` run. When set,
            the report goes to ``analysis/discovery-report/`` of the sink and
            ``output_dir`` is not touched (covered runs never write locally).
        capture: Keep a resumable capture record in ``sink``
            (:class:`~starboard.discovery.capture.CaptureLog`): queries finished by
            an earlier run of the same capture (run, source/scope, window and pack
            selection) are reused, and their statement timeouts carry over.
            Independent of ``enable_cache``. Needs ``capture_sink`` or ``sink``.
        capture_sink: Where the capture record goes when it is not ``sink``: a
            local run directory, whose report still goes to ``output_dir``.
        deadline: ``time.monotonic()`` value at which a ``capture`` run stops
            starting queries, cancels in-flight ones (best-effort), saves its
            progress and raises
            :class:`~starboard_core.domain.models.discovery.capture.CaptureIncomplete`.
            Ignored without ``capture``.
    """

    lookback_days: int = 30
    max_parallelism: int = 4
    domains: list[str] | None = None
    exact_packs: list[str] | None = None
    data_only: bool = False
    output_dir: str = "./discovery_output"
    llm_model: str | None = None
    llm_temperature: float = 0.3
    min_dbu_threshold: float = 10.0
    enable_cache: bool = True
    cache_freshness_floor_s: int = 900
    source: str = "external"
    internal_workspace_ids: tuple[str, ...] | None = None
    internal_account: str | None = None
    discovery_mode: DiscoveryMode = DiscoveryMode.GENERAL
    timeout_retries: int = DEFAULT_TIMEOUT_RETRIES
    authorized_workspace_ids: tuple[str, ...] | None = None
    sink: ArtifactSink | None = None
    capture: bool = False
    capture_sink: ArtifactSink | None = None
    deadline: float | None = None


@dataclass
class EngineResult:
    """Result of a discovery engine run.

    Args:
        report: The final discovery report (None if data_only).
        pack_results: Raw query pack results.
        domain_analyses: Per-domain LLM analyses (empty if data_only).
        audit_result: The audit query result.
        output_files: Paths to written output files.
        trace_id: Trace ID for this run.
        elapsed_ms: Total wall-clock time.
        errors: Errors encountered during the run.
        filtered_queries: Queries in the selected packs that were NOT scheduled
            because their ``discovery_mode`` (e.g. DEEP_DIVE under GENERAL) is
            not enabled for this run. They never execute, so they are absent
            from ``pack_results`` and would otherwise make the scheduled total
            disagree with the executed total.
        products_without_packs: Products detected by P-AUDIT01 for which no
            query pack is registered (D10).  These are surfaced in the
            ``data.skipped`` envelope field with a coverage-gap reason so a
            host knows the product was seen but not specifically analyzed.
        resumed: On a ``capture`` run, ``{"queries_reused": n}`` (plus
            ``fresh_reason`` when an earlier record could not be used); else None.
    """

    report: DiscoveryReport | None = None
    pack_results: list[PackResult] = field(default_factory=list)
    domain_analyses: list[DomainAnalysis] = field(default_factory=list)
    audit_result: QueryResult | None = None
    output_files: list[str] = field(default_factory=list)
    trace_id: str = ""
    elapsed_ms: float = 0.0
    errors: list[str] = field(default_factory=list)
    filtered_queries: int = 0
    products_without_packs: list[str] = field(default_factory=list)
    resumed: dict[str, Any] | None = None


@dataclass
class PlanResult:
    """Selection-only result from :meth:`DiscoveryEngine.plan` (no packs run).

    Args:
        products: Active products with DBU totals from the audit.
        selection: Recommended domains and packs (no execution).
        audit_succeeded: Whether the audit query returned data.
        trace_id: Trace ID for this plan run.
    """

    products: dict[str, float]
    selection: PlanSelection
    audit_succeeded: bool
    trace_id: str


class DiscoveryEngine:
    """Orchestrates the full workspace discovery pipeline.

    Args:
        sql_executor: Client for executing SQL queries.
        llm_client: LLM client for analysis and synthesis (optional if data_only).
        config: Engine configuration.
        query_registry: Query pack registry (uses default if None).
        workspace_id_probe: Async callable returning the connected workspace's
            server ID. Required when ``config.authorized_workspace_ids`` is set.
    """

    #: Seconds between Phase-2 ``query_heartbeat`` progress events, emitted even
    #: when no query completes so a long quiet stretch never looks stalled.
    _HEARTBEAT_INTERVAL_S: float = 30.0

    def __init__(
        self,
        sql_executor: SQLExecutor,
        llm_client: Any | None = None,
        config: EngineConfig | None = None,
        query_registry: QueryPackRegistry | None = None,
        workspace_id_probe: WorkspaceIdProbe | None = None,
    ) -> None:
        self._config = config or EngineConfig()
        self._sql_executor = sql_executor
        self._workspace_id_probe = workspace_id_probe
        self._llm_client = llm_client
        self._query_registry = query_registry or create_default_registry()

        self._pack_executor = QueryPackExecutor(
            sql_executor=sql_executor,
            max_parallelism=self._config.max_parallelism,
            default_lookback_days=self._config.lookback_days,
            enable_cache=self._config.enable_cache,
            cache_freshness_floor_s=self._config.cache_freshness_floor_s,
            source=self._resolve_source(),
            discovery_mode=self._config.discovery_mode,
            timeout_retries=self._config.timeout_retries,
        )

        # Packs phase 1 already ran (the audit), kept so phase 2 never runs them again.
        self._phase1_results: dict[str, PackResult] = {}

        self._heuristic_registry = create_default_heuristic_registry()
        self._prompt_builder = PromptBuilder()
        self._output_formatter = OutputFormatter()

    def _resolve_source(self) -> QuerySource | None:
        """Select the discovery ``QuerySource`` for this run.

        ``"external"`` returns ``None`` so the executor keeps its default
        ``SystemTablesSource`` (byte-identical to today). ``"internal"`` resolves
        the gated ``MirrorSource`` through the port-adapter registry/gate, scoped
        to ``internal_workspace_ids``; an absent provider/closed gate raises.
        """
        if self._config.source == "external":
            if self._config.authorized_workspace_ids is not None:
                return ScopedSystemTablesSource(
                    self._sql_executor, self._config.authorized_workspace_ids
                )
            return None
        if self._config.source == "internal":
            return resolve_internal_source(
                self._config.internal_workspace_ids,
                account=self._config.internal_account,
            )
        raise ValueError(f"unknown discovery source: {self._config.source!r}")

    async def _require_authorized_workspace(self) -> None:
        """Refuse the run unless the connected workspace is in the authorized scope.

        Applies only to the public customer source with ``authorized_workspace_ids``
        set. Runs before any query; raises rather than reading anything.

        Raises:
            WorkspaceAuthorizationError: empty scope, no way to read the connected
                workspace's ID, or that ID is not authorized.
        """
        authorized = self._config.authorized_workspace_ids
        if authorized is None or self._config.source != "external":
            return
        if not authorized:
            raise WorkspaceAuthorizationError(
                "the run's authorized scope names no workspace — refusing to run"
            )
        if self._workspace_id_probe is None:
            raise WorkspaceAuthorizationError(
                "cannot verify the connected workspace's ID against the authorized "
                "scope — refusing to run"
            )
        connected = str(await self._workspace_id_probe())
        if connected not in authorized:
            raise WorkspaceAuthorizationError(
                f"connected workspace {connected} is not in the run's authorized "
                f"scope ({', '.join(authorized)}) — refusing to run"
            )

    async def run(
        self,
        on_progress: ProgressCallback | None = None,
    ) -> EngineResult:
        """Execute the full discovery pipeline.

        Args:
            on_progress: Optional callback ``(phase, details)`` fired at each
                phase boundary so callers can render live status.

        Returns:
            EngineResult with report, raw data, and metadata.

        Raises:
            CaptureIncomplete: A ``capture`` run reached ``deadline``; its
                progress is saved and the same run resumes it.
        """
        trace_id = str(uuid.uuid4())
        start = time.monotonic()
        _emit = on_progress or (lambda _phase, _info: None)

        result = EngineResult(trace_id=trace_id)
        self._phase1_results = {}

        await self._require_authorized_workspace()

        capture = await self._open_capture()
        # Queries the capture has to finish (audit + scheduled); None until the
        # packs are selected.
        total: int | None = None

        logger.info(
            "discovery_pipeline_started",
            trace_id=trace_id,
            lookback_days=self._config.lookback_days,
            max_parallelism=self._config.max_parallelism,
            data_only=self._config.data_only,
        )

        try:
            if self._config.exact_packs is not None:
                # --only: run exactly these packs; no audit, no selection.
                _emit("queries_start", {"exact_packs": self._config.exact_packs})
                packs = self._query_registry.resolve_exact(self._config.exact_packs)
                total = sum(len(self._pack_executor.eligible_queries(p)) for p in packs)
                pack_results = await self._budgeted(
                    self._pack_executor.execute_packs(packs)
                )
                result.pack_results = pack_results
                result.resumed = await self._close_capture(capture)
                _emit("queries_done", {"packs": len(pack_results)})
                result.elapsed_ms = (time.monotonic() - start) * 1000
                return result

            # Phase 1: Audit
            _emit("audit_start", {})
            audit_result = await self._budgeted(self._run_audit(trace_id))
            result.audit_result = audit_result
            active_products = self._extract_products(audit_result)
            _emit(
                "audit_done",
                {
                    "products": list(active_products.keys()),
                    "succeeded": audit_result.succeeded,
                },
            )

            # Phase 2: Query execution
            selected_packs = self._query_registry.get_packs_for_products(
                active_products=active_products,
                min_dbu_threshold=self._config.min_dbu_threshold,
                target_domains=list(self._config.domains)
                if self._config.domains is not None
                else None,
            )
            # Count only queries that will actually run: the executor drops
            # queries whose discovery_mode isn't enabled (DEEP_DIVE under
            # GENERAL), so len(p.queries) would overstate what executes.
            scheduled = sum(
                len(self._pack_executor.eligible_queries(p))
                for p in selected_packs
                if p.pack_id not in self._phase1_results
            )
            # A selected pack phase 1 already ran (the audit) keeps its results,
            # which the final counts include, so the banner counts them too.
            already_ran = sum(
                len(self._phase1_results[p.pack_id].results)
                for p in selected_packs
                if p.pack_id in self._phase1_results
            )
            defined = sum(
                len(p.queries)
                for p in selected_packs
                if p.pack_id not in self._phase1_results
            )
            result.filtered_queries = defined - scheduled
            total = (capture.done if capture is not None else 0) + scheduled

            # D10: products detected by the audit that have no dedicated query
            # pack. Derived from the single routing source of truth
            # (PRODUCT_TO_DOMAIN_PACKS ∩ registered packs), NOT from per-pack
            # gating_products and NOT from this run's --domains filter or
            # post-execution results — a domain filter or a query failure must
            # never be mistaken for "no coverage" (issue #17). Below-threshold
            # products are excluded here (logged separately as
            # products_below_dbu_threshold), so only genuinely-unmapped products
            # surface as a coverage gap.
            result.products_without_packs = (
                self._query_registry.products_without_coverage(
                    active_products,
                    min_dbu_threshold=self._config.min_dbu_threshold,
                )
            )

            _emit(
                "queries_start",
                {
                    "pack_count": len(selected_packs),
                    "query_count": scheduled + already_ran,
                    "filtered_count": result.filtered_queries,
                },
            )

            # D4: per-query liveness callback — fires every 10 completed
            # queries or every 30 s (whichever comes first) so the CLI can
            # emit "N/M queries done" on stderr without waiting for the full
            # Phase 2 to finish.
            _q_done = 0
            _q_last_emit = time.monotonic()

            def _on_query_done(qid: str, domain: str) -> None:  # noqa: ARG001
                nonlocal _q_done, _q_last_emit
                _q_done += 1
                _now = time.monotonic()
                if _q_done % 10 == 0 or _now - _q_last_emit >= 30.0:
                    _q_last_emit = _now
                    _emit(
                        "query_progress",
                        {
                            "done": _q_done,
                            "total": scheduled,
                            "elapsed_s": round(_now - start, 1),
                        },
                    )

            # D3: per-pack "done" events + a timed heartbeat (elapsed, done/total,
            # in-flight) that fires even with no completions. The heartbeat task
            # sleeps between beats (no busy-loop) and is always cancelled when
            # Phase 2 ends, success or failure.
            _packs_done = 0

            def _on_pack_done(pr: PackResult) -> None:
                nonlocal _packs_done
                _packs_done += 1
                _emit(
                    "pack_done",
                    {
                        "pack_id": pr.pack_id,
                        "domain": pr.domain,
                        "succeeded": sum(1 for qr in pr.results if qr.succeeded),
                        "skipped": sum(
                            1 for qr in pr.results if qr.skipped and not qr.succeeded
                        ),
                        "failed": sum(
                            1
                            for qr in pr.results
                            if not qr.succeeded and not qr.skipped
                        ),
                        "packs_done": _packs_done,
                        "packs_total": len(selected_packs),
                        "elapsed_s": round(time.monotonic() - start, 1),
                        # The finished PackResult itself, so a caller can persist
                        # this pack's rows as soon as it completes (B3).
                        "pack_result": pr,
                    },
                )

            async def _heartbeat() -> None:
                while True:
                    await asyncio.sleep(self._HEARTBEAT_INTERVAL_S)
                    ids = tuple(getattr(self._pack_executor, "in_flight_ids", ()))
                    _emit(
                        "query_heartbeat",
                        {
                            "done": _q_done,
                            "total": scheduled,
                            "in_flight": getattr(self._pack_executor, "in_flight", 0),
                            # Which statements are still running (oldest first),
                            # truncated so the line stays readable.
                            "in_flight_ids": list(ids[:MAX_IN_FLIGHT_IDS_SHOWN]),
                            "in_flight_more": max(
                                0, len(ids) - MAX_IN_FLIGHT_IDS_SHOWN
                            ),
                            "packs_done": _packs_done,
                            "packs_total": len(selected_packs),
                            "elapsed_s": round(time.monotonic() - start, 1),
                        },
                    )

            heartbeat = asyncio.create_task(_heartbeat())
            try:
                pack_results = await self._budgeted(
                    self._run_queries(
                        active_products,
                        trace_id,
                        on_query_done=_on_query_done,
                        on_pack_done=_on_pack_done,
                    )
                )
            finally:
                heartbeat.cancel()
                # A progress-callback error must never fail the discovery run.
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await heartbeat
            result.pack_results = pack_results
            result.resumed = await self._close_capture(capture)

            total_queries = sum(len(pr.results) for pr in pack_results)
            all_results = [qr for pr in pack_results for qr in pr.results]
            succeeded = sum(1 for qr in all_results if qr.succeeded)
            skipped = sum(1 for qr in all_results if qr.skipped and not qr.succeeded)
            _emit(
                "queries_done",
                {
                    "packs": len(pack_results),
                    "queries": total_queries,
                    "succeeded": succeeded,
                    "skipped": skipped,
                    # Attempted-and-failed only — skips are an expected coverage
                    # gap, not failures.
                    "failed": total_queries - succeeded - skipped,
                },
            )

            if self._config.data_only:
                logger.info(
                    "discovery_data_only_complete",
                    trace_id=trace_id,
                    packs=len(pack_results),
                )
            else:
                if self._llm_client is None:
                    result.errors.append(
                        "LLM client not provided — skipping analysis and synthesis."
                    )
                else:
                    # Phase 3: Domain analysis
                    domain_results = self._group_by_domain(pack_results)
                    domains = list(domain_results.keys())
                    _emit("analysis_start", {"domains": domains})
                    domain_analyses = await self._run_analysis(
                        domain_results, trace_id, on_progress=on_progress
                    )
                    result.domain_analyses = domain_analyses
                    _emit(
                        "analysis_done",
                        {
                            "domains": len(domain_analyses),
                            "grades": {a.domain: a.grade for a in domain_analyses},
                        },
                    )

                    # Phase 4: Synthesis + output
                    _emit("synthesis_start", {"domains": len(domain_analyses)})
                    context = self._build_context(pack_results, domain_analyses)
                    report = await self._run_synthesis(
                        domain_analyses, audit_result, context, trace_id
                    )
                    result.report = report

                    _emit("output_start", {})
                    if self._config.sink is not None:
                        output_files: list[Any] = self._output_formatter.write_to_sink(
                            report, self._config.sink
                        )
                    else:
                        output_files = await self._output_formatter.write_to_directory(
                            report, self._config.output_dir
                        )
                    result.output_files = [str(p) for p in output_files]
                    _emit("output_done", {"files": len(output_files)})

        except _BudgetSpent:
            raise await self._capture_incomplete(capture, total) from None
        except Exception as exc:  # noqa: BLE001 - discovery pipeline boundary
            refusal = _storage_refusal(exc)
            if refusal is not None:
                # A refused local write or a run-sink failure fails the run; it
                # must never become a "Pipeline error" line on an ok result.
                raise refusal from None
            result.errors.append(f"Pipeline error: {exc}")
            logger.exception(
                "discovery_pipeline_failed",
                trace_id=trace_id,
                error=str(exc),
            )

        result.elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "discovery_pipeline_complete",
            trace_id=trace_id,
            elapsed_ms=round(result.elapsed_ms, 1),
            packs_executed=len(result.pack_results),
            domains_analyzed=len(result.domain_analyses),
            errors=len(result.errors),
            has_report=result.report is not None,
        )

        return result

    def _capture_key(self) -> dict[str, Any]:
        """What a saved capture must match to be resumed (JSON-comparable)."""
        cfg = self._config
        scope = (
            cfg.internal_workspace_ids
            if cfg.source == "internal"
            else cfg.authorized_workspace_ids
        )
        catalog = [
            [p.pack_id, sorted(q.query_id for q in p.queries)]
            for p in sorted(self._query_registry.all_packs, key=lambda p: p.pack_id)
        ]
        return {
            "run_id": self._capture_store.run_id if self._capture_store else None,
            "source": cfg.source,
            "scope": {
                "workspace_ids": sorted(scope) if scope is not None else None,
                "account": cfg.internal_account if cfg.source == "internal" else None,
            },
            "lookback_days": cfg.lookback_days,
            "discovery_mode": str(cfg.discovery_mode),
            "domains": sorted(cfg.domains) if cfg.domains is not None else None,
            "exact_packs": list(cfg.exact_packs)
            if cfg.exact_packs is not None
            else None,
            "min_dbu_threshold": cfg.min_dbu_threshold,
            "catalog": sql_digest(json.dumps(catalog)),
        }

    @property
    def _capture_store(self) -> ArtifactSink | None:
        """The sink the capture record lives in (``capture_sink``, else ``sink``)."""
        return self._config.capture_sink or self._config.sink

    async def _open_capture(self) -> CaptureLog | None:
        """Open the run's capture record and hand it to the pack executor."""
        store = self._capture_store
        if not self._config.capture or store is None:
            return None
        capture = await CaptureLog.open(store, self._capture_key())
        if capture.fresh_reason:
            logger.warning("discovery_capture_fresh", reason=capture.fresh_reason)
        self._pack_executor.capture = capture
        return capture

    async def _close_capture(self, capture: CaptureLog | None) -> dict[str, Any] | None:
        """Save the capture record; its ``resumed`` summary (``None`` when off)."""
        if capture is None:
            return None
        await capture.flush()
        logger.info("discovery_capture_saved", **capture.summary())
        return capture.summary()

    async def _budgeted(self, work: Awaitable[_T]) -> _T:
        """Await ``work`` within the capture deadline; :class:`_BudgetSpent` past it."""
        deadline = self._config.deadline
        if deadline is None or self._pack_executor.capture is None:
            return await work
        loop = asyncio.get_running_loop()
        budget = asyncio.timeout_at(loop.time() + (deadline - time.monotonic()))
        try:
            async with budget:
                return await work
        except TimeoutError:
            if not budget.expired():
                raise
            raise _BudgetSpent from None

    async def _capture_incomplete(
        self, capture: CaptureLog | None, total: int | None
    ) -> CaptureIncomplete:
        """Stop in-flight statements, save progress; the error to leave with."""
        await asyncio.to_thread(self._pack_executor.cancel_in_flight)
        done = reused = 0
        if capture is not None:
            await capture.flush()
            done, reused = capture.done, capture.reused
        remaining = None if total is None else max(0, total - done)
        logger.warning(
            "discovery_capture_incomplete",
            done=done,
            remaining=remaining,
            reused=reused,
        )
        return CaptureIncomplete(done=done, remaining=remaining, reused=reused)

    async def plan(self) -> PlanResult:
        """Run the audit and compute recommended domains WITHOUT executing packs.

        Returns:
            PlanResult with active products, recommended selection, and trace ID.
        """
        trace_id = str(uuid.uuid4())
        await self._require_authorized_workspace()
        audit_result = await self._run_audit(trace_id)
        products = self._extract_products(audit_result)
        selection = self._query_registry.select_for_plan(
            active_products=products,
            min_dbu_threshold=self._config.min_dbu_threshold,
        )
        return PlanResult(
            products=products,
            selection=selection,
            audit_succeeded=audit_result.succeeded,
            trace_id=trace_id,
        )

    async def _run_audit(self, trace_id: str) -> QueryResult:
        """Phase 1: Execute the audit query to discover active products.

        Args:
            trace_id: Trace ID for observability.

        Returns:
            QueryResult from the audit pack.
        """
        logger.info("discovery_phase_1_audit", trace_id=trace_id)

        audit_packs = [
            p for p in self._query_registry.all_packs if p.pack_id == "audit"
        ]

        if not audit_packs:
            return QueryResult(
                query_id="P-AUDIT01",
                domain="audit",
                data=None,
                error="No audit pack registered",
            )

        results = await self._pack_executor.execute_packs(audit_packs)
        self._phase1_results = {pr.pack_id: pr for pr in results}

        for pr in results:
            for qr in pr.results:
                if qr.query_id == "P-AUDIT01":
                    return qr

        return QueryResult(
            query_id="P-AUDIT01",
            domain="audit",
            data=None,
            error="Audit query not found in results",
        )

    def _extract_products(self, audit_result: QueryResult) -> dict[str, float]:
        """Extract active products with DBU totals from the audit result.

        Args:
            audit_result: Result of the P-AUDIT01 query.

        Returns:
            Mapping of product name to total DBUs. Empty if audit failed.
        """
        if not audit_result.succeeded or audit_result.data is None:
            logger.warning(
                "audit_failed_running_all_packs",
                error=audit_result.error,
            )
            return {}

        col = "billing_origin_product"
        # P-AUDIT01 was renamed total_dbus → total_usage (W3: usage_unit in grain,
        # so each row is a single-unit slice; the old name implied DBU but could be DSU).
        # Support both names: new audits emit total_usage; old cached results have total_dbus.
        dbu_col = (
            "total_usage"
            if "total_usage" in audit_result.data.columns
            else "total_dbus"
        )
        if col not in audit_result.data.columns:
            return {}

        if dbu_col not in audit_result.data.columns:
            return dict.fromkeys(audit_result.data[col].unique().to_list(), 0.0)

        product_dbus: dict[str, float] = {}
        for row in audit_result.data.iter_rows(named=True):
            product = row[col]
            dbus = float(row.get(dbu_col, 0.0) or 0.0)
            product_dbus[product] = product_dbus.get(product, 0.0) + dbus
        return product_dbus

    async def _run_queries(
        self,
        active_products: dict[str, float],
        trace_id: str,
        on_query_done: Callable[[str, str], None] | None = None,
        on_pack_done: Callable[[PackResult], None] | None = None,
    ) -> list[PackResult]:
        """Phase 2: Execute conditional query packs.

        Args:
            active_products: Products with DBU totals from audit.
            trace_id: Trace ID for observability.
            on_query_done: Optional per-query completion callback threaded into
                the pack executor for liveness progress (D4).
            on_pack_done: Optional per-pack completion callback (D3).

        Returns:
            List of pack results.
        """
        logger.info(
            "discovery_phase_2_queries",
            trace_id=trace_id,
            active_products=len(active_products),
        )

        packs = self._query_registry.get_packs_for_products(
            active_products=active_products,
            min_dbu_threshold=self._config.min_dbu_threshold,
            target_domains=list(self._config.domains)
            if self._config.domains is not None
            else None,
        )

        # The audit is an always-run pack: keep phase 1's result, don't run it again.
        ran = await self._pack_executor.execute_packs(
            [p for p in packs if p.pack_id not in self._phase1_results],
            on_query_done=on_query_done,
            on_pack_done=on_pack_done,
        )
        by_id = {pr.pack_id: pr for pr in ran}
        kept = [
            self._phase1_results[p.pack_id]
            for p in packs
            if p.pack_id in self._phase1_results
        ]
        if on_pack_done is not None:
            for pr in kept:
                on_pack_done(pr)
        return [
            self._phase1_results.get(p.pack_id) or by_id[p.pack_id]
            for p in packs
            if p.pack_id in self._phase1_results or p.pack_id in by_id
        ]

    async def _run_analysis(
        self,
        domain_results: dict[str, list[PackResult]],
        trace_id: str,
        on_progress: ProgressCallback | None = None,
    ) -> list[DomainAnalysis]:
        """Phase 3: Run heuristic + LLM analysis per domain.

        Args:
            domain_results: Pack results grouped by domain.
            trace_id: Trace ID for observability.
            on_progress: Optional callback for per-domain progress.

        Returns:
            List of domain analyses.
        """
        logger.info(
            "discovery_phase_3_analysis",
            trace_id=trace_id,
            domains=list(domain_results.keys()),
        )

        assert self._llm_client is not None

        analyzer = DomainAnalyzer(
            llm_client=self._llm_client,
            heuristic_registry=self._heuristic_registry,
            prompt_builder=self._prompt_builder,
            max_parallelism=self._config.max_parallelism,
            model=self._config.llm_model,
            temperature=self._config.llm_temperature,
        )

        return await analyzer.analyze_all_domains(
            domain_results,
            trace_id=trace_id,
            on_domain_complete=on_progress,
        )

    async def _run_synthesis(
        self,
        domain_analyses: list[DomainAnalysis],
        audit_result: QueryResult,  # noqa: ARG002
        context: AnalysisContext,
        trace_id: str,
    ) -> DiscoveryReport:
        """Phase 4: Assemble domain analyses into final report.

        Deterministically builds report cards, sorts findings, and
        optionally calls the LLM for a lightweight executive summary.

        Args:
            domain_analyses: Completed domain analyses.
            audit_result: Audit query result.
            context: Analysis context metadata.
            trace_id: Trace ID for observability.

        Returns:
            Complete DiscoveryReport.
        """
        logger.info(
            "discovery_phase_4_assembly",
            trace_id=trace_id,
            domains=len(domain_analyses),
        )

        assembler = ReportAssembler(
            llm_client=self._llm_client,
            model=self._config.llm_model,
            temperature=self._config.llm_temperature,
        )

        return await assembler.assemble(
            domain_analyses=domain_analyses,
            context=context,
            trace_id=trace_id,
        )

    def _group_by_domain(
        self, pack_results: list[PackResult]
    ) -> dict[str, list[PackResult]]:
        """Group pack results by domain.

        Args:
            pack_results: Flat list of pack results.

        Returns:
            Dict mapping domain name to its pack results.
        """
        grouped: dict[str, list[PackResult]] = {}
        for pr in pack_results:
            if pr.domain == "audit":
                continue
            grouped.setdefault(pr.domain, []).append(pr)
        return grouped

    def _build_context(
        self,
        pack_results: list[PackResult],
        domain_analyses: list[DomainAnalysis],
    ) -> AnalysisContext:
        """Build analysis context from pipeline results.

        Args:
            pack_results: All pack results.
            domain_analyses: Completed domain analyses.

        Returns:
            AnalysisContext with pipeline metadata.
        """
        total_queries = sum(len(pr.results) for pr in pack_results)
        total_time = sum(
            qr.execution_time_ms for pr in pack_results for qr in pr.results
        )

        return AnalysisContext(
            lookback_days=self._config.lookback_days,
            analysis_timestamp=datetime.now(UTC).isoformat(),
            domains_analyzed=[a.domain for a in domain_analyses],
            total_queries_executed=total_queries,
            total_execution_time_ms=total_time,
        )
