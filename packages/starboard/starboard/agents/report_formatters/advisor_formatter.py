# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Advisor report formatter for optimization agents.

Formats AdvisorReport (used by query, job, table, compute agents)
into readable markdown with:
- Summary with current state
- Optimization findings with impact/effort estimates
- Optional query rewrites

NOTE: Next Steps are rendered separately by the frontend NextStepsBubble component
for better visibility and interactivity. They are NOT embedded in the markdown report.
"""

from typing import Any

from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


class AdvisorReportFormatter:
    """
    Formats AdvisorReport to markdown.

    Used by optimization agents (query, job, table, compute) that focus on
    performance improvements, configuration tuning, and resource efficiency.
    """

    def get_report_type(self) -> str:
        """Return supported report type."""
        return "advisor"

    def format_to_markdown(self, report: dict[str, Any]) -> str:
        """
        Format AdvisorReport to markdown.

        Sections:
        - Summary (overview, current state, key symptoms)
        - Recommendations (findings with impact/effort)
        - Optimized Query (if applicable)

        NOTE: Next Steps are rendered separately by the frontend for better visibility.

        Args:
            report: AdvisorReport dict

        Returns:
            Formatted markdown string

        Example:
            >>> report = {
            ...     "report_type": "advisor",
            ...     "summary": {"overview": "Query is slow..."},
            ...     "analysis": {"findings": [...]},
            ...     "next_steps": [...]
            ... }
            >>> formatter = AdvisorReportFormatter()
            >>> markdown = formatter.format_to_markdown(report)
        """
        if not isinstance(report, dict):
            logger.warning(
                "advisor_formatter_invalid_type",
                report_type=type(report).__name__,
            )
            return "Analysis complete."

        parts = []

        # Summary section
        summary = report.get("summary", {})
        logger.debug(
            "formatting_summary",
            has_summary=bool(summary),
            summary_type=type(summary).__name__,
            summary_keys=list(summary.keys()) if isinstance(summary, dict) else [],
        )
        summary_md = self._format_summary(summary)
        logger.debug(
            "summary_formatted",
            summary_md_length=len(summary_md) if summary_md else 0,
        )
        if summary_md:
            parts.append(summary_md)

        # Recommendations section (findings)
        analysis = report.get("analysis", {})
        if isinstance(analysis, dict):
            # Debug: check for double-nested analysis
            if "analysis" in analysis and isinstance(analysis["analysis"], dict):
                logger.warning(
                    "double_nested_analysis_in_formatter",
                    note="analysis.analysis detected, using inner analysis",
                )
                analysis = analysis["analysis"]  # Unwrap

            findings = analysis.get("findings", [])
            logger.debug(
                "formatting_findings",
                findings_count=len(findings) if isinstance(findings, list) else 0,
                analysis_keys=list(analysis.keys()),
            )
            findings_md = self._format_findings(findings)
            logger.debug(
                "findings_formatted",
                findings_md_length=len(findings_md) if findings_md else 0,
            )
            if findings_md:
                parts.append(findings_md)

            # Query rewrite section (query agent only)
            query_rewrite = analysis.get("query_rewrite")
            if isinstance(query_rewrite, dict) and query_rewrite.get("applicable"):
                rewrite_md = self._format_query_rewrite(query_rewrite)
                if rewrite_md:
                    parts.append(rewrite_md)

        # NOTE: Next Steps are NOT embedded in markdown.
        # They are rendered separately by frontend NextStepsBubble for better visibility.
        # The next_steps data is still returned in the agent output and streamed via SSE.

        if parts:
            result = "\n".join(parts)
            logger.debug(
                "advisor_report_formatted",
                length=len(result),
                sections=len(parts),
                parts_preview=[p[:50] + "..." if len(p) > 50 else p for p in parts],
            )
            return result

        # Fallback
        logger.warning(
            "advisor_report_no_content",
            report_keys=list(report.keys()) if isinstance(report, dict) else [],
        )
        return "Analysis complete."

    def _format_summary(self, summary: dict[str, Any]) -> str:
        """Format summary section."""
        if not isinstance(summary, dict):
            return ""

        lines = []

        overview = summary.get("overview", "")
        if overview:
            lines.append("## Summary\n")
            lines.append(f"{overview}\n")

            # Current state symptoms
            current_state = summary.get("current_state", {})
            if isinstance(current_state, dict):
                symptoms = current_state.get("key_symptoms", [])
                if symptoms and isinstance(symptoms, list):
                    lines.append(f"**Key Symptoms:** {', '.join(symptoms)}\n")

        return "\n".join(lines) if lines else ""

    def _format_findings(self, findings: list[dict[str, Any]]) -> str:
        """Format findings/recommendations section."""
        if not findings or not isinstance(findings, list):
            return ""

        lines = ["### Recommendations\n"]

        for i, finding in enumerate(findings, 1):
            if not isinstance(finding, dict):
                continue

            finding_md = self._format_finding(i, finding)
            if finding_md:
                lines.append(finding_md)

        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_finding(self, index: int, finding: dict[str, Any]) -> str:
        """Format a single finding."""
        lines = []

        title = finding.get("title", "")
        category = finding.get("category", "")
        recommendation = finding.get("recommendation", "")

        if title:
            lines.append(f"\n### {index}. {title}")
            if category:
                lines.append(f"**Category:** {category}")

            if recommendation:
                lines.append(f"\n{recommendation}")

            # Impact estimate
            impact_md = self._format_impact(finding.get("impact_estimate", {}))
            if impact_md:
                lines.append(impact_md)

            # Effort estimate
            effort_md = self._format_effort(finding.get("effort", {}))
            if effort_md:
                lines.append(effort_md)

            # Fixes/code snippets
            fixes_md = self._format_fixes(finding.get("fixes", []))
            if fixes_md:
                lines.append(fixes_md)

            lines.append("")  # Blank line between findings

        return "\n".join(lines) if lines else ""

    def _format_impact(self, impact: dict[str, Any]) -> str:
        """Format impact estimate."""
        if not isinstance(impact, dict):
            return ""

        query_time = impact.get("query_time_pct", 0)
        cost = impact.get("cost_pct", 0)
        confidence = impact.get("confidence", "")

        impact_parts = []

        if query_time != 0:
            sign = "faster" if query_time < 0 else "slower"
            impact_parts.append(f"{abs(query_time):.0f}% {sign}")

        if cost != 0:
            sign = "cheaper" if cost < 0 else "more expensive"
            impact_parts.append(f"{abs(cost):.0f}% {sign}")

        if impact_parts:
            impact_str = ", ".join(impact_parts)
            return f"**Impact:** {impact_str} ({confidence} confidence)"

        return ""

    def _format_effort(self, effort: dict[str, Any]) -> str:
        """Format effort estimate."""
        if not isinstance(effort, dict):
            return ""

        level = effort.get("level", "")
        hours = effort.get("estimate_hours")

        if level:
            effort_str = f"**Effort:** {level.capitalize()}"
            if hours:
                effort_str += f" (~{hours}h)"
            return effort_str

        return ""

    def _format_fixes(self, fixes: list[dict[str, Any]]) -> str:
        """Format code fixes/snippets."""
        if not fixes or not isinstance(fixes, list):
            return ""

        lines = ["\n**Suggested Changes:**"]

        for fix in fixes:
            if not isinstance(fix, dict):
                continue

            snippet = fix.get("snippet", "")
            notes = fix.get("notes", "")

            if snippet:
                lines.append(f"\n```sql\n{snippet}\n```")

            if notes:
                lines.append(f"*{notes}*")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_query_rewrite(self, rewrite: dict[str, Any]) -> str:
        """Format query rewrite section."""
        if not isinstance(rewrite, dict):
            return ""

        sql = rewrite.get("sql", "")
        notes = rewrite.get("notes", "")

        if not sql:
            return ""

        lines = ["\n### Optimized Query\n"]

        lines.append("```sql")
        lines.append(sql)
        lines.append("```")

        if notes:
            lines.append(f"\n**Notes:** {notes}")

        lines.append("")  # Blank line

        return "\n".join(lines)

    def _format_next_steps(self, next_steps: list[dict[str, Any]]) -> str:
        """Format next steps section using detailed format.

        Expects each step to have: id, number, title, description, action_type.
        """
        if not next_steps or not isinstance(next_steps, list):
            return ""

        lines = ["\n### Suggested Next Steps\n"]

        for step in next_steps:
            if not isinstance(step, dict):
                continue

            number = step.get("number", 0)
            title = step.get("title", "")
            description = step.get("description", "")

            if title:
                lines.append(f"{number}. **{title}**")
                if description:
                    lines.append(f"   {description}")
                lines.append("")  # Blank line between steps

        return "\n".join(lines) if len(lines) > 1 else ""
