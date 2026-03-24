"""Input validation models for compute tool operations.

These models serve as the boundary validation layer for LLM inputs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WarehouseConfigInput:
    """
    Input for fetching warehouse configuration.

    Attributes:
        warehouse_id: Target warehouse ID.

    Example:
        >>> WarehouseConfigInput(warehouse_id="abc123")
    """

    warehouse_id: str

    def __post_init__(self) -> None:
        """Validate warehouse_id is not empty."""
        if not self.warehouse_id or not self.warehouse_id.strip():
            raise ValueError("warehouse_id must not be empty")


@dataclass(frozen=True)
class WarehouseMetricsInput:
    """
    Input for fetching warehouse metrics.

    Attributes:
        warehouse_id: Target warehouse ID.

    Example:
        >>> WarehouseMetricsInput(warehouse_id="abc123")
    """

    warehouse_id: str

    def __post_init__(self) -> None:
        """Validate warehouse_id is not empty."""
        if not self.warehouse_id or not self.warehouse_id.strip():
            raise ValueError("warehouse_id must not be empty")


@dataclass(frozen=True)
class ClusterConfigInput:
    """
    Input for fetching cluster configuration.

    Attributes:
        cluster_id: Target cluster ID.

    Example:
        >>> ClusterConfigInput(cluster_id="abc123")
    """

    cluster_id: str

    def __post_init__(self) -> None:
        """Validate cluster_id is not empty."""
        if not self.cluster_id or not self.cluster_id.strip():
            raise ValueError("cluster_id must not be empty")


@dataclass(frozen=True)
class ClusterMetricsInput:
    """
    Input for fetching cluster metrics.

    Attributes:
        cluster_id: Target cluster ID.

    Example:
        >>> ClusterMetricsInput(cluster_id="abc123")
    """

    cluster_id: str

    def __post_init__(self) -> None:
        """Validate cluster_id is not empty."""
        if not self.cluster_id or not self.cluster_id.strip():
            raise ValueError("cluster_id must not be empty")


@dataclass(frozen=True)
class ClusterEventsInput:
    """
    Input for fetching cluster events.

    Attributes:
        cluster_id: Target cluster ID.

    Example:
        >>> ClusterEventsInput(cluster_id="abc123")
    """

    cluster_id: str

    def __post_init__(self) -> None:
        """Validate cluster_id is not empty."""
        if not self.cluster_id or not self.cluster_id.strip():
            raise ValueError("cluster_id must not be empty")


@dataclass(frozen=True)
class QueryRuntimeMetricsInput:
    """
    Input for fetching query runtime metrics.

    Attributes:
        statement_id: Statement ID to analyze.

    Example:
        >>> QueryRuntimeMetricsInput(statement_id="abc123")
    """

    statement_id: str

    def __post_init__(self) -> None:
        """Validate statement_id is not empty."""
        if not self.statement_id or not self.statement_id.strip():
            raise ValueError("statement_id must not be empty")


@dataclass(frozen=True)
class SparkLogsInput:
    """
    Input for fetching Spark logs.

    Attributes:
        cluster_id: Target cluster ID.
        max_runs: Maximum runs to fetch. Default: 1.

    Example:
        >>> SparkLogsInput(cluster_id="abc123", max_runs=3)
    """

    cluster_id: str
    max_runs: int = 1

    def __post_init__(self) -> None:
        """Validate inputs."""
        if not self.cluster_id or not self.cluster_id.strip():
            raise ValueError("cluster_id must not be empty")
        if self.max_runs < 1 or self.max_runs > 10:
            raise ValueError("max_runs must be between 1 and 10")
