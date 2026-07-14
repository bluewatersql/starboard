# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Warehouse topology analysis.

Domain logic for analyzing warehouse fleet topology including:
- Duplicate/similar warehouse detection
- Workload clustering
- Consolidation opportunities
- Noisy neighbor detection
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SimilarityMatch:
    """Match between two similar warehouses.

    Attributes:
        warehouse_id_a: First warehouse ID.
        warehouse_id_b: Second warehouse ID.
        warehouse_name_a: First warehouse name.
        warehouse_name_b: Second warehouse name.
        similarity_score: Overall similarity (0-1).
        workload_similarity: Workload pattern similarity.
        user_overlap_pct: Percentage of overlapping users.
        time_overlap_pct: Percentage of overlapping peak hours.
        consolidation_potential: Estimated savings from consolidation.
        recommendation: Suggested action.
    """

    warehouse_id_a: str
    warehouse_id_b: str
    warehouse_name_a: str
    warehouse_name_b: str
    similarity_score: float
    workload_similarity: float
    user_overlap_pct: float
    time_overlap_pct: float
    consolidation_potential: str
    recommendation: str


@dataclass(frozen=True)
class WorkloadCluster:
    """Cluster of warehouses with similar workloads.

    Attributes:
        cluster_id: Unique cluster identifier.
        cluster_type: Type of workload (interactive, batch, etc.).
        warehouse_ids: Warehouses in this cluster.
        warehouse_names: Names of warehouses.
        avg_p95_latency_sec: Average p95 latency across cluster.
        total_queries: Total queries across cluster.
        consolidation_candidate: Whether cluster is consolidation candidate.
    """

    cluster_id: str
    cluster_type: str
    warehouse_ids: tuple[str, ...]
    warehouse_names: tuple[str, ...]
    avg_p95_latency_sec: float
    total_queries: int
    consolidation_candidate: bool


@dataclass(frozen=True)
class TopologyInsight:
    """Single topology insight/finding.

    Attributes:
        insight_type: Category of insight.
        severity: Importance level.
        title: Short title.
        description: Detailed description.
        affected_warehouses: Warehouses involved.
        recommendation: Suggested action.
        estimated_impact: Potential benefit.
    """

    insight_type: Literal[
        "duplicate_detected",
        "consolidation_opportunity",
        "workload_mismatch",
        "underutilized",
        "noisy_neighbor",
        "capacity_imbalance",
    ]
    severity: Literal["info", "warning", "critical"]
    title: str
    description: str
    affected_warehouses: tuple[str, ...]
    recommendation: str
    estimated_impact: str


@dataclass(frozen=True)
class TopologyAnalysis:
    """Complete topology analysis result.

    Attributes:
        total_warehouses: Number of warehouses analyzed.
        similar_pairs: Detected similar warehouse pairs.
        workload_clusters: Warehouses grouped by workload type.
        insights: Topology insights and recommendations.
        consolidation_opportunities: Number of consolidation opportunities.
        estimated_savings_pct: Estimated cost savings from optimization.
    """

    total_warehouses: int
    similar_pairs: tuple[SimilarityMatch, ...]
    workload_clusters: tuple[WorkloadCluster, ...]
    insights: tuple[TopologyInsight, ...]
    consolidation_opportunities: int
    estimated_savings_pct: float


class TopologyAnalyzer:
    """Analyze warehouse fleet topology for optimization opportunities.

    Detects:
    - Similar/duplicate warehouses that could be consolidated
    - Workload patterns that suggest clustering opportunities
    - Underutilized warehouses
    - Capacity imbalances

    Example:
        ```python
        analyzer = TopologyAnalyzer()
        analysis = analyzer.analyze(warehouse_fingerprints)

        for insight in analysis.insights:
            if insight.severity == "critical":
                print(f"ACTION: {insight.recommendation}")
        ```
    """

    # Thresholds for similarity detection
    HIGH_SIMILARITY_THRESHOLD = 0.8
    MEDIUM_SIMILARITY_THRESHOLD = 0.6

    # Thresholds for workload classification
    INTERACTIVE_P95_THRESHOLD_SEC = 10.0
    BATCH_P95_THRESHOLD_SEC = 300.0

    # Underutilization thresholds
    LOW_QUERY_THRESHOLD = 100  # queries per week
    LOW_UTILIZATION_THRESHOLD = 0.1  # 10% avg utilization

    def analyze(
        self,
        fingerprints: list[dict[str, Any]],
    ) -> TopologyAnalysis:
        """Analyze warehouse topology from fingerprints.

        Args:
            fingerprints: List of warehouse fingerprints (as dicts).

        Returns:
            Complete topology analysis with insights.
        """
        if not fingerprints:
            return TopologyAnalysis(
                total_warehouses=0,
                similar_pairs=(),
                workload_clusters=(),
                insights=(),
                consolidation_opportunities=0,
                estimated_savings_pct=0.0,
            )

        # Find similar warehouses
        similar_pairs = self._find_similar_warehouses(fingerprints)

        # Cluster by workload type
        clusters = self._cluster_by_workload(fingerprints)

        # Generate insights
        insights = self._generate_insights(fingerprints, similar_pairs, clusters)

        # Count consolidation opportunities
        consolidation_count = len(
            [
                p
                for p in similar_pairs
                if p.similarity_score >= self.HIGH_SIMILARITY_THRESHOLD
            ]
        )

        # Estimate savings
        estimated_savings = self._estimate_savings(similar_pairs, fingerprints)

        return TopologyAnalysis(
            total_warehouses=len(fingerprints),
            similar_pairs=tuple(similar_pairs),
            workload_clusters=tuple(clusters),
            insights=tuple(insights),
            consolidation_opportunities=consolidation_count,
            estimated_savings_pct=round(estimated_savings, 1),
        )

    def _find_similar_warehouses(
        self,
        fingerprints: list[dict[str, Any]],
    ) -> list[SimilarityMatch]:
        """Find pairs of similar warehouses."""
        similar_pairs: list[SimilarityMatch] = []

        # Compare each pair
        for i, fp_a in enumerate(fingerprints):
            for fp_b in fingerprints[i + 1 :]:
                similarity = self._calculate_similarity(fp_a, fp_b)

                if similarity["overall"] >= self.MEDIUM_SIMILARITY_THRESHOLD:
                    # Determine consolidation potential
                    if similarity["overall"] >= self.HIGH_SIMILARITY_THRESHOLD:
                        potential = "high"
                        recommendation = (
                            "Consider consolidating these warehouses - "
                            "high similarity detected"
                        )
                    else:
                        potential = "medium"
                        recommendation = (
                            "Review for potential consolidation - "
                            "moderate similarity detected"
                        )

                    similar_pairs.append(
                        SimilarityMatch(
                            warehouse_id_a=fp_a.get("warehouse_id", ""),
                            warehouse_id_b=fp_b.get("warehouse_id", ""),
                            warehouse_name_a=fp_a.get("warehouse_name", ""),
                            warehouse_name_b=fp_b.get("warehouse_name", ""),
                            similarity_score=round(similarity["overall"], 2),
                            workload_similarity=round(similarity["workload"], 2),
                            user_overlap_pct=round(similarity["user_overlap"] * 100, 1),
                            time_overlap_pct=round(similarity["time_overlap"] * 100, 1),
                            consolidation_potential=potential,
                            recommendation=recommendation,
                        )
                    )

        # Sort by similarity score descending
        similar_pairs.sort(key=lambda p: p.similarity_score, reverse=True)
        return similar_pairs

    def _calculate_similarity(
        self,
        fp_a: dict[str, Any],
        fp_b: dict[str, Any],
    ) -> dict[str, float]:
        """Calculate similarity between two fingerprints."""
        # Workload pattern similarity
        pattern_a = fp_a.get("workload_pattern", {}).get("pattern_type", "")
        pattern_b = fp_b.get("workload_pattern", {}).get("pattern_type", "")
        workload_sim = 1.0 if pattern_a == pattern_b else 0.3

        # Query type distribution similarity
        dist_a = fp_a.get("query_type_distribution", {})
        dist_b = fp_b.get("query_type_distribution", {})
        type_sim = self._distribution_similarity(dist_a, dist_b)

        # Performance profile similarity (p95 within 2x)
        p95_a = fp_a.get("p95_runtime_sec", 0)
        p95_b = fp_b.get("p95_runtime_sec", 0)
        if p95_a > 0 and p95_b > 0:
            ratio = max(p95_a, p95_b) / max(min(p95_a, p95_b), 0.001)
            perf_sim = max(0, 1 - (ratio - 1) / 10)
        else:
            perf_sim = 0.5

        # Time overlap (peak hours)
        time_a = set(fp_a.get("time_distribution", {}).get("peak_hours", []))
        time_b = set(fp_b.get("time_distribution", {}).get("peak_hours", []))
        if time_a and time_b:
            time_overlap = len(time_a & time_b) / len(time_a | time_b)
        else:
            time_overlap = 0.5

        # User overlap (placeholder - would need user lists)
        # For now, estimate based on query volume similarity
        vol_a = fp_a.get("total_queries", 0)
        vol_b = fp_b.get("total_queries", 0)
        if vol_a > 0 and vol_b > 0:
            vol_ratio = min(vol_a, vol_b) / max(vol_a, vol_b)
            user_overlap = vol_ratio * 0.5  # Conservative estimate
        else:
            user_overlap = 0.0

        # Overall similarity (weighted average)
        overall = (
            workload_sim * 0.30
            + type_sim * 0.25
            + perf_sim * 0.20
            + time_overlap * 0.15
            + user_overlap * 0.10
        )

        return {
            "overall": overall,
            "workload": workload_sim,
            "query_type": type_sim,
            "performance": perf_sim,
            "time_overlap": time_overlap,
            "user_overlap": user_overlap,
        }

    def _distribution_similarity(
        self,
        dist_a: dict[str, float],
        dist_b: dict[str, float],
    ) -> float:
        """Calculate similarity between two distributions."""
        keys = {"select_pct", "insert_pct", "update_pct", "delete_pct"}
        total_diff = 0.0

        for key in keys:
            val_a = dist_a.get(key, 0)
            val_b = dist_b.get(key, 0)
            total_diff += abs(val_a - val_b)

        # Max possible difference is 200 (each could be 0 vs 100)
        return max(0, 1 - total_diff / 200)

    def _cluster_by_workload(
        self,
        fingerprints: list[dict[str, Any]],
    ) -> list[WorkloadCluster]:
        """Group warehouses by workload type."""
        clusters: dict[str, list[dict[str, Any]]] = {
            "interactive": [],
            "batch": [],
            "reporting": [],
            "mixed": [],
            "unknown": [],
        }

        for fp in fingerprints:
            pattern = fp.get("workload_pattern", {}).get("pattern_type", "unknown")
            if pattern in clusters:
                clusters[pattern].append(fp)
            else:
                clusters["mixed"].append(fp)

        result: list[WorkloadCluster] = []
        for cluster_type, members in clusters.items():
            if not members:
                continue

            warehouse_ids = tuple(fp.get("warehouse_id", "") for fp in members)
            warehouse_names = tuple(fp.get("warehouse_name", "") for fp in members)

            avg_p95 = sum(fp.get("p95_runtime_sec", 0) for fp in members) / len(members)
            total_queries = sum(fp.get("total_queries", 0) for fp in members)

            # Consolidation candidate if multiple similar warehouses
            consolidation_candidate = len(members) > 1 and cluster_type in (
                "interactive",
                "reporting",
            )

            result.append(
                WorkloadCluster(
                    cluster_id=f"cluster-{cluster_type}",
                    cluster_type=cluster_type,
                    warehouse_ids=warehouse_ids,
                    warehouse_names=warehouse_names,
                    avg_p95_latency_sec=round(avg_p95, 2),
                    total_queries=total_queries,
                    consolidation_candidate=consolidation_candidate,
                )
            )

        return result

    def _generate_insights(
        self,
        fingerprints: list[dict[str, Any]],
        similar_pairs: list[SimilarityMatch],
        clusters: list[WorkloadCluster],
    ) -> list[TopologyInsight]:
        """Generate topology insights from analysis."""
        insights: list[TopologyInsight] = []

        # Duplicate detection insights
        for pair in similar_pairs:
            if pair.similarity_score >= self.HIGH_SIMILARITY_THRESHOLD:
                insights.append(
                    TopologyInsight(
                        insight_type="duplicate_detected",
                        severity="warning",
                        title=f"Similar warehouses: {pair.warehouse_name_a} & {pair.warehouse_name_b}",
                        description=(
                            f"These warehouses have {pair.similarity_score:.0%} similarity "
                            f"in workload patterns and usage. User overlap: {pair.user_overlap_pct:.0f}%."
                        ),
                        affected_warehouses=(pair.warehouse_id_a, pair.warehouse_id_b),
                        recommendation=pair.recommendation,
                        estimated_impact="20-40% cost reduction if consolidated",
                    )
                )

        # Underutilization insights
        for fp in fingerprints:
            total_queries = fp.get("total_queries", 0)
            queries_per_day = fp.get("queries_per_day", 0)
            warehouse_id = fp.get("warehouse_id", "")
            warehouse_name = fp.get("warehouse_name", warehouse_id)

            if total_queries < self.LOW_QUERY_THRESHOLD:
                insights.append(
                    TopologyInsight(
                        insight_type="underutilized",
                        severity="info",
                        title=f"Underutilized warehouse: {warehouse_name}",
                        description=(
                            f"Only {total_queries} queries in the analysis period "
                            f"({queries_per_day:.1f}/day). Consider downsizing or consolidating."
                        ),
                        affected_warehouses=(warehouse_id,),
                        recommendation=(
                            "Review if this warehouse is still needed or can be merged"
                        ),
                        estimated_impact="Up to 100% cost savings if consolidated",
                    )
                )

        # Consolidation opportunity insights from clusters
        for cluster in clusters:
            if cluster.consolidation_candidate and len(cluster.warehouse_ids) > 2:
                insights.append(
                    TopologyInsight(
                        insight_type="consolidation_opportunity",
                        severity="warning",
                        title=f"Multiple {cluster.cluster_type} warehouses detected",
                        description=(
                            f"Found {len(cluster.warehouse_ids)} warehouses with "
                            f"{cluster.cluster_type} workload pattern. "
                            f"Consider consolidating to reduce overhead."
                        ),
                        affected_warehouses=cluster.warehouse_ids,
                        recommendation=(
                            f"Evaluate consolidating {cluster.cluster_type} warehouses "
                            "into fewer, larger instances"
                        ),
                        estimated_impact="15-30% cost reduction possible",
                    )
                )

        # Workload mismatch detection
        for fp in fingerprints:
            pattern = fp.get("workload_pattern", {}).get("pattern_type", "")
            p95 = fp.get("p95_runtime_sec", 0)
            warehouse_id = fp.get("warehouse_id", "")
            warehouse_name = fp.get("warehouse_name", warehouse_id)

            # Interactive warehouse with high latency
            if pattern == "interactive" and p95 > self.INTERACTIVE_P95_THRESHOLD_SEC:
                insights.append(
                    TopologyInsight(
                        insight_type="workload_mismatch",
                        severity="warning",
                        title=f"High latency for interactive warehouse: {warehouse_name}",
                        description=(
                            f"P95 latency is {p95:.1f}s but workload is interactive. "
                            f"Users may be experiencing slow response times."
                        ),
                        affected_warehouses=(warehouse_id,),
                        recommendation="Consider scaling up or optimizing queries",
                        estimated_impact="Improved user experience",
                    )
                )

        # Sort by severity
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        insights.sort(key=lambda i: severity_order.get(i.severity, 3))

        return insights

    def _estimate_savings(
        self,
        similar_pairs: list[SimilarityMatch],
        fingerprints: list[dict[str, Any]],
    ) -> float:
        """Estimate potential cost savings from consolidation."""
        if not fingerprints:
            return 0.0

        # Count warehouses that could potentially be consolidated
        consolidation_candidates = set()
        for pair in similar_pairs:
            if pair.similarity_score >= self.HIGH_SIMILARITY_THRESHOLD:
                consolidation_candidates.add(pair.warehouse_id_a)
                consolidation_candidates.add(pair.warehouse_id_b)

        if not consolidation_candidates:
            return 0.0

        # Estimate: each consolidation pair saves ~30% of the smaller warehouse
        savings_pct = (len(consolidation_candidates) / len(fingerprints)) * 30

        return min(savings_pct, 50.0)  # Cap at 50%
