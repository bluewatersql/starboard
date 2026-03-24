"""Warehouse chargeback calculation.

Domain logic for calculating cost allocation per user/team
based on warehouse usage metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class UserAllocation:
    """Cost allocation for a single user.

    Attributes:
        user_name: User identifier.
        total_queries: Number of queries executed.
        total_runtime_sec: Total query runtime in seconds.
        total_bytes_read: Total data scanned.
        usage_share_pct: Percentage of total warehouse usage.
        allocated_cost_usd: Allocated cost based on usage share.
    """

    user_name: str
    total_queries: int
    total_runtime_sec: float
    total_bytes_read: int
    usage_share_pct: float
    allocated_cost_usd: float


@dataclass(frozen=True)
class WarehouseChargeback:
    """Complete chargeback report for a warehouse.

    Attributes:
        warehouse_id: Warehouse identifier.
        warehouse_name: Human-readable name.
        period_start: Start of billing period.
        period_end: End of billing period.
        total_cost_usd: Total warehouse cost for period.
        allocations: Per-user cost allocations.
        allocation_method: Method used (runtime, queries, bytes).
    """

    warehouse_id: str
    warehouse_name: str
    period_start: datetime
    period_end: datetime
    total_cost_usd: float
    allocations: tuple[UserAllocation, ...]
    allocation_method: str


class ChargebackCalculator:
    """Calculate cost allocations for warehouse users.

    Allocates warehouse costs to users based on their usage share.
    Supports multiple allocation methods:
    - runtime: Allocate based on query runtime (default)
    - queries: Allocate based on query count
    - bytes: Allocate based on bytes processed

    Example:
        ```python
        calculator = ChargebackCalculator(
            warehouse_id="wh-001",
            warehouse_name="Analytics Warehouse",
            total_cost_usd=1500.0,
            period_start=datetime(2025, 1, 1),
            period_end=datetime(2025, 2, 1),
        )

        chargeback = calculator.calculate(user_activity_rows)
        for alloc in chargeback.allocations:
            print(f"{alloc.user_name}: ${alloc.allocated_cost_usd:.2f}")
        ```
    """

    def __init__(
        self,
        warehouse_id: str,
        warehouse_name: str,
        total_cost_usd: float,
        period_start: datetime,
        period_end: datetime,
        allocation_method: str = "runtime",
    ) -> None:
        """Initialize the calculator.

        Args:
            warehouse_id: Target warehouse.
            warehouse_name: Warehouse name.
            total_cost_usd: Total cost to allocate.
            period_start: Billing period start.
            period_end: Billing period end.
            allocation_method: How to allocate ("runtime", "queries", "bytes").
        """
        self.warehouse_id = warehouse_id
        self.warehouse_name = warehouse_name
        self.total_cost_usd = total_cost_usd
        self.period_start = period_start
        self.period_end = period_end
        self.allocation_method = allocation_method

    def calculate(
        self,
        user_activity: list[dict[str, Any]],
    ) -> WarehouseChargeback:
        """Calculate cost allocations from user activity data.

        Args:
            user_activity: List of user activity rows from query template.
                Expected fields: user_name, total_queries, total_runtime_sec,
                total_bytes_read, usage_share_pct

        Returns:
            Complete WarehouseChargeback with per-user allocations.
        """
        if not user_activity:
            return WarehouseChargeback(
                warehouse_id=self.warehouse_id,
                warehouse_name=self.warehouse_name,
                period_start=self.period_start,
                period_end=self.period_end,
                total_cost_usd=self.total_cost_usd,
                allocations=(),
                allocation_method=self.allocation_method,
            )

        # Calculate total for allocation method
        total_metric = self._calculate_total_metric(user_activity)

        # Calculate per-user allocations
        allocations: list[UserAllocation] = []
        for row in user_activity:
            user_metric = self._get_user_metric(row)
            share_pct = (user_metric / total_metric * 100) if total_metric > 0 else 0
            allocated_cost = self.total_cost_usd * (share_pct / 100)

            allocations.append(
                UserAllocation(
                    user_name=str(row.get("user_name", "unknown")),
                    total_queries=int(row.get("total_queries", 0)),
                    total_runtime_sec=float(row.get("total_runtime_sec", 0)),
                    total_bytes_read=int(row.get("total_bytes_read", 0)),
                    usage_share_pct=round(share_pct, 2),
                    allocated_cost_usd=round(allocated_cost, 2),
                )
            )

        # Sort by allocated cost descending
        allocations.sort(key=lambda a: a.allocated_cost_usd, reverse=True)

        return WarehouseChargeback(
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            period_start=self.period_start,
            period_end=self.period_end,
            total_cost_usd=self.total_cost_usd,
            allocations=tuple(allocations),
            allocation_method=self.allocation_method,
        )

    def _calculate_total_metric(self, user_activity: list[dict[str, Any]]) -> float:
        """Calculate total for the allocation method."""
        if self.allocation_method == "queries":
            return sum(int(row.get("total_queries", 0)) for row in user_activity)
        elif self.allocation_method == "bytes":
            return sum(int(row.get("total_bytes_read", 0)) for row in user_activity)
        else:  # runtime (default)
            return sum(float(row.get("total_runtime_sec", 0)) for row in user_activity)

    def _get_user_metric(self, row: dict[str, Any]) -> float:
        """Get the metric value for a user based on allocation method."""
        if self.allocation_method == "queries":
            return float(row.get("total_queries", 0))
        elif self.allocation_method == "bytes":
            return float(row.get("total_bytes_read", 0))
        else:  # runtime (default)
            return float(row.get("total_runtime_sec", 0))


@dataclass(frozen=True)
class PortfolioChargeback:
    """Chargeback report across all warehouses.

    Attributes:
        period_start: Start of billing period.
        period_end: End of billing period.
        total_cost_usd: Total cost across all warehouses.
        warehouse_chargebacks: Per-warehouse chargeback reports.
        user_summary: Aggregated cost per user across all warehouses.
    """

    period_start: datetime
    period_end: datetime
    total_cost_usd: float
    warehouse_chargebacks: tuple[WarehouseChargeback, ...]
    user_summary: tuple[UserAllocation, ...]


def aggregate_user_chargebacks(
    chargebacks: list[WarehouseChargeback],
) -> tuple[UserAllocation, ...]:
    """Aggregate user allocations across multiple warehouses.

    Args:
        chargebacks: List of per-warehouse chargebacks.

    Returns:
        Aggregated allocations per user across all warehouses.
    """
    user_totals: dict[str, dict[str, float]] = {}

    for cb in chargebacks:
        for alloc in cb.allocations:
            if alloc.user_name not in user_totals:
                user_totals[alloc.user_name] = {
                    "total_queries": 0,
                    "total_runtime_sec": 0,
                    "total_bytes_read": 0,
                    "allocated_cost_usd": 0,
                }

            user_totals[alloc.user_name]["total_queries"] += alloc.total_queries
            user_totals[alloc.user_name]["total_runtime_sec"] += alloc.total_runtime_sec
            user_totals[alloc.user_name]["total_bytes_read"] += alloc.total_bytes_read
            user_totals[alloc.user_name]["allocated_cost_usd"] += (
                alloc.allocated_cost_usd
            )

    # Calculate total for percentage
    total_cost = sum(t["allocated_cost_usd"] for t in user_totals.values())

    # Build allocations
    allocations = [
        UserAllocation(
            user_name=user,
            total_queries=int(totals["total_queries"]),
            total_runtime_sec=totals["total_runtime_sec"],
            total_bytes_read=int(totals["total_bytes_read"]),
            usage_share_pct=(
                round(totals["allocated_cost_usd"] / total_cost * 100, 2)
                if total_cost > 0
                else 0
            ),
            allocated_cost_usd=round(totals["allocated_cost_usd"], 2),
        )
        for user, totals in user_totals.items()
    ]

    # Sort by cost
    allocations.sort(key=lambda a: a.allocated_cost_usd, reverse=True)

    return tuple(allocations)
