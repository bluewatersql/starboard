# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Polymorphic report type schemas for multi-agent system.

This module defines the report type hierarchy that allows different agent
categories to return domain-specific structured outputs:

- AdvisorReport: Performance optimization agents (query, job, table, compute)
- AnalyticsReport: Cost/usage analysis agents (FinOps)
- Future: DiagnosticReport, SecurityReport, GovernanceReport, etc.

All reports share common base fields (summary, next_steps) but add
domain-specific fields as needed. This enables:
1. Type-safe backend validation
2. Adapter-based rendering (markdown, CLI, React)
3. Extensibility for new agent types

Design:
- Pydantic V2 models with discriminated union support
- Literal report_type field for runtime discrimination
- Frozen=True for immutability (best practice)
- Comprehensive validation and error messages
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from starboard_core.domain.models.llm_schemas import (
    Analysis,
    EffortEstimate,
    NextStepAction,
    Summary,
)

# =============================================================================
# Data Table (Generic tabular data for reports)
# =============================================================================


class DataTable(BaseModel):
    """Generic data table for report outputs.

    Use this when the user expects to see tabular data (lists, enumerations,
    reports, breakdowns). The frontend renders this as an interactive table.

    Signal words that indicate a data table is expected:
    - "show me", "list", "what are", "which", "give me"
    - "tables in", "schemas in", "who reads", "who writes"

    Attributes:
        title: Table title (e.g., "Tables in cprice_main.sales")
        description: Brief description of what the table shows
        columns: Column headers
        rows: Data rows - values in column order
        total_rows: Total row count for display
        summary: Optional aggregates/context (catalog, schema, filters)
    """

    title: str = Field(..., description="Table title for display")
    description: str | None = Field(
        default=None, description="Brief description of the data"
    )
    columns: list[str] = Field(..., description="Column headers")
    rows: list[list[str | int | float | None]] = Field(
        ..., description="Data rows in column order"
    )
    total_rows: int | None = Field(
        default=None, description="Total row count for display"
    )
    summary: dict[str, str | int | float] | None = Field(
        default=None, description="Summary/context values (catalog, schema, etc.)"
    )


# =============================================================================
# Base Report Class
# =============================================================================


class AgentReport(BaseModel):
    """
    Base class for all agent reports.

    Common fields present in every agent response regardless of specialization.
    Subclasses add domain-specific fields.

    Attributes:
        report_type: Report type discriminator (advisor, analytics, diagnostic, etc.)
        summary: High-level summary with overview and current state
        next_steps: Suggested next actions (1-5 steps)

    Design:
        - Extra fields allowed for subclass extensions
        - Frozen for immutability
        - report_type used for runtime type discrimination
    """

    report_type: str = Field(
        ...,
        description="Report type discriminator (advisor, analytics, diagnostic, etc.)",
    )
    summary: Summary = Field(..., description="High-level summary")
    next_steps: list[NextStepAction] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Suggested next actions for the conversation",
    )

    model_config = {
        "extra": "allow",  # Allow subclass extensions
        "frozen": True,  # Immutable
    }


# =============================================================================
# AdvisorReport (Optimization Agents)
# =============================================================================


class AdvisorReport(AgentReport):
    """
    Optimization advisor report for performance-focused agents.

    Used by: query, job, table, compute agents
    Focus: Performance optimization, configuration tuning, resource efficiency

    Attributes:
        report_type: Always "advisor"
        summary: Analysis summary with current state
        analysis: Optimization findings with impact/effort estimates
        next_steps: Suggested actions
        query_rewrite: Optional SQL rewrite (query agent only)

    Example:
        >>> report = AdvisorReport(
        ...     summary=Summary(
        ...         overview="Query is slow due to missing index",
        ...         current_state=CurrentState(cloud_provider="AWS")
        ...     ),
        ...     analysis=Analysis(findings=[...]),
        ...     next_steps=[NextStepAction(
        ...         id="add_index_1",
        ...         number=1,
        ...         title="Add index to table",
        ...         description="Create index on user_id column",
        ...         action_type="continue",
        ...         target_agent=None,
        ...         tool_name=None,
        ...         parameters=None
        ...     )]
        ... )
        >>> assert report.report_type == "advisor"
    """

    report_type: Literal["advisor"] = "advisor"
    analysis: Analysis = Field(
        ..., description="Optimization findings with impact/effort estimates"
    )

    # Generic data table - agent includes when user expects tabular data
    # (e.g., "list tables in catalog", "show me schemas", "who reads from X")
    data_table: DataTable | None = Field(
        default=None,
        description="Data table for listing/enumeration requests",
    )

    # Inherited from AgentReport:
    # - summary: Summary
    # - next_steps: list[NextStep]


# =============================================================================
# AnalyticsReport (FinOps Agent)
# =============================================================================


class CostImpact(BaseModel):
    """
    Cost impact estimate for a finding.

    Attributes:
        current_monthly_cost: Current monthly spend for this resource
        projected_savings_monthly: Expected monthly savings if recommendation applied
        cost_unit: Cost unit (dollar | dbu)
        savings_pct: Percentage reduction in cost
        confidence: Confidence level (low, medium, high)

    Example:
        >>> impact = CostImpact(
        ...     current_monthly_cost=2400.00,
        ...     projected_savings_monthly=2040.00,
        ...     cost_unit="dollar",
        ...     savings_pct=85.0,
        ...     confidence="high"
        ... )
    """

    current_monthly_cost: float = Field(
        ..., description="Current monthly spend for this resource", ge=0
    )
    projected_savings_monthly: float = Field(
        ..., description="Expected monthly savings if recommendation applied", ge=0
    )
    cost_unit: Literal["dollar", "dbu"] = Field(
        ..., description="Cost unit (dollar or dbu)"
    )
    savings_pct: float = Field(
        ..., description="Percentage reduction in cost", ge=0, le=100
    )
    confidence: Literal["low", "medium", "high"] = Field(
        ..., description="Confidence level in savings estimate"
    )

    model_config = {"frozen": True}


class TopContributor(BaseModel):
    """
    Top cost contributor detail.

    Attributes:
        id: Resource identifier (job_id, warehouse_id, cluster_id)
        name: Resource name
        value: Metric value (cost, DBUs, etc.)
        unit: Metric unit (USD, DBU, or other)
        notes: Additional context or notes

    Example:
        >>> contributor = TopContributor(
        ...     id="job_123",
        ...     name="ETL Pipeline",
        ...     value=844.65,
        ...     unit="USD",
        ...     notes="31 runs in period"
        ... )
    """

    id: str = Field(..., description="Resource identifier", min_length=1)
    name: str = Field(..., description="Resource name", min_length=1)
    value: float = Field(..., description="Metric value", ge=0)
    unit: str = Field(..., description="Metric unit (USD, DBU, or other)", min_length=1)
    notes: str = Field(default="", description="Additional context or notes")

    model_config = {"frozen": True}


class CostSummary(BaseModel):
    """
    Aggregated cost statistics for the analysis period.

    Attributes:
        primary_metric: Primary metric column name (e.g., "list_cost", "run_dbus")
        primary_metric_unit: Primary metric unit (USD or DBU)
        total: Total value of primary metric
        mean: Mean value of primary metric
        max: Maximum value of primary metric
        period: Analysis period description (e.g., "30 days", "last month")
        cost_trend: Cost trend direction (increasing, stable, decreasing)
        top_contributors: Top cost contributors with details

    Example:
        >>> summary = CostSummary(
        ...     primary_metric="list_cost",
        ...     primary_metric_unit="USD",
        ...     total=45000.00,
        ...     mean=1500.00,
        ...     max=5000.00,
        ...     period="30 days",
        ...     cost_trend="increasing",
        ...     top_contributors=[TopContributor(...)]
        ... )
    """

    primary_metric: str = Field(
        ..., description="Primary metric column name", min_length=1
    )
    primary_metric_unit: str = Field(
        ..., description="Primary metric unit (USD or DBU)", min_length=1
    )
    total: float = Field(..., description="Total value of primary metric", ge=0)
    mean: float = Field(..., description="Mean value of primary metric", ge=0)
    max: float = Field(..., description="Maximum value of primary metric", ge=0)
    period: str = Field(
        ...,
        description='Analysis period description (e.g., "30 days", "last month")',
        min_length=1,
    )
    cost_trend: Literal["increasing", "stable", "decreasing"] = Field(
        ..., description="Cost trend direction"
    )
    top_contributors: list[TopContributor] = Field(
        default_factory=list,
        description="Top cost contributors with detailed information",
    )

    model_config = {"frozen": True}


class VisualizationRecommendation(BaseModel):
    """
    Chart/visualization recommendation for query results.

    Provides frontend with metadata to render appropriate chart types
    for the data returned by analytics queries.

    Attributes:
        recommended_chart: Recommended chart type (line, bar, area, pie, scatter, table)
        primary_metric: Y-axis metric column name
        primary_dimension: X-axis dimension column name
        time_dimension: Time column for time-series charts (optional)
        secondary_metrics: Additional metrics to plot (optional)
        chart_config: Chart-specific configuration for rendering (optional)
        notes: Visualization guidance notes
        data_reference: Cache key for query results (for frontend chart rendering)
        has_visualization: Whether a chart is available (False for table-only)

    Example:
        >>> viz = VisualizationRecommendation(
        ...     recommended_chart="line",
        ...     primary_metric="total_cost",
        ...     primary_dimension="usage_date",
        ...     time_dimension="usage_date",
        ...     notes="Use line chart to show cost trends over time",
        ...     data_reference="data_ref_abc123",
        ...     has_visualization=True,
        ... )
    """

    recommended_chart: Literal["line", "bar", "area", "pie", "scatter", "table"] = (
        Field(..., description="Recommended chart type")
    )
    primary_metric: str = Field(
        ..., description="Y-axis metric column name", min_length=1
    )
    primary_dimension: str = Field(
        ..., description="X-axis dimension column name", min_length=1
    )
    time_dimension: str | None = Field(
        default=None, description="Time column for time-series charts (optional)"
    )
    secondary_metrics: list[str] = Field(
        default_factory=list, description="Additional metrics to plot"
    )
    chart_config: dict[str, Any] | None = Field(
        ...,
        description="Chart-specific configuration for rendering (null for table views)",
    )
    notes: str = Field(default="", description="Visualization guidance notes")
    data_reference: str | None = Field(
        ...,
        description="Cache key for query results (required for frontend data fetching)",
    )
    has_visualization: bool = Field(
        ...,
        description="Whether a chart is available (False for table-only, True for charts)",
    )

    model_config = {"frozen": True}


class AnalyticsFinding(BaseModel):
    """
    Cost/usage finding for analytics reports.

    Represents a cost optimization opportunity with estimated savings
    and implementation details.

    Attributes:
        id: Finding identifier (e.g., "finops_001")
        category: Finding category (cost optimization, waste detection, etc.)
        title: Finding title (concise description)
        recommendation: Cost-saving action to take
        cost_impact: Cost impact estimate
        effort: Implementation effort estimate
        rank: Priority rank by savings percentage (1 = highest)

    Example:
        >>> finding = AnalyticsFinding(
        ...     id="finops_001",
        ...     category="WASTE_DETECTION",
        ...     title="Idle warehouse consuming $2,400/month",
        ...     recommendation="Enable auto-stop after 10 minutes",
        ...     cost_impact=CostImpact(...),
        ...     effort=EffortEstimate(level="low", estimate_hours=0.5),
        ...     rank=1
        ... )
    """

    id: str = Field(..., description="Finding identifier", min_length=1)
    category: Literal[
        "COST_OPTIMIZATION",
        "WASTE_DETECTION",
        "UTILIZATION",
        "PERFORMANCE_COST",
        "ATTRIBUTION",
        "ANOMALY",
    ] = Field(..., description="Finding category")
    title: str = Field(..., description="Finding title (concise description)")
    recommendation: str = Field(..., description="Cost-saving action to take")
    cost_impact: CostImpact = Field(..., description="Cost impact estimate")
    effort: EffortEstimate = Field(..., description="Implementation effort estimate")
    rank: int = Field(
        ..., description="Priority rank by savings percentage (1 = highest)", ge=1
    )

    model_config = {"frozen": True}


class AnalyticsReport(AgentReport):
    """
    Analytics report for cost/usage-focused agents.

    Used by: analytics (FinOps) agent
    Focus: Cost analysis, usage trends, resource attribution, waste detection

    Attributes:
        report_type: Always "analytics"
        summary: Cost analysis summary
        findings: Cost/usage findings ranked by savings potential
        cost_summary: Aggregated cost statistics
        visualization: Chart recommendation (optional)
        next_steps: Suggested actions

    Example:
        >>> report = AnalyticsReport(
        ...     summary=Summary(overview="Total spend: $45k/month"),
        ...     findings=[AnalyticsFinding(...)],
        ...     cost_summary=CostSummary(...),
        ...     visualization=VisualizationRecommendation(...),
        ...     next_steps=[NextStepAction(
        ...         id="implement_savings_1",
        ...         number=1,
        ...         title="Implement top cost savings",
        ...         description="Apply configuration changes to reduce spending",
        ...         action_type="continue",
        ...         target_agent=None,
        ...         tool_name=None,
        ...         parameters=None
        ...     )]
        ... )
        >>> assert report.report_type == "analytics"
    """

    report_type: Literal["analytics"] = "analytics"
    findings: list[AnalyticsFinding] = Field(
        ..., description="Cost/usage findings ranked by savings potential"
    )
    cost_summary: CostSummary = Field(..., description="Aggregated cost statistics")
    visualization: VisualizationRecommendation | None = Field(
        default=None, description="Chart recommendation for results"
    )

    # Inherited from AgentReport:
    # - summary: Summary
    # - next_steps: list[NextStep]


# =============================================================================
# Future Report Types (Placeholders)
# =============================================================================

# When adding new agent types, follow this pattern:
#
# class DiagnosticReport(AgentReport):
#     """Diagnostic report for troubleshooting agents."""
#     report_type: Literal["diagnostic"] = "diagnostic"
#     error_traces: list[ErrorTrace] = Field(...)
#     root_causes: list[RootCause] = Field(...)
#     ...
#
# class SecurityReport(AgentReport):
#     """Security report for compliance/vulnerability agents."""
#     report_type: Literal["security"] = "security"
#     vulnerabilities: list[Vulnerability] = Field(...)
#     compliance_checks: list[ComplianceCheck] = Field(...)
#     ...
