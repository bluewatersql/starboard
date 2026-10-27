# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for Warehouse report Pydantic models.

Tests cover:
- WarehouseReport model validation
- Portfolio summary model validation
- Health metrics model validation
- Topology analysis model validation
- User activity model validation
- Serialization/deserialization
"""

import pytest
from pydantic import ValidationError
from starboard_core.domain.models.compute_schemas import (
    ConsolidationOpportunity,
    HealthDistribution,
    HealthMetrics,
    MetricScores,
    PortfolioSummary,
    ResourceMetrics,
    ResourceSummary,
    SLOCompliance,
    SLODetail,
    TopologyAnalysis,
    UserActivity,
    UserActivitySummary,
    WarehouseReport,
    WorkloadCluster,
)
from starboard_core.domain.models.llm_schemas import (
    CurrentState,
    NextStepAction,
    Summary,
)


class TestResourceMetrics:
    """Tests for ResourceMetrics model."""

    def test_valid_resource_metrics(self):
        """Test creating valid ResourceMetrics with all fields."""
        metrics = ResourceMetrics(
            p50_latency_ms=100.0,
            p95_latency_ms=500.0,
            avg_queue_time_ms=50.0,
            query_count=1000,
            dbu_usage=150.5,
        )

        assert metrics.p50_latency_ms == 100.0
        assert metrics.p95_latency_ms == 500.0
        assert metrics.avg_queue_time_ms == 50.0
        assert metrics.query_count == 1000
        assert metrics.dbu_usage == 150.5

    def test_resource_metrics_defaults(self):
        """Test ResourceMetrics with default None values."""
        metrics = ResourceMetrics()

        assert metrics.p50_latency_ms is None
        assert metrics.p95_latency_ms is None
        assert metrics.avg_queue_time_ms is None
        assert metrics.query_count is None
        assert metrics.dbu_usage is None


class TestResourceSummary:
    """Tests for ResourceSummary model."""

    def test_valid_resource_summary_warehouse(self):
        """Test creating valid warehouse ResourceSummary."""
        resource = ResourceSummary(
            id="wh_123",
            name="analytics-warehouse",
            resource_type="warehouse",
            health_score=85,
            health_status="healthy",
        )

        assert resource.id == "wh_123"
        assert resource.name == "analytics-warehouse"
        assert resource.resource_type == "warehouse"
        assert resource.health_score == 85
        assert resource.health_status == "healthy"

    def test_valid_resource_summary_cluster(self):
        """Test creating valid cluster ResourceSummary."""
        resource = ResourceSummary(
            id="cl_456",
            name="etl-cluster",
            resource_type="cluster",
            health_score=72,
            health_status="warning",
            metrics=ResourceMetrics(p50_latency_ms=200.0),
        )

        assert resource.resource_type == "cluster"
        assert resource.health_status == "warning"
        assert resource.metrics.p50_latency_ms == 200.0

    def test_resource_summary_health_score_bounds(self):
        """Test health_score must be 0-100."""
        with pytest.raises(ValidationError):
            ResourceSummary(
                id="wh_123",
                name="test",
                resource_type="warehouse",
                health_score=150,  # Invalid: > 100
                health_status="healthy",
            )

        with pytest.raises(ValidationError):
            ResourceSummary(
                id="wh_123",
                name="test",
                resource_type="warehouse",
                health_score=-10,  # Invalid: < 0
                health_status="healthy",
            )

    def test_resource_summary_invalid_type(self):
        """Test invalid resource_type is rejected."""
        with pytest.raises(ValidationError):
            ResourceSummary(
                id="x_123",
                name="test",
                resource_type="invalid_type",
                health_score=80,
                health_status="healthy",
            )

    def test_resource_summary_invalid_status(self):
        """Test invalid health_status is rejected."""
        with pytest.raises(ValidationError):
            ResourceSummary(
                id="wh_123",
                name="test",
                resource_type="warehouse",
                health_score=80,
                health_status="unknown_status",
            )


class TestHealthDistribution:
    """Tests for HealthDistribution model."""

    def test_valid_health_distribution(self):
        """Test creating valid HealthDistribution."""
        dist = HealthDistribution(healthy=3, warning=1, critical=1, inactive=0)

        assert dist.healthy == 3
        assert dist.warning == 1
        assert dist.critical == 1
        assert dist.inactive == 0

    def test_health_distribution_defaults(self):
        """Test HealthDistribution default values."""
        dist = HealthDistribution()

        assert dist.healthy == 0
        assert dist.warning == 0
        assert dist.critical == 0
        assert dist.inactive == 0


class TestPortfolioSummary:
    """Tests for PortfolioSummary model."""

    def test_valid_portfolio_summary(self):
        """Test creating valid PortfolioSummary."""
        portfolio = PortfolioSummary(
            total_count=5,
            health_distribution=HealthDistribution(
                healthy=3, warning=1, critical=1, inactive=0
            ),
            top_resources=[
                ResourceSummary(
                    id="wh_1",
                    name="main-warehouse",
                    resource_type="warehouse",
                    health_score=90,
                    health_status="healthy",
                ),
            ],
        )

        assert portfolio.total_count == 5
        assert portfolio.health_distribution.healthy == 3
        assert len(portfolio.top_resources) == 1
        assert portfolio.top_resources[0].name == "main-warehouse"


class TestHealthMetrics:
    """Tests for HealthMetrics model."""

    def test_valid_health_metrics(self):
        """Test creating valid HealthMetrics."""
        health = HealthMetrics(
            overall_score=78,
            metric_scores=MetricScores(
                latency=85, availability=95, queue_time=60, error_rate=90
            ),
            slo_compliance=SLOCompliance(
                targets_met=3,
                targets_total=4,
                details=[
                    SLODetail(metric="p95_latency", target=1000, actual=850, met=True),
                ],
            ),
            risk_factors=["High queue times during peak hours"],
        )

        assert health.overall_score == 78
        assert health.metric_scores.latency == 85
        assert health.slo_compliance.targets_met == 3
        assert len(health.risk_factors) == 1

    def test_health_metrics_score_bounds(self):
        """Test overall_score must be 0-100."""
        with pytest.raises(ValidationError):
            HealthMetrics(overall_score=150)

    def test_metric_scores_bounds(self):
        """Test metric scores must be 0-100."""
        with pytest.raises(ValidationError):
            HealthMetrics(
                overall_score=80,
                metric_scores=MetricScores(latency=150),  # Invalid
            )


class TestTopologyAnalysis:
    """Tests for TopologyAnalysis model."""

    def test_valid_topology_analysis(self):
        """Test creating valid TopologyAnalysis."""
        topology = TopologyAnalysis(
            clusters=[
                WorkloadCluster(
                    id="cluster_1",
                    name="BI Workloads",
                    resources=["wh_1", "wh_2"],
                    similarity_score=0.85,
                )
            ],
            consolidation_opportunities=[
                ConsolidationOpportunity(
                    source_resources=["wh_1", "wh_2"],
                    target_resource="wh_3",
                    estimated_savings_pct=25.0,
                    confidence="medium",
                    recommendation="Consolidate BI warehouses to reduce overhead",
                )
            ],
        )

        assert len(topology.clusters) == 1
        assert topology.clusters[0].similarity_score == 0.85
        assert len(topology.consolidation_opportunities) == 1
        assert topology.consolidation_opportunities[0].estimated_savings_pct == 25.0

    def test_workload_cluster_similarity_bounds(self):
        """Test similarity_score must be 0.0-1.0."""
        with pytest.raises(ValidationError):
            WorkloadCluster(
                id="c1",
                name="test",
                resources=["r1"],
                similarity_score=1.5,  # Invalid: > 1.0
            )


class TestUserActivitySummary:
    """Tests for UserActivitySummary model."""

    def test_valid_user_activity_summary(self):
        """Test creating valid UserActivitySummary."""
        activity = UserActivitySummary(
            period="30 days",
            top_users=[
                UserActivity(
                    user_email="alice@example.com",
                    query_count=500,
                    total_runtime_seconds=3600.0,
                    bytes_scanned=1_000_000_000,
                    cost_attribution_pct=35.5,
                ),
            ],
            allocation_method="runtime",
        )

        assert activity.period == "30 days"
        assert len(activity.top_users) == 1
        assert activity.top_users[0].query_count == 500
        assert activity.allocation_method == "runtime"

    def test_user_activity_allocation_methods(self):
        """Test all valid allocation methods."""
        for method in ["runtime", "queries", "bytes"]:
            activity = UserActivitySummary(
                period="7 days",
                top_users=[],
                allocation_method=method,
            )
            assert activity.allocation_method == method


class TestWarehouseReport:
    """Tests for WarehouseReport model."""

    def _make_summary(self) -> Summary:
        """Helper to create a valid Summary."""
        return Summary(
            overview="Portfolio analysis complete",
            current_state=CurrentState(
                cloud_provider="AWS",
                resource_type="warehouse",
                key_symptoms=["High queue times"],
            ),
        )

    def _make_next_steps(self) -> list[NextStepAction]:
        """Helper to create valid next steps."""
        return [
            NextStepAction(
                id="drill_down_1",
                number=1,
                title="Analyze top warehouse",
                description="Deep dive into the highest usage warehouse",
                action_type="continue",
            ),
        ]

    def test_warehouse_report_type_is_warehouse(self):
        """Test that report_type is always 'warehouse'."""
        report = WarehouseReport(
            summary=self._make_summary(),
            next_steps=self._make_next_steps(),
        )

        assert report.report_type == "warehouse"

    def test_compute_report_with_portfolio_summary(self):
        """Test WarehouseReport with portfolio summary section."""
        report = WarehouseReport(
            summary=self._make_summary(),
            next_steps=self._make_next_steps(),
            portfolio_summary=PortfolioSummary(
                total_count=5,
                health_distribution=HealthDistribution(healthy=3, warning=2),
                top_resources=[],
            ),
        )

        assert report.portfolio_summary is not None
        assert report.portfolio_summary.total_count == 5

    def test_compute_report_with_health_metrics(self):
        """Test WarehouseReport with health metrics section."""
        report = WarehouseReport(
            summary=self._make_summary(),
            next_steps=self._make_next_steps(),
            health_metrics=HealthMetrics(overall_score=82),
        )

        assert report.health_metrics is not None
        assert report.health_metrics.overall_score == 82

    def test_compute_report_with_topology(self):
        """Test WarehouseReport with topology analysis section."""
        report = WarehouseReport(
            summary=self._make_summary(),
            next_steps=self._make_next_steps(),
            topology_analysis=TopologyAnalysis(
                clusters=[],
                consolidation_opportunities=[],
            ),
        )

        assert report.topology_analysis is not None

    def test_compute_report_with_user_activity(self):
        """Test WarehouseReport with user activity section."""
        report = WarehouseReport(
            summary=self._make_summary(),
            next_steps=self._make_next_steps(),
            user_activity=UserActivitySummary(
                period="30 days",
                top_users=[],
            ),
        )

        assert report.user_activity is not None
        assert report.user_activity.period == "30 days"

    def test_compute_report_requires_next_steps(self):
        """Test that next_steps is required (min 1)."""
        with pytest.raises(ValidationError):
            WarehouseReport(
                summary=self._make_summary(),
                next_steps=[],  # Empty - should fail min_length=1
            )

    def test_warehouse_report_max_next_steps(self):
        """Test that next_steps max is 5."""
        too_many_steps = [
            NextStepAction(
                id=f"step_{i}",
                number=i,
                title=f"Step {i}",
                action_type="continue",
            )
            for i in range(1, 7)  # 6 steps
        ]

        with pytest.raises(ValidationError):
            WarehouseReport(
                summary=self._make_summary(),
                next_steps=too_many_steps,
            )

    def test_warehouse_report_serialization(self):
        """Test WarehouseReport can be serialized and deserialized."""
        report = WarehouseReport(
            summary=self._make_summary(),
            next_steps=self._make_next_steps(),
            portfolio_summary=PortfolioSummary(
                total_count=3,
                health_distribution=HealthDistribution(healthy=3),
            ),
        )

        # Serialize to dict
        data = report.model_dump()
        assert data["report_type"] == "warehouse"
        assert data["portfolio_summary"]["total_count"] == 3

        # Deserialize back
        new_report = WarehouseReport(**data)
        assert new_report.report_type == "warehouse"
        assert new_report.portfolio_summary.total_count == 3

    def test_warehouse_report_json_serialization(self):
        """Test WarehouseReport JSON round-trip."""
        report = WarehouseReport(
            summary=self._make_summary(),
            next_steps=self._make_next_steps(),
            health_metrics=HealthMetrics(
                overall_score=75,
                metric_scores=MetricScores(latency=80, availability=90),
            ),
        )

        json_str = report.model_dump_json()
        assert '"report_type":"warehouse"' in json_str
        assert '"overall_score":75' in json_str

        # Parse back
        new_report = WarehouseReport.model_validate_json(json_str)
        assert new_report.health_metrics.overall_score == 75
