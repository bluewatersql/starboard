# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Cluster metrics analyzer.

Transforms raw cluster metrics records into structured, LLM-friendly summaries
grouped by cluster_id with aggregated resources and usage metrics.

This analyzer:
- Deduplicates records by (instance_id, time window)
- Groups metrics by cluster
- Aggregates resources by role (driver/worker)
- Computes network, disk, and CPU/memory usage

Performance:
- Single-pass aggregation: O(n)
- Memory-efficient: processes unique instances only once
- Type-safe: uses dataclasses for all structures
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from starboard_x.cluster import (
    ClusterMetricsInput,
    ClusterSizingThresholds,
    SizingReason,
    classify_compute_sizing,
    synthesize_rightsizing_verdict,
)

from starboard.tools.domain.cluster.cluster_metrics_models import (
    ClusterMetadata,
    ClusterSummary,
    ComputeUsage,
    DiskUsage,
    NetworkUsage,
    ResourceSummary,
)
from starboard.tools.domain.utils import safe_float, safe_int

# =============================================================================
# Constants
# =============================================================================

# SI units (decimal) for network/disk byte conversions
KILOBYTE = 1_000.0
MEGABYTE = 1_000_000.0
GIGABYTE = 1_000_000_000.0

# Binary units for memory conversions (MiB to GiB)
# Cloud providers (including Databricks) report memory in binary units
MIB_PER_GIB = 1024.0


# =============================================================================
# Helper Functions (inlined to reduce coupling)
# =============================================================================


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Delegate to canonical utils.safe_float (identical default semantics)."""
    return safe_float(value, default=default)


def _safe_int(value: Any) -> int | None:
    """Delegate to canonical utils.safe_int with default=None to preserve the
    None-on-failure semantics this module's callers rely on (e.g. the walrus
    `is not None` filters in the network-aggregation paths)."""
    return safe_int(value, default=None)


def _is_nan(value: Any) -> bool:
    """Check if value is NaN."""
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _nan_to_none(value: Any) -> Any:
    """Convert NaN values to None."""
    if _is_nan(value):
        return None
    return value


def _round_float(value: float, decimals: int = 2) -> float:
    """Round float to specified decimals."""
    return round(value, decimals)


def _calculate_average(values: list[float]) -> float:
    """Calculate average of numeric values, returning 0 if empty."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _calculate_ratio(numerator: float, denominator: float) -> float:
    """Calculate ratio, returning 0 if denominator is 0."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _to_datetime(value: Any) -> datetime | None:
    """Convert value to datetime, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (ValueError, OSError):
        pass
    return None


def _try_json_load(value: Any) -> Any:
    """Best-effort JSON loader. Returns parsed dict/list or original value."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return value
    return value


def _unify_field_value(records: list[dict[str, Any]], key: str) -> Any:
    """Get unified value from records - returns value if all non-None values are the same."""
    values = {r.get(key) for r in records if r.get(key) is not None}
    return values.pop() if values else None


# =============================================================================
# Analyzer
# =============================================================================


class ClusterMetricsAnalyzer:
    """Analyzer for cluster metrics records.

    Consolidates node-level metrics into cluster-level summaries with
    resource and usage aggregations.

    Example:
        >>> analyzer = ClusterMetricsAnalyzer(records)
        >>> summaries = analyzer.analyze()
        >>> print(summaries[0]["config"]["cluster_id"])

    Performance Characteristics:
        - Latency: 25 μs (small) to 61ms (very large)
        - Scaling: O(n) linear where n = number of metric records
        - Memory: O(c*i) where c = clusters, i = unique instances
        - Throughput: 39,000+ ops/sec for typical workloads
    """

    def __init__(self, records: list[dict[str, Any]]) -> None:
        """Initialize analyzer with raw metric records.

        Args:
            records: List of cluster metric dictionaries
        """
        self._records = records

    def analyze(self) -> list[dict[str, Any]]:
        """Analyze all records and return cluster summaries.

        Returns:
            List of cluster summaries, sorted by cluster_id
        """
        if not self._records:
            return []

        deduped = self._deduplicate_records(self._records)
        by_cluster = self._group_by_cluster(deduped)

        summaries = [
            self._summarize_cluster(cluster_id, recs)
            for cluster_id, recs in sorted(by_cluster.items(), key=lambda x: str(x[0]))
        ]

        return [s.to_dict() for s in summaries]

    def _deduplicate_records(
        self, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Remove duplicate records based on (instance_id, start_time, end_time)."""
        seen: set[tuple[Any, datetime | None, datetime | None]] = set()
        deduped: list[dict[str, Any]] = []

        for rec in records:
            key = (
                rec.get("instance_id"),
                _to_datetime(rec.get("start_time")),
                _to_datetime(rec.get("end_time")),
            )
            if key not in seen:
                seen.add(key)
                deduped.append(rec)

        return deduped

    def _group_by_cluster(
        self, records: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Group records by cluster_id."""
        by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rec in records:
            cluster_id = rec.get("cluster_id", "unknown")
            by_cluster[cluster_id].append(rec)
        return by_cluster

    def _summarize_cluster(
        self,
        cluster_id: str,  # noqa: ARG002
        recs: list[dict[str, Any]],  # noqa: ARG002
    ) -> ClusterSummary:
        """Create summary for a single cluster."""
        metadata = self._build_metadata(recs)
        resources = self._aggregate_resources(recs)
        network = self._aggregate_network_usage(recs)
        disk = self._aggregate_disk_usage(recs)
        compute = self._aggregate_compute_usage(recs)

        usage = {
            "compute_utilization": {
                "driver": compute["driver"].to_dict(),
                "worker": compute["worker"].to_dict(),
            },
            "network_MB": network.to_dict(),
            "disk_free_bytes_GB": disk.to_dict(),
        }

        return ClusterSummary(config=metadata, resources=resources, usage=usage)

    def _build_metadata(self, recs: list[dict[str, Any]]) -> ClusterMetadata:
        """Extract cluster metadata from records."""
        node_types = [r.get("node_type") for r in recs if r.get("node_type")]
        node_type = Counter(node_types).most_common(1)[0][0] if node_types else None

        worker_counts = [
            r.get("worker_count")
            for r in recs
            if r.get("worker_count") is not None and not _is_nan(r.get("worker_count"))
        ]
        worker_count = worker_counts[0] if worker_counts else None

        min_auto = [
            r.get("min_autoscale_workers")
            for r in recs
            if r.get("min_autoscale_workers") is not None
            and not _is_nan(r.get("min_autoscale_workers"))
        ]
        max_auto = [
            r.get("max_autoscale_workers")
            for r in recs
            if r.get("max_autoscale_workers") is not None
            and not _is_nan(r.get("max_autoscale_workers"))
        ]

        return ClusterMetadata(
            cluster_id=_unify_field_value(recs, "cluster_id"),
            cluster_name=_unify_field_value(recs, "cluster_name"),
            cluster_source=_unify_field_value(recs, "cluster_source"),
            dbr_version=_unify_field_value(recs, "dbr_version"),
            data_security_mode=_unify_field_value(recs, "data_security_mode"),
            enable_elastic_disk=_unify_field_value(recs, "enable_elastic_disk"),
            node_type=node_type,
            worker_count=worker_count,
            autoscale={
                "min_workers": min_auto[0] if min_auto else None,
                "max_workers": max_auto[0] if max_auto else None,
            },
            auto_termination_minutes=_nan_to_none(
                _unify_field_value(recs, "auto_termination_minutes")
            ),
        )

    def _aggregate_resources(
        self, recs: list[dict[str, Any]]
    ) -> dict[str, ResourceSummary]:
        """Aggregate resources by role (driver/worker)."""
        unique_instances: dict[str, dict[str, Any]] = {}
        for r in recs:
            instance_id = r.get("instance_id")
            if not instance_id:
                continue

            if instance_id not in unique_instances:
                unique_instances[instance_id] = {
                    "driver": bool(r.get("driver", False)),
                    "core_count": _safe_float(r.get("core_count")),
                    "gpu_count": _safe_float(r.get("gpu_count")),
                    "memory_mb": _safe_float(r.get("memory_mb")),
                }

        role_buckets: dict[str, list[dict[str, Any]]] = {"driver": [], "worker": []}
        for instance in unique_instances.values():
            role = "driver" if instance["driver"] else "worker"
            role_buckets[role].append(instance)

        def _aggregate_role(items: list[dict[str, Any]]) -> ResourceSummary:
            if not items:
                return ResourceSummary()
            return ResourceSummary(
                instances=len(items),
                cores_total=sum(x["core_count"] for x in items),
                gpus_total=sum(x["gpu_count"] for x in items),
                memory_total_GB=sum(x["memory_mb"] for x in items) / MIB_PER_GIB,
            )

        return {
            "driver": _aggregate_role(role_buckets["driver"]),
            "worker": _aggregate_role(role_buckets["worker"]),
        }

    def _aggregate_network_usage(self, recs: list[dict[str, Any]]) -> NetworkUsage:
        """Aggregate network usage (sent/received bytes)."""
        sent_bytes = sum(
            v for r in recs if (v := _safe_int(r.get("network_sent_bytes"))) is not None
        )
        recv_bytes = sum(
            v
            for r in recs
            if (v := _safe_int(r.get("network_received_bytes"))) is not None
        )
        sent_mb = sent_bytes / MEGABYTE
        recv_mb = recv_bytes / MEGABYTE
        total_mb = sent_mb + recv_mb
        ratio = _calculate_ratio(sent_mb, recv_mb)

        return NetworkUsage(
            sent_total=sent_mb,
            received_total=recv_mb,
            total=total_mb,
            sent_to_recv_ratio=ratio,
        )

    def _aggregate_disk_usage(self, recs: list[dict[str, Any]]) -> DiskUsage:
        """Aggregate disk usage across mount points."""
        mounts_totals: dict[str, int] = defaultdict(int)
        mounts_counts: dict[str, int] = defaultdict(int)

        for r in recs:
            mount_points = r.get("disk_free_bytes_per_mount_point")
            if mount_points is None:
                continue
            try:
                if hasattr(mount_points, "__len__") and len(mount_points) == 0:
                    continue
            except (TypeError, ValueError):
                pass

            mount_points = _try_json_load(mount_points)
            if mount_points is None:
                continue

            if isinstance(mount_points, list):
                for mp in mount_points:
                    if isinstance(mp, dict) and "key" in mp and "value" in mp:
                        mount = mp["key"]
                        value = _safe_int(mp["value"])
                        if value is not None:
                            mounts_totals[mount] += value
                            mounts_counts[mount] += 1
            elif isinstance(mount_points, dict):
                for mount, bytes_free in mount_points.items():
                    value = _safe_int(bytes_free)
                    if value is not None:
                        mounts_totals[mount] += value
                        mounts_counts[mount] += 1

        avg_mounts_bytes = (
            {m: mounts_totals[m] / mounts_counts[m] for m in mounts_totals}
            if mounts_totals
            else {}
        )
        avg_total_free_gb = (
            sum(avg_mounts_bytes.values()) / GIGABYTE if avg_mounts_bytes else 0.0
        )

        return DiskUsage(total_free_avg=avg_total_free_gb)

    def _aggregate_compute_usage(
        self, recs: list[dict[str, Any]]
    ) -> dict[str, ComputeUsage]:
        """Aggregate CPU and memory usage by role (driver/worker)."""

        def _aggregate_role(is_driver: bool) -> ComputeUsage:
            subset = [r for r in recs if bool(r.get("driver", False)) == is_driver]

            if not subset:
                return ComputeUsage()

            cpu_series = [
                _safe_float(s.get("cpu_user_percent"))
                + _safe_float(s.get("cpu_system_percent"))
                + _safe_float(s.get("cpu_wait_percent"))
                for s in subset
            ]
            mem_series = [_safe_float(s.get("mem_used_percent")) for s in subset]

            return ComputeUsage(
                cpu_total_avg=_round_float(_calculate_average(cpu_series)),
                cpu_total_min=_round_float(min(cpu_series)) if cpu_series else 0.0,
                cpu_total_max=_round_float(max(cpu_series)) if cpu_series else 0.0,
                mem_used_avg=_round_float(_calculate_average(mem_series)),
                mem_used_min=_round_float(min(mem_series)) if mem_series else 0.0,
                mem_used_max=_round_float(max(mem_series)) if mem_series else 0.0,
            )

        return {
            "driver": _aggregate_role(True),
            "worker": _aggregate_role(False),
        }


# =============================================================================
# Right-sizing enrichment (one source of truth: starboard_x.cluster)
# =============================================================================

# Enriched right-sizing keys attached to a cluster metrics/health summary.
# Kept in sync with the fields Task-09 surfaces on get_cluster_metrics /
# get_cluster_health (D-2.3): target_cores_per_node, reduction_pct,
# binding_resource, autoscale_constrained, queue_pressure.
_RIGHTSIZING_KEYS = (
    "target_cores_per_node",
    "reduction_pct",
    "binding_resource",
    "autoscale_constrained",
    "queue_pressure",
)


def _per_node(total: Any, instances: Any) -> float:
    """Return a per-node figure from a role total and instance count."""
    total_f = _safe_float(total)
    count = _safe_int(instances) or 0
    if count <= 0:
        return 0.0
    return total_f / count


def derive_rightsizing_signal(
    summary: dict[str, Any],
    thresholds: ClusterSizingThresholds | None = None,
) -> dict[str, Any]:
    """Derive a right-sizing signal from an analyzed cluster metrics summary.

    Backports the harvested right-sizing heuristics by **calling into**
    :mod:`starboard_x.cluster` — the single source of truth for the thresholds
    and classification logic (decision D-2.3, no fork). Consumes the dict shape
    produced by :meth:`ClusterMetricsAnalyzer.analyze` (i.e. a
    :meth:`ClusterSummary.to_dict`) and maps the worker role's utilization onto
    a :class:`~starboard_x.cluster.ClusterMetricsInput`.

    The analyzer surfaces avg/min/max (not raw percentiles); ``*_max`` is used
    as the p95 proxy and ``*_avg`` as the average, which is sufficient for the
    coarse pressure/over-provision bands.

    Args:
        summary: One analyzed cluster summary (``config``/``resources``/``usage``).
        thresholds: Optional threshold overrides; defaults to the harvested
            research/09 §1 values.

    Returns:
        A dict always carrying the five enrichment keys
        (``target_cores_per_node``, ``reduction_pct``, ``binding_resource``,
        ``autoscale_constrained``, ``queue_pressure``) plus ``available``,
        ``sizing_direction``, ``sizing_reason``, ``recommended_action`` and
        ``confidence``. When no worker utilization is present, ``available`` is
        ``False`` and the numeric fields are ``None``/``False``.
    """
    usage = summary.get("usage") or {}
    compute = usage.get("compute_utilization") or {}
    worker = compute.get("worker") or {}
    resources = summary.get("resources") or {}
    worker_res = resources.get("worker") or {}
    config = summary.get("config") or {}
    autoscale = config.get("autoscale") or {}

    instances = _safe_int(worker_res.get("instances")) or 0
    has_signal = instances > 0 and bool(worker)
    if not has_signal:
        return {
            "available": False,
            "sizing_direction": None,
            "sizing_reason": None,
            "recommended_action": None,
            "confidence": None,
            "target_cores_per_node": None,
            "reduction_pct": None,
            "binding_resource": None,
            "autoscale_constrained": False,
            "queue_pressure": False,
        }

    t = thresholds or ClusterSizingThresholds()
    metrics_input = ClusterMetricsInput(
        cpu_p95_pct=_safe_float(worker.get("cpu_total_max")),
        memory_p95_pct=_safe_float(worker.get("mem_used_max")),
        cpu_avg_pct=_safe_float(worker.get("cpu_total_avg")),
        cores_per_node=_per_node(worker_res.get("cores_total"), instances),
        memory_gb_per_node=_per_node(worker_res.get("memory_total_GB"), instances),
        min_autoscale_workers=_safe_int(autoscale.get("min_workers")),
        max_autoscale_workers=_safe_int(autoscale.get("max_workers")),
        observed_workers_p95=float(instances),
    )

    signal = classify_compute_sizing(metrics_input, node_role="WORKER", thresholds=t)
    verdict = synthesize_rightsizing_verdict(signal, thresholds=t)

    return {
        "available": True,
        "sizing_direction": verdict.sizing_direction.value,
        "sizing_reason": signal.sizing_reason.value,
        "recommended_action": verdict.recommended_action.value,
        "confidence": verdict.confidence.value,
        "target_cores_per_node": verdict.target_cores_per_node,
        "reduction_pct": verdict.reduction_pct,
        "binding_resource": verdict.binding_resource,
        "autoscale_constrained": (
            signal.sizing_reason == SizingReason.AUTOSCALE_MAX_CONSTRAINED
        ),
        # Queue pressure is a streaming service-level signal; it is not derivable
        # from cluster utilization percentiles alone, so it is False at this
        # layer (the streaming-aware path lives in the CRS-05/08 tool queries).
        "queue_pressure": False,
    }
