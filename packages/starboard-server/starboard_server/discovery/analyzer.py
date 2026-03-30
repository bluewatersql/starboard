"""Domain analyzer — two-stage analysis: heuristics then LLM.

The ``DomainAnalyzer`` evaluates query results for each domain by:
1. Running deterministic heuristic rules to catch known patterns
2. Feeding query data + heuristic findings to an LLM for graded analysis

Produces a ``DomainAnalysis`` per domain with grade, findings, and actions.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from starboard_core.domain.models.discovery.analysis import (
    DataCoverage,
    DiscoveryFinding,
    DomainAnalysis,
    Evidence,
    Remediation,
)
from starboard_core.domain.models.discovery.query import PackResult, QueryResult

from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.discovery.heuristics.base import (
    HeuristicFinding,
    HeuristicRegistry,
)
from starboard_server.discovery.prompts.domain_analysis import PromptBuilder
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

DomainProgressCallback = Callable[[str, dict[str, Any]], None]


def _normalize_domain(analysis: DomainAnalysis, canonical: str) -> DomainAnalysis:
    """Ensure ``analysis.domain`` and all finding domains use the canonical pack domain.

    LLMs may rewrite the domain to a human-friendly variant (e.g. "Billing & Attribution"
    instead of "billing"). This function forces consistency so filenames, keys, and
    cross-references always use the canonical pack domain identifier.
    """
    updates: dict[str, Any] = {}
    if analysis.domain != canonical:
        updates["domain"] = canonical
    mismatched = [f for f in analysis.findings if f.domain != canonical]
    if mismatched:
        updates["findings"] = [
            f.model_copy(update={"domain": canonical}) if f.domain != canonical else f
            for f in analysis.findings
        ]
    if updates:
        return analysis.model_copy(update=updates)
    return analysis


class DomainAnalyzer:
    """Analyzes domain query results with heuristics and LLM reasoning.

    Two-stage analysis pipeline:
    1. Deterministic heuristic evaluation against best-practice thresholds
    2. LLM-driven analysis consuming query data and heuristic context

    Args:
        llm_client: LLM client for structured JSON responses.
        heuristic_registry: Registry of domain-specific heuristic rules.
        prompt_builder: Builds domain-specific prompt strings.
        max_parallelism: Maximum concurrent LLM calls for domain analysis.
        model: Optional LLM model override for discovery analysis.
        temperature: LLM temperature for analysis calls.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        heuristic_registry: HeuristicRegistry,
        prompt_builder: PromptBuilder | None = None,
        max_parallelism: int = 4,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> None:
        self._llm = llm_client
        self._heuristics = heuristic_registry
        self._prompts = prompt_builder or PromptBuilder()
        self._semaphore = asyncio.Semaphore(max_parallelism)
        self._model = model
        self._temperature = temperature

    async def analyze_domain(
        self,
        domain: str,
        pack_results: list[PackResult],
        trace_id: str | None = None,
    ) -> DomainAnalysis:
        """Analyze a single domain's query results.

        Args:
            domain: The domain being analyzed (e.g. "billing", "jobs").
            pack_results: Query pack results for this domain.
            trace_id: Optional trace ID for observability.

        Returns:
            A graded DomainAnalysis with findings and recommendations.

        Raises:
            ValueError: If LLM returns invalid or unparseable output.
        """
        start = time.monotonic()

        query_results = self._flatten_results(pack_results)
        result_map = self._build_result_map(query_results)

        heuristic_findings = self._heuristics.evaluate(domain, result_map)

        logger.info(
            "heuristic_evaluation_complete",
            trace_id=trace_id,
            domain=domain,
            findings_count=len(heuristic_findings),
            rules_evaluated=len(self._heuristics.get_rules_for_domain(domain)),
        )

        prompt = self._prompts.build_domain_prompt(
            domain=domain,
            query_results=query_results,
            heuristic_findings=heuristic_findings,
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"Analyze the {domain} domain and produce a DomainAnalysis JSON.",
            },
        ]

        async with self._semaphore:
            try:
                raw = await self._llm.json_response(
                    messages=messages,
                    phase="discovery_analysis",
                    schema=DomainAnalysis,
                    model=self._model,
                    temperature=self._temperature,
                )
                analysis = DomainAnalysis.model_validate(raw)
                analysis = _normalize_domain(analysis, domain)
            except (ValidationError, ValueError, TypeError) as exc:
                logger.warning(
                    "llm_analysis_failed",
                    trace_id=trace_id,
                    domain=domain,
                    error=str(exc),
                )
                analysis = self._fallback_analysis(
                    domain, query_results, heuristic_findings
                )

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "domain_analysis_complete",
            trace_id=trace_id,
            domain=domain,
            grade=analysis.grade,
            score=analysis.score,
            findings_count=len(analysis.findings),
            latency_ms=round(elapsed_ms, 1),
        )

        return analysis

    async def analyze_all_domains(
        self,
        domain_results: dict[str, list[PackResult]],
        trace_id: str | None = None,
        on_domain_complete: DomainProgressCallback | None = None,
    ) -> list[DomainAnalysis]:
        """Analyze all domains concurrently with bounded parallelism.

        Args:
            domain_results: Map of domain name to its pack results.
            trace_id: Optional trace ID for observability.
            on_domain_complete: Optional callback fired after each domain
                finishes. Receives ``(event_name, details_dict)``.

        Returns:
            List of DomainAnalysis objects, one per domain.
        """
        total = len(domain_results)
        completed_count = 0
        _emit = on_domain_complete or (lambda _e, _d: None)

        async def _analyze_and_report(
            domain: str, results: list[PackResult]
        ) -> DomainAnalysis:
            nonlocal completed_count
            analysis = await self.analyze_domain(domain, results, trace_id=trace_id)
            completed_count += 1
            _emit(
                "domain_analysis_done",
                {
                    "domain": domain,
                    "grade": analysis.grade,
                    "score": analysis.score,
                    "finding_count": len(analysis.findings),
                    "completed": completed_count,
                    "total": total,
                },
            )
            return analysis

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_analyze_and_report(domain, results))
                for domain, results in domain_results.items()
            ]
        return [t.result() for t in tasks]

    def _flatten_results(self, pack_results: list[PackResult]) -> list[QueryResult]:
        """Extract all QueryResult objects from pack results.

        Args:
            pack_results: Pack results containing nested query results.

        Returns:
            Flat list of all query results.
        """
        return [qr for pr in pack_results for qr in pr.results]

    def _build_result_map(self, query_results: list[QueryResult]) -> dict[str, Any]:
        """Build a query_id -> DataFrame map for heuristic evaluation.

        Only includes successful queries with non-empty data.

        Args:
            query_results: Flat list of query results.

        Returns:
            Dict mapping query_id to Polars DataFrame.
        """
        return {
            qr.query_id: qr.data
            for qr in query_results
            if qr.succeeded and qr.data is not None
        }

    def _fallback_analysis(
        self,
        domain: str,
        query_results: list[QueryResult],
        heuristic_findings: list[HeuristicFinding],
    ) -> DomainAnalysis:
        """Delegate to the module-level fallback builder."""
        return build_fallback_analysis(domain, query_results, heuristic_findings)


_DIMENSION_TO_FINDING_TYPE: dict[str, str] = {
    "performance": "PERFORMANCE",
    "reliability": "RELIABILITY",
    "consumption": "COST_OPTIMIZATION",
    "governance": "GOVERNANCE",
    "configuration": "CONFIGURATION",
}


def build_fallback_analysis(
    domain: str,
    query_results: list[QueryResult],
    heuristic_findings: list[HeuristicFinding],
) -> DomainAnalysis:
    """Build a DomainAnalysis from heuristic findings when LLM is unavailable.

    Converts each ``HeuristicFinding`` into a full ``DiscoveryFinding``
    so the downstream pipeline retains all detected signals.

    Args:
        domain: The domain name.
        query_results: Raw query results for the domain.
        heuristic_findings: Deterministic findings from heuristics.

    Returns:
        A DomainAnalysis populated from heuristic rules.
    """
    has_critical = any(f.severity == "CRITICAL" for f in heuristic_findings)
    has_high = any(f.severity == "HIGH" for f in heuristic_findings)

    if has_critical:
        grade = "D"
        score = 35
    elif has_high:
        grade = "C"
        score = 55
    elif heuristic_findings:
        grade = "B"
        score = 75
    else:
        grade = "B"
        score = 80

    succeeded = sum(1 for qr in query_results if qr.succeeded)
    failed = sum(1 for qr in query_results if not qr.succeeded)

    findings = [
        DiscoveryFinding(
            finding_id=f"F-{i + 1:03d}",
            title=hf.title,
            priority=hf.severity,
            impact="HIGH" if hf.severity in ("CRITICAL", "HIGH") else "MEDIUM",
            effort="MEDIUM",
            confidence="HIGH",
            finding_type=_DIMENSION_TO_FINDING_TYPE.get(hf.dimension, "CONFIGURATION"),
            domain=domain,
            description=hf.description,
            evidence=[
                Evidence(
                    source_query_id=hf.evidence_query_id,
                    excerpt=f"Threshold: {hf.threshold} | Actual: {hf.actual_value}",
                    metric_name=hf.dimension,
                    metric_value=hf.actual_value,
                )
            ],
            remediation=Remediation(
                immediate=[f"Investigate {hf.rule_id}: {hf.title}"],
            ),
            expected_outcome=f"Resolving {hf.title.lower()} will improve {hf.dimension}.",
        )
        for i, hf in enumerate(heuristic_findings[:15])
    ]

    observations = [
        f"[{hf.severity}] {hf.title}: {hf.description}" for hf in heuristic_findings
    ]
    patterns: list[str] = []
    severity_counts: dict[str, int] = {}
    for hf in heuristic_findings:
        severity_counts[hf.severity] = severity_counts.get(hf.severity, 0) + 1
    if severity_counts:
        patterns.append(
            "Severity distribution: "
            + ", ".join(f"{s}: {c}" for s, c in sorted(severity_counts.items()))
        )
    dimension_counts: dict[str, int] = {}
    for hf in heuristic_findings:
        dimension_counts[hf.dimension] = dimension_counts.get(hf.dimension, 0) + 1
    if dimension_counts:
        patterns.append(
            "Affected dimensions: "
            + ", ".join(f"{d}: {c}" for d, c in sorted(dimension_counts.items()))
        )

    return DomainAnalysis(
        domain=domain,
        grade=grade,
        score=score,
        summary=(
            f"Heuristic-only analysis (LLM unavailable). "
            f"{len(heuristic_findings)} findings detected across "
            f"{succeeded} successful queries."
        ),
        observations=observations,
        patterns=patterns,
        findings=findings,
        recommended_actions=[
            f"[{hf.severity}] Investigate {hf.rule_id}: {hf.title}"
            for hf in heuristic_findings[:10]
        ],
        data_coverage=DataCoverage(
            queries_executed=succeeded + failed,
            queries_succeeded=succeeded,
            time_range_start=None,
            time_range_end=None,
            gaps=[
                f"Query {qr.query_id} failed: {qr.error}"
                for qr in query_results
                if not qr.succeeded
            ],
        ),
    )
