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

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from starboard_core.domain.models.discovery.analysis import DomainAnalysis
from starboard_core.domain.models.discovery.query import PackResult, QueryResult
from starboard_core.domain.models.discovery.report import (
    AnalysisContext,
    DiscoveryReport,
)

from starboard.discovery.analyzer import DomainAnalyzer
from starboard.discovery.executor import QueryPackExecutor, SQLExecutor
from starboard.discovery.heuristics import create_default_heuristic_registry
from starboard.discovery.output.formatters import OutputFormatter
from starboard.discovery.prompts.domain_analysis import PromptBuilder
from starboard.discovery.query_packs.registry import (
    QueryPackRegistry,
    create_default_registry,
)
from starboard.discovery.synthesizer import ReportAssembler
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

ProgressCallback = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class EngineConfig:
    """Configuration for the discovery engine.

    Args:
        lookback_days: Time window for queries (30, 60, or 90).
        max_parallelism: Max concurrent SQL/LLM operations.
        domains: Specific domains to analyze (None = all active).
        data_only: Skip LLM analysis and synthesis.
        output_dir: Directory for report output.
        llm_model: Optional LLM model override.
        llm_temperature: LLM temperature for analysis/synthesis.
        min_dbu_threshold: Minimum DBUs for a product to be considered active.
    """

    lookback_days: int = 30
    max_parallelism: int = 4
    domains: list[str] | None = None
    data_only: bool = False
    output_dir: str = "./discovery_output"
    llm_model: str | None = None
    llm_temperature: float = 0.3
    min_dbu_threshold: float = 10.0


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
    """

    report: DiscoveryReport | None = None
    pack_results: list[PackResult] = field(default_factory=list)
    domain_analyses: list[DomainAnalysis] = field(default_factory=list)
    audit_result: QueryResult | None = None
    output_files: list[str] = field(default_factory=list)
    trace_id: str = ""
    elapsed_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


class DiscoveryEngine:
    """Orchestrates the full workspace discovery pipeline.

    Args:
        sql_executor: Client for executing SQL queries.
        llm_client: LLM client for analysis and synthesis (optional if data_only).
        config: Engine configuration.
        query_registry: Query pack registry (uses default if None).
    """

    def __init__(
        self,
        sql_executor: SQLExecutor,
        llm_client: Any | None = None,
        config: EngineConfig | None = None,
        query_registry: QueryPackRegistry | None = None,
    ) -> None:
        self._config = config or EngineConfig()
        self._sql_executor = sql_executor
        self._llm_client = llm_client
        self._query_registry = query_registry or create_default_registry()

        self._pack_executor = QueryPackExecutor(
            sql_executor=sql_executor,
            max_parallelism=self._config.max_parallelism,
            default_lookback_days=self._config.lookback_days,
        )

        self._heuristic_registry = create_default_heuristic_registry()
        self._prompt_builder = PromptBuilder()
        self._output_formatter = OutputFormatter()

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
        """
        trace_id = str(uuid.uuid4())
        start = time.monotonic()
        _emit = on_progress or (lambda _phase, _info: None)

        result = EngineResult(trace_id=trace_id)

        logger.info(
            "discovery_pipeline_started",
            trace_id=trace_id,
            lookback_days=self._config.lookback_days,
            max_parallelism=self._config.max_parallelism,
            data_only=self._config.data_only,
        )

        try:
            # Phase 1: Audit
            _emit("audit_start", {})
            audit_result = await self._run_audit(trace_id)
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
                include=list(self._config.domains)
                if self._config.domains is not None
                else None,
            )
            _emit(
                "queries_start",
                {
                    "pack_count": len(selected_packs),
                    "query_count": sum(len(p.queries) for p in selected_packs),
                },
            )
            pack_results = await self._run_queries(active_products, trace_id)
            result.pack_results = pack_results

            total_queries = sum(len(pr.results) for pr in pack_results)
            succeeded = sum(
                1 for pr in pack_results for qr in pr.results if qr.succeeded
            )
            _emit(
                "queries_done",
                {
                    "packs": len(pack_results),
                    "queries": total_queries,
                    "succeeded": succeeded,
                    "failed": total_queries - succeeded,
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
                    output_files = await self._output_formatter.write_to_directory(
                        report, self._config.output_dir
                    )
                    result.output_files = [str(p) for p in output_files]
                    _emit("output_done", {"files": len(output_files)})

        except Exception as exc:  # noqa: BLE001 - discovery pipeline boundary
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
        dbu_col = "total_dbus"
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
        self, active_products: dict[str, float], trace_id: str
    ) -> list[PackResult]:
        """Phase 2: Execute conditional query packs.

        Args:
            active_products: Products with DBU totals from audit.
            trace_id: Trace ID for observability.

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
            include=list(self._config.domains)
            if self._config.domains is not None
            else None,
        )

        return await self._pack_executor.execute_packs(packs)

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
