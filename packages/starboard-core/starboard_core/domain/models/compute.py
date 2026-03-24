"""Domain models for compute operations.

Pure domain models for cluster and warehouse identification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClusterIdentifier:
    """Identifier for a compute cluster."""

    cluster_id: str


@dataclass(frozen=True)
class WarehouseIdentifier:
    """Identifier for a SQL warehouse."""

    warehouse_id: str


@dataclass(frozen=True)
class ClusterLogConfig:
    """Configuration for cluster logging."""

    cluster_id: str
    log_destination: str | None


@dataclass(frozen=True)
class JobClusterInfo:
    """Information about a job cluster."""

    cluster_id: str
    timestamp: str | None = None
    metadata: dict[str, Any] | None = None
