"""Warehouse health models.

Health scoring and risk assessment for warehouses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RiskFactor:
    """Individual risk factor affecting warehouse health.

    Attributes:
        factor_id: Unique identifier for the risk factor.
        name: Human-readable name.
        description: Detailed description.
        severity: Risk severity level.
        impact_score: Numeric impact on health score (0-100).
        recommendation: Suggested action to mitigate.
    """

    factor_id: str
    name: str
    description: str
    severity: Literal["low", "medium", "high", "critical"]
    impact_score: float
    recommendation: str


@dataclass(frozen=True)
class SLOStatus:
    """Status of a specific SLO.

    Attributes:
        slo_type: Type of SLO being tracked.
        target: Target value.
        actual: Actual measured value.
        compliant: Whether the SLO is currently met.
        compliance_pct: Percentage of time in compliance.
        trend: Recent trend direction.
    """

    slo_type: str  # e.g., "p95_latency", "availability", "queue_time"
    target: float
    actual: float
    compliant: bool
    compliance_pct: float
    trend: Literal["improving", "stable", "degrading"]


@dataclass(frozen=True)
class HealthSummary:
    """Complete health summary for a warehouse.

    Attributes:
        warehouse_id: Warehouse identifier.
        warehouse_name: Human-readable name.

        # Overall health
        health_score: Overall health score (0-100).
        health_status: Categorical status.
        health_trend: Recent health trend.

        # SLO compliance
        slo_statuses: Status of configured SLOs.
        overall_slo_compliance: Aggregate SLO compliance percentage.

        # Risk factors
        risk_factors: Active risk factors.
        risk_level: Aggregate risk level.

        # Recommendations
        immediate_actions: Urgent recommended actions.
        optimization_opportunities: Non-urgent improvements.
    """

    warehouse_id: str
    warehouse_name: str

    # Overall health
    health_score: float
    health_status: Literal["healthy", "warning", "critical", "inactive", "unknown"]
    health_trend: Literal["improving", "stable", "degrading"]

    # SLO compliance
    slo_statuses: tuple[SLOStatus, ...]
    overall_slo_compliance: float

    # Risk factors
    risk_factors: tuple[RiskFactor, ...]
    risk_level: Literal["low", "medium", "high", "critical"]

    # Recommendations
    immediate_actions: tuple[str, ...]
    optimization_opportunities: tuple[str, ...]

    @property
    def is_healthy(self) -> bool:
        """Check if warehouse is in healthy state."""
        return self.health_status == "healthy"

    @property
    def needs_attention(self) -> bool:
        """Check if warehouse needs immediate attention."""
        return self.health_status in ("warning", "critical")

    @property
    def has_slo_violations(self) -> bool:
        """Check if any SLOs are violated."""
        return any(not s.compliant for s in self.slo_statuses)
