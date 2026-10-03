# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Cluster report formatter for Cluster agent.

Formats ClusterReport into readable markdown with:
- Summary with key observations
- Cluster configuration analysis
- Performance metrics
- Recommendations with effort/impact estimates

This formatter is used as a fallback when rich frontend rendering is unavailable.
The primary rendering is done by the frontend ClusterReportBubble component.
"""

from typing import Any

from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


class ClusterReportFormatter:
    """Formats ClusterReport to markdown.

    Implements the ReportFormatter protocol for 'cluster' report type.
    Used by Cluster Agent for Databricks cluster optimization.

    Example:
        >>> formatter = ClusterReportFormatter()
        >>> report = {"report_type": "cluster", "summary": {...}, ...}
        >>> markdown = formatter.format_to_markdown(report)
    """

    def get_report_type(self) -> str:
        """Return supported report type.

        Returns:
            "cluster" - the report type this formatter handles
        """
        return "cluster"

    def format_to_markdown(self, report: dict[str, Any]) -> str:
        """Format ClusterReport to markdown.

        Sections formatted:
        - Summary (overview, key observations)
        - Configuration Analysis
        - Performance Metrics
        - Recommendations (advisor-style findings)

        Args:
            report: ClusterReport dict (from Pydantic model.model_dump())

        Returns:
            Formatted markdown string

        Example:
            >>> formatter = ClusterReportFormatter()
            >>> report = {
            ...     "report_type": "cluster",
            ...     "summary": {"overview": "Cluster analysis complete"},
            ... }
            >>> markdown = formatter.format_to_markdown(report)
        """
        if not isinstance(report, dict):
            logger.warning(
                "cluster_formatter_invalid_type",
                report_type=type(report).__name__,
            )
            return "Analysis complete."

        parts = []

        # Summary section
        summary = report.get("summary", {})
        if summary:
            summary_md = self._format_summary(summary)
            if summary_md:
                parts.append(summary_md)

        # Performance findings
        analysis = report.get("analysis")
        if analysis and analysis.get("findings"):
            findings_md = self._format_findings(analysis.get("findings", []))
            if findings_md:
                parts.append(findings_md)

        if parts:
            result = "\n\n".join(parts)
            logger.debug(
                "cluster_report_formatted",
                length=len(result),
                sections=len(parts),
            )
            return result

        return "Analysis complete."

    def _format_summary(self, summary: dict[str, Any]) -> str:
        """Format summary section."""
        if not isinstance(summary, dict):
            return ""

        lines = ["## Summary\n"]

        overview = summary.get("overview", "")
        if overview:
            lines.append(overview)

        current_state = summary.get("current_state", {})
        if isinstance(current_state, dict):
            resource_type = current_state.get("resource_type", "")
            if resource_type:
                lines.append(f"\n**Resource Type:** {resource_type}")

            symptoms = current_state.get("key_symptoms", [])
            if symptoms and isinstance(symptoms, list):
                lines.append(f"\n**Key Observations:** {', '.join(symptoms)}")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_findings(self, findings: list[dict[str, Any]]) -> str:
        """Format performance findings (advisor format)."""
        if not findings or not isinstance(findings, list):
            return ""

        lines = ["## Recommendations\n"]

        for i, finding in enumerate(findings, 1):
            if not isinstance(finding, dict):
                continue

            title = finding.get("title", "")
            category = finding.get("category", "")
            recommendation = finding.get("recommendation", "")

            if title:
                lines.append(f"\n### {i}. {title}")
                if category:
                    lines.append(f"**Category:** {category}")
                if recommendation:
                    lines.append(f"\n{recommendation}")

                # Impact estimate
                impact = finding.get("impact_estimate", {})
                if isinstance(impact, dict):
                    cost_pct = impact.get("cost_pct")
                    if cost_pct is not None:
                        lines.append(
                            f"\n**Estimated Impact:** {cost_pct:+.0f}% cost change"
                        )

                # Effort
                effort = finding.get("effort", {})
                if isinstance(effort, dict):
                    level = effort.get("level", "")
                    hours = effort.get("estimate_hours")
                    if level:
                        effort_str = f"**Effort:** {level}"
                        if hours:
                            effort_str += f" (~{hours}h)"
                        lines.append(effort_str)

        return "\n".join(lines) if len(lines) > 1 else ""
