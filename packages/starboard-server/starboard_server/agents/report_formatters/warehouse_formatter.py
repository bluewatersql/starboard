"""Warehouse report formatter for SQL Warehouse agent.

Formats WarehouseReport into readable markdown with:
- Portfolio summary with health distribution
- Individual resource health metrics
- Topology analysis and consolidation opportunities
- User activity / chargeback summaries
- Performance findings (advisor format)

This formatter is used as a fallback when rich frontend rendering is unavailable.
The primary rendering is done by the frontend WarehouseReportBubble component.
"""

from typing import Any

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class WarehouseReportFormatter:
    """Formats WarehouseReport to markdown.

    Implements the ReportFormatter protocol for 'warehouse' report type.
    Used by the Warehouse Agent for SQL warehouse portfolio analysis.

    Example:
        >>> formatter = WarehouseReportFormatter()
        >>> report = {"report_type": "warehouse", "summary": {...}, ...}
        >>> markdown = formatter.format_to_markdown(report)
    """

    def get_report_type(self) -> str:
        """Return supported report type.

        Returns:
            "warehouse" - the report type this formatter handles
        """
        return "warehouse"

    def format_to_markdown(self, report: dict[str, Any]) -> str:
        """Format WarehouseReport to markdown.

        Sections formatted:
        - Summary (overview, key observations)
        - Portfolio Overview (health distribution, top resources)
        - Health Analysis (scores, SLO compliance, risks)
        - Topology Analysis (clusters, consolidation opportunities)
        - User Activity (top users, allocation method)
        - Performance Recommendations (advisor-style findings)

        Args:
            report: WarehouseReport dict (from Pydantic model.model_dump())

        Returns:
            Formatted markdown string

        Example:
            >>> formatter = WarehouseReportFormatter()
            >>> report = {
            ...     "report_type": "warehouse",
            ...     "summary": {"overview": "Analysis complete"},
            ...     "portfolio_summary": {"total_count": 5, ...}
            ... }
            >>> markdown = formatter.format_to_markdown(report)
        """
        if not isinstance(report, dict):
            logger.warning(
                "warehouse_formatter_invalid_type",
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

        # Portfolio summary
        portfolio = report.get("portfolio_summary")
        if portfolio:
            portfolio_md = self._format_portfolio(portfolio)
            if portfolio_md:
                parts.append(portfolio_md)

        # Health metrics
        health = report.get("health_metrics")
        if health:
            health_md = self._format_health_metrics(health)
            if health_md:
                parts.append(health_md)

        # Topology analysis
        topology = report.get("topology_analysis")
        if topology:
            topology_md = self._format_topology(topology)
            if topology_md:
                parts.append(topology_md)

        # User activity
        user_activity = report.get("user_activity")
        if user_activity:
            activity_md = self._format_user_activity(user_activity)
            if activity_md:
                parts.append(activity_md)

        # Performance findings (reuses advisor format)
        analysis = report.get("analysis")
        if analysis and analysis.get("findings"):
            findings_md = self._format_findings(analysis.get("findings", []))
            if findings_md:
                parts.append(findings_md)

        if parts:
            result = "\n\n".join(parts)
            logger.debug(
                "warehouse_report_formatted",
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
            symptoms = current_state.get("key_symptoms", [])
            if symptoms and isinstance(symptoms, list):
                lines.append(f"\n**Key Observations:** {', '.join(symptoms)}")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_portfolio(self, portfolio: dict[str, Any]) -> str:
        """Format portfolio summary section."""
        if not isinstance(portfolio, dict):
            return ""

        lines = ["## Portfolio Overview\n"]

        total = portfolio.get("total_count", 0)
        lines.append(f"**Total Resources:** {total}\n")

        dist = portfolio.get("health_distribution", {})
        if dist and isinstance(dist, dict):
            lines.append("**Health Distribution:**")
            lines.append(f"- 🟢 Healthy: {dist.get('healthy', 0)}")
            lines.append(f"- 🟡 Warning: {dist.get('warning', 0)}")
            lines.append(f"- 🔴 Critical: {dist.get('critical', 0)}")
            lines.append(f"- ⚪ Inactive: {dist.get('inactive', 0)}")

        top_resources = portfolio.get("top_resources", [])
        if top_resources and isinstance(top_resources, list):
            lines.append("\n**Top Resources:**")
            for r in top_resources[:5]:
                if isinstance(r, dict):
                    name = r.get("name", "Unknown")
                    score = r.get("health_score", 0)
                    status = r.get("health_status", "unknown")
                    lines.append(f"- **{name}**: {score}/100 ({status})")

        return "\n".join(lines)

    def _format_health_metrics(self, health: dict[str, Any]) -> str:
        """Format health metrics section."""
        if not isinstance(health, dict):
            return ""

        lines = ["## Health Analysis\n"]

        overall = health.get("overall_score", 0)
        lines.append(f"**Overall Health Score:** {overall}/100\n")

        scores = health.get("metric_scores", {})
        if scores and isinstance(scores, dict):
            lines.append("**Metric Breakdown:**")
            lines.append(f"- Latency: {scores.get('latency', 0)}/100")
            lines.append(f"- Availability: {scores.get('availability', 0)}/100")
            lines.append(f"- Queue Time: {scores.get('queue_time', 0)}/100")
            lines.append(f"- Error Rate: {scores.get('error_rate', 0)}/100")

        slo = health.get("slo_compliance")
        if slo and isinstance(slo, dict):
            met = slo.get("targets_met", 0)
            total = slo.get("targets_total", 0)
            lines.append(f"\n**SLO Compliance:** {met}/{total} targets met")

        risks = health.get("risk_factors", [])
        if risks and isinstance(risks, list):
            lines.append("\n**Risk Factors:**")
            for risk in risks:
                lines.append(f"- ⚠️ {risk}")

        return "\n".join(lines)

    def _format_topology(self, topology: dict[str, Any]) -> str:
        """Format topology analysis section."""
        if not isinstance(topology, dict):
            return ""

        lines = ["## Topology Analysis\n"]

        clusters = topology.get("clusters", [])
        if clusters and isinstance(clusters, list):
            lines.append("**Workload Clusters Identified:**")
            for c in clusters:
                if isinstance(c, dict):
                    name = c.get("name", "Cluster")
                    resources = c.get("resources", [])
                    similarity = c.get("similarity_score", 0)
                    lines.append(
                        f"- **{name}**: {len(resources)} resources "
                        f"({similarity:.0%} similarity)"
                    )

        consolidation = topology.get("consolidation_opportunities", [])
        if consolidation and isinstance(consolidation, list):
            lines.append("\n**Consolidation Opportunities:**")
            for opp in consolidation:
                if isinstance(opp, dict):
                    rec = opp.get("recommendation", "")
                    savings = opp.get("estimated_savings_pct", 0)
                    confidence = opp.get("confidence", "low")
                    lines.append(
                        f"- {rec} (Est. {savings:.0f}% savings, {confidence} confidence)"
                    )

        return "\n".join(lines)

    def _format_user_activity(self, activity: dict[str, Any]) -> str:
        """Format user activity summary section."""
        if not isinstance(activity, dict):
            return ""

        lines = ["## User Activity\n"]

        period = activity.get("period", "")
        if period:
            lines.append(f"**Period:** {period}\n")

        method = activity.get("allocation_method")
        if method:
            lines.append(f"**Allocation Method:** {method}\n")

        users = activity.get("top_users", [])
        if users and isinstance(users, list):
            lines.append("**Top Users:**")
            for u in users[:10]:
                if isinstance(u, dict):
                    email = u.get("user_email", "Unknown")
                    queries = u.get("query_count", 0)
                    runtime = u.get("total_runtime_seconds", 0)
                    pct = u.get("cost_attribution_pct")
                    pct_str = f" ({pct:.1f}%)" if pct is not None else ""
                    lines.append(
                        f"- **{email}**: {queries:,} queries, "
                        f"{runtime / 3600:.1f}h runtime{pct_str}"
                    )

        return "\n".join(lines)

    def _format_findings(self, findings: list[dict[str, Any]]) -> str:
        """Format performance findings (reuses advisor format)."""
        if not findings or not isinstance(findings, list):
            return ""

        lines = ["### Performance Recommendations\n"]

        for i, finding in enumerate(findings, 1):
            if not isinstance(finding, dict):
                continue

            title = finding.get("title", "")
            category = finding.get("category", "")
            recommendation = finding.get("recommendation", "")

            if title:
                lines.append(f"\n#### {i}. {title}")
                if category:
                    lines.append(f"**Category:** {category}")
                if recommendation:
                    lines.append(f"\n{recommendation}")

        return "\n".join(lines) if len(lines) > 1 else ""
