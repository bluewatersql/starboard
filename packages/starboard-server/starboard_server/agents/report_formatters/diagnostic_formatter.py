"""Diagnostic report formatter for troubleshooting agent.

Formats DiagnosticReport (used by diagnostic agent) into readable markdown with:
- Summary with mode, confidence, and artifact type
- Key findings with evidence references
- Metrics summary (when applicable for query profiles, Spark logs)
- Recommendations from findings
- Optimized query/code (when available)
- Evidence windows and Databricks context

BB-09: Enhanced format with flexible sections based on context.
"""

from typing import Any

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class DiagnosticReportFormatter:
    """
    Formats DiagnosticReport to markdown.

    Used by diagnostic agent for troubleshooting Databricks failures,
    performance issues, and code analysis with evidence-based findings.
    """

    def get_report_type(self) -> str:
        """Return supported report type."""
        return "diagnostic"

    def format_to_markdown(self, report: dict[str, Any]) -> str:
        """
        Format DiagnosticReport to markdown.

        Sections (flexible based on context):
        - Summary (overview, mode, confidence, artifact type)
        - Key Findings (with evidence references)
        - Metrics Summary (only for query profiles, Spark logs, etc.)
        - Recommendations (actionable fixes)
        - Optimized Query/Code (when applicable)
        - Evidence Windows (fallback if no structured metrics)

        NOTE: Next Steps are rendered separately by the frontend for better visibility.

        Args:
            report: DiagnosticReport dict

        Returns:
            Formatted markdown string

        Example:
            >>> report = {
            ...     "report_type": "diagnostic",
            ...     "summary": {"overview": "Exit code 137 indicates OOM..."},
            ...     "findings": [...],
            ...     "metrics_summary": {...},
            ...     "optimized_code": "SELECT ...",
            ...     "next_steps": [...]
            ... }
            >>> formatter = DiagnosticReportFormatter()
            >>> markdown = formatter.format_to_markdown(report)
        """
        if not isinstance(report, dict):
            logger.warning(
                "diagnostic_formatter_invalid_type",
                report_type=type(report).__name__,
            )
            return "Diagnostic analysis complete."

        parts = []

        # Summary section
        summary = report.get("summary", {})
        summary_md = self._format_summary(summary)
        if summary_md:
            parts.append(summary_md)

        # Key Findings section
        findings = report.get("findings", [])
        if findings:
            findings_md = self._format_findings(findings)
            if findings_md:
                parts.append(findings_md)

        # Metrics Summary section (context-specific)
        metrics_summary = report.get("metrics_summary")
        artifact_type = (
            summary.get("artifact_type", "") if isinstance(summary, dict) else ""
        )

        # Only include metrics for applicable artifact types (BB-09)
        has_metrics_context = artifact_type in [
            "query_profile",
            "spark_log",
            "task_log",
            "execution_log",
        ]

        if has_metrics_context and metrics_summary:
            metrics_md = self._format_metrics_summary(metrics_summary)
            if metrics_md:
                parts.append(metrics_md)

        # Recommendations section (aggregated from findings)
        if findings:
            recommendations_md = self._format_recommendations(findings)
            if recommendations_md:
                parts.append(recommendations_md)

        # Optimized Query/Code section (when available)
        optimized_code = report.get("optimized_code")
        if optimized_code:
            code_md = self._format_optimized_code(optimized_code)
            if code_md:
                parts.append(code_md)

        # Evidence Windows section (fallback if no structured metrics)
        if not has_metrics_context or not metrics_summary:
            evidence_windows = report.get("evidence_windows", [])
            if evidence_windows:
                evidence_md = self._format_evidence_windows(evidence_windows)
                if evidence_md:
                    parts.append(evidence_md)

        # NOTE: Next Steps are NOT embedded in markdown.
        # They are rendered separately by frontend NextStepsBubble for better visibility.

        if parts:
            result = "\n".join(parts)
            logger.debug(
                "diagnostic_report_formatted",
                length=len(result),
                sections=len(parts),
            )
            return result

        # Fallback
        logger.warning(
            "diagnostic_report_no_content",
            report_keys=list(report.keys()) if isinstance(report, dict) else [],
        )
        return "Diagnostic analysis complete."

    def _format_summary(self, summary: dict[str, Any]) -> str:
        """Format summary section with mode, confidence, and artifact type."""
        if not isinstance(summary, dict):
            return ""

        lines = []
        overview = summary.get("overview", "")

        if overview:
            lines.append("## Summary\n")

            # Add badges for mode, confidence, artifact type
            badges = []
            mode = summary.get("mode", "")
            if mode:
                badges.append(f"**Mode:** {mode.upper()}")

            confidence = summary.get("confidence")
            if confidence is not None:
                if isinstance(confidence, (int, float)):
                    conf_pct = int(confidence * 100)
                    badges.append(f"**Confidence:** {conf_pct}%")
                else:
                    badges.append(f"**Confidence:** {confidence}")

            artifact_type = summary.get("artifact_type", "")
            if artifact_type:
                badges.append(f"**Artifact:** {artifact_type}")

            if badges:
                lines.append(" | ".join(badges))
                lines.append("")

            lines.append(f"{overview}\n")

        return "\n".join(lines) if lines else ""

    def _format_findings(self, findings: list[dict[str, Any]]) -> str:
        """Format findings section with evidence references."""
        if not findings or not isinstance(findings, list):
            return ""

        lines = ["## Key Findings\n"]

        # Summary table with severity emojis
        lines.append("| # | Category | Confidence | Issue |")
        lines.append("|---|----------|------------|-------|")

        for i, finding in enumerate(findings, 1):
            if not isinstance(finding, dict):
                continue

            category = finding.get("category", "Unknown")
            title = finding.get("title", "Untitled")
            confidence = finding.get("confidence", "medium")

            # Map confidence to emoji
            emoji = self._get_confidence_emoji(confidence)
            conf_str = self._format_confidence_value(confidence)

            # Escape table cell content
            category_esc = self._escape_table_cell(category)
            title_esc = self._escape_table_cell(title)

            lines.append(f"| {i} | {emoji} {category_esc} | {conf_str} | {title_esc} |")

        lines.append("")

        # Detailed findings
        lines.append("### Detailed Findings\n")

        for i, finding in enumerate(findings, 1):
            if not isinstance(finding, dict):
                continue

            finding_md = self._format_finding(i, finding)
            if finding_md:
                lines.append(finding_md)

        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_finding(self, index: int, finding: dict[str, Any]) -> str:
        """Format a single diagnostic finding."""
        lines = []

        title = finding.get("title", "")
        category = finding.get("category", "")
        confidence = finding.get("confidence", "")
        explanation = finding.get("explanation", "")
        evidence_refs = finding.get("evidence_refs", [])

        if title:
            lines.append(f"#### {index}. {title}\n")

            if category:
                lines.append(f"**Category:** {category}")

            if confidence:
                conf_str = self._format_confidence_value(confidence)
                lines.append(f"**Confidence:** {conf_str}")

            lines.append("")

            if explanation:
                lines.append(explanation)
                lines.append("")

            if evidence_refs and isinstance(evidence_refs, list):
                evidence_str = ", ".join([f"`{ref}`" for ref in evidence_refs])
                lines.append(f"**Evidence:** {evidence_str}")
                lines.append("")

            lines.append("---\n")

        return "\n".join(lines) if lines else ""

    def _format_metrics_summary(self, metrics: dict[str, Any]) -> str:
        """Format metrics summary for query profiles, Spark logs, etc."""
        if not isinstance(metrics, dict):
            return ""

        lines = ["## Metrics Summary\n"]

        # Execution Summary
        execution = metrics.get("execution", {})
        if execution and isinstance(execution, dict):
            exec_md = self._format_execution_metrics(execution)
            if exec_md:
                lines.append(exec_md)

        # I/O Statistics
        io = metrics.get("io", {})
        if io and isinstance(io, dict):
            io_md = self._format_io_metrics(io)
            if io_md:
                lines.append(io_md)

        # Processing Efficiency
        processing = metrics.get("processing", {})
        if processing and isinstance(processing, dict):
            proc_md = self._format_processing_metrics(processing)
            if proc_md:
                lines.append(proc_md)

        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_execution_metrics(self, execution: dict[str, Any]) -> str:
        """Format execution timing metrics."""
        lines = ["### Execution Summary\n"]
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")

        total_time = execution.get("total_time_ms")
        if total_time is not None:
            lines.append(f"| **Total Time** | {self._format_duration(total_time)} |")

        comp_time = execution.get("compilation_time_ms")
        if comp_time is not None:
            lines.append(
                f"| **Compilation Time** | {self._format_duration(comp_time)} |"
            )

        exec_time = execution.get("execution_time_ms")
        if exec_time is not None:
            lines.append(f"| **Execution Time** | {self._format_duration(exec_time)} |")

        rows = execution.get("rows_produced")
        if rows is not None:
            lines.append(f"| **Rows Produced** | {rows:,} |")

        lines.append("")
        return "\n".join(lines) if len(lines) > 3 else ""

    def _format_io_metrics(self, io: dict[str, Any]) -> str:
        """Format I/O statistics."""
        lines = ["### I/O Statistics\n"]
        lines.append("| Metric | Value | Notes |")
        lines.append("|--------|-------|-------|")

        bytes_read = io.get("bytes_read")
        if bytes_read is not None:
            lines.append(
                f"| **Bytes Read** | {self._format_bytes(bytes_read)} | From cloud storage |"
            )

        bytes_pruned = io.get("bytes_pruned")
        if bytes_pruned is not None:
            lines.append(
                f"| **Bytes Pruned** | {self._format_bytes(bytes_pruned)} | ✅ Partition pruning |"
            )

        rows_scanned = io.get("rows_scanned")
        if rows_scanned is not None:
            lines.append(f"| **Rows Scanned** | {rows_scanned:,} | Before filtering |")

        cache_hit_pct = io.get("cache_hit_pct")
        if cache_hit_pct is not None:
            if cache_hit_pct >= 80:
                cache_emoji = "✅"
            elif cache_hit_pct >= 50:
                cache_emoji = "⚠️"
            else:
                cache_emoji = "❌"
            lines.append(f"| **Cache Hit Ratio** | {cache_hit_pct}% | {cache_emoji} |")

        lines.append("")
        return "\n".join(lines) if len(lines) > 3 else ""

    def _format_processing_metrics(self, processing: dict[str, Any]) -> str:
        """Format processing efficiency metrics."""
        lines = ["### Processing Efficiency\n"]
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")

        photon_enabled = processing.get("photon_enabled")
        if photon_enabled is not None:
            emoji = "✅" if photon_enabled else "❌"
            lines.append(
                f"| **Photon Enabled** | {emoji} {'Yes' if photon_enabled else 'No'} |"
            )

        photon_coverage = processing.get("photon_coverage_pct")
        if photon_coverage is not None:
            lines.append(f"| **Photon Coverage** | {photon_coverage}% |")

        peak_memory = processing.get("peak_memory")
        if peak_memory is not None:
            lines.append(
                f"| **Peak Memory Usage** | {self._format_bytes(peak_memory)} |"
            )

        spill = processing.get("spill_to_disk")
        if spill is not None:
            spill_str = f"⚠️ {self._format_bytes(spill)}" if spill > 0 else "0 bytes"
            lines.append(f"| **Spill to Disk** | {spill_str} |")

        lines.append("")
        return "\n".join(lines) if len(lines) > 3 else ""

    def _format_recommendations(self, findings: list[dict[str, Any]]) -> str:
        """Format recommendations aggregated from findings."""
        lines = []
        all_recommendations = []

        for finding in findings:
            if not isinstance(finding, dict):
                continue

            recommendations = finding.get("recommendations", [])
            if recommendations and isinstance(recommendations, list):
                all_recommendations.extend(recommendations)

        if all_recommendations:
            lines.append("## Recommendations\n")
            for rec in all_recommendations:
                lines.append(f"- {rec}")
            lines.append("")

        return "\n".join(lines) if lines else ""

    def _format_optimized_code(self, code: str) -> str:
        """Format optimized query/code section."""
        if not code or not isinstance(code, str):
            return ""

        lines = ["## Optimized Query/Code\n"]
        lines.append("```sql")
        lines.append(code.strip())
        lines.append("```")
        lines.append("")

        return "\n".join(lines)

    def _format_evidence_windows(self, evidence_windows: list[dict[str, Any]]) -> str:
        """Format evidence windows section (fallback when no structured metrics)."""
        if not evidence_windows or not isinstance(evidence_windows, list):
            return ""

        lines = ["## Evidence Windows\n"]

        # Group by type
        evidence_by_type: dict[str, list[dict[str, Any]]] = {}
        for ev in evidence_windows:
            if not isinstance(ev, dict):
                continue
            ev_type = ev.get("type", "other")
            if ev_type not in evidence_by_type:
                evidence_by_type[ev_type] = []
            evidence_by_type[ev_type].append(ev)

        for ev_type, evidence_list in evidence_by_type.items():
            # Convert type to title case
            type_title = ev_type.replace("_", " ").title()
            lines.append(f"### {type_title}\n")

            for ev in evidence_list:
                ev_id = ev.get("id", "unknown")
                content = ev.get("content", "")
                line_start = ev.get("line_start")
                line_end = ev.get("line_end")

                lines.append(f"**{ev_id}:**")
                lines.append("```")
                # Truncate long content
                if len(content) > 500:
                    lines.append(content[:500] + "\n...")
                else:
                    lines.append(content)
                lines.append("```")

                if line_start:
                    if line_end:
                        lines.append(f"*Lines {line_start}-{line_end}*")
                    else:
                        lines.append(f"*Line {line_start}*")
                lines.append("")

        return "\n".join(lines) if len(lines) > 1 else ""

    # Helper methods

    def _get_confidence_emoji(self, confidence: str | float) -> str:
        """Get emoji for confidence level."""
        if isinstance(confidence, (int, float)):
            match confidence:
                case _ if confidence >= 0.9:
                    return "🔴"
                case _ if confidence >= 0.7:
                    return "🟠"
                case _:
                    return "🟡"

        match str(confidence).lower():
            case "high":
                return "🔴"
            case "medium":
                return "🟠"
            case "low":
                return "🟡"
            case _:
                return "⚪"

    def _format_confidence_value(self, confidence: str | float) -> str:
        """Format confidence value for display."""
        if isinstance(confidence, (int, float)):
            pct = int(confidence * 100)
            return f"{pct}%"
        return str(confidence).capitalize()

    def _escape_table_cell(self, value: Any) -> str:
        """Escape pipe characters for markdown tables."""
        if value is None:
            return "-"
        return str(value).replace("|", "\\|").replace("\n", " ")

    def _format_duration(self, ms: float | int) -> str:
        """Format milliseconds to human-readable duration."""
        if ms < 1000:
            return f"{ms} ms"
        elif ms < 60000:
            return f"{ms / 1000:.1f} s"
        elif ms < 3600000:
            return f"{ms / 60000:.1f} min"
        else:
            return f"{ms / 3600000:.1f} hr"

    def _format_bytes(self, bytes_val: int | float) -> str:
        """Format bytes to human-readable size."""
        if bytes_val == 0:
            return "0 B"

        units = ["B", "KB", "MB", "GB", "TB"]
        k = 1024
        i = 0
        val = float(bytes_val)

        while val >= k and i < len(units) - 1:
            val /= k
            i += 1

        return f"{val:.2f} {units[i]}"
