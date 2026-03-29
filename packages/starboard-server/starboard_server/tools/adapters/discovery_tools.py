"""Discovery tool adapters — expose the DiscoveryEngine phases as agent tools.

Provides 4 granular tools matching the engine's 4-phase pipeline, allowing the
discovery agent to reason between phases and adapt its workflow dynamically:

1. ``discover_active_products`` — Phase 1 (Audit)
2. ``run_discovery_queries``    — Phase 2 (Query)
3. ``analyze_discovery_domain`` — Phase 3 (Analyze, per-domain)
4. ``synthesize_discovery_report`` — Phase 4 (Synthesize)

Also retains the legacy ``run_workspace_discovery`` for backward-compatible
programmatic/CLI-direct use.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from starboard_core.domain.models.discovery.analysis import DomainAnalysis
from starboard_core.domain.models.discovery.query import PackResult
from starboard_core.domain.models.discovery.report import AnalysisContext

from starboard_server.discovery.analyzer import DomainAnalyzer, build_fallback_analysis
from starboard_server.discovery.engine import DiscoveryEngine, EngineConfig
from starboard_server.discovery.executor import QueryPackExecutor, SQLExecutor
from starboard_server.discovery.heuristics import create_default_heuristic_registry
from starboard_server.discovery.output.formatters import OutputFormatter
from starboard_server.discovery.prompts.domain_analysis import PromptBuilder
from starboard_server.discovery.query_packs.registry import create_default_registry
from starboard_server.discovery.synthesizer import ReportAssembler
from starboard_server.infra.core.config import EnvConfig, get_config
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.adapters.base import BaseToolAdapter

if TYPE_CHECKING:
    from starboard_core.domain.models.discovery.report import DiscoveryReport

logger = get_logger(__name__)


def _build_report_summary(report: DiscoveryReport) -> dict[str, Any]:
    """Build a detailed report summary dict from a DiscoveryReport.

    Shared between the granular Phase 4 tool and the legacy monolithic tool
    to avoid duplicating the serialisation logic.

    Args:
        report: Completed discovery report with executive summary.

    Returns:
        Dict with overview, per-domain report cards with findings,
        top priorities, and recommended actions.
    """
    return {
        "overview": report.executive_summary.overview,
        "primary_risks": report.executive_summary.primary_risks,
        "report_cards": [
            {
                "domain": rc.domain,
                "grade": rc.grade,
                "score": rc.score,
                "discussion": rc.discussion,
                "finding_count": len(rc.top_findings),
                "top_findings": [
                    {
                        "finding_id": f.finding_id,
                        "title": f.title,
                        "priority": f.priority,
                        "impact": f.impact,
                        "description": f.description,
                        "evidence": [
                            {
                                "source_query_id": e.source_query_id,
                                "excerpt": e.excerpt,
                                "metric_name": e.metric_name,
                                "metric_value": e.metric_value,
                            }
                            for e in f.evidence[:3]
                        ],
                        "remediation": {
                            "immediate": f.remediation.immediate[:3],
                            "medium_term": f.remediation.medium_term[:2],
                        },
                    }
                    for f in rc.top_findings[:15]
                ],
            }
            for rc in report.executive_summary.report_cards
        ],
        "domain_summaries": [
            {
                "domain": da.domain,
                "grade": da.grade,
                "score": da.score,
                "summary": da.summary,
                "observations": da.observations[:10],
                "patterns": da.patterns[:5],
                "recommended_actions": da.recommended_actions[:10],
            }
            for da in report.domain_analyses
        ],
        "top_findings": [
            {
                "finding_id": f.finding_id,
                "title": f.title,
                "priority": f.priority,
                "impact": f.impact,
                "domain": f.domain,
                "description": f.description,
                "expected_outcome": f.expected_outcome,
            }
            for f in report.top_priorities[:20]
        ],
        "top_actions": report.executive_summary.top_actions[:10],
    }


class DiscoveryTools(BaseToolAdapter):
    """Agent tool adapters for workspace discovery.

    Wraps the discovery pipeline components to expose each phase as an
    independently callable agent tool, enabling step-by-step reasoning.

    Args:
        sql_executor: SQL executor for Databricks queries.
        llm_client: LLM client for analysis and synthesis.
        env_config: Environment configuration with discovery settings.
    """

    def __init__(
        self,
        sql_executor: SQLExecutor,
        llm_client: Any | None = None,
        env_config: EnvConfig | None = None,
    ) -> None:
        super().__init__()
        self._sql_executor = sql_executor
        self._llm_client = llm_client
        self._env_config = env_config or get_config()

        self._query_registry = create_default_registry()
        self._heuristic_registry = create_default_heuristic_registry()
        self._prompt_builder = PromptBuilder()
        self._output_formatter = OutputFormatter()

        # Shared state across tool calls within a single agent session.
        # The agent calls tools sequentially within one reasoning loop, so
        # these are safe to share without locking.
        self._active_products: list[str] | None = None
        self._pack_results: list[PackResult] | None = None
        self._domain_analyses: list[DomainAnalysis] = []
        self._trace_id: str = ""
        self._lookback_days: int = self._env_config.discovery_lookback_days
        self._discovery_markdown: str | None = None

        # Background analysis state for async polling pattern.
        self._bg_task: asyncio.Task[None] | None = None
        self._bg_completed: dict[str, DomainAnalysis] = {}
        self._bg_failed: list[dict[str, str]] = []
        self._bg_target_domains: list[str] = []
        self._bg_start: float = 0.0

    def get_discovery_markdown(self) -> str | None:
        """Return the rendered discovery report markdown, if available.

        Populated after ``synthesize_discovery_report`` completes. Used by
        the reasoning loop to inject pre-rendered content into the agent
        output, bypassing LLM summarization.
        """
        return self._discovery_markdown

    # ------------------------------------------------------------------
    # Phase 1: Audit — discover active products
    # ------------------------------------------------------------------

    async def discover_active_products(
        self,
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """Audit the workspace to discover active Databricks products.

        Queries ``system.billing.usage`` to determine which products
        (JOBS, SQL, SERVING, etc.) have been active in the lookback window.
        The result drives which query packs run in Phase 2.

        Args:
            lookback_days: Time window for the audit (30, 60, or 90 days).

        Returns:
            Dict with ``active_products``, ``available_domains``, and metadata.
        """
        self._trace_id = str(uuid.uuid4())
        self._lookback_days = lookback_days
        start = time.monotonic()

        pack_executor = QueryPackExecutor(
            sql_executor=self._sql_executor,
            max_parallelism=self._env_config.discovery_max_parallelism,
            default_lookback_days=lookback_days,
        )

        audit_packs = [
            p for p in self._query_registry.all_packs if p.pack_id == "audit"
        ]

        if not audit_packs:
            return {
                "status": "error",
                "error": "No audit pack registered",
                "error_code": "tool_error",
                "active_products": [],
            }

        results = await pack_executor.execute_packs(audit_packs)

        audit_result = None
        for pr in results:
            for qr in pr.results:
                if qr.query_id == "P-AUDIT01":
                    audit_result = qr
                    break

        if (
            audit_result is None
            or not audit_result.succeeded
            or audit_result.data is None
        ):
            self._active_products = []
            error_msg = audit_result.error if audit_result else "Audit query not found"
            return {
                "status": "completed_with_warnings",
                "trace_id": self._trace_id,
                "warning": f"Audit query issue: {error_msg}. Will run default packs.",
                "active_products": [],
                "available_domains": ["billing", "governance", "migration"],
                "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
            }

        col = "billing_origin_product"
        if col in audit_result.data.columns:
            self._active_products = audit_result.data[col].unique().to_list()
        else:
            self._active_products = []

        # Determine which domains will be analyzed
        selected_packs = self._query_registry.get_packs_for_products(
            active_products=set(self._active_products),
        )
        available_domains = sorted(
            {p.domain for p in selected_packs if p.domain != "audit"}
        )

        return {
            "status": "completed",
            "trace_id": self._trace_id,
            "lookback_days": lookback_days,
            "active_products": self._active_products,
            "product_count": len(self._active_products),
            "available_domains": available_domains,
            "pack_count": len(selected_packs),
            "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
        }

    # ------------------------------------------------------------------
    # Phase 2: Query — execute discovery query packs
    # ------------------------------------------------------------------

    async def run_discovery_queries(
        self,
        domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute discovery query packs against system tables.

        Runs SQL queries across selected domains. Must be called after
        ``discover_active_products`` so the pack selection is informed by
        which products are active.

        Args:
            domains: Optional list of specific domains to query.
                     If omitted, queries all domains relevant to active products.

        Returns:
            Dict with per-domain query result summaries and metadata.
        """
        if self._active_products is None:
            return {
                "status": "error",
                "error": "Call discover_active_products first to detect active products.",
                "error_code": "tool_error",
            }

        start = time.monotonic()

        pack_executor = QueryPackExecutor(
            sql_executor=self._sql_executor,
            max_parallelism=self._env_config.discovery_max_parallelism,
            default_lookback_days=self._lookback_days,
        )

        packs = self._query_registry.get_packs_for_products(
            active_products=set(self._active_products),
            include=domains,
        )

        self._pack_results = await pack_executor.execute_packs(packs)

        # Build per-domain summary
        domain_summaries: dict[str, dict[str, Any]] = {}
        for pr in self._pack_results:
            if pr.domain == "audit":
                continue
            succeeded = sum(1 for qr in pr.results if qr.succeeded)
            failed = sum(1 for qr in pr.results if not qr.succeeded)
            total_rows = sum(qr.row_count for qr in pr.results if qr.succeeded)
            domain_summaries.setdefault(
                pr.domain,
                {
                    "queries_succeeded": 0,
                    "queries_failed": 0,
                    "total_rows": 0,
                },
            )
            domain_summaries[pr.domain]["queries_succeeded"] += succeeded
            domain_summaries[pr.domain]["queries_failed"] += failed
            domain_summaries[pr.domain]["total_rows"] += total_rows

        total_queries = sum(len(pr.results) for pr in self._pack_results)
        total_succeeded = sum(
            1 for pr in self._pack_results for qr in pr.results if qr.succeeded
        )

        domains_ready = list(domain_summaries.keys())

        return {
            "status": "completed",
            "trace_id": self._trace_id,
            "packs_executed": len(self._pack_results),
            "total_queries": total_queries,
            "queries_succeeded": total_succeeded,
            "queries_failed": total_queries - total_succeeded,
            "domains_with_data": domains_ready,
            "domain_summaries": domain_summaries,
            "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
            "next_step": (
                "Call analyze_discovery_domain with "
                "domains=<domains_with_data list> to analyze all "
                "domains in a single batch call. The server runs all "
                "domains in parallel internally."
            ),
            "next_tool": {
                "tool": "analyze_discovery_domain",
                "arguments": {"domains": domains_ready},
            },
            "parallel_calls": [
                {
                    "tool": "analyze_discovery_domain",
                    "arguments": {"domain": d},
                }
                for d in domains_ready
            ],
        }

    # ------------------------------------------------------------------
    # Phase 3: Analyze — run heuristics + LLM for one or more domains
    # ------------------------------------------------------------------

    async def analyze_discovery_domain(
        self,
        domain: str | None = None,
        domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """Analyze one or more domains using heuristics and LLM reasoning.

        Applies deterministic heuristic rules first, then uses the LLM for
        deeper analysis. Produces a grade (A-F), score, findings, and
        recommendations per domain.

        For batch mode, pass all domains from ``run_discovery_queries``
        ``domains_with_data`` via ``domains``.  All domains are analyzed
        in parallel (bounded by ``discovery_max_parallelism``).

        Must be called after ``run_discovery_queries``.

        Args:
            domain: Single domain to analyze (e.g. ``billing``).
            domains: List of domains to analyze in one batch call.

        Returns:
            Dict with per-domain grades, scores, findings, and recommendations.
        """
        if self._pack_results is None:
            return {
                "status": "error",
                "error": "Call run_discovery_queries first to gather data.",
                "error_code": "tool_error",
            }

        target_domains = self._resolve_target_domains(domain, domains)
        if isinstance(target_domains, dict):
            return target_domains  # error response
        is_batch = len(target_domains) > 1

        start = time.monotonic()

        domain_packs: dict[str, list[PackResult]] = {}
        skipped: list[str] = []
        for d in target_domains:
            packs = [pr for pr in self._pack_results if pr.domain == d]
            if packs:
                domain_packs[d] = packs
            else:
                skipped.append(d)

        if not domain_packs:
            resp: dict[str, Any] = {
                "status": "no_data",
                "message": "No query data available for any requested domain.",
            }
            if is_batch:
                resp["domains"] = target_domains
            else:
                resp["domain"] = target_domains[0]
            return resp

        if self._llm_client is None:
            return {
                "status": "error",
                "error": "LLM client is required for domain analysis but was not configured.",
                "error_code": "tool_error",
            }

        analyzer = DomainAnalyzer(
            llm_client=self._llm_client,
            heuristic_registry=self._heuristic_registry,
            prompt_builder=self._prompt_builder,
            max_parallelism=self._env_config.discovery_max_parallelism,
            model=self._env_config.discovery_llm_model,
            temperature=self._env_config.discovery_llm_temperature,
        )

        analyses: list[DomainAnalysis] = []
        failed_domains: list[dict[str, str]] = []

        async def _analyze_one(d: str, packs: list[PackResult]) -> None:
            try:
                result = await analyzer.analyze_domain(
                    d, packs, trace_id=self._trace_id
                )
                analyses.append(result)
                self._domain_analyses.append(result)
            except Exception as exc:  # noqa: BLE001 — must not leak to TaskGroup
                logger.error(
                    "domain_analysis_failed_using_heuristic_fallback",
                    extra={"domain": d, "error": str(exc)},
                    exc_info=True,
                )
                query_results = [qr for pr in packs for qr in pr.results]
                result_map = {
                    qr.query_id: qr.data
                    for qr in query_results
                    if qr.succeeded and qr.data is not None
                }
                heuristic_findings = self._heuristic_registry.evaluate(d, result_map)
                fallback = build_fallback_analysis(d, query_results, heuristic_findings)
                analyses.append(fallback)
                self._domain_analyses.append(fallback)
                failed_domains.append(
                    {
                        "domain": d,
                        "error": f"{type(exc).__name__}: {exc}",
                        "fallback": "heuristic_analysis",
                        "grade": fallback.grade,
                    }
                )

        async with asyncio.TaskGroup() as tg:
            for d, packs in domain_packs.items():
                tg.create_task(_analyze_one(d, packs))

        if not analyses:
            return {
                "status": "error",
                "domains": target_domains,
                "error": "Analysis produced no results for any domain.",
                "error_code": "tool_error",
                "failed_domains": failed_domains,
            }

        domain_results_out = self._format_analysis_results(
            analyses, is_batch=is_batch
        )

        # Single-domain backward-compatible response
        if not is_batch and len(domain_results_out) == 1:
            result_out = domain_results_out[0]
            result_out["status"] = "completed"
            result_out["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
            return result_out

        return {
            "status": "completed",
            "domains_analyzed": len(analyses),
            "domains_skipped": skipped,
            "domains_failed": failed_domains,
            "domain_results": domain_results_out,
            "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
        }

    _RESULT_BUDGET_CHARS = 90_000

    @staticmethod
    def _format_analysis_results(
        analyses: list[DomainAnalysis],
        *,
        is_batch: bool,
        budget: int = _RESULT_BUDGET_CHARS,
    ) -> list[dict[str, Any]]:
        """Format DomainAnalysis objects into serializable dicts.

        Uses progressive detail shedding to keep the serialized response
        under ``budget`` characters.  Full data is always preserved in
        ``self._domain_analyses`` for the synthesize step.

        Shedding levels (applied per domain, in order):
          0 — full detail (10 findings in batch, 15 single)
          1 — drop evidence & remediation from findings
          2 — keep only top-5 CRITICAL/HIGH findings (title + priority only)
          3 — findings replaced by count-only summary
        """
        detail_level = 0
        max_levels = 4
        while detail_level < max_levels:
            results_out = DiscoveryTools._build_results_at_level(
                analyses, is_batch=is_batch, detail_level=detail_level
            )
            size = len(json.dumps(results_out, separators=(",", ":")))
            if size <= budget:
                if detail_level > 0:
                    logger.info(
                        "analysis_results_detail_shed",
                        extra={
                            "detail_level": detail_level,
                            "result_chars": size,
                            "budget_chars": budget,
                            "domains": len(analyses),
                        },
                    )
                return results_out
            detail_level += 1

        return results_out  # type: ignore[possibly-undefined]

    @staticmethod
    def _build_results_at_level(
        analyses: list[DomainAnalysis],
        *,
        is_batch: bool,
        detail_level: int,
    ) -> list[dict[str, Any]]:
        """Build result list at a specific detail level."""
        max_findings = 10 if is_batch else 15
        results_out: list[dict[str, Any]] = []

        for analysis in analyses:
            entry: dict[str, Any] = {
                "domain": analysis.domain,
                "grade": analysis.grade,
                "score": analysis.score,
                "summary": analysis.summary,
                "finding_count": len(analysis.findings),
                "data_coverage": {
                    "queries_executed": analysis.data_coverage.queries_executed,
                    "queries_succeeded": analysis.data_coverage.queries_succeeded,
                    "queries_failed": (
                        analysis.data_coverage.queries_executed
                        - analysis.data_coverage.queries_succeeded
                    ),
                },
            }

            if detail_level == 0:
                entry["observations"] = analysis.observations[:10]
                entry["patterns"] = analysis.patterns[:5]
                entry["findings"] = [
                    {
                        "finding_id": f.finding_id,
                        "title": f.title,
                        "priority": f.priority,
                        "impact": f.impact,
                        "domain": f.domain,
                        "type": f.finding_type,
                        "description": f.description,
                        "evidence": [
                            {
                                "source_query_id": e.source_query_id,
                                "excerpt": e.excerpt,
                                "metric_name": e.metric_name,
                                "metric_value": e.metric_value,
                            }
                            for e in f.evidence[:3]
                        ],
                        "remediation": {
                            "immediate": f.remediation.immediate[:3],
                            "medium_term": f.remediation.medium_term[:2],
                        },
                        "expected_outcome": f.expected_outcome,
                    }
                    for f in analysis.findings[:max_findings]
                ]
                entry["recommended_actions"] = analysis.recommended_actions[:10]

            elif detail_level == 1:
                entry["observations"] = analysis.observations[:5]
                entry["patterns"] = analysis.patterns[:3]
                entry["findings"] = [
                    {
                        "finding_id": f.finding_id,
                        "title": f.title,
                        "priority": f.priority,
                        "impact": f.impact,
                        "type": f.finding_type,
                        "description": f.description,
                    }
                    for f in analysis.findings[:max_findings]
                ]
                entry["recommended_actions"] = analysis.recommended_actions[:5]

            elif detail_level == 2:
                top_findings = [
                    f
                    for f in analysis.findings
                    if f.priority in ("CRITICAL", "HIGH")
                ][:5]
                entry["findings"] = [
                    {
                        "finding_id": f.finding_id,
                        "title": f.title,
                        "priority": f.priority,
                        "impact": f.impact,
                    }
                    for f in top_findings
                ]
                entry["recommended_actions"] = analysis.recommended_actions[:3]

            else:
                priority_counts: dict[str, int] = {}
                for f in analysis.findings:
                    priority_counts[f.priority] = priority_counts.get(f.priority, 0) + 1
                entry["findings_by_priority"] = priority_counts
                entry["top_action"] = (
                    analysis.recommended_actions[0]
                    if analysis.recommended_actions
                    else None
                )
                entry["detail_note"] = (
                    "Full findings preserved for synthesize_discovery_report"
                )

            results_out.append(entry)

        return results_out

    # ------------------------------------------------------------------
    # Async polling pattern — start / check progress
    # ------------------------------------------------------------------

    async def start_discovery_analysis(
        self,
        domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """Start background domain analysis and return immediately.

        Launches all domain analyses in parallel on the server's event loop.
        Poll ``get_discovery_analysis_progress`` to check completion.

        Must be called after ``run_discovery_queries``.

        Args:
            domains: Domains to analyze.  Defaults to all domains with data.

        Returns:
            Dict with ``status: "started"`` and the list of target domains.
        """
        if self._pack_results is None:
            return {
                "status": "error",
                "error": "Call run_discovery_queries first to gather data.",
                "error_code": "tool_error",
            }

        if self._bg_task is not None and not self._bg_task.done():
            completed = list(self._bg_completed.keys())
            return {
                "status": "already_running",
                "domains": self._bg_target_domains,
                "completed": completed,
                "remaining": [
                    d for d in self._bg_target_domains if d not in completed
                ],
                "instruction": (
                    "Analysis is already running. "
                    "Call get_discovery_analysis_progress to check status."
                ),
            }

        if self._llm_client is None:
            return {
                "status": "error",
                "error": "LLM client is required for domain analysis.",
                "error_code": "tool_error",
            }

        # Determine target domains
        all_domains_with_data = sorted(
            {
                pr.domain
                for pr in self._pack_results
                if pr.domain != "audit"
            }
        )
        target = domains if domains else all_domains_with_data
        skipped = [d for d in target if d not in all_domains_with_data]
        target = [d for d in target if d in all_domains_with_data]

        if not target:
            return {
                "status": "no_data",
                "message": "No query data available for any requested domain.",
            }

        # Reset background state
        self._bg_completed = {}
        self._bg_failed = []
        self._bg_target_domains = target
        self._bg_start = time.monotonic()

        # Build domain → packs mapping
        domain_packs: dict[str, list[PackResult]] = {}
        for d in target:
            packs = [pr for pr in self._pack_results if pr.domain == d]
            if packs:
                domain_packs[d] = packs

        # Launch background task
        self._bg_task = asyncio.create_task(
            self._run_background_analysis(domain_packs)
        )

        resp: dict[str, Any] = {
            "status": "started",
            "domains": target,
            "domain_count": len(target),
            "instruction": (
                "Analysis is now running in the background. "
                "Call get_discovery_analysis_progress every 30-60 seconds "
                "to check completion. When status is 'completed', call "
                "synthesize_discovery_report."
            ),
        }
        if skipped:
            resp["skipped"] = skipped
        return resp

    async def _run_background_analysis(
        self,
        domain_packs: dict[str, list[PackResult]],
    ) -> None:
        """Background coroutine that analyzes all domains in parallel."""
        analyzer = DomainAnalyzer(
            llm_client=self._llm_client,
            heuristic_registry=self._heuristic_registry,
            prompt_builder=self._prompt_builder,
            max_parallelism=self._env_config.discovery_max_parallelism,
            model=self._env_config.discovery_llm_model,
            temperature=self._env_config.discovery_llm_temperature,
        )

        async def _analyze_one(d: str, packs: list[PackResult]) -> None:
            try:
                result = await analyzer.analyze_domain(
                    d, packs, trace_id=self._trace_id
                )
            except Exception as exc:  # noqa: BLE001 — must not leak to TaskGroup
                logger.error(
                    "bg_domain_analysis_failed",
                    extra={"domain": d, "error": str(exc)},
                    exc_info=True,
                )
                query_results = [qr for pr in packs for qr in pr.results]
                result_map = {
                    qr.query_id: qr.data
                    for qr in query_results
                    if qr.succeeded and qr.data is not None
                }
                heuristic_findings = self._heuristic_registry.evaluate(
                    d, result_map
                )
                result = build_fallback_analysis(
                    d, query_results, heuristic_findings
                )
                self._bg_failed.append(
                    {
                        "domain": d,
                        "error": f"{type(exc).__name__}: {exc}",
                        "fallback": "heuristic_analysis",
                    }
                )
            self._bg_completed[d] = result
            self._domain_analyses.append(result)

        async with asyncio.TaskGroup() as tg:
            for d, packs in domain_packs.items():
                tg.create_task(_analyze_one(d, packs))

    async def get_discovery_analysis_progress(self) -> dict[str, Any]:
        """Check progress of background domain analysis.

        Returns completed domain results and remaining domains.
        Each call completes instantly — no blocking.

        Returns:
            Dict with ``status`` (``running`` | ``completed`` | ``idle``),
            completed domain results, and remaining domains.
        """
        if self._bg_task is None:
            return {
                "status": "idle",
                "message": "No analysis in progress. Call start_discovery_analysis first.",
            }

        completed_domains = list(self._bg_completed.keys())
        remaining = [
            d for d in self._bg_target_domains if d not in self._bg_completed
        ]
        elapsed_s = round(time.monotonic() - self._bg_start, 1)
        is_done = self._bg_task.done()

        domain_results = self._format_analysis_results(
            list(self._bg_completed.values()), is_batch=True
        )

        result: dict[str, Any] = {
            "status": "completed" if is_done else "running",
            "domains_completed": len(completed_domains),
            "domains_total": len(self._bg_target_domains),
            "domains_remaining": remaining,
            "elapsed_s": elapsed_s,
        }

        if self._bg_failed:
            result["domains_failed"] = self._bg_failed

        if is_done:
            result["domain_results"] = domain_results
            result["instruction"] = (
                "All domains analyzed. Call synthesize_discovery_report "
                "to assemble the final report."
            )
            # Check for task exception
            if self._bg_task.exception() is not None:
                result["warning"] = str(self._bg_task.exception())
        else:
            result["completed_domains"] = completed_domains
            result["instruction"] = (
                f"{len(completed_domains)}/{len(self._bg_target_domains)} "
                "domains complete. Call get_discovery_analysis_progress "
                "again in 30-60 seconds."
            )

        return result

    def _resolve_target_domains(
        self,
        domain: str | None,
        domains: list[str] | None,
    ) -> list[str] | dict[str, Any]:
        """Validate and resolve the domain/domains parameters.

        Returns a list of domain strings, or an error dict if invalid.
        """
        if domain and domains:
            return {
                "status": "error",
                "error": "Provide either 'domain' (single) or 'domains' (batch), not both.",
                "error_code": "tool_error",
            }
        if domains:
            return domains
        if domain:
            return [domain]
        return {
            "status": "error",
            "error": "Provide 'domain' (single) or 'domains' (batch of all domains from Phase 2).",
            "error_code": "tool_error",
        }

    # ------------------------------------------------------------------
    # Phase 4: Synthesize — assemble the final report
    # ------------------------------------------------------------------

    async def synthesize_discovery_report(self) -> dict[str, Any]:
        """Assemble all domain analyses into a final discovery report.

        Builds report cards, ranks findings by priority, generates an
        executive summary (via LLM if available), and writes output files.

        Must be called after one or more ``analyze_discovery_domain`` calls.

        Returns:
            Dict with executive summary, report cards, top findings,
            recommended actions, and output file paths.
        """
        if not self._domain_analyses:
            return {
                "status": "error",
                "error": "No domain analyses available. Call analyze_discovery_domain first.",
                "error_code": "tool_error",
            }

        start = time.monotonic()

        # Build context
        total_queries = sum(len(pr.results) for pr in (self._pack_results or []))
        total_time = sum(
            qr.execution_time_ms
            for pr in (self._pack_results or [])
            for qr in pr.results
        )
        context = AnalysisContext(
            lookback_days=self._lookback_days,
            analysis_timestamp=datetime.now(UTC).isoformat(),
            domains_analyzed=[a.domain for a in self._domain_analyses],
            total_queries_executed=total_queries,
            total_execution_time_ms=total_time,
        )

        assembler = ReportAssembler(
            llm_client=self._llm_client,
            model=self._env_config.discovery_llm_model,
            temperature=self._env_config.discovery_llm_temperature,
        )

        report = await assembler.assemble(
            domain_analyses=self._domain_analyses,
            context=context,
            trace_id=self._trace_id,
        )

        output_dir = self._env_config.discovery_output_dir
        output_files = await self._output_formatter.write_to_directory(
            report, output_dir
        )

        self._discovery_markdown = self._output_formatter.to_markdown(report)

        response: dict[str, Any] = {
            "status": "completed",
            "trace_id": self._trace_id,
            "domains_analyzed": len(self._domain_analyses),
            "output_files": [str(p) for p in output_files],
            "report_summary": _build_report_summary(report),
            "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
        }

        # Reset shared state for next run
        self._active_products = None
        self._pack_results = None
        self._domain_analyses = []

        return response

    # ------------------------------------------------------------------
    # Legacy: monolithic run (kept for backward compatibility)
    # ------------------------------------------------------------------

    async def run_workspace_discovery(
        self,
        lookback_days: int = 30,
        domains: list[str] | None = None,
        data_only: bool = False,
    ) -> dict[str, Any]:
        """Run a full workspace health assessment (all 4 phases).

        Retained for backward compatibility and programmatic use.
        The discovery agent should prefer the granular phase tools.

        Args:
            lookback_days: Time window for analysis (30, 60, or 90 days).
            domains: Specific domains to analyze (None = all active).
            data_only: Skip LLM analysis and return raw query data.

        Returns:
            Dict with report summary, grades, top findings, and output paths.
        """
        env = self._env_config

        config = EngineConfig(
            lookback_days=lookback_days,
            max_parallelism=env.discovery_max_parallelism,
            domains=domains,
            data_only=data_only,
            output_dir=env.discovery_output_dir,
            llm_model=env.discovery_llm_model,
            llm_temperature=env.discovery_llm_temperature,
        )

        engine = DiscoveryEngine(
            sql_executor=self._sql_executor,
            llm_client=self._llm_client,
            config=config,
        )

        result = await engine.run()

        response: dict[str, Any] = {
            "status": "completed" if not result.errors else "completed_with_errors",
            "trace_id": result.trace_id,
            "elapsed_ms": round(result.elapsed_ms, 1),
            "packs_executed": len(result.pack_results),
            "domains_analyzed": len(result.domain_analyses),
            "output_files": result.output_files,
            "errors": result.errors,
        }

        if result.report is not None:
            report = result.report
            response["report_summary"] = _build_report_summary(report)
            response["markdown_report"] = self._output_formatter.to_markdown(report)
        elif result.domain_analyses:
            response["domain_summaries"] = [
                {
                    "domain": a.domain,
                    "grade": a.grade,
                    "score": a.score,
                    "summary": a.summary,
                }
                for a in result.domain_analyses
            ]

        return response
