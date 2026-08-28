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
# --- Phase-2 D-a: DLT / ML / vector-search review domains ----------------- #
# P-DLT03: pipeline update failure rate (%) at/above which a pipeline is flagged.
DLT_PIPELINE_FAILURE_RATE_PCT_THRESHOLD = 20.0
# P-DLT03: minimum updates before a failure rate is worth flagging.
DLT_PIPELINE_MIN_UPDATES_THRESHOLD = 5
# P-DLT01: days since last update at/above which a pipeline is flagged stale.
DLT_STALE_PIPELINE_DAYS_THRESHOLD = 60
# P-DLT05: classic-pipeline billed DBU at/above which serverless is worth evaluating.
DLT_SERVERLESS_CANDIDATE_DBU_THRESHOLD = 50.0
# C-ML01: the endpoint_type label the classification query uses for cleanup.
ML_CLEANUP_ENDPOINT_TYPE = "Test/Demo (cleanup candidate)"
# C-ML01: minimum billed DBU before a test/demo endpoint is worth flagging.
ML_CLEANUP_MIN_DBU_THRESHOLD = 1.0
# P-VS01: endpoint total DBU at/above which it is a right-sizing review target.
VECTOR_SEARCH_HIGH_COST_DBU_THRESHOLD = 100.0


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


def _is_truthy(value: Any) -> bool:
    """True for ``True`` / positive numbers / the string ``"true"`` (never raises).

    Used for boolean-flag columns (e.g. ``is_noisy``) that may arrive as a
    Python ``bool`` from a DataFrame or as a rendered string.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


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


# --- Phase-2 D-a: DLT / pipelines detectors ------------------------------- #
def detect_dlt_high_pipeline_failure_rate(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag pipelines whose update failure rate exceeds the review threshold.

    Evidence: ``P-DLT03`` (pipeline health scorecard). Triggers when
    ``failure_rate_pct >= DLT_PIPELINE_FAILURE_RATE_PCT_THRESHOLD`` over at least
    ``DLT_PIPELINE_MIN_UPDATES_THRESHOLD`` updates (enough to be meaningful).
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        rate = _as_float(row.get("failure_rate_pct"))
        if rate is None or rate < DLT_PIPELINE_FAILURE_RATE_PCT_THRESHOLD:
            continue
        updates = _as_float(row.get("total_updates"))
        if updates is not None and updates < DLT_PIPELINE_MIN_UPDATES_THRESHOLD:
            continue
        pid = _entity(row, "pipeline_name", "pipeline_id", fallback=f"row-{idx}")
        updates_txt = f" across {updates:g} updates" if updates is not None else ""
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Pipeline {pid} failed {rate:g}% of its updates{updates_txt} "
                    "— a high failure rate that re-runs compute and leaves target "
                    "tables stale."
                ),
                location=Location(entity=pid, entity_type="pipeline"),
                entity_key=pid,
            )
        )
    return matches


def detect_dlt_stale_pipeline(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag pipelines with no updates for longer than the staleness threshold.

    Evidence: ``P-DLT01`` (stale pipelines). Triggers when
    ``days_since_last_update >= DLT_STALE_PIPELINE_DAYS_THRESHOLD``.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        days = _as_float(row.get("days_since_last_update"))
        if days is None or days < DLT_STALE_PIPELINE_DAYS_THRESHOLD:
            continue
        pid = _entity(row, "pipeline_name", "pipeline_id", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Pipeline {pid} has not updated in {days:g} days — a cleanup "
                    "or governance candidate."
                ),
                location=Location(entity=pid, entity_type="pipeline"),
                entity_key=pid,
            )
        )
    return matches


def detect_dlt_classic_compute_serverless_candidate(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag classic-compute pipelines with real spend to evaluate for serverless.

    Evidence: ``P-DLT05`` (serverless migration candidates). Triggers when the
    pipeline is classic (``is_serverless_config`` falsy) and its billed ``dbus``
    is at/above ``DLT_SERVERLESS_CANDIDATE_DBU_THRESHOLD``.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        if _is_truthy(row.get("is_serverless_config")):
            continue  # already serverless — not a candidate
        dbus = _as_float(row.get("dbus"))
        if dbus is None or dbus < DLT_SERVERLESS_CANDIDATE_DBU_THRESHOLD:
            continue
        pid = _entity(row, "pipeline_name", "pipeline_id", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Pipeline {pid} runs on classic compute with {dbus:g} DBU of "
                    "billed usage — worth evaluating against serverless "
                    "(list-price DBU estimate)."
                ),
                location=Location(entity=pid, entity_type="pipeline"),
                entity_key=pid,
            )
        )
    return matches


# --- Phase-2 D-a: ML / model-serving detectors ---------------------------- #
def detect_ml_test_demo_endpoint_cleanup(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag billed test/demo serving endpoints as cleanup candidates.

    Evidence: ``C-ML01`` (model-serving classification). Triggers when
    ``endpoint_type == ML_CLEANUP_ENDPOINT_TYPE`` and ``total_dbus`` is at/above
    ``ML_CLEANUP_MIN_DBU_THRESHOLD``.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        if row.get("endpoint_type") != ML_CLEANUP_ENDPOINT_TYPE:
            continue
        dbus = _as_float(row.get("total_dbus"))
        if dbus is None or dbus < ML_CLEANUP_MIN_DBU_THRESHOLD:
            continue
        name = _entity(row, "endpoint_name", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Endpoint {name} is classified as a test/demo cleanup "
                    f"candidate yet still billed {dbus:g} DBU "
                    "(list-price DBU estimate)."
                ),
                location=Location(entity=name, entity_type="serving_endpoint"),
                entity_key=name,
            )
        )
    return matches


def detect_ml_noisy_experiment(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag MLflow experiments the reliability query marks noisy.

    Evidence: ``P-MLF04`` (experiment reliability + noise). Triggers when
    ``is_noisy`` is truthy (a high run count with a sub-threshold success ratio).
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        if not _is_truthy(row.get("is_noisy")):
            continue
        name = _entity(row, "experiment_name", "experiment_id", fallback=f"row-{idx}")
        runs = _as_float(row.get("run_count"))
        ratio = _as_float(row.get("success_ratio"))
        detail = ""
        if runs is not None and ratio is not None:
            detail = f" ({runs:g} runs at a {ratio:.0%} success ratio)"
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Experiment {name} is noisy{detail} — many runs with a low "
                    "success ratio that waste compute and bury useful results."
                ),
                location=Location(entity=name, entity_type="experiment"),
                entity_key=name,
            )
        )
    return matches


# --- Phase-2 D-a: Vector Search detectors --------------------------------- #
def detect_vector_search_idle_endpoint(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag Vector Search endpoints that bill but serve no queries.

    Evidence: ``P-VS03`` (idle endpoints). The query already returns only billed
    endpoints with no query activity; this fires when the endpoint shows any
    billed storage or serving quantity.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        storage = _as_float(row.get("storage_quantity")) or 0.0
        serving = _as_float(row.get("serving_quantity")) or 0.0
        if storage <= 0.0 and serving <= 0.0:
            continue
        name = _entity(row, "endpoint_name", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Endpoint {name} billed capacity (storage {storage:g}, "
                    f"serving {serving:g}) with no query activity in the window "
                    "— idle capacity to remove."
                ),
                location=Location(entity=name, entity_type="vector_search_endpoint"),
                entity_key=name,
            )
        )
    return matches


def detect_vector_search_high_cost_endpoint(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag the highest-DBU Vector Search endpoints as right-sizing review targets.

    Evidence: ``P-VS01`` (endpoint billing history). Triggers when
    ``total_dbus >= VECTOR_SEARCH_HIGH_COST_DBU_THRESHOLD``.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        dbus = _as_float(row.get("total_dbus"))
        if dbus is None or dbus < VECTOR_SEARCH_HIGH_COST_DBU_THRESHOLD:
            continue
        name = _entity(row, "endpoint_name", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Endpoint {name} consumed {dbus:g} DBU in the window "
                    "(list-price DBU estimate) — a top right-sizing review target."
                ),
                location=Location(entity=name, entity_type="vector_search_endpoint"),
                entity_key=name,
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
    # Phase-2 D-a: DLT / ML / vector-search review domains.
    "dlt_high_pipeline_failure_rate": detect_dlt_high_pipeline_failure_rate,
    "dlt_stale_pipeline": detect_dlt_stale_pipeline,
    "dlt_classic_compute_serverless_candidate": detect_dlt_classic_compute_serverless_candidate,
    "ml_test_demo_endpoint_cleanup": detect_ml_test_demo_endpoint_cleanup,
    "ml_noisy_experiment": detect_ml_noisy_experiment,
    "vector_search_idle_endpoint": detect_vector_search_idle_endpoint,
    "vector_search_high_cost_endpoint": detect_vector_search_high_cost_endpoint,
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
    "DLT_PIPELINE_FAILURE_RATE_PCT_THRESHOLD",
    "DLT_PIPELINE_MIN_UPDATES_THRESHOLD",
    "DLT_STALE_PIPELINE_DAYS_THRESHOLD",
    "DLT_SERVERLESS_CANDIDATE_DBU_THRESHOLD",
    "ML_CLEANUP_ENDPOINT_TYPE",
    "ML_CLEANUP_MIN_DBU_THRESHOLD",
    "VECTOR_SEARCH_HIGH_COST_DBU_THRESHOLD",
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
    "detect_dlt_high_pipeline_failure_rate",
    "detect_dlt_stale_pipeline",
    "detect_dlt_classic_compute_serverless_candidate",
    "detect_ml_test_demo_endpoint_cleanup",
    "detect_ml_noisy_experiment",
    "detect_vector_search_idle_endpoint",
    "detect_vector_search_high_cost_endpoint",
]
