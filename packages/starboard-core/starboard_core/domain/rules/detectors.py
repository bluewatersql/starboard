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

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from starboard_core.domain.models.finding import Location, Severity

# --- Detection thresholds (reviewable constants) -------------------------- #
# W-W02: fraction of running time spent idle (no queries) that flags an
# oversized auto-stop window.
AUTO_STOP_WASTE_PCT_THRESHOLD = 50.0
# W-W01: the utilization band the query itself labels as under-utilized.
UNDER_UTILIZED_BAND = "Under-utilized"
# C-Q02: shuffle volume (GiB) that flags a wide-projection / SELECT * candidate.
SHUFFLE_GB_THRESHOLD = 10.0
# C-Q02: an unqualified ``SELECT *`` / ``SELECT DISTINCT *`` projection in the
# statement text (``COUNT(*)`` and ``t.*`` never match; ``EXISTS (SELECT * ...)``
# is excluded by the look-behind).
_SELECT_STAR_RE = re.compile(
    r"(?<!exists\s\()(?<!exists\()\bselect\s+(?:distinct\s+)?\*",
    re.IGNORECASE,
)
# C-Q02: partition-pruning ratio below which pruning is effectively not working
# (a non-sargable partition predicate reads far more partitions than needed).
PRUNING_RATIO_THRESHOLD = 0.10
# C-Q02: minimum partitions read before poor pruning is worth flagging.
READ_PARTITIONS_THRESHOLD = 100
# C-J04: run failure rate (%) at/above which a job is flagged unreliable.
JOB_FAILURE_RATE_PCT_THRESHOLD = 20.0
# C-J04: minimum runs before a failure *rate* is a pattern rather than one
# failed run. Below it, only a material failure (see below) is reported.
JOB_FAILURE_MIN_RUNS_THRESHOLD = 3
# C-J04: failure DBU (list-price estimate) at/above which failures are material.
# Severity is ``high`` only when the rate is high over enough runs AND material.
JOB_FAILURE_MATERIAL_DBU_THRESHOLD = 10.0
# C-J04: failure DBU at/above which a material failure gets the top impact (5).
JOB_FAILURE_MAJOR_DBU_THRESHOLD = 100.0
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
# --- Phase-2 X4: Portfolio Readiness (workload-maturity) domain ----------- #
# Window DBU (list-price estimate) at/above which a single workload's consumption
# is treated as "production-scale" — the maturity model's boundary between a
# pilot/exploratory workload and a production one. Rationale + tuning guidance
# live in docs/reference/portfolio_readiness.md.
PORTFOLIO_PRODUCTION_DBU_THRESHOLD = 100.0
# C-B01: minimum unattributed DBU (list-price estimate) before untracked
# consumption is worth flagging — a noise floor so trivial spend is ignored.
PORTFOLIO_UNTRACKED_MIN_DBU_THRESHOLD = 50.0
# C-J04: run failure rate (%) at/above which a production-scale workload has not
# reached the reliable, optimized maturity stage. Deliberately stricter than the
# jobs-domain acute-failure threshold: the optimized stage demands sustained
# reliability, not merely the absence of an outage.
PORTFOLIO_MATURITY_MAX_ERROR_RATE_PCT = 10.0
# C-B01: the user_type label the consumption query assigns when a usage record
# has no attributable run-as identity.
PORTFOLIO_UNATTRIBUTED_USER_TYPE = "Unattributed"
# --- W-W01: warehouse capacity queueing (catalog OPP-WH-QUEUE) ------------ #
# Share (%) of a warehouse's queries that waited at capacity worth flagging.
WAREHOUSE_QUEUED_PCT_THRESHOLD = 10.0
# Average capacity wait (seconds) worth flagging even below the queued share.
WAREHOUSE_AVG_WAIT_SECS_THRESHOLD = 10.0
# The wait-only trigger also needs at least this queued share (when measured):
# avg_capacity_wait_secs may average only the queued subset, so a few outlier
# waits on an otherwise unqueued warehouse must not fire.
WAREHOUSE_WAIT_TRIGGER_MIN_QUEUED_PCT = 1.0
# Minimum queries in the window before queueing is meaningful.
WAREHOUSE_QUEUE_MIN_QUERIES = 1000
# Severity escalates to ``high`` at/above either of these on a busy warehouse.
WAREHOUSE_QUEUED_PCT_HIGH = 25.0
WAREHOUSE_AVG_WAIT_SECS_HIGH = 30.0
# Query volume at/above which strong queueing is ``high`` severity.
WAREHOUSE_QUEUE_HIGH_VOLUME_QUERIES = 10000
# --- Catalog alignment: overlap / wait tasks / recent resize / step change - #
# C-J08 (OPP-JOB-OVERLAP): trigger types whose overlap is scheduler pile-up.
JOB_OVERLAP_TRIGGER_TYPES = "CRON"
# Share (%) of a trigger type's runs that started while another run was active.
JOB_OVERLAP_STARTED_WHILE_RUNNING_PCT = 10.0
# Peak simultaneous runs (within the trigger type) that make it an overlap.
JOB_OVERLAP_MIN_CONCURRENT_RUNS = 2
# Minimum runs of the trigger type before the share is a pattern.
JOB_OVERLAP_MIN_RUNS = 5
# Share (%) at/above which overlap is ``high`` severity.
JOB_OVERLAP_HIGH_STARTED_WHILE_RUNNING_PCT = 50.0
# C-J09 (OPP-JOB-WAIT-TASK): wait/poll/sensor-shaped task keys.
JOB_WAIT_TASK_PATTERN = "wait|poll|sensor|readiness"
# Task-hours in the window at/above which a wait task is material.
JOB_WAIT_TASK_MIN_HOURS = 10.0
# Task-hours at/above which a wait task is ``high`` severity.
JOB_WAIT_TASK_HIGH_HOURS = 100.0
# W-W07 (OPP-WH-RESIZE): a config change this many days old or newer is recent.
WAREHOUSE_RECENT_CHANGE_DAYS = 7
# W-W01 queueing (share %, avg wait secs) that makes a recent change relevant.
WAREHOUSE_RESIZE_QUEUED_PCT = 5.0
WAREHOUSE_RESIZE_AVG_WAIT_SECS = 10.0
# W-W05 per-day execution-time change (%) T7 vs T28 that makes it relevant.
WAREHOUSE_RESIZE_EXEC_CHANGE_PCT = 25.0
# F-03 (OPP-STEP-CHANGE): 7-day mean daily-DBU lift that counts as a step.
SPEND_STEP_MIN_LIFT_PCT = 20.0
SPEND_STEP_MIN_LIFT_DAILY_DBUS = 100.0
SPEND_STEP_HIGH_LIFT_PCT = 50.0
# Days averaged either side of a candidate step date (matches discovery facts).
SPEND_STEP_SPAN_DAYS = 7


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
        severity: Per-trigger severity override (``None`` = the rule default).
        impact: Per-trigger impact override 1-5 (``None`` = the rule default).
    """

    row_index: int
    row: dict[str, Any]
    current_state: str
    location: Location
    entity_key: str
    severity: Severity | None = None
    impact: int | None = None


# A detector inspects an evidence query's rows and returns the triggering rows.
# Detectors that read rule ``params`` accept them as an optional second argument;
# the evaluator passes them only when the rule declares any.
Detector = Callable[..., list[RowMatch]]


def _param(params: Mapping[str, Any] | None, key: str, default: float) -> float:
    """Numeric rule param ``key`` (else ``default``; never raises)."""
    if not params:
        return default
    value = _as_float(params.get(key))
    return default if value is None else value


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


# Identity values that mean "no attributable owner" (see the finops attribution
# reference: null run_as falls back to a system/unattributed sentinel).
_UNATTRIBUTED_OWNERS = frozenset({"", "null", "none", "unattributed", "system"})


def _is_missing_owner(value: Any) -> bool:
    """True when an owner/run-as value is absent or an unattributed sentinel."""
    if value is None:
        return True
    return str(value).strip().lower() in _UNATTRIBUTED_OWNERS


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


def detect_warehouse_queueing(
    rows: Sequence[dict[str, Any]],
    params: Mapping[str, Any] | None = None,
) -> list[RowMatch]:
    """Flag warehouses whose queries queue behind full capacity (OPP-WH-QUEUE).

    Evidence: ``W-W01`` (``queued_query_pct`` = share of queries with
    ``waiting_at_capacity_duration_ms > 0``; ``avg_capacity_wait_secs``;
    ``total_queries``). Triggers on a warehouse with ``>= min_queries`` queries
    when ``queued_query_pct >= queued_pct`` or ``avg_capacity_wait_secs >=
    avg_wait_secs``. ``avg_capacity_wait_secs`` can be an average over only the
    queued subset, so the wait-only trigger also needs ``queued_query_pct >=
    wait_trigger_min_queued_pct`` when the share is measured (a handful of
    outlier waits is not a capacity problem).

    Severity: ``high`` (impact 4) at ``>= high_volume_queries`` queries with
    ``queued_query_pct >= high_queued_pct``, or a wait ``>= high_avg_wait_secs``
    alongside a triggering queued share; otherwise the rule default.

    Degrades gracefully: rows without the queueing columns (or without
    ``total_queries``) produce no finding.
    """
    queued_min = _param(params, "queued_pct", WAREHOUSE_QUEUED_PCT_THRESHOLD)
    wait_min = _param(params, "avg_wait_secs", WAREHOUSE_AVG_WAIT_SECS_THRESHOLD)
    wait_floor = _param(
        params, "wait_trigger_min_queued_pct", WAREHOUSE_WAIT_TRIGGER_MIN_QUEUED_PCT
    )
    min_queries = _param(params, "min_queries", WAREHOUSE_QUEUE_MIN_QUERIES)
    queued_high = _param(params, "high_queued_pct", WAREHOUSE_QUEUED_PCT_HIGH)
    wait_high = _param(params, "high_avg_wait_secs", WAREHOUSE_AVG_WAIT_SECS_HIGH)
    high_volume = _param(
        params, "high_volume_queries", WAREHOUSE_QUEUE_HIGH_VOLUME_QUERIES
    )

    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        queued = _as_float(row.get("queued_query_pct"))
        wait = _as_float(row.get("avg_capacity_wait_secs"))
        queries = _as_float(row.get("total_queries"))
        if (queued is None and wait is None) or queries is None:
            continue
        if queries < min_queries:
            continue
        share_trigger = queued is not None and queued >= queued_min
        wait_trigger = (
            wait is not None
            and wait >= wait_min
            and (queued is None or queued >= wait_floor)
        )
        if not (share_trigger or wait_trigger):
            continue

        severity: Severity | None = None
        impact: int | None = None
        if queries >= high_volume and (
            (queued is not None and queued >= queued_high)
            or (share_trigger and wait is not None and wait >= wait_high)
        ):
            severity, impact = Severity.HIGH, 4

        wid = _entity(row, "warehouse_id", fallback=f"row-{idx}")
        parts = []
        if queued is not None:
            parts.append(f"{queued:g}% of its {queries:g} queries queued at capacity")
        else:
            parts.append(f"{queries:g} queries")
        if wait is not None:
            parts.append(f"average capacity wait {wait:g}s")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Warehouse {wid}: {', '.join(parts)} — demand exceeds the "
                    "warehouse's cluster capacity, so queries wait before running."
                ),
                location=Location(entity=wid, entity_type="warehouse"),
                entity_key=wid,
                severity=severity,
                impact=impact,
            )
        )
    return matches


def detect_select_star_projection(
    rows: Sequence[dict[str, Any]],
    params: Mapping[str, Any] | None = None,
) -> list[RowMatch]:
    """Flag large-shuffle queries whose statement text is an unqualified SELECT *.

    Evidence: ``C-Q02`` (multi-signal optimization candidates). Triggers when
    ``shuffle_gb >=`` the ``shuffle_gb`` param (default ``SHUFFLE_GB_THRESHOLD``)
    AND the row's ``statement_text`` contains an unqualified ``SELECT *``
    projection. A row without statement text never fires: a shuffle volume alone
    does not support a projection claim. (The evaluator additionally suppresses
    the whole rule when no evidence row carries statement text — see the rule's
    ``requires_column`` param.)
    """
    threshold = _param(params, "shuffle_gb", SHUFFLE_GB_THRESHOLD)
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        shuffle = _as_float(row.get("shuffle_gb"))
        if shuffle is None or shuffle < threshold:
            continue
        text = row.get("statement_text")
        if not isinstance(text, str) or not _SELECT_STAR_RE.search(text):
            continue
        sid = _entity(row, "statement_id", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Query {sid} uses an unqualified SELECT * and shuffled "
                    f"{shuffle:g} GiB — the wide projection scans and shuffles "
                    "columns the query may never use."
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


def _grade_job_failures(
    row: dict[str, Any],
    params: Mapping[str, Any] | None,
    *,
    base_impact: int,
) -> tuple[Severity, int] | None:
    """Grade a C-J04 failure trigger by run count and failure-DBU materiality.

    * enough runs (``>= min_runs``) and material failure DBU
      (``>= material_failure_dbu``) → ``high``, ``base_impact`` (+1 at
      ``>= major_failure_dbu``, capped at 5);
    * too few runs but material failure DBU → ``medium`` (one costly failure,
      not yet a pattern);
    * enough runs, failure DBU known but immaterial → ``low``, impact 2;
    * enough runs, failure DBU not reported → ``medium``, impact 3;
    * too few runs and not material (or unknown) → ``None`` (no finding).

    A missing ``total_runs`` counts as enough runs, so an absent column never
    drops a finding on its own.
    """
    min_runs = _param(params, "min_runs", JOB_FAILURE_MIN_RUNS_THRESHOLD)
    material_dbu = _param(
        params, "material_failure_dbu", JOB_FAILURE_MATERIAL_DBU_THRESHOLD
    )
    major_dbu = _param(params, "major_failure_dbu", JOB_FAILURE_MAJOR_DBU_THRESHOLD)
    runs = _as_float(row.get("total_runs"))
    failure_dbu = _as_float(row.get("failure_dbus"))
    enough_runs = runs is None or runs >= min_runs
    if failure_dbu is not None and failure_dbu >= material_dbu:
        if not enough_runs:
            return Severity.MEDIUM, 3
        bump = 1 if failure_dbu >= major_dbu else 0
        return Severity.HIGH, min(5, base_impact + bump)
    if not enough_runs:
        return None  # one or two cheap failed runs: not a reliability pattern
    if failure_dbu is not None:
        return Severity.LOW, 2
    return Severity.MEDIUM, 3


def _failure_dbu_txt(row: dict[str, Any]) -> str:
    failure_dbu = _as_float(row.get("failure_dbus"))
    if failure_dbu is None:
        return ""
    return f" ({failure_dbu:g} DBU on failed runs, list-price DBU estimate)"


def detect_job_high_failure_rate(
    rows: Sequence[dict[str, Any]],
    params: Mapping[str, Any] | None = None,
) -> list[RowMatch]:
    """Flag jobs whose run failure rate exceeds the reliability threshold.

    Evidence: ``C-J04`` (compound reliability scorecard). Triggers when
    ``failure_rate_pct`` is at/above the ``failure_rate_pct`` param (default
    ``JOB_FAILURE_RATE_PCT_THRESHOLD``); severity and impact are graded by
    :func:`_grade_job_failures` (run count + failure-DBU materiality).
    """
    rate_min = _param(params, "failure_rate_pct", JOB_FAILURE_RATE_PCT_THRESHOLD)
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        rate = _as_float(row.get("failure_rate_pct"))
        if rate is None or rate < rate_min:
            continue
        grade = _grade_job_failures(row, params, base_impact=4)
        if grade is None:
            continue
        jid = _entity(row, "job_id", "job_name", fallback=f"row-{idx}")
        runs = _as_float(row.get("total_runs"))
        runs_txt = f" across {runs:g} runs" if runs is not None else ""
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Job {jid} failed {rate:g}% of its runs{runs_txt}"
                    f"{_failure_dbu_txt(row)} — a high failure rate that re-runs "
                    "compute without delivering output."
                ),
                location=Location(entity=jid, entity_type="job"),
                entity_key=jid,
                severity=grade[0],
                impact=grade[1],
            )
        )
    return matches


def detect_job_wasted_dbu_on_failures_retries(
    rows: Sequence[dict[str, Any]],
    params: Mapping[str, Any] | None = None,
) -> list[RowMatch]:
    """Flag jobs burning a large share of DBU on failed / retried runs.

    Evidence: ``C-J04``. Triggers when ``wasted_dbu_pct`` (failed-run DBU as a
    share of total) is at/above the ``wasted_dbu_pct`` param (default
    ``JOB_WASTED_DBU_PCT_THRESHOLD``); graded like the failure-rate rule by
    :func:`_grade_job_failures`, so a 100% share of 0.01 DBU is not ``high``.
    """
    wasted_min = _param(params, "wasted_dbu_pct", JOB_WASTED_DBU_PCT_THRESHOLD)
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        wasted = _as_float(row.get("wasted_dbu_pct"))
        if wasted is None or wasted < wasted_min:
            continue
        grade = _grade_job_failures(row, params, base_impact=3)
        if grade is None:
            continue
        jid = _entity(row, "job_id", "job_name", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Job {jid} spent {wasted:g}% of its DBU on failed "
                    f"runs{_failure_dbu_txt(row)} — compute paid for with no "
                    "successful output."
                ),
                location=Location(entity=jid, entity_type="job"),
                entity_key=jid,
                severity=grade[0],
                impact=grade[1],
            )
        )
    return matches


def detect_job_high_runtime_variance(
    rows: Sequence[dict[str, Any]],
    params: Mapping[str, Any] | None = None,
) -> list[RowMatch]:
    """Flag jobs whose successful runtime swings widely run-to-run.

    Evidence: ``C-J03`` (runtime variance). Triggers when ``max_min_ratio`` is
    at or above the ``max_min_ratio`` param (default
    ``JOB_RUNTIME_VARIANCE_RATIO_THRESHOLD``) and the job has at least ``min_runs``
    (default ``JOB_RUNTIME_MIN_RUNS_THRESHOLD``) successful runs.
    """
    ratio_threshold = _param(
        params, "max_min_ratio", JOB_RUNTIME_VARIANCE_RATIO_THRESHOLD
    )
    min_runs = _param(params, "min_runs", JOB_RUNTIME_MIN_RUNS_THRESHOLD)
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        ratio = _as_float(row.get("max_min_ratio"))
        if ratio is None or ratio < ratio_threshold:
            continue
        runs = _as_float(row.get("total_runs"))
        if runs is not None and runs < min_runs:
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


# --- Phase-2 X4: Portfolio Readiness (workload-maturity) detectors -------- #
def detect_portfolio_untracked_production_consumption(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag unattributed, production-scale consumption (an untracked workload).

    Evidence: ``C-B01`` (DBU by workspace x product x identity). Triggers when
    ``user_type == PORTFOLIO_UNATTRIBUTED_USER_TYPE`` (no attributable run-as
    identity) and ``dbus_consumed >= PORTFOLIO_UNTRACKED_MIN_DBU_THRESHOLD``.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        if row.get("user_type") != PORTFOLIO_UNATTRIBUTED_USER_TYPE:
            continue
        dbus = _as_float(row.get("dbus_consumed"))
        if dbus is None or dbus < PORTFOLIO_UNTRACKED_MIN_DBU_THRESHOLD:
            continue
        workspace = _entity(row, "workspace_id", fallback=f"row-{idx}")
        product = _entity(row, "billing_origin_product", fallback="unknown-product")
        key = f"{workspace}:{product}"
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"{product} consumption in workspace {workspace} billed "
                    f"{dbus:g} DBU (list-price estimate) with no attributable "
                    "identity — untracked production-scale consumption with no "
                    "owner or cost attribution."
                ),
                location=Location(entity=key, entity_type="workspace"),
                entity_key=key,
            )
        )
    return matches


def detect_portfolio_unattended_production_job(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag production-scale jobs with no attributable owner (run-as identity).

    Evidence: ``C-J01`` (job DBU leaderboard). Triggers when ``total_dbus >=
    PORTFOLIO_PRODUCTION_DBU_THRESHOLD`` and the job's ``run_as`` identity is
    missing or unattributed.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        dbus = _as_float(row.get("total_dbus"))
        if dbus is None or dbus < PORTFOLIO_PRODUCTION_DBU_THRESHOLD:
            continue
        if not _is_missing_owner(row.get("run_as")):
            continue
        jid = _entity(row, "name", "job_id", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Job {jid} consumed {dbus:g} DBU (list-price estimate) at "
                    "production scale but has no attributable run-as owner — "
                    "mature in consumption, immature in governance."
                ),
                location=Location(entity=jid, entity_type="job"),
                entity_key=jid,
            )
        )
    return matches


def detect_portfolio_unreliable_production_workload(
    rows: Sequence[dict[str, Any]],
) -> list[RowMatch]:
    """Flag production-scale jobs whose failure rate blocks the optimized stage.

    Evidence: ``C-J04`` (compound reliability scorecard). Triggers when
    ``total_dbus >= PORTFOLIO_PRODUCTION_DBU_THRESHOLD`` and ``failure_rate_pct
    >= PORTFOLIO_MATURITY_MAX_ERROR_RATE_PCT`` — production-scale spend that is
    not yet reliable enough to be considered optimized.
    """
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        dbus = _as_float(row.get("total_dbus"))
        if dbus is None or dbus < PORTFOLIO_PRODUCTION_DBU_THRESHOLD:
            continue
        rate = _as_float(row.get("failure_rate_pct"))
        if rate is None or rate < PORTFOLIO_MATURITY_MAX_ERROR_RATE_PCT:
            continue
        jid = _entity(row, "job_name", "job_id", fallback=f"row-{idx}")
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Job {jid} consumed {dbus:g} DBU (list-price estimate) at "
                    f"production scale yet failed {rate:g}% of its runs — "
                    "production-scale spend that has not reached a reliable, "
                    "optimized maturity stage."
                ),
                location=Location(entity=jid, entity_type="job"),
                entity_key=jid,
            )
        )
    return matches


# --- Catalog alignment detectors ------------------------------------------ #
def _param_str(params: Mapping[str, Any] | None, key: str, default: str) -> str:
    """String rule param ``key`` (else ``default``; never raises)."""
    value = (params or {}).get(key)
    return value if isinstance(value, str) and value.strip() else default


def detect_job_cron_overlap(
    rows: Sequence[dict[str, Any]],
    params: Mapping[str, Any] | None = None,
) -> list[RowMatch]:
    """Flag scheduled jobs whose runs start while a previous run is still active.

    Evidence: ``C-J08`` (one row per job x ``trigger_type``). Triggers on a row
    whose ``trigger_type`` is in ``trigger_types`` (comma list, default CRON)
    with ``total_runs >= min_runs``, ``max_concurrent_runs >=
    min_concurrent_runs`` and ``runs_started_while_running / total_runs`` at or
    above ``started_while_running_pct``. Severity ``high`` at
    ``high_started_while_running_pct``. Rows without the overlap columns produce
    no finding.
    """
    triggers = {
        t.strip().upper()
        for t in _param_str(params, "trigger_types", JOB_OVERLAP_TRIGGER_TYPES).split(",")
        if t.strip()
    }
    share_min = _param(
        params, "started_while_running_pct", JOB_OVERLAP_STARTED_WHILE_RUNNING_PCT
    )
    conc_min = _param(params, "min_concurrent_runs", JOB_OVERLAP_MIN_CONCURRENT_RUNS)
    runs_min = _param(params, "min_runs", JOB_OVERLAP_MIN_RUNS)
    share_high = _param(
        params,
        "high_started_while_running_pct",
        JOB_OVERLAP_HIGH_STARTED_WHILE_RUNNING_PCT,
    )
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        trigger = str(row.get("trigger_type") or "").upper()
        if trigger not in triggers:
            continue
        runs = _as_float(row.get("total_runs"))
        started = _as_float(row.get("runs_started_while_running"))
        peak = _as_float(row.get("max_concurrent_runs"))
        if runs is None or started is None or peak is None or runs <= 0:
            continue
        if runs < runs_min or peak < conc_min:
            continue
        share = 100.0 * started / runs
        if share < share_min:
            continue
        jid = _entity(row, "job_id", "job_name", fallback=f"row-{idx}")
        avg = _as_float(row.get("avg_run_mins"))
        avg_txt = f"; average run {avg:g} min" if avg is not None else ""
        high = share >= share_high
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Job {jid}: {started:g} of {runs:g} {trigger} runs ({share:.1f}%) "
                    f"started while another run was still active (peak "
                    f"{peak:g} at once{avg_txt}) — scheduled runs stack up and "
                    "each bills its own compute."
                ),
                location=Location(entity=jid, entity_type="job"),
                entity_key=jid,
                severity=Severity.HIGH if high else None,
                impact=4 if high else None,
            )
        )
    return matches


def detect_job_wait_tasks(
    rows: Sequence[dict[str, Any]],
    params: Mapping[str, Any] | None = None,
) -> list[RowMatch]:
    """Flag wait / poll / sensor-shaped tasks that hold compute for many hours.

    Evidence: ``C-J09`` (long-running tasks). Triggers when ``task_key`` matches
    ``task_key_pattern`` (case-insensitive regex) and ``total_task_hours`` is at
    or above ``min_task_hours``; ``high`` at ``high_task_hours``.
    """
    try:
        pattern = re.compile(
            _param_str(params, "task_key_pattern", JOB_WAIT_TASK_PATTERN), re.IGNORECASE
        )
    except re.error:
        pattern = re.compile(JOB_WAIT_TASK_PATTERN, re.IGNORECASE)
    hours_min = _param(params, "min_task_hours", JOB_WAIT_TASK_MIN_HOURS)
    hours_high = _param(params, "high_task_hours", JOB_WAIT_TASK_HIGH_HOURS)
    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        task_key = row.get("task_key")
        if not isinstance(task_key, str) or not pattern.search(task_key):
            continue
        hours = _as_float(row.get("total_task_hours"))
        if hours is None or hours < hours_min:
            continue
        jid = _entity(row, "job_id", "job_name", fallback=f"row-{idx}")
        runs = _as_float(row.get("task_runs"))
        p50 = _as_float(row.get("p50_duration_mins"))
        detail = ""
        if runs is not None and p50 is not None:
            detail = f" over {runs:g} task runs (p50 {p50:g} min)"
        high = hours >= hours_high
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=(
                    f"Job {jid} task '{task_key}' looks like a wait/poll step and "
                    f"held compute for {hours:g} task-hours{detail} — a cluster "
                    "kept running while the task waits."
                ),
                location=Location(entity=jid, entity_type="job"),
                entity_key=f"{jid}:{task_key}",
                severity=Severity.HIGH if high else None,
                impact=4 if high else None,
            )
        )
    return matches


def _parse_day(value: Any) -> date | None:
    """``YYYY-MM-DD`` prefix of a date/timestamp cell as a ``date`` (else None)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _rows_by_warehouse(
    context: Mapping[str, Sequence[dict[str, Any]]] | None, query_id: str
) -> dict[str, dict[str, Any]] | None:
    """Context rows of ``query_id`` keyed by ``warehouse_id`` (None when absent)."""
    if not context or query_id not in context:
        return None
    return {
        str(r["warehouse_id"]): r
        for r in context[query_id]
        if isinstance(r, dict) and r.get("warehouse_id") is not None
    }


def _change_list(value: Any) -> list[str]:
    """``recent_changes`` as a list of strings (JSON-array string or list)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and str(v).strip()]
    return []


def detect_warehouse_recent_resize(
    rows: Sequence[dict[str, Any]],
    params: Mapping[str, Any] | None = None,
    context: Mapping[str, Sequence[dict[str, Any]]] | None = None,
) -> list[RowMatch]:
    """Flag warehouses whose config changed recently while load was moving.

    Evidence: ``W-W07`` (config history: ``last_change_time``,
    ``recent_changes``). A change at most ``recent_days`` old (vs ``as_of``, an
    ISO date param; default today UTC) on a warehouse that also shows queueing
    in ``W-W01`` (``queued_query_pct >= queued_pct`` or
    ``avg_capacity_wait_secs >= avg_wait_secs``) or a per-day execution-time
    change in ``W-W05`` (T7 vs T28, ``|Δ| >= exec_change_pct``). The change is
    too new to judge, so the finding asks to measure it before acting again.

    Degrades: when neither context query has a row for the warehouse, the
    recent change alone is reported at ``low`` severity (load not measured).
    """
    recent_days = _param(params, "recent_days", WAREHOUSE_RECENT_CHANGE_DAYS)
    queued_min = _param(params, "queued_pct", WAREHOUSE_RESIZE_QUEUED_PCT)
    wait_min = _param(params, "avg_wait_secs", WAREHOUSE_RESIZE_AVG_WAIT_SECS)
    exec_min = _param(params, "exec_change_pct", WAREHOUSE_RESIZE_EXEC_CHANGE_PCT)
    as_of = _parse_day((params or {}).get("as_of")) or datetime.now(UTC).date()
    utilization = _rows_by_warehouse(context, "W-W01")
    trend = _rows_by_warehouse(context, "W-W05")

    matches: list[RowMatch] = []
    for idx, row in enumerate(rows):
        if row.get("delete_time"):
            continue
        changed = _parse_day(row.get("last_change_time"))
        if changed is None or not (0 <= (as_of - changed).days <= recent_days):
            continue
        wid = _entity(row, "warehouse_id", fallback=f"row-{idx}")
        signals: list[str] = []
        measured = False
        util = (utilization or {}).get(wid)
        if util is not None:
            measured = True
            queued = _as_float(util.get("queued_query_pct"))
            wait = _as_float(util.get("avg_capacity_wait_secs"))
            if (queued is not None and queued >= queued_min) or (
                wait is not None and wait >= wait_min
            ):
                signals.append(
                    f"{queued if queued is not None else '?'}% of queries queued, "
                    f"average capacity wait {wait if wait is not None else '?'}s"
                )
        tr = (trend or {}).get(wid)
        if tr is not None:
            t7 = _as_float(tr.get("exec_secs_t7"))
            t28 = _as_float(tr.get("exec_secs_t28"))
            if t7 is not None and t28 is not None and t28 > 0:
                measured = True
                change = 100.0 * ((t7 / 7.0) / (t28 / 28.0) - 1.0)
                if abs(change) >= exec_min:
                    signals.append(
                        f"daily execution time {change:+.0f}% (last 7 vs 28 days)"
                    )
        if measured and not signals:
            continue
        changes = _change_list(row.get("recent_changes"))
        change_txt = f" ({'; '.join(changes[-3:])})" if changes else ""
        if signals:
            state = (
                f"Warehouse {wid} changed configuration on {changed.isoformat()}"
                f"{change_txt} while {' and '.join(signals)} — the change is too "
                "recent to judge; measure it before resizing again."
            )
            severity: Severity | None = None
        else:
            state = (
                f"Warehouse {wid} changed configuration on {changed.isoformat()}"
                f"{change_txt}; queueing and load change were not measured — "
                "measure the change before resizing again."
            )
            severity = Severity.LOW
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(row),
                current_state=state,
                location=Location(entity=wid, entity_type="warehouse"),
                entity_key=wid,
                severity=severity,
                impact=2 if severity is Severity.LOW else None,
            )
        )
    return matches


def _step_for_workspace(
    daily: dict[date, float], window: list[date], span: int
) -> tuple[date, float, float] | None:
    """Largest ``span``-day mean lift day in ``window`` → ``(day, before, after)``."""
    if not window:
        return None
    start, end = min(window), max(window)
    best: tuple[float, date, float, float] | None = None
    d = start
    while d <= end - timedelta(days=span - 1):
        before = sum(daily.get(d - timedelta(days=i), 0.0) for i in range(1, span + 1))
        after = sum(daily.get(d + timedelta(days=i), 0.0) for i in range(span))
        lift = (after - before) / span
        if best is None or lift > best[0]:  # strict: earliest date wins ties
            best = (lift, d, before / span, after / span)
        d += timedelta(days=1)
    if best is None or best[0] <= 0:
        return None
    return best[1], best[2], best[3]


def detect_spend_step_change(
    rows: Sequence[dict[str, Any]],
    params: Mapping[str, Any] | None = None,
) -> list[RowMatch]:
    """Flag a workspace whose daily DBU stepped up within the window.

    Evidence: ``F-03`` (daily DBU per workspace: the window plus a 7-day
    baseline, ``in_window`` flag). Per workspace, the same method as the
    discovery facts ``step_change``: the window day with the largest lift of
    the 7-day mean daily DBU (``d..d+6``) over the 7 days before it (missing
    day = 0; ties → earliest). Triggers when the lift is at least
    ``min_lift_daily_dbus`` and ``min_lift_pct`` of the before mean; ``high`` at
    ``high_lift_pct``. Without ``in_window`` the first 7 days are the baseline.
    Cites the step-date row. DBU are list-price DBU estimates.
    """
    span = int(_param(params, "span_days", SPEND_STEP_SPAN_DAYS))
    pct_min = _param(params, "min_lift_pct", SPEND_STEP_MIN_LIFT_PCT)
    dbu_min = _param(params, "min_lift_daily_dbus", SPEND_STEP_MIN_LIFT_DAILY_DBUS)
    pct_high = _param(params, "high_lift_pct", SPEND_STEP_HIGH_LIFT_PCT)
    if span < 1:
        return []

    by_ws: dict[str, dict[date, float]] = {}
    in_window: dict[str, set[date]] = {}
    flagged: set[str] = set()
    first_row: dict[tuple[str, date], int] = {}
    for idx, row in enumerate(rows):
        day = _parse_day(row.get("usage_date"))
        dbus = _as_float(row.get("dbus"))
        if day is None or dbus is None:
            continue
        ws = _entity(row, "workspace_id", fallback="workspace")
        by_ws.setdefault(ws, {})
        by_ws[ws][day] = by_ws[ws].get(day, 0.0) + dbus
        first_row.setdefault((ws, day), idx)
        if "in_window" in row:
            flagged.add(ws)
            if _is_truthy(row.get("in_window")):
                in_window.setdefault(ws, set()).add(day)

    matches: list[RowMatch] = []
    for ws in sorted(by_ws):
        daily = by_ws[ws]
        if ws in flagged:
            window = sorted(in_window.get(ws, set()))
        else:
            days = sorted(daily)
            window = [d for d in days if d >= days[0] + timedelta(days=span)]
        step = _step_for_workspace(daily, window, span)
        if step is None:
            continue
        day, before, after = step
        lift = after - before
        pct = 100.0 * lift / before if before > 0 else None
        if lift < dbu_min or (pct is not None and pct < pct_min):
            continue
        high = pct is None or pct >= pct_high
        pct_txt = f", +{pct:.0f}%" if pct is not None else ""
        idx = first_row.get((ws, day), 0)
        matches.append(
            RowMatch(
                row_index=idx,
                row=dict(rows[idx]),
                current_state=(
                    f"Workspace {ws} daily DBU stepped up on {day.isoformat()}: "
                    f"{span}-day mean {before:,.0f} → {after:,.0f} DBU/day "
                    f"(+{lift:,.0f}{pct_txt}; list-price DBU estimate) — find the "
                    "workloads that changed on that date."
                ),
                location=Location(entity=ws, entity_type="workspace"),
                entity_key=ws,
                severity=Severity.HIGH if high else None,
                impact=4 if high else None,
            )
        )
    return matches


# Registry of detectors keyed by ``rule.id``. Rules absent here produce no
# findings (graceful no-op) rather than naive one-finding-per-row noise.
DETECTORS: dict[str, Detector] = {
    "warehouse_auto_stop_disabled": detect_warehouse_auto_stop_disabled,
    "warehouse_persistently_underutilized": detect_warehouse_persistently_underutilized,
    "warehouse_queueing": detect_warehouse_queueing,
    "select_star_projection": detect_select_star_projection,
    "non_sargable_partition_filter": detect_non_sargable_partition_filter,
    "job_high_failure_rate": detect_job_high_failure_rate,
    "job_wasted_dbu_on_failures_retries": detect_job_wasted_dbu_on_failures_retries,
    "job_high_runtime_variance": detect_job_high_runtime_variance,
    # Catalog alignment (OPP-JOB-OVERLAP / OPP-JOB-WAIT-TASK / OPP-WH-RESIZE /
    # OPP-STEP-CHANGE).
    "job_cron_overlap": detect_job_cron_overlap,
    "job_wait_tasks": detect_job_wait_tasks,
    "warehouse_recent_resize": detect_warehouse_recent_resize,
    "spend_step_change": detect_spend_step_change,
    # Phase-2 D-a: DLT / ML / vector-search review domains.
    "dlt_high_pipeline_failure_rate": detect_dlt_high_pipeline_failure_rate,
    "dlt_stale_pipeline": detect_dlt_stale_pipeline,
    "dlt_classic_compute_serverless_candidate": detect_dlt_classic_compute_serverless_candidate,
    "ml_test_demo_endpoint_cleanup": detect_ml_test_demo_endpoint_cleanup,
    "ml_noisy_experiment": detect_ml_noisy_experiment,
    "vector_search_idle_endpoint": detect_vector_search_idle_endpoint,
    "vector_search_high_cost_endpoint": detect_vector_search_high_cost_endpoint,
    # Phase-2 X4: Portfolio Readiness (workload-maturity) review domain.
    "portfolio_untracked_production_consumption": detect_portfolio_untracked_production_consumption,
    "portfolio_unattended_production_job": detect_portfolio_unattended_production_job,
    "portfolio_unreliable_production_workload": detect_portfolio_unreliable_production_workload,
}


__all__ = [
    "AUTO_STOP_WASTE_PCT_THRESHOLD",
    "PRUNING_RATIO_THRESHOLD",
    "READ_PARTITIONS_THRESHOLD",
    "SHUFFLE_GB_THRESHOLD",
    "UNDER_UTILIZED_BAND",
    "JOB_FAILURE_RATE_PCT_THRESHOLD",
    "JOB_FAILURE_MIN_RUNS_THRESHOLD",
    "JOB_FAILURE_MATERIAL_DBU_THRESHOLD",
    "JOB_FAILURE_MAJOR_DBU_THRESHOLD",
    "JOB_WASTED_DBU_PCT_THRESHOLD",
    "WAREHOUSE_QUEUED_PCT_THRESHOLD",
    "WAREHOUSE_AVG_WAIT_SECS_THRESHOLD",
    "WAREHOUSE_QUEUE_MIN_QUERIES",
    "WAREHOUSE_WAIT_TRIGGER_MIN_QUEUED_PCT",
    "WAREHOUSE_QUEUED_PCT_HIGH",
    "WAREHOUSE_AVG_WAIT_SECS_HIGH",
    "WAREHOUSE_QUEUE_HIGH_VOLUME_QUERIES",
    "JOB_RUNTIME_VARIANCE_RATIO_THRESHOLD",
    "JOB_RUNTIME_MIN_RUNS_THRESHOLD",
    "DLT_PIPELINE_FAILURE_RATE_PCT_THRESHOLD",
    "DLT_PIPELINE_MIN_UPDATES_THRESHOLD",
    "DLT_STALE_PIPELINE_DAYS_THRESHOLD",
    "DLT_SERVERLESS_CANDIDATE_DBU_THRESHOLD",
    "ML_CLEANUP_ENDPOINT_TYPE",
    "ML_CLEANUP_MIN_DBU_THRESHOLD",
    "VECTOR_SEARCH_HIGH_COST_DBU_THRESHOLD",
    "PORTFOLIO_PRODUCTION_DBU_THRESHOLD",
    "PORTFOLIO_UNTRACKED_MIN_DBU_THRESHOLD",
    "PORTFOLIO_MATURITY_MAX_ERROR_RATE_PCT",
    "PORTFOLIO_UNATTRIBUTED_USER_TYPE",
    "JOB_OVERLAP_TRIGGER_TYPES",
    "JOB_OVERLAP_STARTED_WHILE_RUNNING_PCT",
    "JOB_OVERLAP_MIN_CONCURRENT_RUNS",
    "JOB_OVERLAP_MIN_RUNS",
    "JOB_OVERLAP_HIGH_STARTED_WHILE_RUNNING_PCT",
    "JOB_WAIT_TASK_PATTERN",
    "JOB_WAIT_TASK_MIN_HOURS",
    "JOB_WAIT_TASK_HIGH_HOURS",
    "WAREHOUSE_RECENT_CHANGE_DAYS",
    "WAREHOUSE_RESIZE_QUEUED_PCT",
    "WAREHOUSE_RESIZE_AVG_WAIT_SECS",
    "WAREHOUSE_RESIZE_EXEC_CHANGE_PCT",
    "SPEND_STEP_MIN_LIFT_PCT",
    "SPEND_STEP_MIN_LIFT_DAILY_DBUS",
    "SPEND_STEP_HIGH_LIFT_PCT",
    "SPEND_STEP_SPAN_DAYS",
    "DETECTORS",
    "Detector",
    "RowMatch",
    "detect_non_sargable_partition_filter",
    "detect_select_star_projection",
    "detect_warehouse_auto_stop_disabled",
    "detect_warehouse_persistently_underutilized",
    "detect_warehouse_queueing",
    "detect_job_high_failure_rate",
    "detect_job_wasted_dbu_on_failures_retries",
    "detect_job_high_runtime_variance",
    "detect_job_cron_overlap",
    "detect_job_wait_tasks",
    "detect_warehouse_recent_resize",
    "detect_spend_step_change",
    "detect_dlt_high_pipeline_failure_rate",
    "detect_dlt_stale_pipeline",
    "detect_dlt_classic_compute_serverless_candidate",
    "detect_ml_test_demo_endpoint_cleanup",
    "detect_ml_noisy_experiment",
    "detect_vector_search_idle_endpoint",
    "detect_vector_search_high_cost_endpoint",
    "detect_portfolio_untracked_production_consumption",
    "detect_portfolio_unattended_production_job",
    "detect_portfolio_unreliable_production_workload",
]
