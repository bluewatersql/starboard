"""Output formatters for discovery reports.

Converts a ``DiscoveryReport`` to Markdown / JSON and writes artefacts
to a directory for downstream consumption. Also supports writing
individual domain analyses to separate files so each domain's full
detail is preserved without hitting tool-response size limits.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from starboard_server.infra.io import write_text
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_core.domain.models.discovery.analysis import (
        DomainAnalysis,
        DiscoveryFinding,
    )
    from starboard_core.domain.models.discovery.report import DiscoveryReport

logger = get_logger(__name__)


_DOMAIN_DISPLAY_NAMES: dict[str, str] = {
    "aibi": "AI/BI Dashboards & Genie",
    "ai_gateway": "AI Gateway",
    "apps": "Databricks Apps",
    "billing": "Resource Consumption & Attribution",
    "compute": "Compute & Cluster Health",
    "delta_sharing": "Delta Sharing",
    "dlt_pipelines": "DLT Pipelines",
    "governance": "Governance & Data Management",
    "jobs": "Job Workload & Reliability",
    "lakebase": "Lakebase",
    "lakeflow_connect": "Lakeflow Connect",
    "migration": "Migration Prioritization",
    "ml": "ML & Model Serving",
    "mlflow": "MLflow",
    "monitoring": "Lakehouse Monitoring",
    "query_performance": "Query Performance Analysis",
    "serverless_sql": "Serverless SQL",
    "vector_search": "Vector Search",
    "workflow": "Workflow",
}


def domain_display_name(domain: str) -> str:
    """Return a human-readable display name for a canonical pack domain.

    Falls back to title-casing the domain with underscores replaced by spaces.
    """
    return _DOMAIN_DISPLAY_NAMES.get(domain, domain.replace("_", " ").title())


class OutputFormatter:
    """Formats and persists discovery reports.

    Stateless formatter — safe to share across engine instances.
    """

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    def to_json(self, report: DiscoveryReport) -> str:
        """Serialize a ``DiscoveryReport`` to a JSON string.

        Args:
            report: Completed discovery report.

        Returns:
            Pretty-printed JSON string.
        """
        return json.dumps(report.model_dump(mode="json"), indent=2, default=str)

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------

    def to_markdown(self, report: DiscoveryReport) -> str:
        """Render a ``DiscoveryReport`` as a Markdown string.

        Args:
            report: Completed discovery report.

        Returns:
            Full Markdown representation of the report.
        """
        lines: list[str] = []
        summary = report.executive_summary

        lines.append("# Databricks Workspace Health Assessment")
        lines.append("")

        # Executive Summary — always present
        lines.append("## Executive Summary")
        lines.append("")
        if summary.overview:
            lines.append(summary.overview)
            lines.append("")

        # Report Cards
        if summary.report_cards:
            lines.append("## Report Cards")
            lines.append("")
            lines.append("| Domain | Grade | Score | Discussion |")
            lines.append("|--------|-------|-------|------------|")
            for rc in summary.report_cards:
                disc = rc.discussion.replace("\n", " ") if rc.discussion else ""
                display = domain_display_name(rc.domain)
                lines.append(f"| {display} | {rc.grade} | {rc.score:.0f} | {disc} |")
            lines.append("")

        # Top 10 Priorities
        if report.top_priorities:
            lines.append("## Top 10 Priorities")
            lines.append("")
            for i, finding in enumerate(report.top_priorities[:10], 1):
                display = domain_display_name(finding.domain)
                lines.append(
                    f"{i}. **[{finding.priority}]** {finding.title} "
                    f"({display}) — {finding.impact} impact"
                )
                self._render_finding_detail(finding, lines)
                lines.append("")

        # Domain Analyses
        if report.domain_analyses:
            lines.append("## Domain Analyses")
            lines.append("")
            for analysis in report.domain_analyses:
                display = domain_display_name(analysis.domain)
                lines.append(
                    f"### {display} ({analysis.grade}, {analysis.score:.0f}/100)"
                )
                lines.append("")
                if analysis.summary:
                    lines.append(analysis.summary)
                    lines.append("")

                if analysis.observations:
                    lines.append("**Observations:**")
                    lines.append("")
                    for obs in analysis.observations:
                        lines.append(f"- {obs}")
                    lines.append("")

                if analysis.patterns:
                    lines.append("**Patterns:**")
                    lines.append("")
                    for pat in analysis.patterns:
                        lines.append(f"- {pat}")
                    lines.append("")

                if analysis.findings:
                    lines.append("**Findings:**")
                    lines.append("")
                    for f in analysis.findings:
                        lines.append(f"#### {f.finding_id}: {f.title}")
                        lines.append("")
                        lines.append(
                            f"- **Priority:** {f.priority} | "
                            f"**Impact:** {f.impact} | "
                            f"**Type:** {f.finding_type}"
                        )
                        if f.description:
                            lines.append(f"- {f.description}")
                        self._render_finding_detail(f, lines)
                        lines.append("")

                if analysis.recommended_actions:
                    lines.append("**Recommended Actions:**")
                    lines.append("")
                    for act in analysis.recommended_actions:
                        lines.append(f"- {act}")
                    lines.append("")

        # Recommended Actions (top-level)
        if summary.top_actions:
            lines.append("## Recommended Actions")
            lines.append("")
            for i, action in enumerate(summary.top_actions, 1):
                lines.append(f"{i}. {action}")
            lines.append("")

        # Primary Risks
        if summary.primary_risks:
            lines.append("## Primary Risks")
            lines.append("")
            for risk in summary.primary_risks:
                lines.append(f"- {risk}")
            lines.append("")

        # Footer
        ctx = summary.analysis_context
        lines.append("---")
        lines.append("")
        lines.append(
            f"*Generated: {report.metadata.generated_at or ctx.analysis_timestamp} "
            f"| Lookback: {ctx.lookback_days}d "
            f"| Queries: {ctx.total_queries_executed} "
            f"| Domains: {len(ctx.domains_analyzed)}*"
        )

        if summary.notes:
            lines.append("")
            for note in summary.notes:
                lines.append(f"> {note}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Finding detail helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_finding_detail(finding: DiscoveryFinding, lines: list[str]) -> None:
        """Append evidence, causes, and remediation blocks for a finding."""
        if finding.evidence:
            lines.append("   **Evidence:**")
            for ev in finding.evidence:
                parts = [f"[{ev.source_query_id}]", ev.excerpt]
                if ev.metric_name:
                    parts.append(f"({ev.metric_name}: {ev.metric_value})")
                lines.append(f"   - {' '.join(parts)}")

        if finding.likely_causes:
            lines.append("   **Likely Causes:**")
            for cause in finding.likely_causes:
                tag = " (Hypothesis)" if cause.is_hypothesis else ""
                lines.append(f"   - {cause.description}{tag}")
                if cause.how_to_confirm:
                    lines.append(f"     How to confirm: {cause.how_to_confirm}")

        rem = finding.remediation
        if rem.immediate or rem.medium_term or rem.long_term:
            lines.append("   **Remediation:**")
            if rem.immediate:
                lines.append("   *Immediate*:")
                for a in rem.immediate:
                    lines.append(f"   - {a}")
            if rem.medium_term:
                lines.append("   *Medium-term*:")
                for a in rem.medium_term:
                    lines.append(f"   - {a}")
            if rem.long_term:
                lines.append("   *Long-term*:")
                for a in rem.long_term:
                    lines.append(f"   - {a}")

    # ------------------------------------------------------------------
    # Executive summary (standalone)
    # ------------------------------------------------------------------

    def _render_executive_summary(self, report: DiscoveryReport) -> str:
        """Render a standalone executive summary Markdown file."""
        lines: list[str] = []
        summary = report.executive_summary

        lines.append("# Executive Summary")
        lines.append("")
        if summary.overview:
            lines.append(summary.overview)
            lines.append("")

        if summary.report_cards:
            lines.append("## Report Cards")
            lines.append("")
            lines.append("| Domain | Grade | Score |")
            lines.append("|--------|-------|-------|")
            for rc in summary.report_cards:
                display = domain_display_name(rc.domain)
                lines.append(f"| {display} | {rc.grade} | {rc.score:.0f} |")
            lines.append("")

        if summary.top_actions:
            lines.append("## Top Actions")
            lines.append("")
            for i, action in enumerate(summary.top_actions, 1):
                lines.append(f"{i}. {action}")
            lines.append("")

        if summary.primary_risks:
            lines.append("## Primary Risks")
            lines.append("")
            for risk in summary.primary_risks:
                lines.append(f"- {risk}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Top priorities (standalone)
    # ------------------------------------------------------------------

    def _render_top_priorities(self, report: DiscoveryReport) -> str:
        """Render a standalone top priorities Markdown file."""
        lines: list[str] = []
        lines.append("# Top Priorities")
        lines.append("")

        for i, finding in enumerate(report.top_priorities[:10], 1):
            display = domain_display_name(finding.domain)
            lines.append(
                f"{i}. **[{finding.priority}]** {finding.title} "
                f"({display}) — {finding.impact} impact"
            )
            self._render_finding_detail(finding, lines)
            lines.append("")

        if not report.top_priorities:
            lines.append("No priority findings identified.")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Per-domain rendering
    # ------------------------------------------------------------------

    def render_domain_analysis(self, analysis: DomainAnalysis) -> str:
        """Render a single ``DomainAnalysis`` to a standalone Markdown file.

        Contains the full detail — observations, patterns, every finding
        with evidence and remediation, and recommended actions — so
        the agent tool response can stay compact while nothing is lost.

        Args:
            analysis: Completed analysis for one domain.

        Returns:
            Full Markdown string for this domain.
        """
        lines: list[str] = []

        display = domain_display_name(analysis.domain)
        lines.append(
            f"# {display} — Grade {analysis.grade} ({analysis.score:.0f}/100)"
        )
        lines.append("")

        if analysis.summary:
            lines.append(analysis.summary)
            lines.append("")

        if analysis.observations:
            lines.append("## Observations")
            lines.append("")
            for obs in analysis.observations:
                lines.append(f"- {obs}")
            lines.append("")

        if analysis.patterns:
            lines.append("## Patterns")
            lines.append("")
            for pat in analysis.patterns:
                lines.append(f"- {pat}")
            lines.append("")

        if analysis.findings:
            lines.append("## Findings")
            lines.append("")
            for f in analysis.findings:
                lines.append(f"### {f.finding_id}: {f.title}")
                lines.append("")
                lines.append(
                    f"- **Priority:** {f.priority} | "
                    f"**Impact:** {f.impact} | "
                    f"**Type:** {f.finding_type}"
                )
                if f.description:
                    lines.append(f"- {f.description}")
                self._render_finding_detail(f, lines)
                if f.expected_outcome:
                    lines.append(f"   **Expected Outcome:** {f.expected_outcome}")
                lines.append("")

        if analysis.recommended_actions:
            lines.append("## Recommended Actions")
            lines.append("")
            for i, act in enumerate(analysis.recommended_actions, 1):
                lines.append(f"{i}. {act}")
            lines.append("")

        cov = analysis.data_coverage
        lines.append("---")
        lines.append("")
        lines.append(
            f"*Queries: {cov.queries_succeeded}/{cov.queries_executed} succeeded*"
        )
        if cov.gaps:
            lines.append("")
            for gap in cov.gaps:
                lines.append(f"> {gap}")

        return "\n".join(lines)

    @staticmethod
    def _safe_filename(domain: str) -> str:
        """Convert a domain name to a filesystem-safe filename.

        Replaces slashes, parentheses, spaces, and other special
        characters with underscores, then collapses runs and strips edges.

        Args:
            domain: Raw domain name (e.g. ``"Aibi (AI/BI)"``).

        Returns:
            Sanitized string safe for use as a filename stem.
        """
        safe = re.sub(r"[/\\:*?\"<>|()\s]+", "_", domain)
        safe = re.sub(r"_+", "_", safe).strip("_")
        return safe.lower() or "unknown"

    async def write_domain_analyses(
        self,
        analyses: list[DomainAnalysis],
        output_dir: str | Path,
    ) -> dict[str, str]:
        """Write each domain analysis to its own Markdown file.

        Creates a ``domains/`` subdirectory under ``output_dir`` and writes
        one ``{domain}.md`` file per analysis.

        Args:
            analyses: Domain analyses to persist.
            output_dir: Parent output directory.

        Returns:
            Dict mapping domain name to the written file path.
        """
        domains_dir = Path(output_dir) / "domains"
        await asyncio.to_thread(domains_dir.mkdir, parents=True, exist_ok=True)

        domain_paths: dict[str, str] = {}

        async def _write_one(analysis: DomainAnalysis) -> None:
            safe_name = self._safe_filename(analysis.domain)
            path = domains_dir / f"{safe_name}.md"
            content = self.render_domain_analysis(analysis)
            await write_text(path, content)
            domain_paths[analysis.domain] = str(path)
            logger.info(
                "domain_analysis_written",
                domain=analysis.domain,
                path=str(path),
                chars=len(content),
            )

        await asyncio.gather(*[_write_one(a) for a in analyses])
        return domain_paths

    # ------------------------------------------------------------------
    # File output
    # ------------------------------------------------------------------

    async def write_to_directory(
        self,
        report: DiscoveryReport,
        output_dir: str | Path,
    ) -> list[Path]:
        """Write report artefacts to a directory.

        Produces four files in parallel plus per-domain detail files:
        - ``report.md`` — full Markdown report
        - ``report.json`` — full JSON export
        - ``executive_summary.md`` — standalone executive summary
        - ``top_priorities.md`` — standalone priorities list
        - ``domains/{domain}.md`` — per-domain detailed analysis

        Args:
            report: Completed discovery report.
            output_dir: Directory to write output files into.

        Returns:
            List of paths to written files.
        """
        out = Path(output_dir)
        await asyncio.to_thread(out.mkdir, parents=True, exist_ok=True)

        # Pre-render all content (pure CPU, no I/O)
        md_path = out / "report.md"
        json_path = out / "report.json"
        exec_path = out / "executive_summary.md"
        prio_path = out / "top_priorities.md"

        md_content = self.to_markdown(report)
        json_content = self.to_json(report)
        exec_content = self._render_executive_summary(report)
        prio_content = self._render_top_priorities(report)

        # Write all files in parallel (including per-domain files)
        domain_paths_task = self.write_domain_analyses(
            report.domain_analyses, output_dir
        )
        await asyncio.gather(
            write_text(md_path, md_content),
            write_text(json_path, json_content),
            write_text(exec_path, exec_content),
            write_text(prio_path, prio_content),
            domain_paths_task,
        )

        written = [md_path, json_path, exec_path, prio_path]

        for path, fmt in [
            (md_path, "markdown"),
            (json_path, "json"),
            (exec_path, "markdown"),
            (prio_path, "markdown"),
        ]:
            logger.info("discovery_output_written", path=str(path), format=fmt)

        return written
