"""Warehouse SLO configuration models.

Service Level Objective configuration and tracking for warehouses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SLOType = Literal[
    "p95_latency",  # 95th percentile query latency
    "p99_latency",  # 99th percentile query latency
    "availability",  # Percentage of time available
    "queue_time",  # Maximum acceptable queue time
    "error_rate",  # Maximum error percentage
]


@dataclass(frozen=True)
class SLOTarget:
    """Individual SLO target configuration.

    Attributes:
        slo_type: Type of SLO.
        target_value: Target value (interpretation depends on type).
        unit: Unit of measurement.
        warning_threshold: Value triggering warning state.
        critical_threshold: Value triggering critical state.
        enabled: Whether this SLO is actively tracked.
    """

    slo_type: SLOType
    target_value: float
    unit: str
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    enabled: bool = True

    def is_met(self, actual_value: float) -> bool:
        """Check if the SLO target is met.

        Args:
            actual_value: Actual measured value.

        Returns:
            True if target is met, False otherwise.
        """
        # For latency/queue_time/error_rate, lower is better
        if self.slo_type in ("p95_latency", "p99_latency", "queue_time", "error_rate"):
            return actual_value <= self.target_value
        # For availability, higher is better
        return actual_value >= self.target_value

    def get_status(
        self, actual_value: float
    ) -> Literal["healthy", "warning", "critical"]:
        """Get status based on actual value.

        Args:
            actual_value: Actual measured value.

        Returns:
            Status category.
        """
        is_lower_better = self.slo_type in (
            "p95_latency",
            "p99_latency",
            "queue_time",
            "error_rate",
        )

        if self.critical_threshold is not None:
            if is_lower_better and actual_value >= self.critical_threshold:
                return "critical"
            if not is_lower_better and actual_value <= self.critical_threshold:
                return "critical"

        if self.warning_threshold is not None:
            if is_lower_better and actual_value >= self.warning_threshold:
                return "warning"
            if not is_lower_better and actual_value <= self.warning_threshold:
                return "warning"

        if self.is_met(actual_value):
            return "healthy"

        return "warning"


@dataclass(frozen=True)
class SLOConfig:
    """Complete SLO configuration for a warehouse.

    Attributes:
        warehouse_id: Warehouse identifier.
        targets: Tuple of SLO targets.
        created_at: When the configuration was created.
        updated_at: When the configuration was last updated.
        created_by: User who created the configuration.
        notes: Optional notes about the configuration.
    """

    warehouse_id: str
    targets: tuple[SLOTarget, ...]
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    notes: str | None = None

    def get_target(self, slo_type: SLOType) -> SLOTarget | None:
        """Get a specific SLO target by type.

        Args:
            slo_type: Type of SLO to find.

        Returns:
            SLOTarget if found, None otherwise.
        """
        for target in self.targets:
            if target.slo_type == slo_type:
                return target
        return None

    @property
    def enabled_targets(self) -> tuple[SLOTarget, ...]:
        """Get only enabled SLO targets."""
        return tuple(t for t in self.targets if t.enabled)


# Default SLO configurations for common use cases
DEFAULT_INTERACTIVE_SLOS = (
    SLOTarget(
        slo_type="p95_latency",
        target_value=15.0,
        unit="seconds",
        warning_threshold=20.0,
        critical_threshold=30.0,
    ),
    SLOTarget(
        slo_type="availability",
        target_value=99.5,
        unit="percent",
        warning_threshold=99.0,
        critical_threshold=98.0,
    ),
    SLOTarget(
        slo_type="queue_time",
        target_value=5.0,
        unit="seconds",
        warning_threshold=10.0,
        critical_threshold=30.0,
    ),
)

DEFAULT_BATCH_SLOS = (
    SLOTarget(
        slo_type="p95_latency",
        target_value=300.0,  # 5 minutes
        unit="seconds",
        warning_threshold=600.0,
        critical_threshold=900.0,
    ),
    SLOTarget(
        slo_type="availability",
        target_value=99.0,
        unit="percent",
        warning_threshold=98.0,
        critical_threshold=95.0,
    ),
)
