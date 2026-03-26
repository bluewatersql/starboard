"""Cluster fingerprint models.

Detailed analysis models for Databricks cluster configuration and workload
characterization. Used by the Cluster Agent for optimization recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class ClusterType(StrEnum):
    """Databricks cluster type classification.

    Attributes:
        ALL_PURPOSE: Interactive all-purpose compute cluster.
        JOB: Job cluster created for automated workloads.
        SINGLE_NODE: Single-node cluster (driver only).
    """

    ALL_PURPOSE = "ALL_PURPOSE"
    JOB = "JOB"
    SINGLE_NODE = "SINGLE_NODE"


class ClusterMode(StrEnum):
    """Databricks cluster mode.

    Attributes:
        STANDARD: Standard cluster mode.
        HIGH_CONCURRENCY: High concurrency mode for shared access.
        SINGLE_NODE: Single node (no workers).
    """

    STANDARD = "STANDARD"
    HIGH_CONCURRENCY = "HIGH_CONCURRENCY"
    SINGLE_NODE = "SINGLE_NODE"


class AccessMode(StrEnum):
    """Databricks cluster access mode (Unity Catalog integration).

    Attributes:
        SINGLE_USER: Assigned to single user.
        USER_ISOLATION: Shared with user isolation.
        SHARED: Shared access mode.
        CUSTOM: Custom access mode.
        NO_ISOLATION: No isolation (legacy).
        UNKNOWN: Unknown access mode.
    """

    SINGLE_USER = "SINGLE_USER"
    USER_ISOLATION = "USER_ISOLATION"
    SHARED = "SHARED"
    CUSTOM = "CUSTOM"
    NO_ISOLATION = "NO_ISOLATION"
    UNKNOWN = "UNKNOWN"


class FingerprintScope(StrEnum):
    """Scope of fingerprint data to include.

    Use this to control what data is fetched for fingerprinting,
    avoiding expensive API calls when not needed.

    Attributes:
        CONFIG_ONLY: Only static configuration (fast, no metrics).
        WITH_METRICS: Include performance metrics (requires API calls).
        WITH_COST: Include cost data (requires billing access).
        FULL: All available data (slowest, most comprehensive).
    """

    CONFIG_ONLY = "config_only"
    WITH_METRICS = "with_metrics"
    WITH_COST = "with_cost"
    FULL = "full"


@dataclass(frozen=True)
class RuntimeConfig:
    """DBR runtime configuration.

    Attributes:
        dbr_version: Full DBR version string (e.g., "14.3.x-scala2.12").
        is_lts: Whether this is a long-term support version.
        is_ml: Whether this is an ML runtime.
        is_gpu: Whether GPU runtime is enabled.
        photon_enabled: Whether Photon is enabled.
        is_deprecated: Whether the runtime is deprecated.
        deprecation_date: When the runtime will be/was deprecated.
    """

    dbr_version: str
    is_lts: bool = False
    is_ml: bool = False
    is_gpu: bool = False
    photon_enabled: bool = False
    is_deprecated: bool = False
    deprecation_date: str | None = None


@dataclass(frozen=True)
class NodeConfig:
    """Cluster node configuration.

    Attributes:
        driver_node_type: Instance type for driver node.
        worker_node_type: Instance type for worker nodes.
        min_workers: Minimum workers (for autoscaling).
        max_workers: Maximum workers (for autoscaling).
        num_workers: Fixed worker count (non-autoscaling).
        use_spot_instances: Whether spot instances are used.
        first_on_demand: Number of on-demand instances before spot.
    """

    driver_node_type: str
    worker_node_type: str
    min_workers: int | None = None
    max_workers: int | None = None
    num_workers: int | None = None
    use_spot_instances: bool = False
    first_on_demand: int = 1


@dataclass(frozen=True)
class PerformanceProfile:
    """Observed cluster performance metrics.

    Optional metrics from monitoring data. All fields are optional
    since not all clusters have monitoring enabled.

    Attributes:
        cpu_utilization_p50: Median CPU utilization (0-100).
        cpu_utilization_p95: 95th percentile CPU utilization.
        memory_utilization_p50: Median memory utilization (0-100).
        memory_utilization_p95: 95th percentile memory utilization.
        oom_events_30d: Out-of-memory events in last 30 days.
        task_failure_rate: Task failure rate (0.0-1.0).
    """

    cpu_utilization_p50: float | None = None
    cpu_utilization_p95: float | None = None
    memory_utilization_p50: float | None = None
    memory_utilization_p95: float | None = None
    oom_events_30d: int | None = None
    task_failure_rate: float | None = None


@dataclass(frozen=True)
class CostProfile:
    """Cluster cost data.

    Requires billing data access. All fields optional since
    cost data may not be available in all environments.

    Attributes:
        dbu_total_30d: Total DBU consumption in last 30 days.
        cost_usd_total_30d: Total cost in USD for last 30 days.
        idle_cost_pct: Percentage of cost during idle time.
        spot_savings_pct: Percentage saved by using spot instances.
    """

    dbu_total_30d: float | None = None
    cost_usd_total_30d: float | None = None
    idle_cost_pct: float | None = None
    spot_savings_pct: float | None = None


@dataclass(frozen=True)
class ClusterFingerprint:
    """Comprehensive cluster fingerprint.

    A complete snapshot of cluster configuration and observed behavior.
    Used for optimization recommendations and fleet analysis.

    Attributes:
        fingerprint_version: Schema version for compatibility.
        generated_at: When the fingerprint was generated.
        cluster_id: Databricks cluster ID.
        cluster_name: Human-readable cluster name.
        cluster_type: Type classification (ALL_PURPOSE, JOB, etc.).
        cluster_mode: Operating mode.
        access_mode: Unity Catalog access mode.
        runtime: DBR runtime configuration.
        node_config: Node/worker configuration.
        performance: Performance metrics (optional).
        cost: Cost data (optional).
        autoscaling_enabled: Whether autoscaling is enabled.
        pool_id: Instance pool ID if using pools.
        tags: Custom tags on the cluster.

    Example:
        >>> fingerprint = ClusterFingerprint(
        ...     fingerprint_version="v1",
        ...     generated_at=datetime.now(UTC),
        ...     cluster_id="1201-090640-abc123",
        ...     cluster_name="analytics-cluster",
        ...     cluster_type=ClusterType.ALL_PURPOSE,
        ...     cluster_mode=ClusterMode.STANDARD,
        ...     access_mode=AccessMode.SINGLE_USER,
        ...     runtime=RuntimeConfig(dbr_version="14.3.x-scala2.12"),
        ...     node_config=NodeConfig(
        ...         driver_node_type="i3.xlarge",
        ...         worker_node_type="i3.xlarge",
        ...     ),
        ...     autoscaling_enabled=True,
        ...     tags={"team": "data"},
        ... )
    """

    fingerprint_version: Literal["v1"]
    generated_at: datetime
    cluster_id: str
    cluster_name: str
    cluster_type: ClusterType
    cluster_mode: ClusterMode
    access_mode: AccessMode
    runtime: RuntimeConfig
    node_config: NodeConfig
    performance: PerformanceProfile | None = None
    cost: CostProfile | None = None
    autoscaling_enabled: bool = False
    pool_id: str | None = None
    tags: dict[str, str] | None = None

    @property
    def is_job_cluster(self) -> bool:
        """Check if this is a job cluster."""
        return self.cluster_type == ClusterType.JOB

    @property
    def is_single_node(self) -> bool:
        """Check if this is a single-node cluster."""
        return (
            self.cluster_type == ClusterType.SINGLE_NODE
            or self.cluster_mode == ClusterMode.SINGLE_NODE
        )

    @property
    def uses_spot(self) -> bool:
        """Check if cluster uses spot instances."""
        return self.node_config.use_spot_instances

    @property
    def has_deprecated_runtime(self) -> bool:
        """Check if runtime is deprecated."""
        return self.runtime.is_deprecated
