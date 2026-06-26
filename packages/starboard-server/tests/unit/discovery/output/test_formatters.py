# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for OutputFormatter.

Tests cover:
- to_json: roundtrip, keys
- to_markdown: sections, finding rendering, empty report, report cards
- write_to_directory: file creation, directory creation (async)
"""

from __future__ import annotations

import json

import pytest
from starboard_core.domain.models.discovery.analysis import (
    DataCoverage,
    DiscoveryFinding,
    DomainAnalysis,
    Evidence,
    LikelyCause,
    Remediation,
)
from starboard_core.domain.models.discovery.report import (
    DiscoveryReport,
    ExecutiveSummary,
    ReportCard,
    ReportMetadata,
)
from starboard_server.discovery.output.formatters import OutputFormatter


def make_finding(
    finding_id="F-001",
    priority="HIGH",
    evidence=None,
    likely_causes=None,
    remediation=None,
):
    """Create DiscoveryFinding for tests."""
    return DiscoveryFinding(
        finding_id=finding_id,
        title=f"Finding {finding_id}",
        priority=priority,
        impact="HIGH",
        effort="LOW",
        confidence="HIGH",
        finding_type="PERFORMANCE",
        domain="billing",
        description="Test finding description",
        evidence=evidence or [],
        likely_causes=likely_causes or [],
        remediation=remediation or Remediation(),
    )


def make_report(
    executive_summary=None,
    domain_analyses=None,
    top_priorities=None,
    metadata=None,
):
    """Create DiscoveryReport for tests."""
    return DiscoveryReport(
        executive_summary=executive_summary or ExecutiveSummary(),
        domain_analyses=domain_analyses or [],
        top_priorities=top_priorities or [],
        source_proofs=[],
        metadata=metadata or ReportMetadata(),
    )


class TestOutputFormatter:
    """Tests for OutputFormatter."""

    def test_to_json_roundtrip(self):
        """Create DiscoveryReport, call to_json(), parse back, verify keys."""
        report = make_report(
            executive_summary=ExecutiveSummary(overview="Test"),
            metadata=ReportMetadata(report_version="1.0.0"),
        )
        formatter = OutputFormatter()

        json_str = formatter.to_json(report)
        parsed = json.loads(json_str)

        assert "executive_summary" in parsed
        assert "domain_analyses" in parsed
        assert "top_priorities" in parsed
        assert "source_proofs" in parsed
        assert "metadata" in parsed
        assert parsed["executive_summary"]["overview"] == "Test"

    def test_to_markdown_contains_sections(self):
        """Report with executive summary, domain analyses, findings; verify key headings."""
        finding = make_finding("F-001")
        domain = DomainAnalysis(
            domain="billing",
            grade="B",
            score=75,
            summary="Billing summary",
            findings=[finding],
            data_coverage=DataCoverage(queries_executed=3, queries_succeeded=3),
        )
        report = make_report(
            executive_summary=ExecutiveSummary(
                overview="Overview text",
                report_cards=[
                    ReportCard(
                        domain="billing",
                        grade="B",
                        score=75,
                        discussion="Discussion",
                        top_findings=[finding],
                    ),
                ],
                top_findings=[finding],
            ),
            domain_analyses=[domain],
            top_priorities=[finding],
        )
        formatter = OutputFormatter()

        md = formatter.to_markdown(report)

        assert "# Databricks Workspace Health Assessment" in md
        assert "## Executive Summary" in md
        assert "## Report Cards" in md
        assert "## Top 10 Priorities" in md
        assert "## Domain Analyses" in md

    def test_to_markdown_finding_rendering(self):
        """Report with finding that has evidence, causes, remediation; verify all parts appear."""
        finding = make_finding(
            evidence=[
                Evidence(
                    source_query_id="Q-01",
                    excerpt="Excerpt text",
                    metric_name="dbus_consumed",
                    metric_value="100",
                ),
            ],
            likely_causes=[
                LikelyCause(
                    description="Possible cause",
                    is_hypothesis=True,
                    how_to_confirm="Run query X",
                ),
            ],
            remediation=Remediation(
                immediate=["Fix A"],
                medium_term=["Improve B"],
                long_term=["Refactor C"],
            ),
        )
        report = make_report(
            executive_summary=ExecutiveSummary(),
            top_priorities=[finding],
        )
        formatter = OutputFormatter()

        md = formatter.to_markdown(report)

        assert "**Evidence:**" in md
        assert "[Q-01]" in md
        assert "Excerpt text" in md
        assert "dbus_consumed" in md
        assert "**Likely Causes:**" in md
        assert "Possible cause" in md
        assert "(Hypothesis)" in md
        assert "How to confirm" in md
        assert "Run query X" in md
        assert "**Remediation:**" in md
        assert "*Immediate*" in md
        assert "Fix A" in md
        assert "*Medium-term*" in md
        assert "*Long-term*" in md

    @pytest.mark.asyncio
    async def test_write_to_directory(self, tmp_path):
        """Call write_to_directory; verify 4 files created."""
        report = make_report()
        formatter = OutputFormatter()

        files = await formatter.write_to_directory(report, tmp_path)

        assert len(files) == 4
        assert (tmp_path / "report.md").exists()
        assert (tmp_path / "report.json").exists()
        assert (tmp_path / "executive_summary.md").exists()
        assert (tmp_path / "top_priorities.md").exists()

    @pytest.mark.asyncio
    async def test_write_to_directory_creates_dir(self, tmp_path):
        """Use tmp_path / subdir / nested; verify directory is created and files written."""
        output_dir = tmp_path / "subdir" / "nested"
        report = make_report()
        formatter = OutputFormatter()

        files = await formatter.write_to_directory(report, output_dir)

        assert output_dir.exists()
        assert len(files) == 4
        assert (output_dir / "report.md").exists()
        assert (output_dir / "report.json").exists()

    def test_to_markdown_empty_report(self):
        """Minimal empty report; verify to_markdown still produces valid output with title."""
        report = DiscoveryReport()
        formatter = OutputFormatter()

        md = formatter.to_markdown(report)

        assert "# Databricks Workspace Health Assessment" in md
        assert "## Executive Summary" in md

    def test_report_cards_table(self):
        """Report with report cards; verify markdown table format appears."""
        report = make_report(
            executive_summary=ExecutiveSummary(
                report_cards=[
                    ReportCard(
                        domain="billing",
                        grade="B",
                        score=75,
                        discussion="Billing discussion",
                        top_findings=[],
                    ),
                    ReportCard(
                        domain="jobs",
                        grade="A",
                        score=90,
                        discussion="Jobs discussion",
                        top_findings=[],
                    ),
                ],
            ),
        )
        formatter = OutputFormatter()

        md = formatter.to_markdown(report)

        assert "## Report Cards" in md
        assert "| Domain | Grade | Score | Discussion |" in md
        assert "|--------|-------|-------|------------|" in md
        assert "| Resource Consumption & Attribution | B | 75 |" in md
        assert "| Job Workload & Reliability | A | 90 |" in md
