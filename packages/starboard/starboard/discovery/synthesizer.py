# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Report assembler — builds DiscoveryReport from domain analyses.

Phase 4 of the discovery pipeline. Deterministically assembles report
cards, sorted findings, and metadata from Phase 3 domain analyses.
Optionally calls the LLM for a lightweight executive summary narrative
(~500 tokens input: grades + summaries only, never full findings).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from starboard_core.domain.models.discovery.analysis import (
    DomainAnalysis,
)
from starboard_core.domain.models.discovery.report import (
    AnalysisContext,
    DiscoveryReport,
    ExecutiveSummary,
    ReportCard,
    ReportMetadata,
)

from starboard.adapters.llm.base import BaseLLMClient
from starboard.exceptions import AdapterError
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# Operational findings (performance, cost, reliability) rank above
# governance/attribution findings at the same priority level.
FINDING_TYPE_TIER: dict[str, int] = {
    "PERFORMANCE": 0,
    "COST_OPTIMIZATION": 0,
    "RELIABILITY": 0,
    "DATA_QUALITY": 1,
    "CONFIGURATION": 1,
    "OBSERVABILITY": 1,
    "SECURITY": 1,
    "GOVERNANCE": 2,
}


class ExecutiveSummaryLLMOutput(BaseModel):
    """Structured LLM output for the executive summary narrative.

    Kept intentionally flat and small so the schema overhead is minimal.

    Args:
        overview: 3-5 sentence workspace health narrative.
        top_actions: Top 5 recommended next steps (one sentence each).
        primary_risks: Key risks across performance, cost, reliability, governance.
        cross_domain_themes: Patterns spanning multiple domains.
    """

    overview: str = ""
    top_actions: list[str] = Field(default_factory=list)
    primary_risks: list[str] = Field(default_factory=list)
    cross_domain_themes: list[str] = Field(default_factory=list)


class ReportAssembler:
    """Assembles domain analyses into a final DiscoveryReport.

    Step A (deterministic): report cards, sorted findings, metadata.
    Step B (optional LLM): executive summary narrative from compact
    scorecards (~500 tokens). Falls back to a template summary if the
    LLM is unavailable or fails.

    Args:
        llm_client: Optional LLM client for executive summary generation.
        model: Optional LLM model override.
        temperature: LLM temperature for the executive summary call.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> None:
        self._llm = llm_client
        self._model = model
        self._temperature = temperature

    async def assemble(
        self,
        domain_analyses: list[DomainAnalysis],
        context: AnalysisContext | None = None,
        trace_id: str | None = None,
    ) -> DiscoveryReport:
        """Assemble domain analyses into a complete report.

        Args:
            domain_analyses: Graded analyses from Phase 3.
            context: Analysis context metadata.
            trace_id: Optional trace ID for observability.

        Returns:
            Complete DiscoveryReport with executive summary and priorities.
        """
        start = time.monotonic()

        report_cards = self._build_report_cards(domain_analyses)
        sorted_findings = self._sort_findings(domain_analyses)
        top_actions_fallback = [
            action for a in domain_analyses for action in a.recommended_actions[:3]
        ][:10]
        critical_risks = [
            f"{f.title} ({f.domain})"
            for f in sorted_findings
            if f.priority in ("CRITICAL", "HIGH")
        ][:10]

        exec_summary = await self._generate_executive_summary(
            domain_analyses,
            sorted_findings,
            trace_id,
        )

        report = DiscoveryReport(
            executive_summary=ExecutiveSummary(
                overview=exec_summary.overview,
                analysis_context=context or AnalysisContext(),
                report_cards=report_cards,
                top_findings=sorted_findings[:15],
                top_actions=exec_summary.top_actions or top_actions_fallback,
                primary_risks=exec_summary.primary_risks or critical_risks,
                notes=[],
            ),
            domain_analyses=domain_analyses,
            top_priorities=sorted_findings[:20],
            source_proofs=[],
        )

        if context is not None:
            report.executive_summary.analysis_context = context

        report.metadata = self._build_metadata(domain_analyses, context)

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "report_assembly_complete",
            trace_id=trace_id,
            domains=len(domain_analyses),
            findings=len(report.top_priorities),
            latency_ms=round(elapsed_ms, 1),
        )

        return report

    # ------------------------------------------------------------------
    # Deterministic assembly helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_report_cards(
        analyses: list[DomainAnalysis],
    ) -> list[ReportCard]:
        return [
            ReportCard(
                domain=a.domain,
                grade=a.grade,
                score=a.score,
                discussion=a.summary,
                top_findings=a.findings[:15],
            )
            for a in analyses
        ]

    @staticmethod
    def _sort_findings(
        analyses: list[DomainAnalysis],
    ) -> list[Any]:
        all_findings = [f for a in analyses for f in a.findings]
        return sorted(
            all_findings,
            key=lambda f: (
                PRIORITY_ORDER.get(f.priority, 4),
                FINDING_TYPE_TIER.get(f.finding_type, 1),
                PRIORITY_ORDER.get(f.impact, 4),
            ),
        )

    # ------------------------------------------------------------------
    # Executive summary (lightweight LLM or template fallback)
    # ------------------------------------------------------------------

    async def _generate_executive_summary(
        self,
        analyses: list[DomainAnalysis],
        sorted_findings: list[Any],
        trace_id: str | None,
    ) -> ExecutiveSummaryLLMOutput:
        """Try a lightweight LLM call for the executive summary.

        Input is only scorecards + top finding titles (~500 tokens).
        Falls back to template-based summary on any failure.
        """
        if self._llm is None:
            return self._template_summary(analyses, sorted_findings)

        prompt = self._build_exec_summary_prompt(analyses, sorted_findings)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "Generate the executive summary JSON for this "
                    "workspace health assessment."
                ),
            },
        ]

        try:
            raw = await asyncio.wait_for(
                self._llm.json_response(
                    messages=messages,
                    phase="discovery_executive_summary",
                    schema=ExecutiveSummaryLLMOutput,
                    model=self._model,
                    temperature=self._temperature,
                ),
                timeout=90.0,
            )
            result = ExecutiveSummaryLLMOutput.model_validate(raw)
            logger.info(
                "executive_summary_llm_success",
                trace_id=trace_id,
            )
            return result
        except (AdapterError, ValueError, TimeoutError) as exc:
            logger.warning(
                "executive_summary_llm_failed_using_template",
                trace_id=trace_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return self._template_summary(analyses, sorted_findings)

    @staticmethod
    def _build_exec_summary_prompt(
        analyses: list[DomainAnalysis],
        sorted_findings: list[Any],
    ) -> str:
        """Build a compact prompt for executive summary generation.

        Total input is ~500-800 tokens: one line per domain scorecard,
        plus top 5 finding titles.
        """
        scorecards = "\n".join(
            f"- {a.domain}: {a.grade} ({a.score:.0f}/100) — {a.summary[:300]}"
            for a in analyses
        )
        top_titles = "\n".join(
            f"- [{f.priority}] {f.title} ({f.domain}): {f.description[:150]}"
            for f in sorted_findings[:15]
        )

        return (
            "You are a Databricks Platform Health Expert. "
            "Synthesize the domain scorecards below into a cohesive "
            "executive summary.\n\n"
            "## Rules\n"
            "- Write for Platform Engineering and Data Architects.\n"
            "- Express resource consumption in DBUs only (never dollars).\n"
            "- Identify cross-domain patterns and systemic themes.\n"
            "- Be specific and evidence-based; do not invent data.\n"
            "- Preserve the breadth of findings — do not over-summarize.\n\n"
            "## Domain Scorecards\n"
            f"{scorecards}\n\n"
            "## Top Findings\n"
            f"{top_titles}\n\n"
            "## Output\n"
            "Return a JSON object with:\n"
            "- overview: 5-8 sentence workspace health narrative covering "
            "each domain's grade and key issues\n"
            "- top_actions: list of 10 recommended next steps (one sentence each)\n"
            "- primary_risks: list of key risks across performance, "
            "consumption, reliability, governance\n"
            "- cross_domain_themes: list of patterns spanning multiple domains"
        )

    @staticmethod
    def _template_summary(
        analyses: list[DomainAnalysis],
        sorted_findings: list[Any],
    ) -> ExecutiveSummaryLLMOutput:
        """Data-driven fallback when the LLM is unavailable."""
        grade_groups: dict[str, list[str]] = {}
        for a in analyses:
            grade_groups.setdefault(a.grade, []).append(a.domain)

        n_domains = len(analyses)
        avg_score = sum(a.score for a in analyses) / n_domains if n_domains else 0
        critical_count = sum(1 for f in sorted_findings if f.priority == "CRITICAL")
        high_count = sum(1 for f in sorted_findings if f.priority == "HIGH")

        lines = [
            f"Workspace health assessment across {n_domains} domains "
            f"(avg score {avg_score:.0f}/100).",
        ]
        for grade in ("F", "D", "C", "B", "A"):
            domains = grade_groups.get(grade, [])
            if domains:
                lines.append(f"Grade {grade}: {', '.join(domains)}.")
        if critical_count or high_count:
            lines.append(
                f"{critical_count} critical and {high_count} high-priority "
                f"findings require attention."
            )

        top_actions = [
            action for a in analyses for action in a.recommended_actions[:3]
        ][:10]
        critical_risks = [
            f"{f.title} ({f.domain})"
            for f in sorted_findings
            if f.priority in ("CRITICAL", "HIGH")
        ][:10]

        return ExecutiveSummaryLLMOutput(
            overview=" ".join(lines),
            top_actions=top_actions,
            primary_risks=critical_risks,
            cross_domain_themes=[],
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _build_metadata(
        self,
        domain_analyses: list[DomainAnalysis],
        context: AnalysisContext | None,
    ) -> ReportMetadata:
        total_findings = sum(len(a.findings) for a in domain_analyses)
        return ReportMetadata(
            generated_at=datetime.now(UTC).isoformat(),
            lookback_days=context.lookback_days if context else 30,
            total_findings=total_findings,
            total_domains=len(domain_analyses),
            llm_model=self._model or "",
        )
