"""Discovery report types.

Top-level output models for the workspace discovery report.
All consumption metrics expressed in DBUs (never dollars).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from starboard_core.domain.models.discovery.analysis import (
    DiscoveryFinding,
    DomainAnalysis,
    Grade,
)


class AnalysisContext(BaseModel):
    """Context about when and how the analysis was performed.

    Args:
        workspace_id: Databricks workspace analyzed.
        lookback_days: Time window for the analysis.
        analysis_timestamp: ISO timestamp of when the analysis ran.
        domains_analyzed: Which domains were included.
        domains_skipped: Which domains were skipped and why.
        total_queries_executed: Number of queries run.
        total_execution_time_ms: Total SQL execution time.
    """

    workspace_id: str | None = None
    lookback_days: int = 30
    analysis_timestamp: str = ""
    domains_analyzed: list[str] = Field(default_factory=list)
    domains_skipped: list[str] = Field(default_factory=list)
    total_queries_executed: int = 0
    total_execution_time_ms: float = 0.0


class ReportCard(BaseModel):
    """Graded health assessment for a single domain.

    Args:
        domain: Domain name.
        grade: Letter grade (A-F).
        score: Numeric score (0-100).
        discussion: 2-4 sentence explanation of the grade.
        top_findings: 3-5 most important findings supporting the grade.
    """

    domain: str
    grade: Grade
    score: float = Field(ge=0, le=100)
    discussion: str = ""
    top_findings: list[DiscoveryFinding] = Field(default_factory=list)


class ExecutiveSummary(BaseModel):
    """High-level workspace health assessment.

    Args:
        overview: 3-5 sentence overview of workspace health.
        analysis_context: When/how the analysis was performed.
        report_cards: Per-domain graded assessments.
        top_findings: Top 5 most impactful findings across all domains.
        top_actions: Top 5 recommended actions.
        primary_risks: Key risks across performance, consumption, reliability,
            governance.
        notes: Disclaimers, caveats, references, data gaps.
    """

    overview: str = ""
    analysis_context: AnalysisContext = Field(default_factory=AnalysisContext)
    report_cards: list[ReportCard] = Field(default_factory=list)
    top_findings: list[DiscoveryFinding] = Field(default_factory=list)
    top_actions: list[str] = Field(default_factory=list)
    primary_risks: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SourceProof(BaseModel):
    """Maps a query result to the findings it supports.

    Args:
        query_id: ID of the source query.
        query_name: Human-readable query name.
        domain: Domain the query belongs to.
        description: What the query measures.
        row_count: Number of rows returned.
        supporting_findings: Finding IDs this data supports.
        summary: Brief summary of what the data shows.
    """

    query_id: str
    query_name: str = ""
    domain: str = ""
    description: str = ""
    row_count: int = 0
    supporting_findings: list[str] = Field(default_factory=list)
    summary: str = ""


class ReportMetadata(BaseModel):
    """Metadata about the discovery report itself.

    Args:
        report_version: Version of the report format.
        engine_version: Version of the discovery engine.
        generated_at: ISO timestamp of report generation.
        lookback_days: Time window used.
        total_findings: Number of findings across all domains.
        total_domains: Number of domains analyzed.
        llm_model: Which LLM model was used for analysis.
        llm_tokens_used: Total tokens consumed by LLM calls.
    """

    report_version: str = "1.0.0"
    engine_version: str = "1.0.0"
    generated_at: str = ""
    lookback_days: int = 30
    total_findings: int = 0
    total_domains: int = 0
    llm_model: str = ""
    llm_tokens_used: int = 0


class DiscoveryReport(BaseModel):
    """Complete workspace discovery and health assessment report.

    Args:
        executive_summary: High-level assessment with report cards.
        domain_analyses: Detailed per-domain analyses.
        top_priorities: Top 10 findings ranked by priority and impact.
        source_proofs: Evidence map linking queries to findings.
        metadata: Report generation metadata.
    """

    executive_summary: ExecutiveSummary = Field(default_factory=ExecutiveSummary)
    domain_analyses: list[DomainAnalysis] = Field(default_factory=list)
    top_priorities: list[DiscoveryFinding] = Field(default_factory=list)
    source_proofs: list[SourceProof] = Field(default_factory=list)
    metadata: ReportMetadata = Field(default_factory=ReportMetadata)
