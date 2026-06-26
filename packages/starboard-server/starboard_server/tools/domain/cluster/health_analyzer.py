# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Cluster health analyzer.

Pure functions for analyzing cluster health and identifying risks.
"""

from __future__ import annotations

from datetime import UTC, datetime

from starboard_core.domain.models.cluster import (
    ClusterFingerprint,
    ClusterHealthReport,
    ClusterType,
    HealthScore,
    RiskCategory,
    RiskIndicator,
    RiskSeverity,
)


def analyze_cluster_health(fingerprint: ClusterFingerprint) -> ClusterHealthReport:
    """Analyze cluster health from fingerprint.

    Pure function that examines a ClusterFingerprint and produces
    a health report with scores and identified risks.

    Args:
        fingerprint: ClusterFingerprint to analyze.

    Returns:
        ClusterHealthReport with health scores and risks.

    Example:
        >>> health = analyze_cluster_health(fingerprint)
        >>> print(f"Health: {health.scores.overall}")
        >>> for risk in health.high_priority_risks:
        ...     print(f"  - {risk.title}")
    """
    risks = identify_cluster_risks(fingerprint)
    scores = calculate_health_scores(fingerprint, risks)

    summary = _generate_summary(fingerprint, scores, risks)

    return ClusterHealthReport(
        cluster_id=fingerprint.cluster_id,
        cluster_name=fingerprint.cluster_name,
        generated_at=datetime.now(UTC),
        scores=scores,
        risks=risks,
        summary=summary,
    )


def calculate_health_scores(
    fingerprint: ClusterFingerprint,
    risks: list[RiskIndicator],
) -> HealthScore:
    """Calculate health scores from fingerprint and risks.

    Args:
        fingerprint: ClusterFingerprint to score.
        risks: List of identified risks.

    Returns:
        HealthScore with dimension scores.
    """
    # Start with perfect scores
    performance_score = 100.0
    cost_score = 100.0
    reliability_score = 100.0
    security_score = 100.0

    # Deduct points based on risks
    for risk in risks:
        deduction = _severity_to_deduction(risk.severity)

        if risk.category == RiskCategory.PERFORMANCE:
            performance_score = max(0, performance_score - deduction)
        elif risk.category == RiskCategory.COST:
            cost_score = max(0, cost_score - deduction)
        elif risk.category == RiskCategory.RELIABILITY:
            reliability_score = max(0, reliability_score - deduction)
        elif risk.category == RiskCategory.SECURITY:
            security_score = max(0, security_score - deduction)
        elif risk.category == RiskCategory.MAINTENANCE:
            # Maintenance issues affect reliability
            reliability_score = max(0, reliability_score - deduction)

    # Apply bonuses for good practices
    if fingerprint.runtime.is_lts:
        reliability_score = min(100, reliability_score + 5)

    if fingerprint.uses_spot:
        cost_score = min(100, cost_score + 10)

    if fingerprint.autoscaling_enabled:
        cost_score = min(100, cost_score + 5)
        performance_score = min(100, performance_score + 5)

    if fingerprint.pool_id:
        cost_score = min(100, cost_score + 5)
        performance_score = min(100, performance_score + 5)

    # Calculate overall as weighted average
    overall = (
        performance_score * 0.30
        + cost_score * 0.25
        + reliability_score * 0.30
        + security_score * 0.15
    )

    return HealthScore(
        overall=round(overall, 1),
        performance=round(performance_score, 1),
        cost=round(cost_score, 1),
        reliability=round(reliability_score, 1),
        security=round(security_score, 1),
    )


def identify_cluster_risks(fingerprint: ClusterFingerprint) -> list[RiskIndicator]:
    """Identify risks from cluster fingerprint.

    Args:
        fingerprint: ClusterFingerprint to analyze.

    Returns:
        List of identified RiskIndicators.
    """
    risks: list[RiskIndicator] = []

    # Runtime checks
    risks.extend(_check_runtime_risks(fingerprint))

    # Configuration checks
    risks.extend(_check_config_risks(fingerprint))

    # Performance checks (if metrics available)
    if fingerprint.performance:
        risks.extend(_check_performance_risks(fingerprint))

    # Cost checks (if cost data available)
    if fingerprint.cost:
        risks.extend(_check_cost_risks(fingerprint))

    return risks


def _check_runtime_risks(fingerprint: ClusterFingerprint) -> list[RiskIndicator]:
    """Check for runtime-related risks."""
    risks: list[RiskIndicator] = []

    if fingerprint.runtime.is_deprecated:
        risks.append(
            RiskIndicator(
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.CRITICAL,
                title="Deprecated runtime version",
                description=(
                    f"Cluster uses deprecated DBR version {fingerprint.runtime.dbr_version}. "
                    "Deprecated runtimes no longer receive security patches."
                ),
                impact="Security vulnerabilities may not be patched. Support is limited.",
                recommendation=(
                    "Upgrade to the latest LTS runtime version for continued security "
                    "updates and support."
                ),
            )
        )

    if not fingerprint.runtime.is_lts:
        risks.append(
            RiskIndicator(
                category=RiskCategory.MAINTENANCE,
                severity=RiskSeverity.LOW,
                title="Non-LTS runtime",
                description=(
                    f"Cluster uses non-LTS runtime {fingerprint.runtime.dbr_version}. "
                    "Non-LTS versions have shorter support windows."
                ),
                impact="More frequent upgrade cycles required.",
                recommendation="Consider switching to an LTS version for longer support.",
            )
        )

    return risks


def _check_config_risks(fingerprint: ClusterFingerprint) -> list[RiskIndicator]:
    """Check for configuration-related risks."""
    risks: list[RiskIndicator] = []

    # Single user mode check
    if (
        fingerprint.cluster_type == ClusterType.ALL_PURPOSE
        and not fingerprint.autoscaling_enabled
    ):
        risks.append(
            RiskIndicator(
                category=RiskCategory.COST,
                severity=RiskSeverity.MEDIUM,
                title="Fixed-size interactive cluster",
                description=(
                    "This all-purpose cluster has a fixed size without autoscaling. "
                    "Fixed-size clusters pay for capacity even during idle periods."
                ),
                impact="Paying for unused capacity during low-usage periods.",
                recommendation=(
                    "Enable autoscaling to automatically adjust capacity based on "
                    "workload demands."
                ),
            )
        )

    # Spot instance check
    if (
        not fingerprint.uses_spot
        and fingerprint.cluster_type != ClusterType.SINGLE_NODE
    ):
        risks.append(
            RiskIndicator(
                category=RiskCategory.COST,
                severity=RiskSeverity.LOW,
                title="Not using spot instances",
                description="Cluster is not configured to use spot instances.",
                impact="Potential cost savings of 40-80% not being realized.",
                recommendation=(
                    "Consider enabling spot instances for fault-tolerant workloads "
                    "to reduce costs."
                ),
            )
        )

    # Instance pool check
    if not fingerprint.pool_id and fingerprint.cluster_type == ClusterType.ALL_PURPOSE:
        risks.append(
            RiskIndicator(
                category=RiskCategory.PERFORMANCE,
                severity=RiskSeverity.LOW,
                title="Not using instance pool",
                description="Cluster does not use an instance pool.",
                impact="Longer startup times when scaling up or starting the cluster.",
                recommendation=(
                    "Consider using an instance pool to reduce cluster startup time "
                    "and ensure instance availability."
                ),
            )
        )

    # Access mode check
    if fingerprint.access_mode.value == "NO_ISOLATION":
        risks.append(
            RiskIndicator(
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.HIGH,
                title="No workload isolation",
                description="Cluster has no user isolation configured.",
                impact="Users may access each other's data and credentials.",
                recommendation=(
                    "Configure data_security_mode to USER_ISOLATION or SINGLE_USER "
                    "for Unity Catalog clusters."
                ),
            )
        )

    return risks


def _check_performance_risks(fingerprint: ClusterFingerprint) -> list[RiskIndicator]:
    """Check for performance-related risks from metrics."""
    risks: list[RiskIndicator] = []
    perf = fingerprint.performance

    if perf is None:
        return risks

    # Low CPU utilization indicates over-provisioning
    if perf.cpu_utilization_p50 is not None and perf.cpu_utilization_p50 < 20:
        risks.append(
            RiskIndicator(
                category=RiskCategory.COST,
                severity=RiskSeverity.MEDIUM,
                title="Low CPU utilization",
                description=(
                    f"Average CPU utilization is {perf.cpu_utilization_p50:.1f}%, "
                    "indicating the cluster may be over-provisioned."
                ),
                impact="Paying for unused compute capacity.",
                recommendation=(
                    "Consider reducing worker count or using smaller instance types."
                ),
            )
        )

    # High memory utilization indicates risk of OOM
    if perf.memory_utilization_p95 is not None and perf.memory_utilization_p95 > 90:
        risks.append(
            RiskIndicator(
                category=RiskCategory.PERFORMANCE,
                severity=RiskSeverity.HIGH,
                title="High memory pressure",
                description=(
                    f"P95 memory utilization is {perf.memory_utilization_p95:.1f}%, "
                    "indicating risk of out-of-memory errors."
                ),
                impact="Jobs may fail due to memory exhaustion.",
                recommendation=(
                    "Increase memory per node or add more workers to distribute load."
                ),
            )
        )

    # OOM events
    if perf.oom_events_30d is not None and perf.oom_events_30d > 0:
        severity = (
            RiskSeverity.CRITICAL
            if perf.oom_events_30d > 10
            else RiskSeverity.HIGH
            if perf.oom_events_30d > 3
            else RiskSeverity.MEDIUM
        )
        risks.append(
            RiskIndicator(
                category=RiskCategory.RELIABILITY,
                severity=severity,
                title="Out-of-memory events detected",
                description=(
                    f"{perf.oom_events_30d} out-of-memory events in the last 30 days."
                ),
                impact="Jobs are failing or restarting due to memory issues.",
                recommendation=(
                    "Increase memory allocation, optimize Spark memory settings, "
                    "or review job memory usage patterns."
                ),
            )
        )

    # High task failure rate
    if perf.task_failure_rate is not None and perf.task_failure_rate > 0.05:
        severity = (
            RiskSeverity.HIGH if perf.task_failure_rate > 0.15 else RiskSeverity.MEDIUM
        )
        risks.append(
            RiskIndicator(
                category=RiskCategory.RELIABILITY,
                severity=severity,
                title="High task failure rate",
                description=(
                    f"Task failure rate is {perf.task_failure_rate * 100:.1f}%."
                ),
                impact="Jobs are experiencing significant task retries.",
                recommendation=(
                    "Review Spark logs for root cause. Common issues include "
                    "spot instance interruptions, data skew, or resource contention."
                ),
            )
        )

    return risks


def _check_cost_risks(fingerprint: ClusterFingerprint) -> list[RiskIndicator]:
    """Check for cost-related risks from cost data."""
    risks: list[RiskIndicator] = []
    cost = fingerprint.cost

    if cost is None:
        return risks

    # High idle cost
    if cost.idle_cost_pct is not None and cost.idle_cost_pct > 30:
        severity = RiskSeverity.HIGH if cost.idle_cost_pct > 50 else RiskSeverity.MEDIUM
        risks.append(
            RiskIndicator(
                category=RiskCategory.COST,
                severity=severity,
                title="High idle cost",
                description=(
                    f"{cost.idle_cost_pct:.0f}% of cluster cost is from idle time."
                ),
                impact="Significant spend on unused resources.",
                recommendation=(
                    "Configure auto-termination, reduce idle timeout, "
                    "or use job clusters instead of all-purpose."
                ),
            )
        )

    return risks


def _severity_to_deduction(severity: RiskSeverity) -> float:
    """Convert risk severity to score deduction."""
    deductions = {
        RiskSeverity.LOW: 5,
        RiskSeverity.MEDIUM: 10,
        RiskSeverity.HIGH: 20,
        RiskSeverity.CRITICAL: 35,
    }
    return deductions.get(severity, 0)


def _generate_summary(
    fingerprint: ClusterFingerprint,
    scores: HealthScore,
    risks: list[RiskIndicator],
) -> str:
    """Generate human-readable summary."""
    parts = []

    # Overall health statement
    if scores.overall >= 80:
        parts.append(
            f"Cluster '{fingerprint.cluster_name}' is in good health "
            f"(score: {scores.overall:.0f}/100)."
        )
    elif scores.overall >= 60:
        parts.append(
            f"Cluster '{fingerprint.cluster_name}' has some issues to address "
            f"(score: {scores.overall:.0f}/100)."
        )
    else:
        parts.append(
            f"Cluster '{fingerprint.cluster_name}' needs attention "
            f"(score: {scores.overall:.0f}/100)."
        )

    # Count risks by severity
    critical_count = sum(1 for r in risks if r.severity == RiskSeverity.CRITICAL)
    high_count = sum(1 for r in risks if r.severity == RiskSeverity.HIGH)

    if critical_count > 0:
        parts.append(f"{critical_count} critical issue(s) require immediate attention.")
    if high_count > 0:
        parts.append(f"{high_count} high-priority issue(s) should be addressed soon.")

    # Key recommendations
    if (
        not fingerprint.autoscaling_enabled
        and fingerprint.cluster_type != ClusterType.SINGLE_NODE
    ):
        parts.append("Consider enabling autoscaling to optimize costs.")

    if fingerprint.runtime.is_deprecated:
        parts.append("Upgrade to a supported runtime version for security patches.")

    return " ".join(parts)
