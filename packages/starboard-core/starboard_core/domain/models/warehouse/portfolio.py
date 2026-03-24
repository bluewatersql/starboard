"""Warehouse portfolio models.

Portfolio-level views and summaries for warehouse fleet management.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class WarehouseSummary:
    """Summary metrics for a single warehouse.

    Attributes:
        warehouse_id: Warehouse identifier.
        warehouse_name: Human-readable name.
        warehouse_type: Warehouse type (standard/serverless).
        state: Current state.

        # Configuration
        min_clusters: Minimum cluster count (standard only).
        max_clusters: Maximum cluster count (standard only).
        auto_stop_mins: Auto-stop timeout in minutes.

        # Metrics
        health_score: Current health score (0-100).
        monthly_cost_usd: Estimated monthly cost.
        total_queries_7d: Query count in last 7 days.
        avg_runtime_sec: Average query runtime.
    """

    warehouse_id: str
    warehouse_name: str
    warehouse_type: Literal["standard", "serverless"]
    state: Literal["RUNNING", "STOPPED", "STARTING", "STOPPING", "DELETED"]

    # Configuration
    min_clusters: int | None
    max_clusters: int | None
    auto_stop_mins: int

    # Metrics
    health_score: float
    monthly_cost_usd: float
    total_queries_7d: int
    avg_runtime_sec: float


@dataclass(frozen=True)
class WarehouseInfo:
    """Detailed information for a warehouse.

    Attributes:
        warehouse_id: Warehouse identifier.
        warehouse_name: Human-readable name.
        warehouse_type: Warehouse type.
        creator: User who created the warehouse.
        created_at: Creation timestamp.

        # Configuration
        cluster_size: Cluster size (e.g., "2X-Small", "Large").
        min_clusters: Minimum cluster count.
        max_clusters: Maximum cluster count.
        auto_stop_mins: Auto-stop timeout.
        spot_instance_policy: Spot instance configuration.
        enable_serverless_compute: Serverless flag.

        # Current state
        state: Current operational state.
        num_active_sessions: Active sessions.
        num_clusters: Current running clusters.
    """

    warehouse_id: str
    warehouse_name: str
    warehouse_type: Literal["standard", "serverless"]
    creator: str | None
    created_at: datetime | None

    # Configuration
    cluster_size: str
    min_clusters: int | None
    max_clusters: int | None
    auto_stop_mins: int
    spot_instance_policy: str | None
    enable_serverless_compute: bool

    # Current state
    state: Literal["RUNNING", "STOPPED", "STARTING", "STOPPING", "DELETED"]
    num_active_sessions: int
    num_clusters: int


@dataclass(frozen=True)
class WarehousePortfolio:
    """Complete portfolio view of all warehouses.

    Attributes:
        warehouses: List of warehouse summaries.
        total_monthly_cost_usd: Total monthly cost across all warehouses.
        total_warehouses: Total warehouse count.
        running_count: Warehouses currently running.
        stopped_count: Warehouses currently stopped.
        healthy_count: Warehouses in healthy state.
        warning_count: Warehouses in warning state.
        critical_count: Warehouses in critical state.
        portfolio_health_score: Aggregate portfolio health.
        analyzed_at: When the portfolio was analyzed.
    """

    warehouses: tuple[WarehouseSummary, ...]
    total_monthly_cost_usd: float
    total_warehouses: int
    running_count: int
    stopped_count: int
    healthy_count: int
    warning_count: int
    critical_count: int
    portfolio_health_score: float
    analyzed_at: datetime

    @property
    def healthy_pct(self) -> float:
        """Calculate percentage of healthy warehouses."""
        if self.total_warehouses == 0:
            return 100.0
        return (self.healthy_count / self.total_warehouses) * 100

    @property
    def needs_attention_count(self) -> int:
        """Count warehouses needing attention."""
        return self.warning_count + self.critical_count
