# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for cluster health domain models."""

from datetime import UTC, datetime

import pytest
from starboard_core.domain.models.cluster import (
    ClusterHealthReport,
    HealthScore,
    RiskCategory,
    RiskIndicator,
    RiskSeverity,
)


class TestRiskSeverity:
    """Tests for RiskSeverity enum."""

    def test_all_severities_defined(self) -> None:
        """Test all severity levels are defined."""
        severities = {s.value for s in RiskSeverity}
        expected = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert severities == expected

    def test_string_behavior(self) -> None:
        """Test enum is string-compatible."""
        assert RiskSeverity.CRITICAL == "CRITICAL"
        assert RiskSeverity.HIGH == "HIGH"


class TestRiskCategory:
    """Tests for RiskCategory enum."""

    def test_all_categories_defined(self) -> None:
        """Test all risk categories are defined."""
        categories = {c.value for c in RiskCategory}
        expected = {"PERFORMANCE", "COST", "RELIABILITY", "SECURITY", "MAINTENANCE"}
        assert categories == expected


class TestHealthScore:
    """Tests for HealthScore dataclass."""

    def test_minimal_creation(self) -> None:
        """Test creation with only overall score."""
        score = HealthScore(overall=75)
        assert score.overall == 75
        assert score.performance == 100.0
        assert score.cost == 100.0
        assert score.reliability == 100.0
        assert score.security == 100.0

    def test_full_creation(self) -> None:
        """Test creation with all scores."""
        score = HealthScore(
            overall=75,
            performance=80,
            cost=60,
            reliability=85,
            security=90,
        )
        assert score.overall == 75
        assert score.performance == 80
        assert score.cost == 60
        assert score.reliability == 85
        assert score.security == 90

    def test_frozen(self) -> None:
        """Test dataclass is frozen."""
        score = HealthScore(overall=75)
        with pytest.raises(AttributeError):
            score.overall = 80  # type: ignore[misc]

    def test_validation_rejects_negative(self) -> None:
        """Test validation rejects negative scores."""
        with pytest.raises(ValueError, match="overall must be between 0 and 100"):
            HealthScore(overall=-10)

    def test_validation_rejects_over_100(self) -> None:
        """Test validation rejects scores over 100."""
        with pytest.raises(ValueError, match="overall must be between 0 and 100"):
            HealthScore(overall=150)

    def test_validation_checks_all_fields(self) -> None:
        """Test validation checks all score fields."""
        with pytest.raises(ValueError, match="performance must be between 0 and 100"):
            HealthScore(overall=75, performance=110)

        with pytest.raises(ValueError, match="cost must be between 0 and 100"):
            HealthScore(overall=75, cost=-5)

    def test_boundary_values(self) -> None:
        """Test boundary values are valid."""
        score_zero = HealthScore(overall=0)
        assert score_zero.overall == 0

        score_hundred = HealthScore(overall=100)
        assert score_hundred.overall == 100


class TestRiskIndicator:
    """Tests for RiskIndicator dataclass."""

    def test_creation(self) -> None:
        """Test risk indicator creation."""
        risk = RiskIndicator(
            category=RiskCategory.PERFORMANCE,
            severity=RiskSeverity.MEDIUM,
            title="Low CPU utilization",
            description="Average CPU utilization is 15%, indicating over-provisioning.",
            impact="Paying for unused compute capacity.",
            recommendation="Consider reducing worker count or using smaller instances.",
        )
        assert risk.category == RiskCategory.PERFORMANCE
        assert risk.severity == RiskSeverity.MEDIUM
        assert risk.title == "Low CPU utilization"
        assert "over-provisioning" in risk.description
        assert "unused compute" in risk.impact
        assert "reducing worker count" in risk.recommendation

    def test_frozen(self) -> None:
        """Test dataclass is frozen."""
        risk = RiskIndicator(
            category=RiskCategory.COST,
            severity=RiskSeverity.LOW,
            title="Test risk",
            description="Test description",
            impact="Test impact",
            recommendation="Test recommendation",
        )
        with pytest.raises(AttributeError):
            risk.severity = RiskSeverity.HIGH  # type: ignore[misc]


class TestClusterHealthReport:
    """Tests for ClusterHealthReport dataclass."""

    @pytest.fixture
    def sample_risks(self) -> list[RiskIndicator]:
        """Create sample risk indicators."""
        return [
            RiskIndicator(
                category=RiskCategory.COST,
                severity=RiskSeverity.MEDIUM,
                title="Over-provisioned",
                description="Cluster is over-provisioned.",
                impact="Higher costs.",
                recommendation="Reduce worker count.",
            ),
            RiskIndicator(
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.CRITICAL,
                title="Deprecated runtime",
                description="Using deprecated runtime.",
                impact="Security vulnerabilities.",
                recommendation="Upgrade to latest LTS.",
            ),
            RiskIndicator(
                category=RiskCategory.PERFORMANCE,
                severity=RiskSeverity.HIGH,
                title="High memory usage",
                description="Memory utilization is high.",
                impact="OOM risk.",
                recommendation="Increase memory or optimize jobs.",
            ),
        ]

    def test_minimal_creation(self) -> None:
        """Test creation with minimal fields."""
        report = ClusterHealthReport(
            cluster_id="cluster-123",
            cluster_name="test-cluster",
            generated_at=datetime.now(UTC),
            scores=HealthScore(overall=75),
        )
        assert report.cluster_id == "cluster-123"
        assert report.cluster_name == "test-cluster"
        assert report.scores.overall == 75
        assert report.risks == []
        assert report.summary is None

    def test_creation_with_risks(self, sample_risks: list[RiskIndicator]) -> None:
        """Test creation with risks."""
        report = ClusterHealthReport(
            cluster_id="cluster-123",
            cluster_name="test-cluster",
            generated_at=datetime.now(UTC),
            scores=HealthScore(overall=60, cost=50, security=40),
            risks=sample_risks,
            summary="Cluster has cost and security issues.",
        )
        assert len(report.risks) == 3
        assert report.summary == "Cluster has cost and security issues."

    def test_health_status_healthy(self) -> None:
        """Test health_status returns healthy for high scores."""
        report = ClusterHealthReport(
            cluster_id="cluster-123",
            cluster_name="test-cluster",
            generated_at=datetime.now(UTC),
            scores=HealthScore(overall=85),
        )
        assert report.health_status == "healthy"

    def test_health_status_warning(self) -> None:
        """Test health_status returns warning for medium scores."""
        report = ClusterHealthReport(
            cluster_id="cluster-123",
            cluster_name="test-cluster",
            generated_at=datetime.now(UTC),
            scores=HealthScore(overall=65),
        )
        assert report.health_status == "warning"

    def test_health_status_critical(self) -> None:
        """Test health_status returns critical for low scores."""
        report = ClusterHealthReport(
            cluster_id="cluster-123",
            cluster_name="test-cluster",
            generated_at=datetime.now(UTC),
            scores=HealthScore(overall=35),
        )
        assert report.health_status == "critical"

    def test_critical_risks_property(self, sample_risks: list[RiskIndicator]) -> None:
        """Test critical_risks returns only critical risks."""
        report = ClusterHealthReport(
            cluster_id="cluster-123",
            cluster_name="test-cluster",
            generated_at=datetime.now(UTC),
            scores=HealthScore(overall=50),
            risks=sample_risks,
        )
        critical = report.critical_risks
        assert len(critical) == 1
        assert critical[0].title == "Deprecated runtime"

    def test_high_priority_risks_property(
        self, sample_risks: list[RiskIndicator]
    ) -> None:
        """Test high_priority_risks returns critical and high risks."""
        report = ClusterHealthReport(
            cluster_id="cluster-123",
            cluster_name="test-cluster",
            generated_at=datetime.now(UTC),
            scores=HealthScore(overall=50),
            risks=sample_risks,
        )
        high_priority = report.high_priority_risks
        assert len(high_priority) == 2
        severities = {r.severity for r in high_priority}
        assert RiskSeverity.CRITICAL in severities
        assert RiskSeverity.HIGH in severities
        assert RiskSeverity.MEDIUM not in severities

    def test_frozen(self) -> None:
        """Test dataclass is frozen."""
        report = ClusterHealthReport(
            cluster_id="cluster-123",
            cluster_name="test-cluster",
            generated_at=datetime.now(UTC),
            scores=HealthScore(overall=75),
        )
        with pytest.raises(AttributeError):
            report.cluster_id = "new-id"  # type: ignore[misc]
