# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x.cluster`` — SDK-free cluster right-sizing analyzer (Phase-2 X2).

A pure, ``pydantic``-only progressive analyzer that backports the harvested
right-sizing heuristics from
``changes/2026_26_27_agents/research/09_cluster_health.md`` §1 (the external
``cluster_role_features`` decision logic) into **one source of truth** — the
Starboard server tier's :mod:`starboard.tools.domain.cluster.cluster_metrics_analyzer`
is meant to call *into* this logic rather than fork it (decision D-2.3).

Kernel purity (import-linter contract 3, "pure analyzers are SDK-free"): this
module imports **no** ``databricks-sdk`` / ``openai`` / ``fastapi`` / ``mcp`` and
never reaches back into the heavy ``starboard`` server package. It is
``pydantic`` + stdlib only, mirroring the ``warehouse`` / ``uc`` / ``review``
progressive analyzers.

Public surface:
    Models — :class:`ClusterSizingThresholds`, :class:`ClusterMetricsInput`,
        :class:`StreamingMetricsInput`, :class:`SizingSignal`,
        :class:`CapacitySignal`, :class:`RightsizingVerdict`.
    Functions — :func:`classify_compute_sizing`, :func:`classify_streaming_capacity`,
        :func:`synthesize_rightsizing_verdict`.

All thresholds live in :class:`ClusterSizingThresholds` (config-driven, no magic
numbers). The defaults are the harvested research/09 §1 values; override the
model to retune without touching the classification code.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

#: Standard disclaimer attached to every list-price DBU cost figure on the public
#: path. Single source of truth — the cluster tools and the autonomous monitor
#: both import this so the wording can never drift out of sync.
LIST_PRICE_DISCLAIMER = (
    "list-price DBU estimate; actual billed cost differs under contracted rates"
)

__all__ = [
    "LIST_PRICE_DISCLAIMER",
    "SizingDirection",
    "SizingReason",
    "RecommendedAction",
    "CapacityStatus",
    "Confidence",
    "ClusterSizingThresholds",
    "StreamingCapacityThresholds",
    "ClusterMetricsInput",
    "StreamingMetricsInput",
    "SizingSignal",
    "CapacitySignal",
    "RightsizingVerdict",
    "classify_compute_sizing",
    "classify_streaming_capacity",
    "synthesize_rightsizing_verdict",
]


# --- Enumerations --------------------------------------------------------- #
class SizingDirection(StrEnum):
    """Coarse right-sizing direction (research/09 §1 priority model)."""

    UNDERPROVISIONED = "UNDERPROVISIONED"
    OVERPROVISIONED = "OVERPROVISIONED"
    BALANCED = "BALANCED"
    REVIEW = "REVIEW"


class SizingReason(StrEnum):
    """Specific compute sizing_reason from the ``cluster_role_features`` CASE."""

    DRIVER_MEMORY_PRESSURE = "DRIVER_MEMORY_PRESSURE"
    DRIVER_CPU_PRESSURE = "DRIVER_CPU_PRESSURE"
    WORKER_MEMORY_PRESSURE = "WORKER_MEMORY_PRESSURE"
    WORKER_CPU_PRESSURE = "WORKER_CPU_PRESSURE"
    WORKER_IO_BOUND = "WORKER_IO_BOUND"
    AUTOSCALE_MAX_CONSTRAINED = "AUTOSCALE_MAX_CONSTRAINED"
    AUTOSCALE_MIN_TOO_HIGH = "AUTOSCALE_MIN_TOO_HIGH"
    SEVERELY_OVERPROVISIONED = "SEVERELY_OVERPROVISIONED"
    OVERPROVISIONED = "OVERPROVISIONED"
    BALANCED = "BALANCED"


class CapacityStatus(StrEnum):
    """Streaming service-level capacity status (research/09 §1 stream metrics)."""

    FRESHNESS_SLA_BREACH = "FRESHNESS_SLA_BREACH"
    UNDERPROVISIONED_AUTOSCALE_BOUND = "UNDERPROVISIONED_AUTOSCALE_BOUND"
    UNDERPROVISIONED_TASK_CAPACITY = "UNDERPROVISIONED_TASK_CAPACITY"
    UNDERPROVISIONED_BACKLOG_PRESSURE = "UNDERPROVISIONED_BACKLOG_PRESSURE"
    BALANCED = "BALANCED"


class RecommendedAction(StrEnum):
    """Recommended action (research/09 §1 recommended-actions table)."""

    RAISE_AUTOSCALE_MAX = "RAISE_AUTOSCALE_MAX"
    ADD_WORKERS = "ADD_WORKERS"
    UPSIZE_OR_COMPUTE_OPTIMIZED_SKU = "UPSIZE_OR_COMPUTE_OPTIMIZED_SKU"
    MEMORY_OPTIMIZED_SKU_OR_UPSIZE = "MEMORY_OPTIMIZED_SKU_OR_UPSIZE"
    ADD_LOCAL_DISK_OR_IO_OPTIMIZED_SKU = "ADD_LOCAL_DISK_OR_IO_OPTIMIZED_SKU"
    INVESTIGATE_STREAM_LATENCY = "INVESTIGATE_STREAM_LATENCY"
    DOWNSIZE_WORKERS = "DOWNSIZE_WORKERS"
    DOWNSIZE_OR_SMALLER_SKU = "DOWNSIZE_OR_SMALLER_SKU"
    DOWNSIZE_CANDIDATE = "DOWNSIZE_CANDIDATE"
    LOWER_AUTOSCALE_MIN = "LOWER_AUTOSCALE_MIN"
    NONE = "NONE"
    REVIEW = "REVIEW"


class Confidence(StrEnum):
    """Persistence-derived confidence (research/09 §4 Opt C horizon model)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# --- Thresholds (config-driven; defaults == research/09 §1) --------------- #
class StreamingCapacityThresholds(BaseModel):
    """Streaming service-level thresholds (research/09 §1 recommended actions)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Autoscale is "bound" when the constrained-sample fraction clears this and
    # there is demand pressure (backlog present or queued tasks). (Opt B, §4.)
    autoscale_constrained_pct: float = Field(
        default=10.0,
        description="autoscale_constrained_pct above which autoscale is bound (%).",
    )
    # Slot-utilization floors that qualify queue/backlog pressure as a capacity
    # deficit (research/09 §1 recommended-actions table).
    task_capacity_slot_utilization: float = Field(
        default=0.85,
        description="task-slot utilization ratio gating UNDERPROVISIONED_TASK_CAPACITY.",
    )
    backlog_slot_utilization: float = Field(
        default=0.80,
        description="task-slot utilization ratio gating UNDERPROVISIONED_BACKLOG_PRESSURE.",
    )
    queued_tasks_threshold: float = Field(
        default=0.0,
        description="avg queued tasks strictly above this counts as queue pressure.",
    )


class ClusterSizingThresholds(BaseModel):
    """All right-sizing thresholds in one place (decision D-2.3 — no magic numbers).

    Defaults are the harvested values from research/09 §1
    (``01_setup:cell-28`` lines 287-315, persistence gate lines 202-246, cost
    exposure lines 470-479). Construct with overrides to retune without editing
    the classification logic.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- CPU pressure (driver + worker share the same p95/avg pair) --------- #
    cpu_pressure_p95_pct: float = Field(
        default=90.0, description="cpu_p95 at/above which CPU is under pressure (%)."
    )
    cpu_pressure_avg_pct: float = Field(
        default=50.0, description="cpu_avg co-requirement for CPU pressure (%)."
    )

    # --- Memory pressure: high-p95 OR two swap-coupled bands ---------------- #
    memory_pressure_p95_pct: float = Field(
        default=90.0, description="memory_p95 alone triggering memory pressure (%)."
    )
    # Driver is more sensitive than worker (lower coupled memory floors).
    driver_swap_high_pct: float = Field(default=10.0, description="driver swap band A (%).")
    driver_swap_high_memory_pct: float = Field(
        default=60.0, description="driver memory floor paired with swap band A (%)."
    )
    driver_swap_low_pct: float = Field(default=2.0, description="driver swap band B (%).")
    driver_swap_low_memory_pct: float = Field(
        default=75.0, description="driver memory floor paired with swap band B (%)."
    )
    worker_swap_high_pct: float = Field(default=10.0, description="worker swap band A (%).")
    worker_swap_high_memory_pct: float = Field(
        default=70.0, description="worker memory floor paired with swap band A (%)."
    )
    worker_swap_low_pct: float = Field(default=2.0, description="worker swap band B (%).")
    worker_swap_low_memory_pct: float = Field(
        default=80.0, description="worker memory floor paired with swap band B (%)."
    )

    # --- Worker I/O ---------------------------------------------------------- #
    io_wait_p95_pct: float = Field(
        default=25.0, description="io_wait_p95 at/above which the worker is IO-bound (%)."
    )

    # --- Autoscale constraints ---------------------------------------------- #
    autoscale_max_pressure_pct: float = Field(
        default=80.0,
        description="GREATEST(cpu_p95, memory_p95) floor for AUTOSCALE_MAX_CONSTRAINED (%).",
    )
    autoscale_min_cpu_p95_pct: float = Field(
        default=40.0, description="cpu_p95 ceiling for AUTOSCALE_MIN_TOO_HIGH (%)."
    )
    autoscale_min_memory_p95_pct: float = Field(
        default=50.0, description="memory_p95 ceiling for AUTOSCALE_MIN_TOO_HIGH (%)."
    )

    # --- Overprovisioning bands --------------------------------------------- #
    severely_overprovisioned_cpu_p95_pct: float = Field(
        default=30.0, description="cpu_p95 ceiling for SEVERELY_OVERPROVISIONED (%)."
    )
    severely_overprovisioned_memory_p95_pct: float = Field(
        default=40.0, description="memory_p95 ceiling for SEVERELY_OVERPROVISIONED (%)."
    )
    severely_overprovisioned_cpu_avg_pct: float = Field(
        default=20.0, description="cpu_avg ceiling for SEVERELY_OVERPROVISIONED (%)."
    )
    overprovisioned_cpu_p95_pct: float = Field(
        default=50.0, description="cpu_p95 ceiling for OVERPROVISIONED (%)."
    )
    overprovisioned_memory_p95_pct: float = Field(
        default=60.0, description="memory_p95 ceiling for OVERPROVISIONED (%)."
    )
    overprovisioned_cpu_avg_pct: float = Field(
        default=30.0, description="cpu_avg ceiling for OVERPROVISIONED (%)."
    )

    # --- Persistence gate (7-day history guard, §1 lines 202-246) ----------- #
    persistence_min_days: int = Field(
        default=3, description="minimum distinct observation days before a downsize."
    )
    persistence_min_ratio: float = Field(
        default=0.7, description="fraction of days that must signal over-provision."
    )
    high_confidence_min_days: int = Field(
        default=30, description="observation days at/above which confidence is HIGH."
    )

    # --- Cost exposure / target sizing (§1 lines 470-479) ------------------- #
    headroom_target_ratio: float = Field(
        default=0.7,
        description="target steady-state utilization headroom (p95 / this = need).",
    )
    downsize_bands: tuple[float, ...] = Field(
        default=(0.25, 0.5, 0.75),
        description="allowed fractions of current capacity to downsize toward.",
    )

    streaming: StreamingCapacityThresholds = Field(
        default_factory=StreamingCapacityThresholds,
        description="nested streaming service-level thresholds.",
    )


# --- Inputs --------------------------------------------------------------- #
class ClusterMetricsInput(BaseModel):
    """Per-role utilization percentiles for a cluster (research/09 §1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cpu_p95_pct: float
    memory_p95_pct: float
    io_wait_p95_pct: float = 0.0
    swap_p95_pct: float = 0.0
    cpu_avg_pct: float = 0.0
    cores_per_node: float = 0.0
    memory_gb_per_node: float = 0.0
    configured_fixed_workers: int | None = None
    min_autoscale_workers: int | None = None
    max_autoscale_workers: int | None = None
    observed_workers_p95: float = 0.0


class StreamingMetricsInput(BaseModel):
    """Structured-streaming capacity signals for a pipeline/flow (research/09 §1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_slot_utilization_p95: float = 0.0
    avg_queued_tasks_p95: float = 0.0
    autoscale_constrained_pct: float = 0.0
    backlog_bytes_p95: int | None = None
    backlog_records_p95: int | None = None
    event_time_lag_p95_seconds: float | None = None
    freshness_sla_sec: int | None = None


# --- Signals + verdict ---------------------------------------------------- #
class SizingSignal(BaseModel):
    """Outcome of :func:`classify_compute_sizing` for a single role."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_role: str
    sizing_reason: SizingReason
    sizing_direction: SizingDirection
    recommended_action: RecommendedAction
    target_cores_per_node: float | None = None
    target_gb_per_node: float | None = None
    binding_resource: str | None = None
    reduction_pct: float | None = None


class CapacitySignal(BaseModel):
    """Outcome of :func:`classify_streaming_capacity` for a streaming workload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workload_class: str
    capacity_status: CapacityStatus
    sizing_direction: SizingDirection
    recommended_action: RecommendedAction


class RightsizingVerdict(BaseModel):
    """Merged right-sizing verdict (compute + streaming + persistence gate)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sizing_direction: SizingDirection
    sizing_status: str
    recommended_action: RecommendedAction
    target_cores_per_node: float | None = None
    target_gb_per_node: float | None = None
    binding_resource: str | None = None
    reduction_pct: float | None = None
    confidence: Confidence
    persistence_gate_passed: bool | None = None
    rationale: str = ""


# --- Action map (single source of truth) ---------------------------------- #
_REASON_ACTIONS: dict[SizingReason, RecommendedAction] = {
    SizingReason.DRIVER_MEMORY_PRESSURE: RecommendedAction.MEMORY_OPTIMIZED_SKU_OR_UPSIZE,
    SizingReason.DRIVER_CPU_PRESSURE: RecommendedAction.UPSIZE_OR_COMPUTE_OPTIMIZED_SKU,
    SizingReason.WORKER_MEMORY_PRESSURE: RecommendedAction.MEMORY_OPTIMIZED_SKU_OR_UPSIZE,
    SizingReason.WORKER_CPU_PRESSURE: RecommendedAction.UPSIZE_OR_COMPUTE_OPTIMIZED_SKU,
    SizingReason.WORKER_IO_BOUND: RecommendedAction.ADD_LOCAL_DISK_OR_IO_OPTIMIZED_SKU,
    SizingReason.AUTOSCALE_MAX_CONSTRAINED: RecommendedAction.RAISE_AUTOSCALE_MAX,
    SizingReason.AUTOSCALE_MIN_TOO_HIGH: RecommendedAction.LOWER_AUTOSCALE_MIN,
    SizingReason.SEVERELY_OVERPROVISIONED: RecommendedAction.DOWNSIZE_OR_SMALLER_SKU,
    SizingReason.OVERPROVISIONED: RecommendedAction.DOWNSIZE_CANDIDATE,
    SizingReason.BALANCED: RecommendedAction.NONE,
}

_UNDERPROVISION_REASONS = {
    SizingReason.DRIVER_MEMORY_PRESSURE,
    SizingReason.DRIVER_CPU_PRESSURE,
    SizingReason.WORKER_MEMORY_PRESSURE,
    SizingReason.WORKER_CPU_PRESSURE,
    SizingReason.WORKER_IO_BOUND,
    SizingReason.AUTOSCALE_MAX_CONSTRAINED,
}
_OVERPROVISION_REASONS = {
    SizingReason.AUTOSCALE_MIN_TOO_HIGH,
    SizingReason.SEVERELY_OVERPROVISIONED,
    SizingReason.OVERPROVISIONED,
}


def _direction_for_reason(reason: SizingReason) -> SizingDirection:
    if reason in _UNDERPROVISION_REASONS:
        return SizingDirection.UNDERPROVISIONED
    if reason in _OVERPROVISION_REASONS:
        return SizingDirection.OVERPROVISIONED
    return SizingDirection.BALANCED


# --- Compute classification ----------------------------------------------- #
def _memory_pressure(
    metrics: ClusterMetricsInput, t: ClusterSizingThresholds, *, driver: bool
) -> bool:
    if metrics.memory_p95_pct >= t.memory_pressure_p95_pct:
        return True
    if driver:
        high_swap, high_mem = t.driver_swap_high_pct, t.driver_swap_high_memory_pct
        low_swap, low_mem = t.driver_swap_low_pct, t.driver_swap_low_memory_pct
    else:
        high_swap, high_mem = t.worker_swap_high_pct, t.worker_swap_high_memory_pct
        low_swap, low_mem = t.worker_swap_low_pct, t.worker_swap_low_memory_pct
    if metrics.swap_p95_pct >= high_swap and metrics.memory_p95_pct >= high_mem:
        return True
    return metrics.swap_p95_pct >= low_swap and metrics.memory_p95_pct >= low_mem


def _cpu_pressure(metrics: ClusterMetricsInput, t: ClusterSizingThresholds) -> bool:
    return (
        metrics.cpu_p95_pct >= t.cpu_pressure_p95_pct
        and metrics.cpu_avg_pct >= t.cpu_pressure_avg_pct
    )


def _autoscale_max_constrained(
    metrics: ClusterMetricsInput, t: ClusterSizingThresholds
) -> bool:
    if metrics.max_autoscale_workers is None:
        return False
    return (
        metrics.observed_workers_p95 >= metrics.max_autoscale_workers
        and max(metrics.cpu_p95_pct, metrics.memory_p95_pct)
        >= t.autoscale_max_pressure_pct
    )


def _autoscale_min_too_high(
    metrics: ClusterMetricsInput, t: ClusterSizingThresholds
) -> bool:
    if metrics.min_autoscale_workers is None:
        return False
    return (
        metrics.observed_workers_p95 <= metrics.min_autoscale_workers
        and metrics.cpu_p95_pct < t.autoscale_min_cpu_p95_pct
        and metrics.memory_p95_pct < t.autoscale_min_memory_p95_pct
    )


def _severely_overprovisioned(
    metrics: ClusterMetricsInput, t: ClusterSizingThresholds
) -> bool:
    return (
        metrics.cpu_p95_pct < t.severely_overprovisioned_cpu_p95_pct
        and metrics.memory_p95_pct < t.severely_overprovisioned_memory_p95_pct
        and metrics.cpu_avg_pct < t.severely_overprovisioned_cpu_avg_pct
    )


def _overprovisioned(
    metrics: ClusterMetricsInput, t: ClusterSizingThresholds
) -> bool:
    return (
        metrics.cpu_p95_pct < t.overprovisioned_cpu_p95_pct
        and metrics.memory_p95_pct < t.overprovisioned_memory_p95_pct
        and metrics.cpu_avg_pct < t.overprovisioned_cpu_avg_pct
    )


def _classify_reason(
    metrics: ClusterMetricsInput, node_role: str, t: ClusterSizingThresholds
) -> SizingReason:
    """Apply the ``cluster_role_features`` CASE ladder (pressure wins over waste)."""
    driver = node_role.upper() == "DRIVER"

    # 1) Pressure / underprovision signals take precedence.
    if _memory_pressure(metrics, t, driver=driver):
        return (
            SizingReason.DRIVER_MEMORY_PRESSURE
            if driver
            else SizingReason.WORKER_MEMORY_PRESSURE
        )
    if _cpu_pressure(metrics, t):
        return (
            SizingReason.DRIVER_CPU_PRESSURE
            if driver
            else SizingReason.WORKER_CPU_PRESSURE
        )
    if not driver and metrics.io_wait_p95_pct >= t.io_wait_p95_pct:
        return SizingReason.WORKER_IO_BOUND
    if not driver and _autoscale_max_constrained(metrics, t):
        return SizingReason.AUTOSCALE_MAX_CONSTRAINED

    # 2) Over-provision signals.
    if not driver and _autoscale_min_too_high(metrics, t):
        return SizingReason.AUTOSCALE_MIN_TOO_HIGH
    if _severely_overprovisioned(metrics, t):
        return SizingReason.SEVERELY_OVERPROVISIONED
    if _overprovisioned(metrics, t):
        return SizingReason.OVERPROVISIONED

    return SizingReason.BALANCED


def _target_capacity(
    current: float, utilization_pct: float, t: ClusterSizingThresholds
) -> tuple[float | None, float | None]:
    """Return ``(target, reduction_pct)`` for one resource, or ``(None, None)``.

    Mirrors research/09 §1 lines 209-224: size to the utilization *need*
    (p95 / headroom target) rounded up to the next allowed downsize band.
    """
    if current <= 0:
        return None, None
    need = current * (utilization_pct / 100.0) / t.headroom_target_ratio
    for band in sorted(t.downsize_bands):
        if need <= current * band:
            target = round(current * band, 4)
            reduction = round(100.0 * (current - target) / current, 4)
            return target, reduction
    return current, 0.0


def _cost_exposure(
    metrics: ClusterMetricsInput, t: ClusterSizingThresholds
) -> tuple[float | None, float | None, str | None, float | None]:
    """Return ``(target_cores, target_gb, binding_resource, reduction_pct)``.

    The binding resource is the one that permits the *smaller* reduction; the
    achievable reduction is limited by it (§1 line 224).
    """
    target_cores, cpu_reduction = _target_capacity(
        metrics.cores_per_node, metrics.cpu_p95_pct, t
    )
    target_gb, mem_reduction = _target_capacity(
        metrics.memory_gb_per_node, metrics.memory_p95_pct, t
    )
    if cpu_reduction is None and mem_reduction is None:
        return None, None, None, None

    # Only resources with a known metric can bind the achievable reduction. A
    # missing metric is *not* a 0% reduction (that would spuriously zero out a
    # genuine downsize on the other resource and mislabel the binding resource);
    # it simply does not constrain, so the present metric governs.
    if cpu_reduction is None:
        return target_cores, target_gb, "MEMORY", mem_reduction
    if mem_reduction is None:
        return target_cores, target_gb, "CPU", cpu_reduction

    binding = "CPU" if cpu_reduction <= mem_reduction else "MEMORY"
    reduction_pct = min(cpu_reduction, mem_reduction)
    return target_cores, target_gb, binding, reduction_pct


def classify_compute_sizing(
    metrics: ClusterMetricsInput,
    node_role: str = "WORKER",
    thresholds: ClusterSizingThresholds | None = None,
) -> SizingSignal:
    """Classify a role's utilization into a :class:`SizingSignal`.

    Applies the harvested ``cluster_role_features`` heuristics (research/09 §1).
    For over-provisioned reasons it also derives the target cores/GB, binding
    resource, and achievable reduction percentage (cost-exposure inputs).
    """
    t = thresholds or ClusterSizingThresholds()
    reason = _classify_reason(metrics, node_role, t)
    direction = _direction_for_reason(reason)
    action = _REASON_ACTIONS[reason]

    target_cores = target_gb = binding = reduction = None
    if reason in _OVERPROVISION_REASONS:
        target_cores, target_gb, binding, reduction = _cost_exposure(metrics, t)

    return SizingSignal(
        node_role=node_role.upper(),
        sizing_reason=reason,
        sizing_direction=direction,
        recommended_action=action,
        target_cores_per_node=target_cores,
        target_gb_per_node=target_gb,
        binding_resource=binding,
        reduction_pct=reduction,
    )


# --- Streaming classification --------------------------------------------- #
def _backlog_present(metrics: StreamingMetricsInput) -> bool:
    return bool(metrics.backlog_bytes_p95) or bool(metrics.backlog_records_p95)


def classify_streaming_capacity(
    metrics: StreamingMetricsInput,
    workload_class: str = "CONTINUOUS",
    thresholds: ClusterSizingThresholds | None = None,
) -> CapacitySignal:
    """Classify streaming service-level capacity (research/09 §1 stream metrics)."""
    t = (thresholds or ClusterSizingThresholds()).streaming

    status = CapacityStatus.BALANCED
    action = RecommendedAction.NONE

    lag = metrics.event_time_lag_p95_seconds
    sla = metrics.freshness_sla_sec
    queue_pressure = metrics.avg_queued_tasks_p95 > t.queued_tasks_threshold

    if lag is not None and sla is not None and lag > sla:
        status = CapacityStatus.FRESHNESS_SLA_BREACH
        action = RecommendedAction.INVESTIGATE_STREAM_LATENCY
    elif metrics.autoscale_constrained_pct > t.autoscale_constrained_pct and (
        _backlog_present(metrics) or queue_pressure
    ):
        status = CapacityStatus.UNDERPROVISIONED_AUTOSCALE_BOUND
        action = RecommendedAction.RAISE_AUTOSCALE_MAX
    elif (
        queue_pressure
        and metrics.task_slot_utilization_p95 >= t.task_capacity_slot_utilization
    ):
        status = CapacityStatus.UNDERPROVISIONED_TASK_CAPACITY
        action = RecommendedAction.ADD_WORKERS
    elif (
        _backlog_present(metrics)
        and metrics.task_slot_utilization_p95 >= t.backlog_slot_utilization
    ):
        status = CapacityStatus.UNDERPROVISIONED_BACKLOG_PRESSURE
        action = RecommendedAction.ADD_WORKERS

    direction = (
        SizingDirection.BALANCED
        if status == CapacityStatus.BALANCED
        else SizingDirection.UNDERPROVISIONED
    )
    return CapacitySignal(
        workload_class=workload_class,
        capacity_status=status,
        sizing_direction=direction,
        recommended_action=action,
    )


# --- Synthesis ------------------------------------------------------------ #
# Urgency priority (research/09 §1 lines 183-190): most-urgent signal wins.
_DIRECTION_PRIORITY: dict[SizingDirection, int] = {
    SizingDirection.UNDERPROVISIONED: 4,
    SizingDirection.OVERPROVISIONED: 2,
    SizingDirection.BALANCED: 1,
    SizingDirection.REVIEW: 0,
}


def _persistence_gate(
    persistence_ratio: float | None,
    observed_days: int | None,
    t: ClusterSizingThresholds,
) -> bool | None:
    """Return gate result (``None`` when no history supplied)."""
    if observed_days is None or persistence_ratio is None:
        return None
    return (
        observed_days >= t.persistence_min_days
        and persistence_ratio >= t.persistence_min_ratio
    )


def _confidence(
    gate_passed: bool | None,
    observed_days: int | None,
    t: ClusterSizingThresholds,
) -> Confidence:
    if gate_passed and observed_days is not None:
        if observed_days >= t.high_confidence_min_days:
            return Confidence.HIGH
        return Confidence.MEDIUM
    return Confidence.LOW


def synthesize_rightsizing_verdict(
    compute_signal: SizingSignal,
    streaming_signal: CapacitySignal | None = None,
    persistence_ratio: float | None = None,
    observed_days: int | None = None,
    thresholds: ClusterSizingThresholds | None = None,
) -> RightsizingVerdict:
    """Merge compute + streaming signals and apply the persistence gate.

    Most-urgent direction wins (streaming under-provision / SLA breach outrank a
    compute over-provision). A downsize is only upgraded from ``DOWNSIZE_CANDIDATE``
    to ``DOWNSIZE_WORKERS`` when the 3-day / 70% persistence gate passes
    (research/09 §1 lines 116-137).
    """
    t = thresholds or ClusterSizingThresholds()
    gate_passed = _persistence_gate(persistence_ratio, observed_days, t)
    confidence = _confidence(gate_passed, observed_days, t)

    # Decide which signal drives the verdict.
    use_streaming = streaming_signal is not None and (
        _DIRECTION_PRIORITY[streaming_signal.sizing_direction]
        > _DIRECTION_PRIORITY[compute_signal.sizing_direction]
    )

    if use_streaming and streaming_signal is not None:
        return RightsizingVerdict(
            sizing_direction=streaming_signal.sizing_direction,
            sizing_status=str(streaming_signal.capacity_status.value),
            recommended_action=streaming_signal.recommended_action,
            confidence=confidence,
            persistence_gate_passed=gate_passed,
            rationale=(
                f"Streaming capacity signal "
                f"'{streaming_signal.capacity_status.value}' outranks compute "
                f"'{compute_signal.sizing_reason.value}'."
            ),
        )

    action = compute_signal.recommended_action
    # Persistence-gated downsize upgrade (only for the moderate OVERPROVISIONED
    # reason; SEVERELY_OVERPROVISIONED already recommends a firm downsize).
    if (
        compute_signal.sizing_reason == SizingReason.OVERPROVISIONED
        and gate_passed
    ):
        action = RecommendedAction.DOWNSIZE_WORKERS

    rationale = (
        f"Compute sizing_reason '{compute_signal.sizing_reason.value}' "
        f"({compute_signal.sizing_direction.value})."
    )
    if gate_passed is not None:
        rationale += (
            f" Persistence gate {'passed' if gate_passed else 'not met'} "
            f"(days={observed_days}, ratio={persistence_ratio})."
        )

    return RightsizingVerdict(
        sizing_direction=compute_signal.sizing_direction,
        sizing_status=str(compute_signal.sizing_reason.value),
        recommended_action=action,
        target_cores_per_node=compute_signal.target_cores_per_node,
        target_gb_per_node=compute_signal.target_gb_per_node,
        binding_resource=compute_signal.binding_resource,
        reduction_pct=compute_signal.reduction_pct,
        confidence=confidence,
        persistence_gate_passed=gate_passed,
        rationale=rationale,
    )
