# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Regression tests for the jobs query pack (reliability failure-state handling).

Live prompt test: a workspace whose runs end ERROR / TIMED_OUT / CANCELLED (never
FAILED) reported 0% failures because C-J04/C-J05/C-J06 counted only 'FAILED'.
"""

from __future__ import annotations

import collections
import re

import pytest
from starboard.discovery.heuristics.jobs import JOB_RULES
from starboard.discovery.query_packs.jobs import _FAILURE_STATES_SQL, JOBS_PACK


def _render(sql: str, lookback: int = 30, result_limit: int = 50) -> str:
    """Mirror QueryPackExecutor._render_sql (defaultdict format_map)."""
    return sql.format_map(
        collections.defaultdict(
            str, {"lookback_days": lookback, "result_limit": result_limit}
        )
    )


def _q(query_id: str):
    return next(q for q in JOBS_PACK.queries if q.query_id == query_id)


_RELIABILITY = ("C-J04", "C-J05", "C-J06")


def test_failure_states_constant_covers_error_and_timeout() -> None:
    for state in ("FAILED", "ERROR", "TIMED_OUT"):
        assert f"'{state}'" in _FAILURE_STATES_SQL
    assert "CANCELLED" not in _FAILURE_STATES_SQL


@pytest.mark.parametrize("qid", _RELIABILITY)
def test_reliability_queries_use_failure_state_set(qid: str) -> None:
    sql = _render(_q(qid).sql_template)
    assert f"IN {_FAILURE_STATES_SQL}" in sql
    # No predicate may count only the bare 'FAILED' state.
    assert not re.search(r"=\s*'FAILED'", sql)
    assert "@FAILURE_STATES@" not in sql


@pytest.mark.parametrize("qid", _RELIABILITY)
def test_cancelled_reported_separately_not_as_failure(qid: str) -> None:
    sql = _render(_q(qid).sql_template)
    col = "cancelled_executions" if qid == "C-J06" else "cancelled_runs"
    assert col in sql
    assert "= 'CANCELLED'" in sql


@pytest.mark.parametrize("qid", [q.query_id for q in JOBS_PACK.queries])
def test_templates_render_without_leftover_placeholders(qid: str) -> None:
    sql = _render(_q(qid).sql_template)
    assert not re.search(r"\{[a-z_]+\}", sql), f"{qid} has unrendered placeholder"
    assert "@" not in sql


def test_cj04_no_lexicographic_max_of_result_state() -> None:
    sql = _q("C-J04").sql_template
    assert "MAX(result_state)" not in sql
    assert "MAX_BY(result_state, period_end_time)" in sql


def test_cj04_orders_by_signal_and_filters_clean_jobs() -> None:
    sql = _render(_q("C-J04").sql_template)
    assert "WHERE js.failures > 0 OR js.cancelled_runs > 0" in sql
    assert (
        "ORDER BY ds.failure_dbus DESC NULLS LAST, js.failures DESC, "
        "ds.total_dbus DESC NULLS LAST" in sql
    )


def test_cj04_keeps_downstream_columns() -> None:
    sql = _q("C-J04").sql_template
    for col in ("failure_rate_pct", "wasted_dbu_pct", "failure_dbus", "total_runs"):
        assert col in sql


def test_cj04_stays_off_the_task_run_table() -> None:
    """C-J04 feeds JOB-001 (High Failure Rate); it must NOT depend on
    job_task_run_timeline, or a workspace missing that table would lose
    failure-rate evidence, not just the retry signal (the retry signal lives in
    its own required=False query, C-J10)."""
    q = _q("C-J04")
    assert "system.lakeflow.job_task_run_timeline" not in q.sql_template
    assert "system.lakeflow.job_task_run_timeline" not in q.required_tables


def test_cj10_retry_signal_from_task_attempts() -> None:
    """JOB-002 reads retried_runs/total_runs from C-J10, derived from task
    attempts in job_task_run_timeline (distinct task-level run_id per job run /
    task_key) — NOT run-timeline row counts (the drift commit 4497df6 removed)."""
    q = _q("C-J10")
    sql = _render(q.sql_template)
    # required=False so a workspace without the task-run table degrades gracefully.
    assert q.required is False
    assert q.required_tables == (
        "system.lakeflow.job_task_run_timeline",
        "system.lakeflow.jobs",
    )
    # Retry = a task_key attempted more than once within one job run.
    assert "COUNT(DISTINCT run_id)" in sql and "AS attempts" in sql
    assert "CASE WHEN attempts > 1 THEN 1 ELSE 0 END" in sql
    # retried_runs and total_runs share one population → retry_rate_pct ∈ [0, 100].
    for col in ("total_runs", "retried_runs", "retry_rate_pct"):
        assert f"AS {col}" in sql
    assert "COUNT(DISTINCT rl.job_run_id)" in sql
    # ForEach iterations (parallel fan-out) must not count as retries.
    assert "parent_run_id = job_run_id" in sql
    # LIMIT must retain the highest-RATIO jobs (JOB-002's threshold is on ratio),
    # not the highest absolute retry count — order by retry_rate_pct first.
    assert "ORDER BY retry_rate_pct DESC" in sql
    # Minimum-runs floor: single-run ad-hoc jobs at a 100% "retry rate" are noise.
    assert "HAVING retried_runs > 0 AND total_runs >= 5" in sql


def test_cj03_ratio_ignores_instant_exit_runs() -> None:
    sql = _render(_q("C-J03").sql_template)
    assert "max_min_ratio" in sql and "min_runtime_mins" in sql
    assert "CASE WHEN jrd.duration_mins >= 1 THEN jrd.duration_mins END" in sql
    # ratio must not divide by the raw MIN
    assert "MIN(jrd.duration_mins))" not in sql


# ---------------------------------------------------------------------------
# W1 — timeline slicing: per-run durations must aggregate ALL periods
# ---------------------------------------------------------------------------
# job_run_timeline / job_task_run_timeline emit a long run as ~hourly period
# rows and set result_state only on the terminal one. Filtering
# ``result_state IS NOT NULL`` before the per-run GROUP BY kept only the last
# slice: a 3h run (periods 00:00-01:00, 01:00-02:00, 02:00-03:00, only the last
# carrying SUCCEEDED) read as 60 min, capping C-J03 max_runtime_mins at 59.9.


def _cte(sql: str, name: str) -> str:
    """Return the body of ``<name> AS ( ... )`` (paren-balanced)."""
    start = sql.index(f"{name} AS (") + len(f"{name} AS (")
    depth = 1
    for i in range(start, len(sql)):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return sql[start:i]
    raise AssertionError(f"unbalanced CTE {name}")


def _where_clause(cte_body: str) -> str:
    m = re.search(r"\bWHERE\b(.*?)\bGROUP BY\b", cte_body, re.S)
    assert m, "per-run CTE has no WHERE ... GROUP BY"
    return m.group(1)


_TERMINAL_STATE = "MAX_BY(result_state,\n           IF(result_state IS NOT NULL, period_end_time, NULL))"

_PER_RUN_CTES = (
    ("C-J03", "job_run_durations"),
    ("C-J06", "task_runs"),
    ("C-J08", "runs"),
    ("C-J09", "task_runs"),
)


@pytest.mark.parametrize(("qid", "cte"), _PER_RUN_CTES)
def test_per_run_cte_aggregates_all_periods(qid: str, cte: str) -> None:
    """A >1h multi-period run must not be truncated to its terminal slice."""
    body = _cte(_render(_q(qid).sql_template), cte)
    assert "result_state IS NOT NULL" not in _where_clause(body), (
        f"{qid}.{cte} filters terminal periods BEFORE grouping per run — "
        "runtimes cap at ~60 min"
    )
    assert "GROUP BY workspace_id, job_id, run_id" in body
    # Wall-clock over all periods, in seconds — not CAST(interval AS LONG).
    assert "MAX(period_end_time)" in body and "MIN(period_start_time)" in body
    assert "CAST(" not in body


@pytest.mark.parametrize("qid", ["C-J03", "C-J06", "C-J09"])
def test_terminal_state_via_max_by_over_non_null(qid: str) -> None:
    sql = _q(qid).sql_template
    assert _TERMINAL_STATE in sql
    assert "MAX(result_state)" not in sql


def test_cj03_runtime_is_wall_clock_seconds() -> None:
    body = _cte(_q("C-J03").sql_template, "job_run_durations")
    assert (
        "(UNIX_TIMESTAMP(MAX(period_end_time))\n"
        "       - UNIX_TIMESTAMP(MIN(period_start_time))) / 60.0" in body
    )
    # Completed-run filter applied after aggregation (outer SELECT), not inside.
    assert "WHERE jrd.result_state = 'SUCCEEDED'" in _q("C-J03").sql_template


def test_cj02_state_uses_latest_terminal_not_lexicographic_max() -> None:
    sql = _q("C-J02").sql_template
    assert "MAX(result_state)" not in sql
    assert "MAX_BY(result_state, period_end_time)" in sql


def test_cj06_duration_from_task_run_not_single_period() -> None:
    sql = _q("C-J06").sql_template
    assert "AVG(t.duration_secs)" in sql
    assert "period_end_time - t.period_start_time" not in sql
    assert "FROM task_runs t" in sql


# ---------------------------------------------------------------------------
# W26 — C-J03 total_dbus never NULL; dbus_attributed marks unattributed jobs
# ---------------------------------------------------------------------------


def test_cj03_total_dbus_coalesced_with_attribution_flag() -> None:
    sql = _q("C-J03").sql_template
    assert "ROUND(COALESCE(SUM(jd.run_dbus), 0), 2)" in sql
    assert "AS dbus_attributed" in sql


# ---------------------------------------------------------------------------
# W29 — C-J08 concurrent run overlap / C-J09 long-running tasks
# ---------------------------------------------------------------------------


def test_cj08_concurrency_sweep_shape() -> None:
    q = _q("C-J08")
    sql = _render(q.sql_template)
    assert q.required is False
    for col in (
        "trigger_type",
        "max_concurrent_runs",
        "job_max_concurrent_runs",
        "avg_concurrent_runs",
        "avg_other_runs_overlapping_each_run",
        "max_other_runs_overlapping_one_run",
        "runs_started_while_running",
        "overlapped_hours",
        "job_overlapped_hours",
        "trigger_dbus",
        "avg_dbus_per_run",
        "job_total_dbus",
        "dbus_attributed",
    ):
        assert col in sql
    # Ends sort before starts at a tie so back-to-back runs don't overlap.
    assert "ORDER BY ts, delta" in sql
    assert "PARTITION BY workspace_id, job_id" in sql
    assert "WHERE jp.job_max_concurrent_runs > 1" in sql
    assert "LIMIT 50" in sql


def test_cj08_splits_by_trigger_type() -> None:
    """D6: scheduler overlap (CRON) must not be blended with ONETIME backfills.

    Live evidence: the #1 job's 520 ONETIME backfill runs (~50 DBU/run) folded
    into its hourly CRON runs made the blended per-run DBU look like it FELL
    while scheduled runs went 224 -> 388 DBU/run.
    """
    sql = _render(_q("C-J08").sql_template)
    # Overlap sweep + per-run stats are computed within one trigger type.
    assert "PARTITION BY workspace_id, job_id, trigger_type" in sql
    assert "GROUP BY r.workspace_id, r.job_id, r.trigger_type" in sql
    assert "MAX_BY(trigger_type, period_start_time)" in sql
    # Per-run DBU is joined per run (not a job-level total / run count).
    assert "usage_metadata.job_run_id" in sql
    assert "AVG(d.run_dbus)" in sql


def test_cj08_job_total_dbus_not_a_summable_total_dbus() -> None:
    """C4: the job-level DBU repeats on every trigger row, so it must not be
    named ``total_dbus`` (summing CRON + ONETIME rows double-counts); the
    per-row split stays ``trigger_dbus``."""
    q = _q("C-J08")
    sql = _render(q.sql_template)
    assert "AS job_total_dbus,\n" in sql
    assert "AS total_dbus" not in sql
    assert "AS trigger_dbus" in sql
    assert "job_total_dbus DESC" in sql
    assert "job_total_dbus" in q.metadata.output_hint
    assert "never sum" in q.metadata.output_hint


def test_cj08_no_ambiguous_overlap_column_names() -> None:
    """The lifetime overlap count must not be nameable as 'concurrent runs'."""
    sql = _render(_q("C-J08").sql_template)
    assert "overlapping_runs_per_run" not in sql
    hint = _q("C-J08").metadata.output_hint
    assert "not simultaneous runs" in hint


def test_job_billing_reads_are_dbu_only() -> None:
    """D7: every billing.usage read in the jobs pack filters usage_unit = 'DBU'."""
    for q in JOBS_PACK.queries:
        sql = q.sql_template
        if "system.billing.usage" in sql:
            assert sql.count("usage_unit = 'DBU'") >= sql.count(
                "FROM system.billing.usage"
            ), q.query_id


def test_cj09_long_tasks_ranked_by_task_hours() -> None:
    q = _q("C-J09")
    sql = _render(q.sql_template)
    assert q.required is False
    assert "GROUP BY workspace_id, job_id, run_id, task_key" in sql
    for col in ("p50_duration_mins", "p95_duration_mins", "total_task_hours"):
        assert col in sql
    assert "ORDER BY total_task_hours DESC" in sql
    assert "LIMIT 50" in sql


def test_new_query_ids_do_not_reuse_retired_cj07() -> None:
    # C-J07 was the (moved) DLT query; heuristics still key DLT findings off it.
    ids = [q.query_id for q in JOBS_PACK.queries]
    assert "C-J07" not in ids
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Issue #19 — heuristic/query evidence-column drift guard
# ---------------------------------------------------------------------------
# A heuristic that reads a column its evidence query no longer emits is dead
# code: its guard short-circuits on every run and the check silently never
# fires. This happened to JOB-002 when C-J04 dropped retried_runs (4497df6).
# Jobs heuristics pin the columns they consume in ``evidence_columns``; the
# guard below asserts each is actually produced, so the drift fails CI loudly.

_JOBS_PACK_QUERY_IDS = {q.query_id for q in JOBS_PACK.queries}

_EVIDENCE_COLUMN_CASES = [
    (rule.rule_id, qid, col)
    for rule in JOB_RULES
    for qid, cols in getattr(rule, "evidence_columns", {}).items()
    if qid in _JOBS_PACK_QUERY_IDS
    for col in cols
]


def test_evidence_column_cases_are_non_vacuous() -> None:
    """At least one jobs heuristic pins its evidence columns, so the
    parametrized drift guard below is not silently empty."""
    assert _EVIDENCE_COLUMN_CASES
    # JOB-002 is the regression that motivated the guard.
    assert ("JOB-002", "C-J10", "retried_runs") in _EVIDENCE_COLUMN_CASES


@pytest.mark.parametrize(
    ("rule_id", "query_id", "column"),
    _EVIDENCE_COLUMN_CASES,
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_heuristic_evidence_columns_are_produced(
    rule_id: str, query_id: str, column: str
) -> None:
    """Every column a jobs heuristic consumes must be emitted by its evidence
    query (issue #19). A dropped ``AS <col>`` alias fails here instead of
    silently disabling the rule."""
    sql = _render(_q(query_id).sql_template)
    assert re.search(rf"\bAS {re.escape(column)}\b", sql), (
        f"{rule_id} consumes '{column}' from {query_id}, but {query_id} does not "
        f"emit it (no `AS {column}` alias). Restore the column in the query or "
        f"update the heuristic's evidence_columns."
    )
