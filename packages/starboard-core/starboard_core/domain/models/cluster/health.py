"""Cluster health assessment models.

Models for cluster health scoring and risk identification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RiskSeverity(StrEnum):
    """Risk severity levels.

    Attributes:
        LOW: Minor issue, no immediate action required.
        MEDIUM: Should be addressed in regular maintenance.
        HIGH: Significant issue, prioritize resolution.
        CRITICAL: Immediate attention required.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskCategory(StrEnum):
    """Risk category classification.

    Attributes:
        PERFORMANCE: Performance-related risk.
        COST: Cost optimization opportunity.
        RELIABILITY: Reliability/stability risk.
        SECURITY: Security-related risk.
        MAINTENANCE: Maintenance/upgrade needed.
    """

    PERFORMANCE = "PERFORMANCE"
    COST = "COST"
    RELIABILITY = "RELIABILITY"
    SECURITY = "SECURITY"
    MAINTENANCE = "MAINTENANCE"


@dataclass(frozen=True)
class HealthScore:
    """Health scores by dimension.

    Each score is 0-100 where 100 is optimal health.

    Attributes:
        overall: Overall weighted health score.
        performance: Performance health (utilization, latency).
        cost: Cost efficiency score.
        reliability: Reliability score (error rates, uptime).
        security: Security posture score.

    Example:
        >>> scores = HealthScore(
        ...     overall=75,
        ...     performance=80,
        ...     cost=60,
        ...     reliability=85,
        ...     security=90,
        ... )
    """

    overall: float
    performance: float = 100.0
    cost: float = 100.0
    reliability: float = 100.0
    security: float = 100.0

    def __post_init__(self) -> None:
        """Validate scores are in valid range."""
        for score_name in ["overall", "performance", "cost", "reliability", "security"]:
            score = getattr(self, score_name)
            if not 0 <= score <= 100:
                raise ValueError(f"{score_name} must be between 0 and 100, got {score}")


@dataclass(frozen=True)
class RiskIndicator:
    """Identified risk or optimization opportunity.

    Attributes:
        category: Risk category (PERFORMANCE, COST, etc.).
        severity: Severity level (LOW to CRITICAL).
        title: Short title for the risk.
        description: Detailed description of the risk.
        impact: Description of the impact if not addressed.
        recommendation: Suggested action to mitigate.

    Example:
        >>> risk = RiskIndicator(
        ...     category=RiskCategory.PERFORMANCE,
        ...     severity=RiskSeverity.MEDIUM,
        ...     title="Low CPU utilization",
        ...     description="Average CPU utilization is 15%, indicating over-provisioning.",
        ...     impact="Paying for unused compute capacity.",
        ...     recommendation="Consider reducing worker count or using smaller instances.",
        ... )
    """

    category: RiskCategory
    severity: RiskSeverity
    title: str
    description: str
    impact: str
    recommendation: str


@dataclass(frozen=True)
class ClusterHealthReport:
    """Comprehensive cluster health assessment.

    Combines health scores with identified risks and recommendations.

    Attributes:
        cluster_id: Databricks cluster ID.
        cluster_name: Human-readable cluster name.
        generated_at: When the report was generated.
        scores: Health scores by dimension.
        risks: List of identified risks.
        summary: Optional summary text.

    Example:
        >>> report = ClusterHealthReport(
        ...     cluster_id="1201-090640-abc123",
        ...     cluster_name="analytics-cluster",
        ...     generated_at=datetime.now(UTC),
        ...     scores=HealthScore(overall=75, cost=60),
        ...     risks=[
        ...         RiskIndicator(
        ...             category=RiskCategory.COST,
        ...             severity=RiskSeverity.MEDIUM,
        ...             title="Over-provisioned cluster",
        ...             ...
        ...         )
        ...     ],
        ... )
    """

    cluster_id: str
    cluster_name: str
    generated_at: datetime
    scores: HealthScore
    risks: list[RiskIndicator] = field(default_factory=list)
    summary: str | None = None

    @property
    def health_status(self) -> str:
        """Get categorical health status based on overall score."""
        if self.scores.overall >= 80:
            return "healthy"
        elif self.scores.overall >= 60:
            return "warning"
        elif self.scores.overall >= 40:
            return "critical"
        else:
            return "critical"

    @property
    def critical_risks(self) -> list[RiskIndicator]:
        """Get only critical severity risks."""
        return [r for r in self.risks if r.severity == RiskSeverity.CRITICAL]

    @property
    def high_priority_risks(self) -> list[RiskIndicator]:
        """Get critical and high severity risks."""
        return [
            r
            for r in self.risks
            if r.severity in (RiskSeverity.CRITICAL, RiskSeverity.HIGH)
        ]
