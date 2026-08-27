# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Deterministic rule detectors over query-pack rows (Phase-3 D1b).

Each seed rule (Phase-1 D3) carries a free-text ``detect`` hint and an
``evidence_query`` naming the query-pack query that supplies its evidence. D1b
turns those into **deterministic** detection: a detector is a pure function that
inspects the evidence query's rows and returns the rows that trigger the rule.
The Workload Review engine (D1c is the model council — out of scope here) then
wraps each trigger into a scored :class:`~starboard_core.domain.models.finding.Finding`.

Detectors are keyed by ``rule.id`` and read the **real output columns** of the
evidence query (e.g. ``W-W02.auto_stop_waste_pct``). A rule with no registered
detector produces no findings — the engine degrades gracefully rather than
emitting naive, un-triaged noise. Thresholds are module constants so they are
easy to review and tune.

Kernel-clean: pure Python + the kernel ``Location`` model — no
``databricks-sdk`` / ``openai`` / ``fastapi`` / ``mcp``, no ``polars`` (rows
arrive as plain dicts materialized by the server tier).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from starboard_core.domain.models.finding import Location

# --- Detection thresholds (reviewable constants) -------------------------- #
# W-W02: fraction of running time spent idle (no queries) that flags an
# oversized auto-stop window.
AUTO_STOP_WASTE_PCT_THRESHOLD = 50.0
# W-W01: the utilization band the query itself labels as under-utilized.
UNDER_UTILIZED_BAND = "Under-utilized"
# C-Q02: shuffle volume (GiB) that flags a wide-projection / SELECT * candidate.
SHUFFLE_GB_THRESHOLD = 10.0
# C-Q02: partition-pruning ratio below which pruning is effectively not working
# (a non-sargable partition predicate reads far more partitions than needed).
PRUNING_RATIO_THRESHOLD = 0.10
# C-Q02: minimum partitions read before poor pruning is worth flagging.
READ_PARTITIONS_THRESHOLD = 100
# C-J04: run failure rate (%) at/above which a job is flagged unreliable.
JOB_FAILURE_RATE_PCT_THRESHOLD = 20.0
# C-J04: share (%) of total DBU burned on failed/retried runs worth flagging.
JOB_WASTED_DBU_PCT_THRESHOLD = 25.0
# C-J03: max/min successful-runtime ratio at/above which variance is flagged.
JOB_RUNTIME_VARIANCE_RATIO_THRESHOLD = 3.0
# C-J03: minimum successful runs before runtime variance is worth flagging.
JOB_RUNTIME_MIN_RUNS_THRESHOLD = 5


@dataclass(frozen=True)
class RowMatch:
    """A single row that triggered a rule, plus how to cite/locate it.

    Args:
        row_index: 0-based position of the row within the evidence query result.
        row: The triggering row (verbatim), used as the evidence citation.
        current_state: Paraphrased observed-state text for the finding
            (the "bad" state this row demonstrates).
        location: Where the finding applies (entity id + kind).
        entity_key: Stable identifier for this match within the rule, used to
            build a unique, deterministic finding id.
    """

    row_index: int
    row: dict[str, Any]
    current_state: str
    location: Location
    entity_key: str


# A detector inspects an evidence query's rows and returns the triggering rows.
Detector = Callable[[Sequence[dict[str, Any]]], list[RowMatch]]


def _as_float(value: Any) -> float | None:
    """Coerce a cell to ``float`` when numeric, else ``None`` (never raises)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _entity(row: dict[str, Any], *keys: str, fallback: str) -> str:
    """First present, non-null identifier among ``keys`` (else ``fallback``)."""
    for key in keys:
        value = row.get(key)
        if value is not None and str(value) != "":
            return str(value)
    return fallback


# --- Per-rule detectors --------------------------------------------------- #
def detect_warehouse_auto_stop_disabled(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag warehouses whose idle-running waste exceeds the auto-stop threshold.

    Evidence: ``W-W02`` (auto-stop efficiency / waste). Triggers when
    ``auto_stop_waste_pct >= AUTO_STOP_WASTE_PCT_THRESHOLD``.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        waste = _as_float(row.get("auto_stop_waste_pct"))
        if waste is None or waste < AUTO_STOP_WASTE_PCT_THRESHOLD:
            continue
        wid = _entity(row, "warehouse_id", fallback=f"row-{idx}")
        idle = _as_float(row.get("idle_running_hours"))
        idle_txt = f"{idle:g}h idle" if idle is not None else "idle time"
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Warehouse {wid} spent {waste:g}% of its running time "
                    f"({idle_txt}) with zero queries — auto-stop is effectively "
                    "disabled or set too long."
                ),
                location=Location(entity=wid, entity_type="warehouse"),
                entity_key=wid,
            )
        )
    return matches


def detect_warehouse_persistently_underutilized(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag warehouses the utilization query labels ``Under-utilized``.

    Evidence: ``W-W01`` (utilization bands). Triggers when
    ``utilization_band == UNDER_UTILIZED_BAND``.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        band = row.get("utilization_band")
        if band != UNDER_UTILIZED_BAND:
            continue
        wid = _entity(row, "warehouse_id", fallback=f"row-{idx}")
        ratio = _as_float(row.get("utilization_ratio"))
        ratio_txt = (
            f"a {ratio:.0%} busy/running ratio"
            if ratio is not None
            else "a low busy/running ratio"
        )
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Warehouse {wid} sits in the '{UNDER_UTILIZED_BAND}' band "
                    f"with {ratio_txt} across the window — capacity exceeds demand."
                ),
                location=Location(entity=wid, entity_type="warehouse"),
                entity_key=wid,
            )
        )
    return matches


def detect_select_star_projection(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag optimization-candidate queries with large shuffle (wide projection).

    Evidence: ``C-Q02`` (multi-signal optimization candidates). Triggers when
    ``shuffle_gb >= SHUFFLE_GB_THRESHOLD`` — a wide projection forces the engine
    to scan and shuffle columns the query never uses.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        shuffle = _as_float(row.get("shuffle_gb"))
        if shuffle is None or shuffle < SHUFFLE_GB_THRESHOLD:
            continue
        sid = _entity(row, "statement_id", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Query {sid} shuffled {shuffle:g} GiB — consistent with a "
                    "wide projection (SELECT *) that scans and shuffles unused "
                    "columns."
                ),
                location=Location(entity=sid, entity_type="query"),
                entity_key=sid,
            )
        )
    return matches


def detect_non_sargable_partition_filter(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag queries whose partition pruning is effectively not working.

    Evidence: ``C-Q02``. Triggers when ``pruning_ratio < PRUNING_RATIO_THRESHOLD``
    while reading at least ``READ_PARTITIONS_THRESHOLD`` partitions — the
    signature of a non-sargable partition predicate that defeats pruning.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        pruning = _as_float(row.get("pruning_ratio"))
        partitions = _as_float(row.get("read_partitions"))
        if pruning is None or pruning >= PRUNING_RATIO_THRESHOLD:
            continue
        if partitions is None or partitions < READ_PARTITIONS_THRESHOLD:
            continue
        sid = _entity(row, "statement_id", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Query {sid} read {partitions:g} partitions at a "
                    f"{pruning:.0%} pruning ratio — partition pruning is not "
                    "applying, the hallmark of a non-sargable partition filter."
                ),
                location=Location(entity=sid, entity_type="query"),
                entity_key=sid,
            )
        )
    return matches


def detect_job_high_failure_rate(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag jobs whose run failure rate exceeds the reliability threshold.

    Evidence: ``C-J04`` (compound reliability scorecard). Triggers when
    ``failure_rate_pct >= JOB_FAILURE_RATE_PCT_THRESHOLD``.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        rate = _as_float(row.get("failure_rate_pct"))
        if rate is None or rate < JOB_FAILURE_RATE_PCT_THRESHOLD:
            continue
        jid = _entity(row, "job_id", "job_name", fallback=f"row-{idx}")
        runs = _as_float(row.get("total_runs"))
        runs_txt = f" across {runs:g} runs" if runs is not None else ""
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Job {jid} failed {rate:g}% of its runs{runs_txt} — a high "
                    "failure rate that re-runs compute without delivering output."
                ),
                location=Location(entity=jid, entity_type="job"),
                entity_key=jid,
            )
        )
    return matches


def detect_job_wasted_dbu_on_failures_retries(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag jobs burning a large share of DBU on failed / retried runs.

    Evidence: ``C-J04``. Triggers when ``wasted_dbu_pct`` (failure + retry DBU
    as a share of total) ``>= JOB_WASTED_DBU_PCT_THRESHOLD``.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        wasted = _as_float(row.get("wasted_dbu_pct"))
        if wasted is None or wasted < JOB_WASTED_DBU_PCT_THRESHOLD:
            continue
        jid = _entity(row, "job_id", "job_name", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Job {jid} spent {wasted:g}% of its DBU on failed or retried "
                    "runs — compute paid for repeatedly with no successful output."
                ),
                location=Location(entity=jid, entity_type="job"),
                entity_key=jid,
            )
        )
    return matches


def detect_job_high_runtime_variance(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag jobs whose successful runtime swings widely run-to-run.

    Evidence: ``C-J03`` (runtime variance). Triggers when ``max_min_ratio >=
    JOB_RUNTIME_VARIANCE_RATIO_THRESHOLD`` and the job has at least
    ``JOB_RUNTIME_MIN_RUNS_THRESHOLD`` successful runs (enough to be meaningful).
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        ratio = _as_float(row.get("max_min_ratio"))
        if ratio is None or ratio < JOB_RUNTIME_VARIANCE_RATIO_THRESHOLD:
            continue
        runs = _as_float(row.get("total_runs"))
        if runs is not None and runs < JOB_RUNTIME_MIN_RUNS_THRESHOLD:
            continue
        jid = _entity(row, "job_id", "name", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Job {jid} has a {ratio:g}x spread between its slowest and "
                    "fastest successful runs — unpredictable to schedule and size."
                ),
                location=Location(entity=jid, entity_type="job"),
                entity_key=jid,
            )
        )
    return matches


# Registry of detectors keyed by ``rule.id``. Rules absent here produce no
# findings (graceful no-op) rather than naive one-finding-per-row noise.
DETECTORS: dict[str, Detector] = {
    "warehouse_auto_stop_disabled": detect_warehouse_auto_stop_disabled,
    "warehouse_persistently_underutilized": detect_warehouse_persistently_underutilized,
    "select_star_projection": detect_select_star_projection,
    "non_sargable_partition_filter": detect_non_sargable_partition_filter,
    "job_high_failure_rate": detect_job_high_failure_rate,
    "job_wasted_dbu_on_failures_retries": detect_job_wasted_dbu_on_failures_retries,
    "job_high_runtime_variance": detect_job_high_runtime_variance,
}


__all__ = [
    "AUTO_STOP_WASTE_PCT_THRESHOLD",
    "PRUNING_RATIO_THRESHOLD",
    "READ_PARTITIONS_THRESHOLD",
    "SHUFFLE_GB_THRESHOLD",
    "UNDER_UTILIZED_BAND",
    "JOB_FAILURE_RATE_PCT_THRESHOLD",
    "JOB_WASTED_DBU_PCT_THRESHOLD",
    "JOB_RUNTIME_VARIANCE_RATIO_THRESHOLD",
    "JOB_RUNTIME_MIN_RUNS_THRESHOLD",
    "DETECTORS",
    "Detector",
    "RowMatch",
    "detect_non_sargable_partition_filter",
    "detect_select_star_projection",
    "detect_warehouse_auto_stop_disabled",
    "detect_warehouse_persistently_underutilized",
    "detect_job_high_failure_rate",
    "detect_job_wasted_dbu_on_failures_retries",
    "detect_job_high_runtime_variance",
]
