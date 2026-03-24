"""Unit tests for DiagnosticReportFormatter.

Tests markdown formatting of diagnostic reports with:
- Summary with mode, confidence, artifact type
- Key findings with evidence references
- Metrics summary (context-specific)
- Recommendations
- Optimized query/code
- Evidence windows
"""

from starboard_server.agents.report_formatters.diagnostic_formatter import (
    DiagnosticReportFormatter,
)


class TestDiagnosticReportFormatter:
    """Test DiagnosticReportFormatter."""

    def test_get_report_type(self):
        """Test report type identification."""
        formatter = DiagnosticReportFormatter()
        assert formatter.get_report_type() == "diagnostic"

    def test_format_minimal_report(self):
        """Test formatting minimal diagnostic report."""
        formatter = DiagnosticReportFormatter()
        report = {
            "report_type": "diagnostic",
            "summary": {
                "overview": "Exit code 137 indicates OOM killer terminated the process.",
            },
        }

        markdown = formatter.format_to_markdown(report)

        assert "## Summary" in markdown
        assert "Exit code 137" in markdown
        assert "OOM killer" in markdown

    def test_format_with_mode_confidence_artifact(self):
        """Test formatting with mode, confidence, and artifact type."""
        formatter = DiagnosticReportFormatter()
        report = {
            "report_type": "diagnostic",
            "summary": {
                "overview": "Query performance analysis.",
                "mode": "online",
                "confidence": 0.95,
                "artifact_type": "query_profile",
            },
        }

        markdown = formatter.format_to_markdown(report)

        assert "**Mode:** ONLINE" in markdown
        assert "**Confidence:** 95%" in markdown
        assert "**Artifact:** query_profile" in markdown
        assert "Query performance" in markdown

    def test_format_with_findings(self):
        """Test formatting with diagnostic findings."""
        formatter = DiagnosticReportFormatter()
        report = {
            "report_type": "diagnostic",
            "summary": {"overview": "Multiple issues detected."},
            "findings": [
                {
                    "title": "Memory pressure detected",
                    "category": "memory",
                    "confidence": "high",
                    "explanation": "Container killed due to OOM.",
                    "recommendations": [
                        "Increase executor memory",
                        "Enable dynamic allocation",
                    ],
                    "evidence_refs": ["stderr_line_42", "gc_log_tail"],
                },
                {
                    "title": "Inefficient shuffle",
                    "category": "performance",
                    "confidence": 0.75,
                    "explanation": "Large shuffle spill detected.",
                    "recommendations": ["Increase shuffle partitions"],
                    "evidence_refs": ["spark_ui_stage_5"],
                },
            ],
        }

        markdown = formatter.format_to_markdown(report)

        # Check findings table
        assert "## Key Findings" in markdown
        assert "| # | Category | Confidence | Issue |" in markdown
        assert "Memory pressure detected" in markdown
        assert "Inefficient shuffle" in markdown

        # Check detailed findings
        assert "### Detailed Findings" in markdown
        assert "#### 1. Memory pressure detected" in markdown
        assert "**Category:** memory" in markdown
        assert "**Confidence:** High" in markdown
        assert "Container killed due to OOM" in markdown
        assert "**Evidence:** `stderr_line_42`, `gc_log_tail`" in markdown

        # Check recommendations section
        assert "## Recommendations" in markdown
        assert "- Increase executor memory" in markdown
        assert "- Enable dynamic allocation" in markdown
        assert "- Increase shuffle partitions" in markdown

    def test_format_with_metrics_summary(self):
        """Test formatting with metrics summary for query profile."""
        formatter = DiagnosticReportFormatter()
        report = {
            "report_type": "diagnostic",
            "summary": {
                "overview": "Query analysis complete.",
                "artifact_type": "query_profile",
            },
            "metrics_summary": {
                "execution": {
                    "total_time_ms": 45000,
                    "compilation_time_ms": 2000,
                    "execution_time_ms": 43000,
                    "rows_produced": 1000000,
                },
                "io": {
                    "bytes_read": 1073741824,  # 1 GB
                    "bytes_pruned": 536870912,  # 512 MB
                    "rows_scanned": 5000000,
                    "cache_hit_pct": 85,
                },
                "processing": {
                    "photon_enabled": True,
                    "photon_coverage_pct": 95,
                    "peak_memory": 4294967296,  # 4 GB
                    "spill_to_disk": 0,
                },
            },
        }

        markdown = formatter.format_to_markdown(report)

        # Check metrics sections
        assert "## Metrics Summary" in markdown

        # Execution metrics
        assert "### Execution Summary" in markdown
        assert "45.0 s" in markdown  # Total time
        assert "2.0 s" in markdown  # Compilation time
        assert "43.0 s" in markdown  # Execution time
        assert "1,000,000" in markdown  # Rows produced

        # I/O metrics
        assert "### I/O Statistics" in markdown
        assert "1.00 GB" in markdown  # Bytes read
        assert "512.00 MB" in markdown  # Bytes pruned
        assert "5,000,000" in markdown  # Rows scanned
        assert "85%" in markdown  # Cache hit
        assert "✅" in markdown  # Good cache hit ratio

        # Processing metrics
        assert "### Processing Efficiency" in markdown
        assert "✅ Yes" in markdown  # Photon enabled
        assert "95%" in markdown  # Photon coverage
        assert "4.00 GB" in markdown  # Peak memory
        assert "0 bytes" in markdown  # No spill

    def test_format_with_optimized_code(self):
        """Test formatting with optimized query/code."""
        formatter = DiagnosticReportFormatter()
        report = {
            "report_type": "diagnostic",
            "summary": {"overview": "Query optimization available."},
            "optimized_code": "SELECT id, name\nFROM users\nWHERE status = 'active'",
        }

        markdown = formatter.format_to_markdown(report)

        assert "## Optimized Query/Code" in markdown
        assert "```sql" in markdown
        assert "SELECT id, name" in markdown
        assert "WHERE status = 'active'" in markdown

    def test_format_with_evidence_windows(self):
        """Test formatting with evidence windows (fallback)."""
        formatter = DiagnosticReportFormatter()
        report = {
            "report_type": "diagnostic",
            "summary": {
                "overview": "Error analysis.",
                "artifact_type": "error_message",  # Not a metrics context
            },
            "evidence_windows": [
                {
                    "id": "earliest_fatal",
                    "type": "stack_trace",
                    "content": "java.lang.OutOfMemoryError: Java heap space\n"
                    "    at org.apache.spark.Task.run()",
                    "line_start": 42,
                    "line_end": 45,
                },
                {
                    "id": "crash_tail",
                    "type": "log_excerpt",
                    "content": "Container killed by YARN for exceeding memory limits",
                    "line_start": 120,
                },
            ],
        }

        markdown = formatter.format_to_markdown(report)

        # Evidence windows should be shown (not metrics)
        assert "## Evidence Windows" in markdown
        assert "### Stack Trace" in markdown
        assert "**earliest_fatal:**" in markdown
        assert "OutOfMemoryError" in markdown
        assert "*Lines 42-45*" in markdown

        assert "### Log Excerpt" in markdown
        assert "**crash_tail:**" in markdown
        assert "Container killed" in markdown
        assert "*Line 120*" in markdown

    def test_format_no_metrics_for_non_query_artifact(self):
        """Test that metrics are NOT shown for error messages/code."""
        formatter = DiagnosticReportFormatter()
        report = {
            "report_type": "diagnostic",
            "summary": {
                "overview": "Error analysis.",
                "artifact_type": "error_message",  # Not a metrics context
            },
            "metrics_summary": {
                # This should be ignored for error_message artifact type
                "execution": {"total_time_ms": 1000},
            },
        }

        markdown = formatter.format_to_markdown(report)

        # Metrics should NOT be included
        assert "## Metrics Summary" not in markdown
        assert "### Execution Summary" not in markdown

    def test_format_complete_report(self):
        """Test formatting complete diagnostic report with all sections."""
        formatter = DiagnosticReportFormatter()
        report = {
            "report_type": "diagnostic",
            "summary": {
                "overview": "Query performance issue diagnosed.",
                "mode": "online",
                "confidence": 0.9,
                "artifact_type": "query_profile",
            },
            "findings": [
                {
                    "title": "Full table scan detected",
                    "category": "performance",
                    "confidence": "high",
                    "explanation": "Query scans entire table without partition filters.",
                    "recommendations": [
                        "Add WHERE clause on partition column",
                        "Use OPTIMIZE ZORDER BY",
                    ],
                    "evidence_refs": ["query_plan_line_5"],
                },
            ],
            "metrics_summary": {
                "execution": {
                    "total_time_ms": 120000,
                    "rows_produced": 10000,
                },
                "io": {
                    "bytes_read": 10737418240,  # 10 GB
                    "cache_hit_pct": 25,
                },
            },
            "optimized_code": "SELECT * FROM users WHERE date >= '2024-01-01'",
        }

        markdown = formatter.format_to_markdown(report)

        # All sections should be present
        assert "## Summary" in markdown
        assert "**Mode:** ONLINE" in markdown
        assert "**Confidence:** 90%" in markdown

        assert "## Key Findings" in markdown
        assert "Full table scan detected" in markdown

        assert "## Metrics Summary" in markdown
        assert "2.0 min" in markdown  # 120s
        assert "10.00 GB" in markdown
        assert "25%" in markdown  # Low cache hit

        assert "## Recommendations" in markdown
        assert "Add WHERE clause" in markdown

        assert "## Optimized Query/Code" in markdown
        assert "WHERE date >= '2024-01-01'" in markdown

    def test_format_invalid_report_type(self):
        """Test handling of invalid report input."""
        formatter = DiagnosticReportFormatter()

        # Non-dict input
        markdown = formatter.format_to_markdown("not a dict")
        assert markdown == "Diagnostic analysis complete."

        # Empty dict
        markdown = formatter.format_to_markdown({})
        assert markdown == "Diagnostic analysis complete."

    def test_confidence_emoji_mapping(self):
        """Test confidence to emoji mapping."""
        formatter = DiagnosticReportFormatter()

        # High confidence (numeric)
        assert formatter._get_confidence_emoji(0.95) == "🔴"
        # Medium confidence (numeric)
        assert formatter._get_confidence_emoji(0.75) == "🟠"
        # Low confidence (numeric)
        assert formatter._get_confidence_emoji(0.5) == "🟡"

        # String values
        assert formatter._get_confidence_emoji("high") == "🔴"
        assert formatter._get_confidence_emoji("medium") == "🟠"
        assert formatter._get_confidence_emoji("low") == "🟡"
        assert formatter._get_confidence_emoji("unknown") == "⚪"

    def test_format_bytes(self):
        """Test byte formatting."""
        formatter = DiagnosticReportFormatter()

        assert formatter._format_bytes(0) == "0 B"
        assert formatter._format_bytes(500) == "500.00 B"
        assert formatter._format_bytes(1024) == "1.00 KB"
        assert formatter._format_bytes(1048576) == "1.00 MB"
        assert formatter._format_bytes(1073741824) == "1.00 GB"
        assert formatter._format_bytes(1099511627776) == "1.00 TB"

    def test_format_duration(self):
        """Test duration formatting."""
        formatter = DiagnosticReportFormatter()

        assert formatter._format_duration(500) == "500 ms"
        assert formatter._format_duration(1500) == "1.5 s"
        assert formatter._format_duration(90000) == "1.5 min"
        assert formatter._format_duration(7200000) == "2.0 hr"

    def test_escape_table_cell(self):
        """Test table cell escaping."""
        formatter = DiagnosticReportFormatter()

        assert formatter._escape_table_cell(None) == "-"
        assert formatter._escape_table_cell("simple") == "simple"
        assert formatter._escape_table_cell("with | pipe") == "with \\| pipe"
        assert formatter._escape_table_cell("with\nnewline") == "with newline"
        assert formatter._escape_table_cell(42) == "42"
