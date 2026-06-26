# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for cluster health analyzer."""

from datetime import UTC, datetime

import pytest
from starboard_core.domain.models.cluster import (
    AccessMode,
    ClusterFingerprint,
    ClusterHealthReport,
    ClusterMode,
    ClusterType,
    CostProfile,
    HealthScore,
    NodeConfig,
    PerformanceProfile,
    RiskCategory,
    RiskSeverity,
    RuntimeConfig,
)
from starboard_server.tools.domain.cluster.health_analyzer import (
    analyze_cluster_health,
    calculate_health_scores,
    identify_cluster_risks,
)


@pytest.fixture
def healthy_fingerprint() -> ClusterFingerprint:
    """Create a healthy cluster fingerprint."""
    return ClusterFingerprint(
        fingerprint_version="v1",
        generated_at=datetime.now(UTC),
        cluster_id="healthy-123",
        cluster_name="healthy-cluster",
        cluster_type=ClusterType.ALL_PURPOSE,
        cluster_mode=ClusterMode.STANDARD,
        access_mode=AccessMode.SINGLE_USER,
        runtime=RuntimeConfig(
            dbr_version="14.3.x-scala2.12",
            is_lts=True,
            photon_enabled=True,
        ),
        node_config=NodeConfig(
            driver_node_type="i3.xlarge",
            worker_node_type="i3.xlarge",
            min_workers=2,
            max_workers=10,
            use_spot_instances=True,
            first_on_demand=1,
        ),
        autoscaling_enabled=True,
        pool_id="pool-123",
    )


@pytest.fixture
def unhealthy_fingerprint() -> ClusterFingerprint:
    """Create an unhealthy cluster fingerprint."""
    return ClusterFingerprint(
        fingerprint_version="v1",
        generated_at=datetime.now(UTC),
        cluster_id="unhealthy-123",
        cluster_name="unhealthy-cluster",
        cluster_type=ClusterType.ALL_PURPOSE,
        cluster_mode=ClusterMode.STANDARD,
        access_mode=AccessMode.NO_ISOLATION,
        runtime=RuntimeConfig(
            dbr_version="10.4.x-scala2.12",
            is_deprecated=True,
        ),
        node_config=NodeConfig(
            driver_node_type="i3.xlarge",
            worker_node_type="i3.xlarge",
            num_workers=4,
        ),
        autoscaling_enabled=False,
    )


class TestAnalyzeClusterHealth:
    """Tests for analyze_cluster_health function."""

    def test_returns_health_report(
        self, healthy_fingerprint: ClusterFingerprint
    ) -> None:
        """Test that function returns ClusterHealthReport."""
        result = analyze_cluster_health(healthy_fingerprint)

        assert isinstance(result, ClusterHealthReport)
        assert result.cluster_id == "healthy-123"
        assert result.cluster_name == "healthy-cluster"
        assert isinstance(result.scores, HealthScore)
        assert isinstance(result.risks, list)
        assert result.summary is not None

    def test_healthy_cluster_high_score(
        self, healthy_fingerprint: ClusterFingerprint
    ) -> None:
        """Test healthy cluster gets high score."""
        result = analyze_cluster_health(healthy_fingerprint)

        # Healthy cluster with LTS, autoscaling, spot, pool should score well
        assert result.scores.overall >= 80
        assert result.health_status == "healthy"

    def test_unhealthy_cluster_has_risks(
        self, unhealthy_fingerprint: ClusterFingerprint
    ) -> None:
        """Test unhealthy cluster has identified risks."""
        result = analyze_cluster_health(unhealthy_fingerprint)

        # Deprecated runtime, no isolation, no autoscaling should create risks
        assert len(result.risks) > 0
        # Should have critical or high priority risks
        high_priority = [
            r
            for r in result.risks
            if r.severity in (RiskSeverity.CRITICAL, RiskSeverity.HIGH)
        ]
        assert len(high_priority) >= 1


class TestCalculateHealthScores:
    """Tests for calculate_health_scores function."""

    def test_perfect_score_with_no_risks(
        self, healthy_fingerprint: ClusterFingerprint
    ) -> None:
        """Test perfect base scores with no risks."""
        risks = []
        result = calculate_health_scores(healthy_fingerprint, risks)

        # With no risks and bonuses for LTS, spot, autoscaling, pool
        assert result.performance > 90
        assert result.cost > 90
        assert result.reliability > 90
        assert result.security >= 100

    def test_deductions_for_risks(
        self, healthy_fingerprint: ClusterFingerprint
    ) -> None:
        """Test score deductions for risks."""
        from starboard_core.domain.models.cluster import RiskIndicator

        risks = [
            RiskIndicator(
                category=RiskCategory.PERFORMANCE,
                severity=RiskSeverity.HIGH,
                title="Test risk",
                description="Test",
                impact="Test",
                recommendation="Test",
            ),
        ]
        result = calculate_health_scores(healthy_fingerprint, risks)

        # HIGH severity deducts 20 points from base 100, but bonuses may apply
        # With pool bonus (+5), performance should be around 85
        assert result.performance <= 90

    def test_bonuses_applied(self, healthy_fingerprint: ClusterFingerprint) -> None:
        """Test bonuses for good practices."""
        risks = []
        result = calculate_health_scores(healthy_fingerprint, risks)

        # Should get bonuses for LTS (+5), spot (+10), autoscaling (+5), pool (+5)
        # Cost should be near max due to spot + autoscaling + pool bonuses
        assert result.cost >= 100  # Capped at 100


class TestIdentifyClusterRisks:
    """Tests for identify_cluster_risks function."""

    def test_deprecated_runtime_risk(self) -> None:
        """Test deprecated runtime creates critical risk."""
        fingerprint = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="old-123",
            cluster_name="old-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(
                dbr_version="10.4.x-scala2.12",
                is_deprecated=True,
            ),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
        )

        risks = identify_cluster_risks(fingerprint)

        deprecated_risks = [r for r in risks if "deprecated" in r.title.lower()]
        assert len(deprecated_risks) == 1
        assert deprecated_risks[0].severity == RiskSeverity.CRITICAL
        assert deprecated_risks[0].category == RiskCategory.SECURITY

    def test_no_autoscaling_risk(self) -> None:
        """Test fixed-size all-purpose cluster creates cost risk."""
        fingerprint = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="fixed-123",
            cluster_name="fixed-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
                num_workers=4,
            ),
            autoscaling_enabled=False,
        )

        risks = identify_cluster_risks(fingerprint)

        fixed_size_risks = [r for r in risks if "fixed-size" in r.title.lower()]
        assert len(fixed_size_risks) == 1
        assert fixed_size_risks[0].category == RiskCategory.COST

    def test_no_isolation_risk(self) -> None:
        """Test no isolation creates security risk."""
        fingerprint = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="unsafe-123",
            cluster_name="unsafe-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.NO_ISOLATION,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
        )

        risks = identify_cluster_risks(fingerprint)

        isolation_risks = [r for r in risks if "isolation" in r.title.lower()]
        assert len(isolation_risks) == 1
        assert isolation_risks[0].severity == RiskSeverity.HIGH
        assert isolation_risks[0].category == RiskCategory.SECURITY

    def test_low_cpu_utilization_risk(self) -> None:
        """Test low CPU utilization creates cost risk."""
        fingerprint = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="idle-123",
            cluster_name="idle-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
            performance=PerformanceProfile(
                cpu_utilization_p50=10.0,  # Very low
            ),
        )

        risks = identify_cluster_risks(fingerprint)

        cpu_risks = [r for r in risks if "cpu" in r.title.lower()]
        assert len(cpu_risks) == 1
        assert cpu_risks[0].category == RiskCategory.COST

    def test_high_memory_utilization_risk(self) -> None:
        """Test high memory utilization creates performance risk."""
        fingerprint = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="memory-123",
            cluster_name="memory-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
            performance=PerformanceProfile(
                memory_utilization_p95=95.0,  # Very high
            ),
        )

        risks = identify_cluster_risks(fingerprint)

        memory_risks = [r for r in risks if "memory" in r.title.lower()]
        assert len(memory_risks) == 1
        assert memory_risks[0].category == RiskCategory.PERFORMANCE
        assert memory_risks[0].severity == RiskSeverity.HIGH

    def test_oom_events_risk(self) -> None:
        """Test OOM events create reliability risk."""
        fingerprint = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="oom-123",
            cluster_name="oom-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
            performance=PerformanceProfile(
                oom_events_30d=15,  # Many OOM events
            ),
        )

        risks = identify_cluster_risks(fingerprint)

        oom_risks = [r for r in risks if "memory" in r.title.lower()]
        assert len(oom_risks) == 1
        assert oom_risks[0].category == RiskCategory.RELIABILITY
        assert oom_risks[0].severity == RiskSeverity.CRITICAL

    def test_high_idle_cost_risk(self) -> None:
        """Test high idle cost creates cost risk."""
        fingerprint = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="idle-123",
            cluster_name="idle-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.SINGLE_USER,
            runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
            cost=CostProfile(
                idle_cost_pct=60.0,  # Very high idle cost
            ),
        )

        risks = identify_cluster_risks(fingerprint)

        idle_risks = [r for r in risks if "idle" in r.title.lower()]
        assert len(idle_risks) == 1
        assert idle_risks[0].category == RiskCategory.COST
        assert idle_risks[0].severity == RiskSeverity.HIGH

    def test_healthy_cluster_minimal_risks(
        self, healthy_fingerprint: ClusterFingerprint
    ) -> None:
        """Test healthy cluster has minimal risks."""
        risks = identify_cluster_risks(healthy_fingerprint)

        # May have low-priority risks but no critical/high
        critical_high = [
            r for r in risks if r.severity in (RiskSeverity.CRITICAL, RiskSeverity.HIGH)
        ]
        assert len(critical_high) == 0


class TestSummaryGeneration:
    """Tests for summary generation in health reports."""

    def test_healthy_summary(self, healthy_fingerprint: ClusterFingerprint) -> None:
        """Test summary for healthy cluster."""
        result = analyze_cluster_health(healthy_fingerprint)

        assert "good health" in result.summary.lower()
        assert "healthy-cluster" in result.summary

    def test_unhealthy_summary(self, unhealthy_fingerprint: ClusterFingerprint) -> None:
        """Test summary for unhealthy cluster."""
        result = analyze_cluster_health(unhealthy_fingerprint)

        # Should mention issues
        assert (
            "attention" in result.summary.lower() or "issue" in result.summary.lower()
        )

    def test_critical_issues_mentioned(self) -> None:
        """Test critical issues are mentioned in summary."""
        fingerprint = ClusterFingerprint(
            fingerprint_version="v1",
            generated_at=datetime.now(UTC),
            cluster_id="critical-123",
            cluster_name="critical-cluster",
            cluster_type=ClusterType.ALL_PURPOSE,
            cluster_mode=ClusterMode.STANDARD,
            access_mode=AccessMode.NO_ISOLATION,
            runtime=RuntimeConfig(
                dbr_version="10.4.x-scala2.12",
                is_deprecated=True,
            ),
            node_config=NodeConfig(
                driver_node_type="i3.xlarge",
                worker_node_type="i3.xlarge",
            ),
        )

        result = analyze_cluster_health(fingerprint)

        # Should mention critical issues
        assert (
            "critical" in result.summary.lower()
            or "immediate" in result.summary.lower()
        )
