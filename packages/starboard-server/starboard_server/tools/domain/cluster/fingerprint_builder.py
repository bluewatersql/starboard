"""Cluster fingerprint builder.

Pure functions for building cluster fingerprints from raw API data.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from starboard_core.domain.models.cluster import (
    AccessMode,
    ClusterFingerprint,
    ClusterMode,
    ClusterType,
    CostProfile,
    NodeConfig,
    PerformanceProfile,
    RuntimeConfig,
)


def build_cluster_fingerprint(
    config: dict[str, Any],
    metrics: dict[str, Any] | None = None,
    cost_data: dict[str, Any] | None = None,
) -> ClusterFingerprint:
    """Build a ClusterFingerprint from raw API data.

    Pure function that transforms Databricks API responses into
    a normalized ClusterFingerprint domain model.

    Args:
        config: Cluster configuration from Databricks API.
        metrics: Optional performance metrics from monitoring.
        cost_data: Optional cost data from billing API.

    Returns:
        ClusterFingerprint with normalized data.

    Example:
        >>> config = {"cluster_id": "123", "cluster_name": "my-cluster", ...}
        >>> fingerprint = build_cluster_fingerprint(config)
    """
    cluster_id = config.get("cluster_id", "")
    cluster_name = config.get("cluster_name", "unknown")

    return ClusterFingerprint(
        fingerprint_version="v1",
        generated_at=datetime.now(UTC),
        cluster_id=cluster_id,
        cluster_name=cluster_name,
        cluster_type=_extract_cluster_type(config),
        cluster_mode=_extract_cluster_mode(config),
        access_mode=_extract_access_mode(config),
        runtime=_build_runtime_config(config),
        node_config=_build_node_config(config),
        performance=_build_performance_profile(metrics) if metrics else None,
        cost=_build_cost_profile(cost_data) if cost_data else None,
        autoscaling_enabled=_is_autoscaling_enabled(config),
        pool_id=config.get("instance_pool_id"),
        tags=config.get("custom_tags"),
    )


def _extract_cluster_type(config: dict[str, Any]) -> ClusterType:
    """Extract cluster type from config."""
    cluster_source = config.get("cluster_source", "").upper()

    if cluster_source == "JOB":
        return ClusterType.JOB

    # Check for single node
    num_workers = config.get("num_workers")
    autoscale = config.get("autoscale", {})
    min_workers = autoscale.get("min_workers", 0) if autoscale else 0
    max_workers = autoscale.get("max_workers", 0) if autoscale else 0

    if num_workers == 0 and min_workers == 0 and max_workers == 0:
        return ClusterType.SINGLE_NODE

    return ClusterType.ALL_PURPOSE


def _extract_cluster_mode(config: dict[str, Any]) -> ClusterMode:
    """Extract cluster mode from config."""
    # Check data_security_mode for Unity Catalog clusters
    data_security_mode = config.get("data_security_mode", "").upper()

    if data_security_mode in ("SINGLE_USER", "USER_ISOLATION"):
        return ClusterMode.STANDARD

    # Legacy cluster_mode field
    cluster_mode = config.get("cluster_mode", "").upper()
    if "HIGH_CONCURRENCY" in cluster_mode:
        return ClusterMode.HIGH_CONCURRENCY
    elif "SINGLE_NODE" in cluster_mode:
        return ClusterMode.SINGLE_NODE

    # Check for single node via worker count
    num_workers = config.get("num_workers")
    autoscale = config.get("autoscale", {})
    if num_workers == 0 and not autoscale:
        return ClusterMode.SINGLE_NODE

    return ClusterMode.STANDARD


def _extract_access_mode(config: dict[str, Any]) -> AccessMode:
    """Extract access mode from config."""
    data_security_mode = config.get("data_security_mode", "").upper()

    mode_map = {
        "SINGLE_USER": AccessMode.SINGLE_USER,
        "USER_ISOLATION": AccessMode.USER_ISOLATION,
        "SHARED": AccessMode.SHARED,
        "CUSTOM": AccessMode.CUSTOM,
        "NONE": AccessMode.NO_ISOLATION,
        "NO_ISOLATION": AccessMode.NO_ISOLATION,
    }

    return mode_map.get(data_security_mode, AccessMode.UNKNOWN)


def _build_runtime_config(config: dict[str, Any]) -> RuntimeConfig:
    """Build RuntimeConfig from cluster config."""
    spark_version = config.get("spark_version", "")

    # Parse DBR version components
    is_lts = "-lts-" in spark_version.lower() or spark_version.endswith("-lts")
    is_ml = "-ml-" in spark_version.lower()
    is_gpu = "-gpu-" in spark_version.lower()

    # Check for photon in runtime or config
    photon_enabled = (
        config.get("runtime_engine") == "PHOTON" or "-photon-" in spark_version.lower()
    )

    # Check for deprecated runtime (simplified check)
    # In practice, this would check against a known list
    version_parts = spark_version.split(".")
    major_version = 0
    if version_parts:
        with suppress(ValueError):
            major_version = int(version_parts[0])

    # DBR versions before 13.x are deprecated
    is_deprecated = 0 < major_version < 13

    return RuntimeConfig(
        dbr_version=spark_version,
        is_lts=is_lts,
        is_ml=is_ml,
        is_gpu=is_gpu,
        photon_enabled=photon_enabled,
        is_deprecated=is_deprecated,
    )


def _build_node_config(config: dict[str, Any]) -> NodeConfig:
    """Build NodeConfig from cluster config."""
    autoscale = config.get("autoscale", {})
    aws_attributes = config.get("aws_attributes", {})
    azure_attributes = config.get("azure_attributes", {})
    gcp_attributes = config.get("gcp_attributes", {})

    # Check for spot instances across cloud providers
    use_spot = (
        aws_attributes.get("availability") == "SPOT_WITH_FALLBACK"
        or aws_attributes.get("spot_bid_price_percent") is not None
        or azure_attributes.get("availability") == "SPOT_WITH_FALLBACK"
        or gcp_attributes.get("availability") == "PREEMPTIBLE"
        or gcp_attributes.get("use_preemptible_executors", False)
    )

    first_on_demand = (
        aws_attributes.get("first_on_demand", 1)
        or azure_attributes.get("first_on_demand", 1)
        or gcp_attributes.get("first_on_demand", 1)
    )

    return NodeConfig(
        driver_node_type=config.get("driver_node_type_id", "unknown"),
        worker_node_type=config.get("node_type_id", "unknown"),
        min_workers=autoscale.get("min_workers") if autoscale else None,
        max_workers=autoscale.get("max_workers") if autoscale else None,
        num_workers=config.get("num_workers") if not autoscale else None,
        use_spot_instances=use_spot,
        first_on_demand=first_on_demand,
    )


def _build_performance_profile(
    metrics: dict[str, Any],
) -> PerformanceProfile:
    """Build PerformanceProfile from metrics data."""
    return PerformanceProfile(
        cpu_utilization_p50=metrics.get("cpu_utilization_p50"),
        cpu_utilization_p95=metrics.get("cpu_utilization_p95"),
        memory_utilization_p50=metrics.get("memory_utilization_p50"),
        memory_utilization_p95=metrics.get("memory_utilization_p95"),
        oom_events_30d=metrics.get("oom_events_30d"),
        task_failure_rate=metrics.get("task_failure_rate"),
    )


def _build_cost_profile(cost_data: dict[str, Any]) -> CostProfile:
    """Build CostProfile from cost data."""
    return CostProfile(
        dbu_total_30d=cost_data.get("dbu_total_30d"),
        cost_usd_total_30d=cost_data.get("cost_usd_total_30d"),
        idle_cost_pct=cost_data.get("idle_cost_pct"),
        spot_savings_pct=cost_data.get("spot_savings_pct"),
    )


def _is_autoscaling_enabled(config: dict[str, Any]) -> bool:
    """Check if autoscaling is enabled."""
    autoscale = config.get("autoscale")
    if not autoscale:
        return False
    return bool(autoscale.get("min_workers") is not None)
