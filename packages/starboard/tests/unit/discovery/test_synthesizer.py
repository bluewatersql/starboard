# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ReportAssembler.

Tests cover:
- assemble: LLM success, LLM failure (template fallback), no-LLM mode
- _template_summary: grades, scores, risk counts
- _build_report_cards: correct domain → card mapping
- _sort_findings: CRITICAL > HIGH > MEDIUM > LOW ordering
- _build_metadata: lookback_days, total_findings, total_domains
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.domain.models.discovery.analysis import (
    DataCoverage,
    DiscoveryFinding,
    DomainAnalysis,
    Remediation,
)
from starboard_core.domain.models.discovery.report import AnalysisContext
from starboard.adapters.llm.base import BaseLLMClient
from starboard.discovery.synthesizer import (
    ReportAssembler,
)


def make_domain_analysis(domain="billing", grade="B", score=75, findings=None):
    """Create a minimal DomainAnalysis for tests."""
    return DomainAnalysis(
        domain=domain,
        grade=grade,
        score=score,
        summary=f"{domain} summary",
        observations=["obs1"],
        patterns=[],
        findings=findings or [],
        recommended_actions=["action1"],
        data_coverage=DataCoverage(queries_executed=3, queries_succeeded=3),
    )


def make_finding(finding_id="F-001", priority="HIGH", impact="HIGH", domain="billing"):
    """Create a minimal DiscoveryFinding for tests."""
    return DiscoveryFinding(
        finding_id=finding_id,
        title=f"Finding {finding_id}",
        priority=priority,
        impact=impact,
        effort="LOW",
        confidence="HIGH",
        finding_type="PERFORMANCE",
        domain=domain,
        description="Test",
        evidence=[],
        likely_causes=[],
        remediation=Remediation(),
    )


@pytest.fixture
def mock_llm_exec_summary():
    """Mock LLM returning valid ExecutiveSummaryLLMOutput dict."""
    mock = MagicMock(spec=BaseLLMClient)
    mock.json_response = AsyncMock(
        return_value={
            "overview": "LLM-generated overview across 2 domains.",
            "top_actions": ["Action 1", "Action 2"],
            "primary_risks": ["Risk 1"],
            "cross_domain_themes": ["Theme 1"],
        }
    )
    return mock


@pytest.fixture
def mock_llm_failure():
    """Mock LLM raising ValueError."""
    mock = MagicMock(spec=BaseLLMClient)
    mock.json_response = AsyncMock(side_effect=ValueError("LLM error"))
    return mock


class TestReportAssembler:
    """Tests for ReportAssembler."""

    @pytest.mark.asyncio
    async def test_assemble_with_llm_success(self, mock_llm_exec_summary):
        """LLM returns valid executive summary; verify report uses LLM output."""
        analyses = [
            make_domain_analysis("billing"),
            make_domain_analysis("jobs"),
        ]
        assembler = ReportAssembler(llm_client=mock_llm_exec_summary)

        report = await assembler.assemble(domain_analyses=analyses)

        assert report.metadata.total_domains == 2
        assert report.executive_summary.overview == (
            "LLM-generated overview across 2 domains."
        )
        mock_llm_exec_summary.json_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_assemble_llm_failure_uses_template(self, mock_llm_failure):
        """LLM fails; verify template fallback produces valid report."""
        finding = make_finding("F-001", priority="HIGH")
        analyses = [make_domain_analysis("billing", findings=[finding])]
        assembler = ReportAssembler(llm_client=mock_llm_failure)

        report = await assembler.assemble(domain_analyses=analyses)

        assert len(report.executive_summary.report_cards) == 1
        assert report.executive_summary.report_cards[0].domain == "billing"
        assert "Workspace health assessment" in report.executive_summary.overview
        assert len(report.top_priorities) >= 0

    @pytest.mark.asyncio
    async def test_assemble_no_llm_uses_template(self):
        """No LLM client provided; verify template fallback is used."""
        analyses = [make_domain_analysis("billing")]
        assembler = ReportAssembler(llm_client=None)

        report = await assembler.assemble(domain_analyses=analyses)

        assert "Workspace health assessment" in report.executive_summary.overview
        assert report.metadata.total_domains == 1

    @pytest.mark.asyncio
    async def test_findings_sorted_by_priority(self, mock_llm_failure):
        """Verify top_priorities sorted CRITICAL > HIGH > MEDIUM."""
        findings = [
            make_finding("F-M", priority="MEDIUM", impact="MEDIUM"),
            make_finding("F-C", priority="CRITICAL", impact="HIGH"),
            make_finding("F-H", priority="HIGH", impact="HIGH"),
        ]
        analyses = [
            make_domain_analysis("billing", findings=[findings[0]]),
            make_domain_analysis("jobs", findings=findings[1:3]),
        ]
        assembler = ReportAssembler(llm_client=mock_llm_failure)

        report = await assembler.assemble(domain_analyses=analyses)

        priorities = [f.priority for f in report.top_priorities]
        assert priorities == ["CRITICAL", "HIGH", "MEDIUM"]

    @pytest.mark.asyncio
    async def test_metadata_generation(self, mock_llm_exec_summary):
        """Verify metadata has correct lookback_days, total_findings, total_domains."""
        finding1 = make_finding("F-001")
        finding2 = make_finding("F-002")
        analyses = [
            make_domain_analysis("billing", findings=[finding1]),
            make_domain_analysis("jobs", findings=[finding2]),
        ]
        context = AnalysisContext(
            lookback_days=14,
            domains_analyzed=["billing", "jobs"],
        )
        assembler = ReportAssembler(llm_client=mock_llm_exec_summary)

        report = await assembler.assemble(
            domain_analyses=analyses,
            context=context,
        )

        assert report.metadata.lookback_days == 14
        assert report.metadata.total_findings == 2
        assert report.metadata.total_domains == 2

    @pytest.mark.asyncio
    async def test_report_cards_built_correctly(self):
        """Verify one report card per domain with correct grade/score."""
        analyses = [
            make_domain_analysis("billing", grade="A", score=95),
            make_domain_analysis("jobs", grade="C", score=60),
        ]
        assembler = ReportAssembler(llm_client=None)

        report = await assembler.assemble(domain_analyses=analyses)

        cards = report.executive_summary.report_cards
        assert len(cards) == 2
        assert cards[0].domain == "billing"
        assert cards[0].grade == "A"
        assert cards[0].score == 95
        assert cards[1].domain == "jobs"
        assert cards[1].grade == "C"
        assert cards[1].score == 60

    @pytest.mark.asyncio
    async def test_context_attached(self, mock_llm_exec_summary):
        """Verify analysis_context is attached to executive summary."""
        context = AnalysisContext(
            lookback_days=30,
            domains_analyzed=["billing"],
        )
        analyses = [make_domain_analysis("billing")]
        assembler = ReportAssembler(llm_client=mock_llm_exec_summary)

        report = await assembler.assemble(domain_analyses=analyses, context=context)

        assert report.executive_summary.analysis_context.lookback_days == 30


class TestTemplateSummary:
    """Tests for _template_summary fallback."""

    def test_overview_includes_avg_score(self):
        analyses = [
            make_domain_analysis("billing", score=80),
            make_domain_analysis("jobs", score=60),
        ]
        result = ReportAssembler._template_summary(analyses, [])
        assert "avg score 70/100" in result.overview

    def test_critical_and_high_counts(self):
        findings = [
            make_finding("F-C1", priority="CRITICAL"),
            make_finding("F-C2", priority="CRITICAL"),
            make_finding("F-H1", priority="HIGH"),
        ]
        analyses = [make_domain_analysis("billing")]
        result = ReportAssembler._template_summary(analyses, findings)
        assert "2 critical and 1 high-priority" in result.overview

    def test_grade_groups(self):
        analyses = [
            make_domain_analysis("billing", grade="A"),
            make_domain_analysis("jobs", grade="C"),
            make_domain_analysis("clusters", grade="A"),
        ]
        result = ReportAssembler._template_summary(analyses, [])
        assert "Grade A: billing, clusters" in result.overview
        assert "Grade C: jobs" in result.overview


class TestExecSummaryPrompt:
    """Tests for _build_exec_summary_prompt."""

    def test_prompt_contains_scorecards(self):
        analyses = [make_domain_analysis("billing", grade="B", score=75)]
        prompt = ReportAssembler._build_exec_summary_prompt(analyses, [])
        assert "billing: B (75/100)" in prompt

    def test_prompt_contains_top_findings(self):
        finding = make_finding("F-001", priority="HIGH", domain="billing")
        prompt = ReportAssembler._build_exec_summary_prompt([], [finding])
        assert "[HIGH] Finding F-001 (billing)" in prompt

    def test_prompt_stays_compact(self):
        analyses = [
            make_domain_analysis(f"domain_{i}", score=50 + i) for i in range(10)
        ]
        findings = [make_finding(f"F-{i:03d}", priority="HIGH") for i in range(20)]
        prompt = ReportAssembler._build_exec_summary_prompt(analyses, findings)
        assert len(prompt) < 5000
