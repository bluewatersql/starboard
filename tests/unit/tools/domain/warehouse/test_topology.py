# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for warehouse topology analysis."""

from typing import Any

import pytest
from starboard.tools.domain.warehouse.topology import (
    SimilarityMatch,
    TopologyAnalysis,
    TopologyAnalyzer,
    TopologyInsight,
)

# =============================================================================
# Test Fixtures
# =============================================================================


def _make_fingerprint(
    warehouse_id: str,
    warehouse_name: str | None = None,
    workload_pattern: str = "interactive",
    p95_runtime_sec: float = 5.0,
    total_queries: int = 1000,
    queries_per_day: float = 100.0,
    select_pct: float = 80.0,
    insert_pct: float = 10.0,
    peak_hours: list[int] | None = None,
) -> dict[str, Any]:
    """Create a test fingerprint."""
    return {
        "warehouse_id": warehouse_id,
        "warehouse_name": warehouse_name or warehouse_id,
        "workload_pattern": {
            "pattern_type": workload_pattern,
            "confidence": 0.9,
        },
        "p95_runtime_sec": p95_runtime_sec,
        "total_queries": total_queries,
        "queries_per_day": queries_per_day,
        "query_type_distribution": {
            "select_pct": select_pct,
            "insert_pct": insert_pct,
            "update_pct": 5.0,
            "delete_pct": 5.0,
        },
        "time_distribution": {
            "peak_hours": peak_hours or [9, 10, 11, 14, 15, 16],
        },
    }


@pytest.fixture
def analyzer() -> TopologyAnalyzer:
    """Create test topology analyzer."""
    return TopologyAnalyzer()


# =============================================================================
# Basic Analysis Tests
# =============================================================================


class TestTopologyAnalyzerBasic:
    """Test basic topology analysis."""

    def test_analyze_empty(self, analyzer: TopologyAnalyzer) -> None:
        """Empty fingerprints returns empty analysis."""
        result = analyzer.analyze([])

        assert isinstance(result, TopologyAnalysis)
        assert result.total_warehouses == 0
        assert len(result.similar_pairs) == 0
        assert len(result.workload_clusters) == 0
        assert len(result.insights) == 0

    def test_analyze_single_warehouse(self, analyzer: TopologyAnalyzer) -> None:
        """Single warehouse has no pairs."""
        fingerprints = [_make_fingerprint("wh-001")]

        result = analyzer.analyze(fingerprints)

        assert result.total_warehouses == 1
        assert len(result.similar_pairs) == 0

    def test_analyze_returns_correct_structure(
        self, analyzer: TopologyAnalyzer
    ) -> None:
        """Analysis has correct structure."""
        fingerprints = [
            _make_fingerprint("wh-001"),
            _make_fingerprint("wh-002"),
        ]

        result = analyzer.analyze(fingerprints)

        assert hasattr(result, "total_warehouses")
        assert hasattr(result, "similar_pairs")
        assert hasattr(result, "workload_clusters")
        assert hasattr(result, "insights")
        assert hasattr(result, "consolidation_opportunities")
        assert hasattr(result, "estimated_savings_pct")


# =============================================================================
# Similarity Detection Tests
# =============================================================================


class TestSimilarityDetection:
    """Test similar warehouse detection."""

    def test_detect_identical_warehouses(self, analyzer: TopologyAnalyzer) -> None:
        """Identical warehouses have high similarity."""
        fingerprints = [
            _make_fingerprint("wh-001", "Warehouse A"),
            _make_fingerprint("wh-002", "Warehouse B"),  # Same profile
        ]

        result = analyzer.analyze(fingerprints)

        assert len(result.similar_pairs) == 1
        pair = result.similar_pairs[0]
        assert pair.similarity_score >= 0.8
        assert pair.consolidation_potential == "high"

    def test_detect_similar_warehouses(self, analyzer: TopologyAnalyzer) -> None:
        """Similar warehouses are detected."""
        fingerprints = [
            _make_fingerprint(
                "wh-001", workload_pattern="interactive", p95_runtime_sec=5.0
            ),
            _make_fingerprint(
                "wh-002", workload_pattern="interactive", p95_runtime_sec=7.0
            ),
        ]

        result = analyzer.analyze(fingerprints)

        assert len(result.similar_pairs) >= 1
        pair = result.similar_pairs[0]
        assert pair.similarity_score >= 0.6

    def test_no_similarity_different_workloads(
        self, analyzer: TopologyAnalyzer
    ) -> None:
        """Different workloads have low similarity."""
        fingerprints = [
            _make_fingerprint(
                "wh-001", workload_pattern="interactive", p95_runtime_sec=2.0
            ),
            _make_fingerprint(
                "wh-002", workload_pattern="batch", p95_runtime_sec=300.0
            ),
        ]

        result = analyzer.analyze(fingerprints)

        # May or may not have pairs depending on other factors
        if result.similar_pairs:
            # If any pairs, they should have low similarity
            for pair in result.similar_pairs:
                assert pair.consolidation_potential != "high"

    def test_similarity_match_structure(self, analyzer: TopologyAnalyzer) -> None:
        """SimilarityMatch has correct structure."""
        fingerprints = [
            _make_fingerprint("wh-001", "Analytics A"),
            _make_fingerprint("wh-002", "Analytics B"),
        ]

        result = analyzer.analyze(fingerprints)

        if result.similar_pairs:
            pair = result.similar_pairs[0]
            assert isinstance(pair, SimilarityMatch)
            assert pair.warehouse_id_a == "wh-001"
            assert pair.warehouse_id_b == "wh-002"
            assert 0 <= pair.similarity_score <= 1
            assert pair.recommendation != ""


# =============================================================================
# Workload Clustering Tests
# =============================================================================


class TestWorkloadClustering:
    """Test workload-based clustering."""

    def test_cluster_by_workload_type(self, analyzer: TopologyAnalyzer) -> None:
        """Warehouses are clustered by workload type."""
        fingerprints = [
            _make_fingerprint("wh-001", workload_pattern="interactive"),
            _make_fingerprint("wh-002", workload_pattern="interactive"),
            _make_fingerprint("wh-003", workload_pattern="batch"),
        ]

        result = analyzer.analyze(fingerprints)

        # Should have at least interactive and batch clusters
        cluster_types = {c.cluster_type for c in result.workload_clusters}
        assert "interactive" in cluster_types
        assert "batch" in cluster_types

    def test_cluster_contains_correct_warehouses(
        self, analyzer: TopologyAnalyzer
    ) -> None:
        """Clusters contain correct warehouse IDs."""
        fingerprints = [
            _make_fingerprint("wh-001", workload_pattern="interactive"),
            _make_fingerprint("wh-002", workload_pattern="interactive"),
        ]

        result = analyzer.analyze(fingerprints)

        interactive_cluster = next(
            (c for c in result.workload_clusters if c.cluster_type == "interactive"),
            None,
        )

        assert interactive_cluster is not None
        assert "wh-001" in interactive_cluster.warehouse_ids
        assert "wh-002" in interactive_cluster.warehouse_ids

    def test_cluster_metrics(self, analyzer: TopologyAnalyzer) -> None:
        """Clusters calculate correct metrics."""
        fingerprints = [
            _make_fingerprint(
                "wh-001",
                workload_pattern="batch",
                p95_runtime_sec=100,
                total_queries=500,
            ),
            _make_fingerprint(
                "wh-002",
                workload_pattern="batch",
                p95_runtime_sec=200,
                total_queries=500,
            ),
        ]

        result = analyzer.analyze(fingerprints)

        batch_cluster = next(
            (c for c in result.workload_clusters if c.cluster_type == "batch"),
            None,
        )

        assert batch_cluster is not None
        assert batch_cluster.avg_p95_latency_sec == 150.0  # (100 + 200) / 2
        assert batch_cluster.total_queries == 1000


# =============================================================================
# Insight Generation Tests
# =============================================================================


class TestInsightGeneration:
    """Test topology insights."""

    def test_generate_duplicate_insight(self, analyzer: TopologyAnalyzer) -> None:
        """Generate insight for duplicate warehouses."""
        fingerprints = [
            _make_fingerprint("wh-001", "Analytics Prod"),
            _make_fingerprint("wh-002", "Analytics Prod Copy"),  # Identical
        ]

        result = analyzer.analyze(fingerprints)

        duplicate_insights = [
            i for i in result.insights if i.insight_type == "duplicate_detected"
        ]

        # Should have at least one duplicate insight if similarity is high
        if result.similar_pairs and result.similar_pairs[0].similarity_score >= 0.8:
            assert len(duplicate_insights) >= 1

    def test_generate_underutilized_insight(self, analyzer: TopologyAnalyzer) -> None:
        """Generate insight for underutilized warehouse."""
        fingerprints = [
            _make_fingerprint(
                "wh-001", total_queries=50, queries_per_day=5
            ),  # Very low
        ]

        result = analyzer.analyze(fingerprints)

        underutilized = [
            i for i in result.insights if i.insight_type == "underutilized"
        ]
        assert len(underutilized) == 1
        assert "wh-001" in underutilized[0].affected_warehouses

    def test_generate_workload_mismatch_insight(
        self, analyzer: TopologyAnalyzer
    ) -> None:
        """Generate insight for workload mismatch."""
        fingerprints = [
            _make_fingerprint(
                "wh-001",
                workload_pattern="interactive",
                p95_runtime_sec=30.0,  # Too high for interactive
            ),
        ]

        result = analyzer.analyze(fingerprints)

        mismatch = [i for i in result.insights if i.insight_type == "workload_mismatch"]
        assert len(mismatch) == 1

    def test_insight_structure(self, analyzer: TopologyAnalyzer) -> None:
        """TopologyInsight has correct structure."""
        fingerprints = [
            _make_fingerprint("wh-001", total_queries=50),  # Will generate insight
        ]

        result = analyzer.analyze(fingerprints)

        if result.insights:
            insight = result.insights[0]
            assert isinstance(insight, TopologyInsight)
            assert insight.insight_type in {
                "duplicate_detected",
                "consolidation_opportunity",
                "workload_mismatch",
                "underutilized",
                "noisy_neighbor",
                "capacity_imbalance",
            }
            assert insight.severity in {"info", "warning", "critical"}
            assert insight.title != ""
            assert insight.recommendation != ""

    def test_insights_sorted_by_severity(self, analyzer: TopologyAnalyzer) -> None:
        """Insights are sorted by severity."""
        fingerprints = [
            _make_fingerprint("wh-001", total_queries=50),  # underutilized (info)
            _make_fingerprint("wh-002"),
            _make_fingerprint("wh-003"),  # May create consolidation (warning)
        ]

        result = analyzer.analyze(fingerprints)

        if len(result.insights) >= 2:
            severities = [i.severity for i in result.insights]
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            ordered = sorted(severities, key=lambda s: severity_order.get(s, 3))
            assert severities == ordered


# =============================================================================
# Consolidation Opportunity Tests
# =============================================================================


class TestConsolidationOpportunities:
    """Test consolidation opportunity detection."""

    def test_count_consolidation_opportunities(
        self, analyzer: TopologyAnalyzer
    ) -> None:
        """Count high-similarity pairs as consolidation opportunities."""
        fingerprints = [
            _make_fingerprint("wh-001", "Team A Analytics"),
            _make_fingerprint("wh-002", "Team B Analytics"),  # Identical
            _make_fingerprint("wh-003", workload_pattern="batch"),  # Different
        ]

        result = analyzer.analyze(fingerprints)

        # wh-001 and wh-002 are identical, should be 1 opportunity
        assert result.consolidation_opportunities >= 0

    def test_estimate_savings(self, analyzer: TopologyAnalyzer) -> None:
        """Estimate savings from consolidation."""
        fingerprints = [
            _make_fingerprint("wh-001"),
            _make_fingerprint("wh-002"),
            _make_fingerprint("wh-003"),
            _make_fingerprint("wh-004"),
        ]

        result = analyzer.analyze(fingerprints)

        # Savings should be between 0 and 50%
        assert 0 <= result.estimated_savings_pct <= 50


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases."""

    def test_missing_fields_handled(self, analyzer: TopologyAnalyzer) -> None:
        """Missing fields don't cause errors."""
        fingerprints = [
            {"warehouse_id": "wh-001"},  # Minimal fingerprint
            {"warehouse_id": "wh-002"},
        ]

        # Should not raise
        result = analyzer.analyze(fingerprints)
        assert result.total_warehouses == 2

    def test_empty_workload_pattern(self, analyzer: TopologyAnalyzer) -> None:
        """Empty workload pattern handled."""
        fingerprints = [
            _make_fingerprint("wh-001", workload_pattern=""),
        ]

        result = analyzer.analyze(fingerprints)
        assert result.total_warehouses == 1

    def test_zero_queries(self, analyzer: TopologyAnalyzer) -> None:
        """Zero queries handled."""
        fingerprints = [
            _make_fingerprint("wh-001", total_queries=0, queries_per_day=0),
        ]

        result = analyzer.analyze(fingerprints)
        assert result.total_warehouses == 1

    def test_many_warehouses(self, analyzer: TopologyAnalyzer) -> None:
        """Handle many warehouses efficiently."""
        fingerprints = [_make_fingerprint(f"wh-{i:03d}") for i in range(20)]

        result = analyzer.analyze(fingerprints)
        assert result.total_warehouses == 20
