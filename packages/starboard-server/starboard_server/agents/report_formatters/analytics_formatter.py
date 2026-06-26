# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Analytics report formatter for FinOps agent.

Formats AnalyticsReport (used by analytics/FinOps agent) into readable
markdown with:
- Summary with overview
- Cost overview (total, trend, top contributors)
- Cost optimization opportunities (findings ranked by savings)
- Visualization recommendations (chart metadata)

NOTE: Next Steps are rendered separately by the frontend NextStepsBubble component
for better visibility and interactivity. They are NOT embedded in the markdown report.
"""

from typing import Any

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class AnalyticsReportFormatter:
    """
    Formats AnalyticsReport to markdown.

    Used by analytics (FinOps) agent that focuses on cost analysis,
    usage trends, resource attribution, and waste detection.
    """

    def get_report_type(self) -> str:
        """Return supported report type."""
        return "analytics"

    def format_to_markdown(self, report: dict[str, Any]) -> str:
        """
        Format AnalyticsReport to markdown.

        Sections:
        - Summary (overview)
        - Cost Overview (total, trend, top contributors)
        - Cost Optimization Opportunities (findings ranked by savings %)

        NOTE: Next Steps are rendered separately by the frontend for better visibility.

        Args:
            report: AnalyticsReport dict

        Returns:
            Formatted markdown string

        Example:
            >>> report = {
            ...     "report_type": "analytics",
            ...     "summary": {"overview": "Total spend: $45k/month..."},
            ...     "findings": [...],
            ...     "cost_summary": {...},
            ...     "visualization": {...},
            ...     "next_steps": [...]
            ... }
            >>> formatter = AnalyticsReportFormatter()
            >>> markdown = formatter.format_to_markdown(report)
        """
        if not isinstance(report, dict):
            logger.warning(
                "analytics_formatter_invalid_type",
                report_type=type(report).__name__,
            )
            return "Cost analysis complete."

        parts = []

        # Summary section
        summary_md = self._format_summary(report.get("summary", {}))
        if summary_md:
            parts.append(summary_md)

        # Cost summary section
        cost_summary_md = self._format_cost_summary(report.get("cost_summary", {}))
        if cost_summary_md:
            parts.append(cost_summary_md)

        # Cost findings section
        findings_md = self._format_findings(report.get("findings", []))
        if findings_md:
            parts.append(findings_md)

        # Visualization recommendation (hidden for CLI/console)
        # visualization_md = self._format_visualization(report.get("visualization"))
        # if visualization_md:
        #     parts.append(visualization_md)

        # NOTE: Next Steps are NOT embedded in markdown.
        # They are rendered separately by frontend NextStepsBubble for better visibility.
        # The next_steps data is still returned in the agent output and streamed via SSE.

        if parts:
            result = "\n".join(parts)
            logger.debug(
                "analytics_report_formatted",
                length=len(result),
                sections=len(parts),
            )
            return result

        # Fallback
        logger.warning(
            "analytics_report_no_content",
            report_keys=list(report.keys()) if isinstance(report, dict) else [],
        )
        return "Cost analysis complete."

    def _format_summary(self, summary: dict[str, Any]) -> str:
        """Format summary section."""
        if not isinstance(summary, dict):
            return ""

        overview = summary.get("overview", "")
        if not overview:
            return ""

        return f"### Summary\n\n{overview}\n"

    def _format_cost_summary(self, cost_summary: dict[str, Any]) -> str:
        """Format cost summary section."""
        if not isinstance(cost_summary, dict):
            return ""

        lines = ["### Cost Overview\n"]

        # Get required schema fields
        primary_metric = cost_summary.get("primary_metric", "")
        primary_metric_unit = cost_summary.get("primary_metric_unit", "USD")
        total = cost_summary.get("total", 0)
        mean = cost_summary.get("mean", 0)
        max_value = cost_summary.get("max", 0)
        cost_trend = cost_summary.get("cost_trend", "")
        period = cost_summary.get("period", "")
        top_contributors = cost_summary.get("top_contributors", [])

        # Format total based on unit
        if primary_metric_unit == "USD":
            lines.append(f"**Total Cost:** ${total:,.2f}")
            if mean:
                lines.append(f"**Average:** ${mean:,.2f}")
            if max_value:
                lines.append(f"**Maximum:** ${max_value:,.2f}")
        elif primary_metric_unit == "DBU":
            lines.append(f"**Total DBUs:** {total:,.2f}")
            if mean:
                lines.append(f"**Average:** {mean:,.2f} DBUs")
            if max_value:
                lines.append(f"**Maximum:** {max_value:,.2f} DBUs")
        else:
            # Generic metric
            lines.append(
                f"**Total {primary_metric}:** {total:,.2f} {primary_metric_unit}"
            )
            if mean:
                lines.append(f"**Average:** {mean:,.2f} {primary_metric_unit}")
            if max_value:
                lines.append(f"**Maximum:** {max_value:,.2f} {primary_metric_unit}")

        # Period
        if period:
            lines.append(f"**Period:** {period}")

        # Cost trend with emoji
        if cost_trend:
            trend_emoji = {
                "increasing": "📈",
                "stable": "➡️",
                "decreasing": "📉",
            }.get(cost_trend, "")
            trend_display = cost_trend.capitalize()
            lines.append(f"**Trend:** {trend_emoji} {trend_display}")

        # Top contributors
        if top_contributors and isinstance(top_contributors, list):
            lines.append("\n**Top Contributors:**")
            for contrib in top_contributors[:5]:  # Limit to top 5
                if isinstance(contrib, dict):
                    # Format: {id, name, value, unit, notes}
                    name = contrib.get("name", contrib.get("id", "Unknown"))
                    value = contrib.get("value", 0)
                    unit = contrib.get("unit", primary_metric_unit)
                    notes = contrib.get("notes", "")

                    if unit == "USD":
                        contrib_str = f"- {name}: ${value:,.2f}"
                    elif unit == "DBU":
                        contrib_str = f"- {name}: {value:,.2f} DBUs"
                    else:
                        contrib_str = f"- {name}: {value:,.2f} {unit}"

                    if notes:
                        contrib_str += f" ({notes})"
                    lines.append(contrib_str)

        lines.append("")  # Blank line
        return "\n".join(lines)

    def _format_findings(self, findings: list[dict[str, Any]]) -> str:
        """Format cost findings section."""
        if not findings or not isinstance(findings, list):
            return ""

        lines = ["### Cost Optimization Opportunities\n"]

        for i, finding in enumerate(findings, 1):
            if not isinstance(finding, dict):
                continue

            finding_md = self._format_finding(i, finding)
            if finding_md:
                lines.append(finding_md)

        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_finding(self, index: int, finding: dict[str, Any]) -> str:
        """Format a single cost finding."""
        lines = []

        title = finding.get("title", "")
        category = finding.get("category", "")
        recommendation = finding.get("recommendation", "")

        if title:
            lines.append(f"\n### {index}. {title}")

            # Category (formatted from SNAKE_CASE)
            if category:
                category_display = category.replace("_", " ").title()
                lines.append(f"**Category:** {category_display}")

            # Recommendation
            if recommendation:
                lines.append(f"\n{recommendation}")

            # Cost impact
            cost_impact_md = self._format_cost_impact(finding.get("cost_impact", {}))
            if cost_impact_md:
                lines.append(cost_impact_md)

            # Effort
            effort_md = self._format_effort(finding.get("effort", {}))
            if effort_md:
                lines.append(effort_md)

            lines.append("")  # Blank line between findings

        return "\n".join(lines) if lines else ""

    def _format_cost_impact(self, cost_impact: dict[str, Any]) -> str:
        """Format cost impact estimate."""
        if not isinstance(cost_impact, dict):
            return ""

        current = cost_impact.get("current_monthly_cost", 0)
        savings = cost_impact.get("projected_savings_monthly", 0)
        cost_unit = cost_impact.get("cost_unit", "dollar")
        savings_pct = cost_impact.get("savings_pct", 0)
        confidence = cost_impact.get("confidence", "")

        lines = []

        # Format based on cost unit
        if cost_unit == "dollar":
            lines.append(f"\n**Current Monthly Cost:** ${current:,.2f}")
            lines.append(
                f"**Projected Savings:** ${savings:,.2f}/month ({savings_pct:.0f}%)"
            )
        elif cost_unit == "dbu":
            lines.append(f"\n**Current Monthly Usage:** {current:,.2f} DBUs")
            lines.append(
                f"**Projected Savings:** {savings:,.2f} DBUs/month ({savings_pct:.0f}%)"
            )
        else:
            # Fallback to dollar formatting
            lines.append(f"\n**Current Monthly Cost:** ${current:,.2f}")
            lines.append(
                f"**Projected Savings:** ${savings:,.2f}/month ({savings_pct:.0f}%)"
            )

        if confidence:
            lines.append(f"**Confidence:** {confidence.capitalize()}")

        return "\n".join(lines)

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

    def _format_visualization(self, visualization: dict[str, Any] | None) -> str:
        """Format visualization recommendation section."""
        if not visualization or not isinstance(visualization, dict):
            return ""

        lines = ["\n### 📊 Recommended Visualization\n"]

        chart_type = visualization.get("recommended_chart", "")
        primary_metric = visualization.get("primary_metric", "")
        primary_dimension = visualization.get("primary_dimension", "")
        time_dimension = visualization.get("time_dimension")
        notes = visualization.get("notes", "")

        if chart_type:
            lines.append(f"**Chart Type:** {chart_type.capitalize()}")

        if primary_metric:
            lines.append(f"**Primary Metric:** `{primary_metric}`")

        if primary_dimension:
            lines.append(f"**Dimension:** `{primary_dimension}`")

        if time_dimension:
            lines.append(f"**Time Column:** `{time_dimension}`")

        if notes:
            lines.append(f"\n{notes}")

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
