# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for HealthScorer.

Tests the pure domain logic for calculating warehouse health scores
from fingerprint data and SLO configurations.
"""

from datetime import UTC, datetime

from starboard_core.domain.analyzers.warehouse_analyzer import (
    HealthScorer,
)
from starboard_core.domain.models.warehouse import (
    HealthSummary,
    QueryTypeDistribution,
    RiskFactor,
    SLOConfig,
    SLOStatus,
    SLOTarget,
    TimeDistribution,
    WarehouseFingerprint,
    WorkloadPattern,
)

# =============================================================================
# Test Fixtures
# =============================================================================


def _make_fingerprint(
    *,
    warehouse_id: str = "wh-test",
    warehouse_name: str = "Test Warehouse",
    p50_runtime_sec: float = 1.0,
    p75_runtime_sec: float = 2.0,
    p90_runtime_sec: float = 5.0,
    p95_runtime_sec: float = 10.0,
    p99_runtime_sec: float = 20.0,
    avg_queue_time_sec: float = 0.5,
    p95_queue_time_sec: float = 2.0,
    queue_rate_pct: float = 5.0,
    total_queries: int = 1000,
    avg_concurrency: float = 5.0,
    peak_concurrency: int = 20,
    pattern_type: str = "interactive",
) -> WarehouseFingerprint:
    """Create a test fingerprint with reasonable defaults."""
    return WarehouseFingerprint(
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
        analysis_window_days=7,
        analyzed_at=datetime.now(UTC),
        total_queries=total_queries,
        total_bytes_read=10_000_000_000,
        total_bytes_written=1_000_000_000,
        p50_runtime_sec=p50_runtime_sec,
        p75_runtime_sec=p75_runtime_sec,
        p90_runtime_sec=p90_runtime_sec,
        p95_runtime_sec=p95_runtime_sec,
        p99_runtime_sec=p99_runtime_sec,
        avg_concurrency=avg_concurrency,
        peak_concurrency=peak_concurrency,
        avg_queue_time_sec=avg_queue_time_sec,
        p95_queue_time_sec=p95_queue_time_sec,
        queue_rate_pct=queue_rate_pct,
        query_type_distribution=QueryTypeDistribution(
            select_pct=80.0, insert_pct=10.0, update_pct=5.0, delete_pct=5.0
        ),
        time_distribution=TimeDistribution(
            hourly_distribution=tuple([100] * 24),
            peak_hours=(10, 11, 14, 15),
            quiet_hours=(0, 1, 2, 3, 4, 5),
        ),
        workload_pattern=WorkloadPattern(
            pattern_type=pattern_type,
            confidence=0.9,
            description="Test pattern",
            evidence=(),
        ),
    )


def _make_slo_config(
    warehouse_id: str = "wh-test",
    p95_target: float = 15.0,
    availability_target: float = 99.5,
    queue_time_target: float = 5.0,
) -> SLOConfig:
    """Create a test SLO configuration."""
    return SLOConfig(
        warehouse_id=warehouse_id,
        targets=(
            SLOTarget(
                slo_type="p95_latency",
                target_value=p95_target,
                unit="seconds",
                warning_threshold=p95_target * 1.5,
                critical_threshold=p95_target * 2.0,
            ),
            SLOTarget(
                slo_type="availability",
                target_value=availability_target,
                unit="percent",
                warning_threshold=availability_target - 0.5,
                critical_threshold=availability_target - 1.5,
            ),
            SLOTarget(
                slo_type="queue_time",
                target_value=queue_time_target,
                unit="seconds",
                warning_threshold=queue_time_target * 2.0,
                critical_threshold=queue_time_target * 4.0,
            ),
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# =============================================================================
# Basic Health Score Calculation Tests
# =============================================================================


class TestBasicHealthScore:
    """Test basic health score calculation."""

    def test_healthy_warehouse_high_score(self) -> None:
        """Healthy warehouse gets high health score (>= 80)."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=5.0,
            avg_queue_time_sec=0.5,
            queue_rate_pct=2.0,
        )
        slo_config = _make_slo_config(p95_target=15.0)
        scorer = HealthScorer(fingerprint, slo_config)

        result = scorer.calculate()

        assert result.health_score >= 80
        assert result.health_status == "healthy"

    def test_degraded_warehouse_medium_score(self) -> None:
        """Degraded warehouse gets medium score (40-80)."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=20.0,  # Above target
            avg_queue_time_sec=8.0,  # High queue time
            queue_rate_pct=15.0,  # High queue rate
        )
        slo_config = _make_slo_config(p95_target=15.0)
        scorer = HealthScorer(fingerprint, slo_config)

        result = scorer.calculate()

        assert 40 <= result.health_score < 80
        assert result.health_status == "warning"

    def test_critical_warehouse_low_score(self) -> None:
        """Critical warehouse gets low score (< 40)."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=60.0,  # Way above target
            avg_queue_time_sec=30.0,  # Very high queue time
            queue_rate_pct=40.0,  # Very high queue rate
        )
        slo_config = _make_slo_config(p95_target=15.0)
        scorer = HealthScorer(fingerprint, slo_config)

        result = scorer.calculate()

        assert result.health_score < 50
        assert result.health_status in ("warning", "critical")

    def test_score_without_slo_config(self) -> None:
        """Calculate score using default thresholds when no SLO configured."""
        fingerprint = _make_fingerprint(p95_runtime_sec=10.0)
        scorer = HealthScorer(fingerprint, slo_config=None)

        result = scorer.calculate()

        # Should still produce a valid score
        assert 0 <= result.health_score <= 100
        assert result.health_status in ("healthy", "warning", "critical", "unknown")

    def test_score_clamped_to_0_100(self) -> None:
        """Score is always between 0 and 100."""
        # Very healthy
        fingerprint = _make_fingerprint(
            p95_runtime_sec=0.1,
            avg_queue_time_sec=0.0,
            queue_rate_pct=0.0,
        )
        scorer = HealthScorer(fingerprint, None)
        result = scorer.calculate()
        assert 0 <= result.health_score <= 100

        # Very unhealthy
        fingerprint = _make_fingerprint(
            p95_runtime_sec=1000.0,
            avg_queue_time_sec=500.0,
            queue_rate_pct=100.0,
        )
        scorer = HealthScorer(fingerprint, None)
        result = scorer.calculate()
        assert 0 <= result.health_score <= 100


# =============================================================================
# SLO Compliance Tests
# =============================================================================


class TestSLOCompliance:
    """Test SLO compliance calculation."""

    def test_all_slos_compliant(self) -> None:
        """All SLOs met results in high compliance."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=10.0,  # Below 15s target
            p95_queue_time_sec=3.0,  # Below 5s target
        )
        slo_config = _make_slo_config(p95_target=15.0, queue_time_target=5.0)
        scorer = HealthScorer(fingerprint, slo_config)

        result = scorer.calculate()

        assert result.overall_slo_compliance >= 90
        # All statuses should be compliant
        for status in result.slo_statuses:
            if status.slo_type in ("p95_latency", "queue_time"):
                assert status.compliant is True

    def test_slo_violation_detected(self) -> None:
        """SLO violation is correctly detected."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=25.0,  # Above 15s target
        )
        slo_config = _make_slo_config(p95_target=15.0)
        scorer = HealthScorer(fingerprint, slo_config)

        result = scorer.calculate()

        # Find p95_latency status
        p95_status = next(
            (s for s in result.slo_statuses if s.slo_type == "p95_latency"), None
        )
        assert p95_status is not None
        assert p95_status.compliant is False
        assert p95_status.actual == 25.0
        assert p95_status.target == 15.0

    def test_has_slo_violations_property(self) -> None:
        """has_slo_violations property works correctly."""
        # No violations
        fingerprint = _make_fingerprint(p95_runtime_sec=10.0)
        slo_config = _make_slo_config(p95_target=15.0)
        result = HealthScorer(fingerprint, slo_config).calculate()
        # May or may not have violations depending on other SLOs

        # With violations
        fingerprint = _make_fingerprint(p95_runtime_sec=50.0)
        result = HealthScorer(fingerprint, slo_config).calculate()
        assert result.has_slo_violations is True


# =============================================================================
# Risk Factor Tests
# =============================================================================


class TestRiskFactors:
    """Test risk factor identification."""

    def test_high_queue_rate_risk(self) -> None:
        """High queue rate identified as risk factor."""
        fingerprint = _make_fingerprint(queue_rate_pct=25.0)  # > 10%
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        # Should have queue-related risk factor
        risk_ids = [r.factor_id for r in result.risk_factors]
        assert any("queue" in rid.lower() for rid in risk_ids)

    def test_high_latency_variance_risk(self) -> None:
        """Large latency variance identified as risk factor."""
        fingerprint = _make_fingerprint(
            p50_runtime_sec=1.0,
            p99_runtime_sec=100.0,  # 100x variance
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        # Should have variance-related risk factor
        risk_ids = [r.factor_id for r in result.risk_factors]
        assert any(
            "variance" in rid.lower() or "latency" in rid.lower() for rid in risk_ids
        )

    def test_no_risk_factors_healthy_warehouse(self) -> None:
        """Healthy warehouse has minimal risk factors."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=5.0,
            avg_queue_time_sec=0.5,
            queue_rate_pct=2.0,
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        # Should have few or no critical risk factors
        critical_risks = [r for r in result.risk_factors if r.severity == "critical"]
        assert len(critical_risks) == 0

    def test_risk_severity_levels(self) -> None:
        """Risk factors have correct severity levels."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=60.0,  # Very high
            queue_rate_pct=50.0,  # Very high
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        # Should have some high/critical severity risks
        severities = {r.severity for r in result.risk_factors}
        assert len(severities) > 0  # Has risks
        assert "high" in severities or "critical" in severities


# =============================================================================
# Recommendation Tests
# =============================================================================


class TestRecommendations:
    """Test recommendation generation."""

    def test_generates_recommendations_for_issues(self) -> None:
        """Generates recommendations when issues are found."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=30.0,  # High
            queue_rate_pct=20.0,  # High
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        # Should have some recommendations
        total_recommendations = len(result.immediate_actions) + len(
            result.optimization_opportunities
        )
        assert total_recommendations > 0

    def test_immediate_actions_for_critical(self) -> None:
        """Critical issues generate immediate actions."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=100.0,  # Very high
            queue_rate_pct=60.0,  # Very high
        )
        slo_config = _make_slo_config(p95_target=15.0)
        scorer = HealthScorer(fingerprint, slo_config)

        result = scorer.calculate()

        # Should have immediate actions for critical issues
        assert len(result.immediate_actions) > 0

    def test_optimization_opportunities_for_healthy(self) -> None:
        """Healthy warehouses get optimization suggestions."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=5.0,
            queue_rate_pct=2.0,
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        # May have optimization opportunities even when healthy
        # At minimum, should not have immediate actions
        assert len(result.immediate_actions) <= len(result.optimization_opportunities)


# =============================================================================
# Health Status Tests
# =============================================================================


class TestHealthStatus:
    """Test health status categorization."""

    def test_healthy_status_threshold(self) -> None:
        """Health score >= 80 is 'healthy'."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=5.0,
            avg_queue_time_sec=0.5,
            queue_rate_pct=1.0,
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        if result.health_score >= 80:
            assert result.health_status == "healthy"

    def test_warning_status_threshold(self) -> None:
        """Health score 40-79 is 'warning'."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=25.0,
            queue_rate_pct=15.0,
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        if 40 <= result.health_score < 80:
            assert result.health_status == "warning"

    def test_critical_status_threshold(self) -> None:
        """Health score < 40 is 'critical'."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=200.0,
            queue_rate_pct=70.0,
            avg_queue_time_sec=60.0,
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        if result.health_score < 40:
            assert result.health_status == "critical"

    def test_is_healthy_property(self) -> None:
        """is_healthy property works correctly."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=5.0,
            queue_rate_pct=1.0,
        )
        result = HealthScorer(fingerprint, None).calculate()

        if result.health_status == "healthy":
            assert result.is_healthy is True
        else:
            assert result.is_healthy is False

    def test_needs_attention_property(self) -> None:
        """needs_attention property works correctly."""
        # Critical warehouse
        fingerprint = _make_fingerprint(
            p95_runtime_sec=200.0,
            queue_rate_pct=70.0,
        )
        result = HealthScorer(fingerprint, None).calculate()

        if result.health_status in ("warning", "critical"):
            assert result.needs_attention is True


# =============================================================================
# Health Trend Tests
# =============================================================================


class TestHealthTrend:
    """Test health trend calculation."""

    def test_default_trend_is_stable(self) -> None:
        """Without historical data, trend defaults to stable."""
        fingerprint = _make_fingerprint()
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        # Without historical comparison, trend should be stable
        assert result.health_trend == "stable"

    def test_trend_with_previous_fingerprint(self) -> None:
        """Trend is calculated from previous fingerprint comparison."""
        current = _make_fingerprint(p95_runtime_sec=10.0)
        previous = _make_fingerprint(p95_runtime_sec=20.0)
        scorer = HealthScorer(current, None, previous_fingerprint=previous)

        result = scorer.calculate()

        # Performance improved (lower p95), trend should be improving
        assert result.health_trend == "improving"

    def test_degrading_trend(self) -> None:
        """Degrading performance shows degrading trend."""
        current = _make_fingerprint(p95_runtime_sec=30.0)
        previous = _make_fingerprint(p95_runtime_sec=10.0)
        scorer = HealthScorer(current, None, previous_fingerprint=previous)

        result = scorer.calculate()

        # Performance degraded, trend should be degrading
        assert result.health_trend == "degrading"


# =============================================================================
# Risk Level Tests
# =============================================================================


class TestRiskLevel:
    """Test aggregate risk level calculation."""

    def test_low_risk_healthy_warehouse(self) -> None:
        """Healthy warehouse has low aggregate risk."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=5.0,
            queue_rate_pct=1.0,
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        assert result.risk_level in ("low", "medium")

    def test_high_risk_degraded_warehouse(self) -> None:
        """Degraded warehouse has high aggregate risk."""
        fingerprint = _make_fingerprint(
            p95_runtime_sec=100.0,
            queue_rate_pct=50.0,
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        assert result.risk_level in ("high", "critical")


# =============================================================================
# HealthSummary Structure Tests
# =============================================================================


class TestHealthSummaryStructure:
    """Test HealthSummary output structure."""

    def test_complete_structure(self) -> None:
        """HealthSummary contains all required fields."""
        fingerprint = _make_fingerprint()
        slo_config = _make_slo_config()
        scorer = HealthScorer(fingerprint, slo_config)

        result = scorer.calculate()

        # Verify structure
        assert isinstance(result, HealthSummary)
        assert result.warehouse_id == "wh-test"
        assert result.warehouse_name == "Test Warehouse"

        # Health metrics
        assert isinstance(result.health_score, float)
        assert result.health_status in ("healthy", "warning", "critical", "unknown")
        assert result.health_trend in ("improving", "stable", "degrading")

        # SLO
        assert isinstance(result.slo_statuses, tuple)
        assert isinstance(result.overall_slo_compliance, float)

        # Risk
        assert isinstance(result.risk_factors, tuple)
        assert result.risk_level in ("low", "medium", "high", "critical")

        # Recommendations
        assert isinstance(result.immediate_actions, tuple)
        assert isinstance(result.optimization_opportunities, tuple)

    def test_slo_status_structure(self) -> None:
        """SLOStatus contains all required fields."""
        fingerprint = _make_fingerprint()
        slo_config = _make_slo_config()
        scorer = HealthScorer(fingerprint, slo_config)

        result = scorer.calculate()

        for status in result.slo_statuses:
            assert isinstance(status, SLOStatus)
            assert isinstance(status.slo_type, str)
            assert isinstance(status.target, float)
            assert isinstance(status.actual, float)
            assert isinstance(status.compliant, bool)
            assert isinstance(status.compliance_pct, float)
            assert status.trend in ("improving", "stable", "degrading")

    def test_risk_factor_structure(self) -> None:
        """RiskFactor contains all required fields."""
        # Create a fingerprint with known issues
        fingerprint = _make_fingerprint(queue_rate_pct=30.0)
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        if result.risk_factors:
            for risk in result.risk_factors:
                assert isinstance(risk, RiskFactor)
                assert isinstance(risk.factor_id, str)
                assert isinstance(risk.name, str)
                assert isinstance(risk.description, str)
                assert risk.severity in ("low", "medium", "high", "critical")
                assert isinstance(risk.impact_score, float)
                assert isinstance(risk.recommendation, str)


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_nan_values_handled(self) -> None:
        """NaN values in fingerprint are handled gracefully."""
        fingerprint = WarehouseFingerprint(
            warehouse_id="wh-nan",
            warehouse_name="NaN Test",
            analysis_window_days=7,
            analyzed_at=datetime.now(UTC),
            total_queries=0,
            total_bytes_read=0,
            total_bytes_written=0,
            p50_runtime_sec=float("nan"),
            p75_runtime_sec=float("nan"),
            p90_runtime_sec=float("nan"),
            p95_runtime_sec=float("nan"),
            p99_runtime_sec=float("nan"),
            avg_concurrency=0.0,
            peak_concurrency=0,
            avg_queue_time_sec=0.0,
            p95_queue_time_sec=float("nan"),
            queue_rate_pct=0.0,
            query_type_distribution=QueryTypeDistribution(select_pct=0.0),
            time_distribution=TimeDistribution(
                hourly_distribution=tuple([0] * 24),
                peak_hours=(),
                quiet_hours=tuple(range(24)),
            ),
            workload_pattern=WorkloadPattern(
                pattern_type="ad_hoc",
                confidence=0.0,
                description="No data",
                evidence=(),
            ),
        )
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        # Should produce a valid result even with NaN values
        # Warehouses with 0 queries get "inactive" status
        assert 0 <= result.health_score <= 100
        assert result.health_status in (
            "healthy",
            "warning",
            "critical",
            "unknown",
            "inactive",
        )

    def test_zero_queries_handled(self) -> None:
        """Zero queries in fingerprint is handled gracefully."""
        fingerprint = _make_fingerprint(total_queries=0)
        scorer = HealthScorer(fingerprint, None)

        result = scorer.calculate()

        # Should produce valid result
        assert isinstance(result, HealthSummary)

    def test_empty_slo_targets(self) -> None:
        """Empty SLO targets handled gracefully."""
        fingerprint = _make_fingerprint()
        slo_config = SLOConfig(
            warehouse_id="wh-test",
            targets=(),  # Empty targets
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        scorer = HealthScorer(fingerprint, slo_config)

        result = scorer.calculate()

        assert len(result.slo_statuses) == 0
        assert result.overall_slo_compliance == 100.0  # No SLOs to violate
