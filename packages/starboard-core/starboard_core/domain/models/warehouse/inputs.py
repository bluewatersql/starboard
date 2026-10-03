# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Domain input models for warehouse operations.

Provides validated input models for warehouse tool operations.
These models serve as the boundary validation layer for LLM inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class WarehousePortfolioInput:
    """
    Input for warehouse portfolio retrieval.

    Attributes:
        window_days: Analysis window in days (7, 30, or 90).
        include_inactive: Whether to include warehouses with no recent activity.

    Example:
        >>> WarehousePortfolioInput(window_days=30, include_inactive=True)
    """

    window_days: Literal[7, 30, 90] = 7
    include_inactive: bool = False


@dataclass(frozen=True)
class WarehouseFingerprintInput:
    """
    Input for warehouse fingerprint generation.

    Attributes:
        warehouse_id: Target warehouse ID.
        window_days: Analysis window in days (7, 30, or 90).

    Example:
        >>> WarehouseFingerprintInput(warehouse_id="abc123", window_days=7)
    """

    warehouse_id: str
    window_days: Literal[7, 30, 90] = 7

    def __post_init__(self) -> None:
        """Validate warehouse_id is not empty."""
        if not self.warehouse_id or not self.warehouse_id.strip():
            raise ValueError("warehouse_id must not be empty")


@dataclass(frozen=True)
class WarehouseHealthInput:
    """
    Input for warehouse health scoring.

    Attributes:
        warehouse_id: Target warehouse ID.
        window_days: Analysis window in days (7, 30, or 90).

    Example:
        >>> WarehouseHealthInput(warehouse_id="abc123")
    """

    warehouse_id: str
    window_days: Literal[7, 30, 90] = 7

    def __post_init__(self) -> None:
        """Validate warehouse_id is not empty."""
        if not self.warehouse_id or not self.warehouse_id.strip():
            raise ValueError("warehouse_id must not be empty")


@dataclass(frozen=True)
class WarehouseSLOConfigInput:
    """
    Input for configuring warehouse SLO targets.

    Attributes:
        warehouse_id: Target warehouse ID.
        profile: SLO profile type (interactive, batch, or custom).
        p95_latency_ms: Target p95 latency in ms (for custom profile).
        availability_pct: Target availability percentage (for custom profile).

    Example:
        >>> WarehouseSLOConfigInput(warehouse_id="abc123", profile="interactive")
    """

    warehouse_id: str
    profile: Literal["interactive", "batch", "custom"] = "interactive"
    p95_latency_ms: int | None = None
    availability_pct: float | None = None

    def __post_init__(self) -> None:
        """Validate inputs."""
        if not self.warehouse_id or not self.warehouse_id.strip():
            raise ValueError("warehouse_id must not be empty")

        if self.profile == "custom":
            if self.p95_latency_ms is None:
                raise ValueError("p95_latency_ms required for custom profile")
            if self.availability_pct is None:
                raise ValueError("availability_pct required for custom profile")


@dataclass(frozen=True)
class WarehouseUserActivityInput:
    """
    Input for warehouse user activity analysis.

    Attributes:
        warehouse_id: Target warehouse ID.
        window_days: Analysis window in days (7, 30, or 90).

    Example:
        >>> WarehouseUserActivityInput(warehouse_id="abc123", window_days=30)
    """

    warehouse_id: str
    window_days: Literal[7, 30, 90] = 7

    def __post_init__(self) -> None:
        """Validate warehouse_id is not empty."""
        if not self.warehouse_id or not self.warehouse_id.strip():
            raise ValueError("warehouse_id must not be empty")


@dataclass(frozen=True)
class WarehouseChargebackInput:
    """
    Input for warehouse chargeback report generation.

    Attributes:
        warehouse_id: Target warehouse ID.
        window_days: Analysis window in days (7, 30, or 90).
        cost_per_dbu: Cost per DBU for calculation.
        allocation_method: How to allocate costs (runtime, queries, bytes).

    Example:
        >>> WarehouseChargebackInput(
        ...     warehouse_id="abc123",
        ...     cost_per_dbu=0.22
        ... )
    """

    warehouse_id: str
    window_days: Literal[7, 30, 90] = 7
    cost_per_dbu: float = 0.22
    allocation_method: Literal["runtime", "queries", "bytes"] = "runtime"

    def __post_init__(self) -> None:
        """Validate inputs."""
        if not self.warehouse_id or not self.warehouse_id.strip():
            raise ValueError("warehouse_id must not be empty")
        if self.cost_per_dbu <= 0:
            raise ValueError("cost_per_dbu must be positive")


@dataclass(frozen=True)
class PortfolioChargebackInput:
    """
    Input for portfolio-wide chargeback report generation.

    Attributes:
        window_days: Analysis window in days (7, 30, or 90).
        cost_per_dbu: Cost per DBU for calculation.
        allocation_method: How to allocate costs (runtime, queries, bytes).

    Example:
        >>> PortfolioChargebackInput(window_days=30, cost_per_dbu=0.22)
    """

    window_days: Literal[7, 30, 90] = 7
    cost_per_dbu: float = 0.22
    allocation_method: Literal["runtime", "queries", "bytes"] = "runtime"

    def __post_init__(self) -> None:
        """Validate inputs."""
        if self.cost_per_dbu <= 0:
            raise ValueError("cost_per_dbu must be positive")


@dataclass(frozen=True)
class WarehouseTopologyInput:
    """
    Input for warehouse topology analysis.

    Attributes:
        similarity_threshold: Minimum similarity score (0.0-1.0) for overlap.
        min_cluster_size: Minimum warehouses per cluster.

    Example:
        >>> WarehouseTopologyInput(similarity_threshold=0.7)
    """

    similarity_threshold: float = 0.7
    min_cluster_size: int = 2

    def __post_init__(self) -> None:
        """Validate inputs."""
        if not 0.0 <= self.similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between 0.0 and 1.0")
        if self.min_cluster_size < 2:
            raise ValueError("min_cluster_size must be at least 2")
