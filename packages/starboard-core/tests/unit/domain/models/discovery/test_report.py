"""Tests for discovery report Pydantic models.

Tests cover:
- AnalysisContext, ReportCard, ExecutiveSummary defaults and construction
- SourceProof field population
- ReportMetadata version fields
- DiscoveryReport full composition
"""

from starboard_core.domain.models.discovery.analysis import (
    DiscoveryFinding,
)
from starboard_core.domain.models.discovery.report import (
    AnalysisContext,
    DiscoveryReport,
    ExecutiveSummary,
    ReportCard,
    ReportMetadata,
    SourceProof,
)


class TestAnalysisContext:
    def test_defaults(self):
        ctx = AnalysisContext()
        assert ctx.workspace_id is None
        assert ctx.lookback_days == 30
        assert ctx.domains_analyzed == []
        assert ctx.total_queries_executed == 0

    def test_populated(self):
        ctx = AnalysisContext(
            workspace_id="ws-123",
            lookback_days=90,
            domains_analyzed=["billing", "jobs"],
            domains_skipped=["ml"],
            total_queries_executed=15,
            total_execution_time_ms=4200.0,
        )
        assert ctx.workspace_id == "ws-123"
        assert len(ctx.domains_analyzed) == 2


class TestReportCard:
    def test_construction(self):
        card = ReportCard(
            domain="compute",
            grade="B",
            score=78.0,
            discussion="Clusters are generally well-configured.",
        )
        assert card.top_findings == []

    def test_with_findings(self):
        finding = DiscoveryFinding(
            finding_id="F-001",
            title="Test",
            priority="HIGH",
            impact="HIGH",
            effort="LOW",
            confidence="HIGH",
            finding_type="PERFORMANCE",
            domain="compute",
            description="Test finding",
        )
        card = ReportCard(
            domain="compute",
            grade="C",
            score=62.0,
            discussion="Needs improvement.",
            top_findings=[finding],
        )
        assert len(card.top_findings) == 1


class TestExecutiveSummary:
    def test_defaults(self):
        es = ExecutiveSummary()
        assert es.overview == ""
        assert es.report_cards == []
        assert es.notes == []


class TestSourceProof:
    def test_construction(self):
        sp = SourceProof(
            query_id="C-B01",
            query_name="Billing overview",
            domain="billing",
            row_count=42,
            supporting_findings=["F-001", "F-003"],
            summary="Shows DBU consumption by product.",
        )
        assert len(sp.supporting_findings) == 2


class TestReportMetadata:
    def test_defaults(self):
        m = ReportMetadata()
        assert m.report_version == "1.0.0"
        assert m.engine_version == "1.0.0"
        assert m.total_findings == 0


class TestDiscoveryReport:
    def test_empty_report(self):
        report = DiscoveryReport()
        assert report.domain_analyses == []
        assert report.top_priorities == []
        assert report.source_proofs == []

    def test_serialization_roundtrip(self):
        report = DiscoveryReport(
            executive_summary=ExecutiveSummary(
                overview="Workspace is generally healthy.",
                analysis_context=AnalysisContext(lookback_days=30),
            ),
            metadata=ReportMetadata(total_findings=5, total_domains=3),
        )
        data = report.model_dump()
        reconstructed = DiscoveryReport.model_validate(data)
        assert reconstructed.metadata.total_findings == 5
        assert (
            reconstructed.executive_summary.overview
            == "Workspace is generally healthy."
        )
