# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Cluster domain logic.

Domain functions for cluster analysis, fingerprinting, and health assessment.
"""

from starboard_core.domain.models.compute import (
    ClusterIdentifier,
    ClusterLogConfig,
    JobClusterInfo,
    WarehouseIdentifier,
)

from starboard.tools.domain.cluster.cluster_metrics_analyzer import (
    ClusterMetricsAnalyzer,
)
from starboard.tools.domain.cluster.cluster_metrics_models import (
    ClusterMetadata,
    ClusterSummary,
    ComputeUsage,
    DiskUsage,
    NetworkUsage,
    ResourceSummary,
)

# New fingerprint and health analysis
from starboard.tools.domain.cluster.fingerprint_builder import (
    build_cluster_fingerprint,
)
from starboard.tools.domain.cluster.health_analyzer import (
    analyze_cluster_health,
    calculate_health_scores,
    identify_cluster_risks,
)
from starboard.tools.domain.cluster.resolver import ComputeResolver
from starboard.tools.domain.cluster.transformers import (
    transform_cluster_config,
    transform_cluster_events,
    transform_job_run_clusters,
)

__all__ = [
    # Analyzers
    "ClusterMetricsAnalyzer",
    # Models
    "ClusterIdentifier",
    "ClusterLogConfig",
    "JobClusterInfo",
    "WarehouseIdentifier",
    # Cluster metrics models
    "ClusterMetadata",
    "ClusterSummary",
    "ComputeUsage",
    "DiskUsage",
    "NetworkUsage",
    "ResourceSummary",
    # Resolver
    "ComputeResolver",
    # Transform functions
    "transform_cluster_config",
    "transform_cluster_events",
    "transform_job_run_clusters",
    # Fingerprint and health analysis
    "build_cluster_fingerprint",
    "analyze_cluster_health",
    "calculate_health_scores",
    "identify_cluster_risks",
]
