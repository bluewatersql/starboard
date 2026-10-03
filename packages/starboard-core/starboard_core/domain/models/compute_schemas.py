# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pydantic models for warehouse report type (Warehouse agent).

This module defines schemas for the 'warehouse' report type, which provides
specialized UI rendering for:
- Warehouse portfolio analysis
- Health metrics and SLO compliance
- Topology analysis and consolidation opportunities
- User activity and cost attribution

Note: The 'compute' report type is deprecated in favor of 'warehouse'.
The primary model is WarehouseReport with report_type="warehouse".
"""

from typing import Literal

from pydantic import BaseModel, Field

from starboard_core.domain.models.llm_schemas import (
    Analysis,
    NextStepAction,
    Summary,
)

# =============================================================================
# Resource Metrics
# =============================================================================


class ResourceMetrics(BaseModel):
    """Key metrics for a compute resource.

    Used to summarize performance characteristics of warehouses or clusters.

    Attributes:
        p50_latency_ms: Median query latency in milliseconds
        p95_latency_ms: 95th percentile query latency
        avg_queue_time_ms: Average time queries spend in queue
        query_count: Total number of queries executed
        dbu_usage: DBU consumption

    Example:
        >>> metrics = ResourceMetrics(
        ...     p50_latency_ms=100.0,
        ...     p95_latency_ms=500.0,
        ...     query_count=1000
        ... )
    """

    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    avg_queue_time_ms: float | None = None
    query_count: int | None = None
    dbu_usage: float | None = None


class ResourceSummary(BaseModel):
    """Summary of a single compute resource.

    Represents a warehouse or cluster with health status and key metrics.

    Attributes:
        id: Unique resource identifier
        name: Display name
        resource_type: Type of resource (warehouse or cluster)
        health_score: Overall health score (0-100)
        health_status: Categorical health status
        metrics: Key performance metrics

    Example:
        >>> resource = ResourceSummary(
        ...     id="wh_123",
        ...     name="analytics-warehouse",
        ...     resource_type="warehouse",
        ...     health_score=85,
        ...     health_status="healthy"
        ... )
    """

    id: str = Field(..., description="Resource identifier")
    name: str = Field(..., description="Display name")
    resource_type: Literal["warehouse", "cluster"] = Field(
        ..., description="Resource type"
    )
    health_score: int = Field(..., ge=0, le=100, description="Health score (0-100)")
    health_status: Literal["healthy", "warning", "critical", "inactive"] = Field(
        ..., description="Health status category"
    )
    metrics: ResourceMetrics = Field(
        default_factory=ResourceMetrics, description="Key performance metrics"
    )


# =============================================================================
# Portfolio Summary
# =============================================================================


class HealthDistribution(BaseModel):
    """Distribution of resources by health status.

    Attributes:
        healthy: Count of healthy resources
        warning: Count of resources with warnings
        critical: Count of critical resources
        inactive: Count of inactive resources

    Example:
        >>> dist = HealthDistribution(healthy=3, warning=1, critical=1)
    """

    healthy: int = 0
    warning: int = 0
    critical: int = 0
    inactive: int = 0


class PortfolioSummary(BaseModel):
    """Portfolio-level overview of compute resources.

    Provides a high-level summary of all warehouses or clusters in the fleet.

    Attributes:
        total_count: Total number of resources
        health_distribution: Breakdown by health status
        top_resources: Top resources by usage/importance

    Example:
        >>> portfolio = PortfolioSummary(
        ...     total_count=5,
        ...     health_distribution=HealthDistribution(healthy=3, warning=2),
        ...     top_resources=[...]
        ... )
    """

    total_count: int = Field(..., description="Total resources in portfolio")
    health_distribution: HealthDistribution = Field(
        ..., description="Distribution by health status"
    )
    top_resources: list[ResourceSummary] = Field(
        default_factory=list, description="Top resources by usage"
    )


# =============================================================================
# Health Metrics
# =============================================================================


class SLODetail(BaseModel):
    """Individual SLO target compliance detail.

    Attributes:
        metric: Name of the SLO metric
        target: Target value
        actual: Actual measured value
        met: Whether the SLO was met

    Example:
        >>> slo = SLODetail(metric="p95_latency", target=1000, actual=850, met=True)
    """

    metric: str
    target: float
    actual: float
    met: bool


class SLOCompliance(BaseModel):
    """SLO compliance summary.

    Attributes:
        targets_met: Number of SLO targets met
        targets_total: Total number of SLO targets
        details: Detailed breakdown by SLO

    Example:
        >>> compliance = SLOCompliance(
        ...     targets_met=3,
        ...     targets_total=4,
        ...     details=[SLODetail(...)]
        ... )
    """

    targets_met: int
    targets_total: int
    details: list[SLODetail] = Field(default_factory=list)


class MetricScores(BaseModel):
    """Individual metric health scores.

    Each score is 0-100 indicating health of that metric dimension.

    Attributes:
        latency: Latency health score
        availability: Availability health score
        queue_time: Queue time health score
        error_rate: Error rate health score (higher = better)

    Example:
        >>> scores = MetricScores(latency=85, availability=95)
    """

    latency: int = Field(default=0, ge=0, le=100)
    availability: int = Field(default=0, ge=0, le=100)
    queue_time: int = Field(default=0, ge=0, le=100)
    error_rate: int = Field(default=0, ge=0, le=100)


class HealthMetrics(BaseModel):
    """Health metrics for a compute resource.

    Provides detailed health analysis with metric breakdown and SLO compliance.

    Attributes:
        overall_score: Overall health score (0-100)
        metric_scores: Individual metric health scores
        slo_compliance: SLO compliance summary
        risk_factors: List of identified risk factors

    Example:
        >>> health = HealthMetrics(
        ...     overall_score=78,
        ...     metric_scores=MetricScores(latency=85, availability=95),
        ...     risk_factors=["High queue times"]
        ... )
    """

    overall_score: int = Field(..., ge=0, le=100, description="Overall health (0-100)")
    metric_scores: MetricScores = Field(
        default_factory=MetricScores, description="Individual metric scores"
    )
    slo_compliance: SLOCompliance | None = None
    risk_factors: list[str] = Field(default_factory=list)


# =============================================================================
# Topology Analysis
# =============================================================================


class WorkloadCluster(BaseModel):
    """Group of resources with similar workloads.

    Identifies resources that could potentially be consolidated.

    Attributes:
        id: Cluster identifier
        name: Descriptive name for the workload cluster
        resources: List of resource IDs in this cluster
        similarity_score: How similar the workloads are (0.0-1.0)

    Example:
        >>> cluster = WorkloadCluster(
        ...     id="bi_cluster",
        ...     name="BI Workloads",
        ...     resources=["wh_1", "wh_2"],
        ...     similarity_score=0.85
        ... )
    """

    id: str
    name: str
    resources: list[str]
    similarity_score: float = Field(..., ge=0.0, le=1.0)


class ConsolidationOpportunity(BaseModel):
    """Potential consolidation recommendation.

    Identifies resources that could be merged for cost savings.

    Attributes:
        source_resources: Resources to consolidate from
        target_resource: Recommended target resource (optional)
        estimated_savings_pct: Estimated cost savings percentage
        confidence: Confidence level of recommendation
        recommendation: Human-readable recommendation text

    Example:
        >>> opp = ConsolidationOpportunity(
        ...     source_resources=["wh_1", "wh_2"],
        ...     target_resource="wh_3",
        ...     estimated_savings_pct=25.0,
        ...     confidence="medium",
        ...     recommendation="Consolidate BI warehouses"
        ... )
    """

    source_resources: list[str]
    target_resource: str | None = None
    estimated_savings_pct: float
    confidence: Literal["low", "medium", "high"]
    recommendation: str


class TopologyAnalysis(BaseModel):
    """Cross-resource topology analysis.

    Identifies workload clusters and consolidation opportunities across
    the compute resource portfolio.

    Attributes:
        clusters: Identified workload clusters
        consolidation_opportunities: Potential consolidation actions

    Example:
        >>> topology = TopologyAnalysis(
        ...     clusters=[WorkloadCluster(...)],
        ...     consolidation_opportunities=[ConsolidationOpportunity(...)]
        ... )
    """

    clusters: list[WorkloadCluster] = Field(default_factory=list)
    consolidation_opportunities: list[ConsolidationOpportunity] = Field(
        default_factory=list
    )


# =============================================================================
# Warehouse Data (for data listing requests)
# =============================================================================


class WarehouseData(BaseModel):
    """Detailed warehouse data for data listing requests.

    Agent includes this when user requests a data listing (e.g., "show me all warehouses").
    This is separate from portfolio_summary which is a fleet-level summary.

    Attributes:
        warehouse_id: Unique warehouse identifier
        warehouse_name: Display name
        warehouse_type: Type (PRO, CLASSIC, etc.)
        state: Current state (RUNNING, STOPPED, etc.)
        total_queries: Total queries in the analysis window
        avg_duration_ms: Average query duration
        p50_duration_ms: Median query duration
        p95_duration_ms: 95th percentile duration
        p99_duration_ms: 99th percentile duration
        avg_queue_time_ms: Average queue time
        queued_query_pct: Percentage of queries that were queued
        unique_users: Number of unique users
        error_rate_pct: Error rate percentage
        health_score: Health score (0-100)
        health_status: Categorical health status

    Example:
        >>> wh = WarehouseData(
        ...     warehouse_id="abc123",
        ...     warehouse_name="analytics-wh",
        ...     warehouse_type="PRO",
        ...     state="RUNNING",
        ...     total_queries=1000,
        ...     health_score=85,
        ...     health_status="healthy"
        ... )
    """

    warehouse_id: str
    warehouse_name: str
    warehouse_type: str
    state: str
    total_queries: int
    avg_duration_ms: float = 0.0
    p50_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    p99_duration_ms: float = 0.0
    avg_queue_time_ms: float = 0.0
    queued_query_pct: float = 0.0
    unique_users: int = 0
    error_rate_pct: float = 0.0
    health_score: int = Field(..., ge=0, le=100)
    health_status: Literal["healthy", "warning", "critical", "inactive"]


# =============================================================================
# User Activity
# =============================================================================


class UserActivity(BaseModel):
    """User activity on compute resources.

    Tracks individual user usage for cost attribution and chargeback.

    Attributes:
        user_email: User email address
        query_count: Number of queries executed
        total_runtime_seconds: Total query runtime
        bytes_scanned: Total bytes scanned
        cost_attribution_pct: Percentage of costs attributed to this user

    Example:
        >>> activity = UserActivity(
        ...     user_email="alice@example.com",
        ...     query_count=500,
        ...     total_runtime_seconds=3600.0,
        ...     bytes_scanned=1_000_000_000
        ... )
    """

    user_email: str
    query_count: int
    total_runtime_seconds: float
    bytes_scanned: int
    cost_attribution_pct: float | None = None


class UserActivitySummary(BaseModel):
    """Summary of user activity across resources.

    Provides user-level breakdown for chargeback reporting.

    Attributes:
        period: Time period for the activity (e.g., "30 days")
        top_users: Top users by activity
        allocation_method: Method used for cost allocation

    Example:
        >>> summary = UserActivitySummary(
        ...     period="30 days",
        ...     top_users=[UserActivity(...)],
        ...     allocation_method="runtime"
        ... )
    """

    period: str
    top_users: list[UserActivity] = Field(default_factory=list)
    allocation_method: Literal["runtime", "queries", "bytes"] | None = None


# =============================================================================
# Data Table (Generic tabular data for reports)
# =============================================================================


class DataTable(BaseModel):
    """Generic data table for report outputs.

    Use this when the user expects to see tabular data (reports, lists,
    breakdowns, etc.). The frontend renders this as an interactive table.

    Signal words that indicate a data table is expected:
    - "report", "generate report", "create report"
    - "show me", "list", "give me", "what are all"
    - "breakdown", "table", "export"
    - "who is using", "which users", "chargeback"

    Attributes:
        title: Table title (e.g., "Warehouse Chargeback Report")
        description: Brief description of what the table shows
        columns: Column headers with units (e.g., "Cost ($)")
        rows: Data rows as list of lists (values in column order)
        total_rows: Total row count (for display)
        summary: Optional aggregates/totals

    Example:
        >>> table = DataTable(
        ...     title="Chargeback Report - analytics-warehouse",
        ...     description="Cost allocation by user for the past 30 days",
        ...     columns=["User", "Queries", "Runtime (sec)", "Cost ($)", "Share (%)"],
        ...     rows=[
        ...         ["alice@example.com", 500, 3600, 540.82, 35.5],
        ...         ["bob@example.com", 250, 1800, 304.69, 20.0],
        ...     ],
        ...     total_rows=17,
        ...     summary={"total_cost_usd": 1523.45, "period": "30 days"}
        ... )
    """

    title: str = Field(..., description="Table title for display")
    description: str | None = Field(
        default=None, description="Brief description of the data"
    )
    columns: list[str] = Field(
        ..., description="Column headers with units where applicable"
    )
    rows: list[list[str | int | float | None]] = Field(
        ..., description="Data rows in column order"
    )
    total_rows: int | None = Field(
        default=None, description="Total row count for display"
    )
    summary: dict[str, str | int | float] | None = Field(
        default=None, description="Summary/aggregate values"
    )


# =============================================================================
# Warehouse Report
# =============================================================================


class WarehouseReport(BaseModel):
    """Warehouse report for SQL Warehouse agent.

    This is the main report schema for the 'warehouse' report type.
    It supports multiple optional sections based on the type of analysis:
    - Portfolio overview for fleet-level analysis
    - Health metrics for individual resource analysis
    - Topology analysis for consolidation recommendations
    - User activity for chargeback reporting

    Attributes:
        report_type: Always "warehouse" for frontend routing
        summary: High-level analysis summary
        next_steps: Suggested next actions (1-5)
        portfolio_summary: Portfolio overview (optional)
        health_metrics: Resource health metrics (optional)
        topology_analysis: Topology/consolidation analysis (optional)
        user_activity: User activity summary (optional)
        analysis: Performance findings in advisor format (optional)

    Example:
        >>> report = WarehouseReport(
        ...     summary=Summary(overview="Portfolio analysis complete", ...),
        ...     next_steps=[NextStepAction(...)],
        ...     portfolio_summary=PortfolioSummary(total_count=5, ...),
        ...     health_metrics=HealthMetrics(overall_score=78, ...)
        ... )
    """

    report_type: Literal["warehouse"] = "warehouse"
    summary: Summary
    next_steps: list[NextStepAction] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Suggested next actions (1-5)",
    )

    # Optional sections based on analysis type (agent decides what to include)
    portfolio_summary: PortfolioSummary | None = None
    health_metrics: HealthMetrics | None = None
    topology_analysis: TopologyAnalysis | None = None
    user_activity: UserActivitySummary | None = None

    # Data listing - agent includes when user requests warehouse list
    # (e.g., "show me all our SQL warehouses")
    warehouses: list[WarehouseData] | None = Field(
        default=None,
        description="Full warehouse list for data listing requests",
    )

    # Generic data table - agent includes when user expects tabular data
    # (e.g., "generate chargeback report", "show me user activity")
    data_table: DataTable | None = Field(
        default=None,
        description="Generic data table for reports, chargeback, breakdowns, etc.",
    )

    # Performance findings - agent includes when optimization analysis is relevant
    # (e.g., "why is my warehouse slow?")
    analysis: Analysis | None = None
