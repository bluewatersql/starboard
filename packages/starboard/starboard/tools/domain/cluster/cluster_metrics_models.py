# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Domain models for cluster metrics data structures.

These dataclasses provide type-safe representations of cluster metadata,
resource summaries, and usage metrics for aggregation and analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ClusterMetadata:
    """Cluster configuration metadata.

    Attributes:
        cluster_id: Unique cluster identifier
        cluster_name: Human-readable cluster name
        cluster_source: Source of cluster (UI, API, job, etc.)
        dbr_version: Databricks Runtime version
        data_security_mode: Security mode (NONE, SINGLE_USER, etc.)
        enable_elastic_disk: Whether elastic disk is enabled
        node_type: Instance type (e.g., i3.xlarge)
        worker_count: Fixed number of workers (if not autoscaling)
        autoscale: Autoscale configuration (min/max workers)
        auto_termination_minutes: Minutes until auto-termination
    """

    cluster_id: str | None
    cluster_name: str | None
    cluster_source: str | None
    dbr_version: str | None
    data_security_mode: str | None
    enable_elastic_disk: bool | None
    node_type: str | None
    worker_count: int | None
    autoscale: dict[str, int | None]
    auto_termination_minutes: int | None


@dataclass
class ResourceSummary:
    """Aggregated resource summary for a role (driver/worker).

    Attributes:
        instances: Number of instances
        cores_total: Total CPU cores
        gpus_total: Total GPUs
        memory_total_GB: Total memory in GB
    """

    instances: int = 0
    cores_total: float = 0.0
    gpus_total: float = 0.0
    memory_total_GB: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with rounded values."""
        return {
            "instances": self.instances,
            "cores_total": round(self.cores_total, 2),
            "gpus_total": round(self.gpus_total, 2),
            "memory_total_GB": round(self.memory_total_GB, 2),
        }


@dataclass
class ComputeUsage:
    """Compute utilization metrics (CPU/memory) for a role.

    Attributes:
        cpu_total_avg: Average total CPU utilization (%)
        cpu_total_min: Minimum total CPU utilization (%)
        cpu_total_max: Maximum total CPU utilization (%)
        mem_used_avg: Average memory utilization (%)
        mem_used_min: Minimum memory utilization (%)
        mem_used_max: Maximum memory utilization (%)
    """

    cpu_total_avg: float = 0.0
    cpu_total_min: float = 0.0
    cpu_total_max: float = 0.0
    mem_used_avg: float = 0.0
    mem_used_min: float = 0.0
    mem_used_max: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary with rounded values (2 decimals)."""
        return {
            "cpu_total_avg": round(self.cpu_total_avg, 2),
            "cpu_total_min": round(self.cpu_total_min, 2),
            "cpu_total_max": round(self.cpu_total_max, 2),
            "mem_used_avg": round(self.mem_used_avg, 2),
            "mem_used_min": round(self.mem_used_min, 2),
            "mem_used_max": round(self.mem_used_max, 2),
        }


@dataclass
class NetworkUsage:
    """Network usage metrics.

    Attributes:
        sent_total: Total bytes sent (MB)
        received_total: Total bytes received (MB)
        total: Total network traffic (MB)
        sent_to_recv_ratio: Ratio of sent to received
    """

    sent_total: float = 0.0
    received_total: float = 0.0
    total: float = 0.0
    sent_to_recv_ratio: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary with rounded values (2 decimals)."""
        return {
            "sent_total": round(self.sent_total, 2),
            "received_total": round(self.received_total, 2),
            "total": round(self.total, 2),
            "sent_to_recv_ratio": round(self.sent_to_recv_ratio, 2),
        }


@dataclass
class DiskUsage:
    """Disk usage metrics.

    Attributes:
        total_free_avg: Average total free disk space (GB)
    """

    total_free_avg: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary with rounded values (2 decimals)."""
        return {"total_free_avg": round(self.total_free_avg, 2)}


@dataclass
class ClusterSummary:
    """Complete cluster summary with metadata, resources, and usage.

    Attributes:
        config: Cluster metadata
        resources: Resource summaries by role (driver/worker)
        usage: Usage metrics (compute, network, disk)
    """

    config: ClusterMetadata
    resources: dict[str, ResourceSummary]
    usage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "config": {
                "cluster_id": self.config.cluster_id,
                "cluster_name": self.config.cluster_name,
                "cluster_source": self.config.cluster_source,
                "dbr_version": self.config.dbr_version,
                "data_security_mode": self.config.data_security_mode,
                "enable_elastic_disk": self.config.enable_elastic_disk,
                "node_type": self.config.node_type,
                "worker_count": self.config.worker_count,
                "autoscale": self.config.autoscale,
                "auto_termination_minutes": self.config.auto_termination_minutes,
            },
            "resources": {role: res.to_dict() for role, res in self.resources.items()},
            "usage": self.usage,
        }
