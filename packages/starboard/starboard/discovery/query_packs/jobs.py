# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Job workload and reliability query pack for Databricks discovery.

Job DBU consumption, reliability scoring, failure analysis, DLT pipeline performance.
Gated on JOBS product. All queries use DBU metrics only; no dollar computations.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

# Terminal result_state values that count as a FAILURE. Documented values of
# system.lakeflow.job_run_timeline.result_state / job_task_run_timeline.result_state
# (Databricks "Jobs system table reference"): SUCCEEDED, FAILED, ERROR, TIMED_OUT,
# CANCELLED, SKIPPED (+ BLOCKED). Real workspaces emit ERROR and TIMED_OUT for
# failed runs, so counting only 'FAILED' reports a false 0% failure rate.
# 'TIMEDOUT' is the pipeline-timeline spelling, accepted defensively. CANCELLED is
# a user/platform stop, NOT a failure: it is reported separately. SKIPPED/BLOCKED
# never executed and are counted as neither.
# Single source of truth: templates carry the ``@FAILURE_STATES@`` token (not a
# ``{...}`` placeholder, so it survives ``format_map``) and are resolved below.
_FAILURE_STATES_SQL = "('FAILED', 'ERROR', 'TIMED_OUT', 'TIMEDOUT')"


def _with_failure_states(sql: str) -> str:
    return sql.replace("@FAILURE_STATES@", _FAILURE_STATES_SQL)


# Timeline slicing (W1). system.lakeflow.job_run_timeline / job_task_run_timeline
# emit a long run as several ~hourly period rows, and set result_state ONLY on the
# terminal period(s). Any per-run duration MUST therefore aggregate ALL periods of
# the run — filtering ``result_state IS NOT NULL`` before grouping keeps only the
# last slice and caps every runtime at ~60 min. Convention used across the packs:
#   * runtime  = wall-clock UNIX_TIMESTAMP(MAX(period_end_time))
#                - UNIX_TIMESTAMP(MIN(period_start_time))   (seconds)
#   * terminal = MAX_BY(result_state, IF(result_state IS NOT NULL,
#                                        period_end_time, NULL))
#     (MAX_BY skips NULL orderings, so this is the state of the latest period
#     that carries one; NULL for a still-running run.)
# A "completed runs only" filter (``... IS NOT NULL``) is applied AFTER this
# per-run aggregation, never inside it. Runs that began before the lookback
# cutoff are left-censored (their pre-cutoff periods fall outside the window).


C_J01_SQL = """\
WITH dbu_per_job AS (
  SELECT
    t1.workspace_id,
    t1.usage_metadata.job_id                       AS job_id,
    COUNT(DISTINCT t1.usage_metadata.job_run_id)   AS runs,
    ROUND(SUM(t1.usage_quantity), 2)               AS total_dbus,
    FIRST(t1.identity_metadata.run_as, TRUE)       AS run_as,
    FIRST(t1.custom_tags, TRUE)                    AS custom_tags,
    MAX(t1.usage_end_time)                         AS last_seen_date
  FROM system.billing.usage t1
  WHERE t1.billing_origin_product = 'JOBS'
    AND t1.usage_unit = 'DBU'
    AND t1.usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY ALL
),
most_recent_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
)
SELECT
  t2.name,
  t1.job_id,
  t1.workspace_id,
  t1.runs,
  t1.run_as,
  t1.total_dbus,
  ROUND(TRY_DIVIDE(t1.total_dbus, t1.runs), 2)    AS avg_dbus_per_run,
  t1.last_seen_date
FROM dbu_per_job t1
LEFT JOIN most_recent_jobs t2 USING (workspace_id, job_id)
-- DBU leaderboard: rank by total spend so the highest-consumption jobs survive
-- the LIMIT (consumers — incl. the portfolio-readiness review — filter on
-- total_dbus, not per-run average). avg_dbus_per_run remains an output column.
ORDER BY total_dbus DESC
LIMIT {result_limit}
"""

C_J02_SQL = """\
WITH dbu_per_run AS (
  SELECT
    t1.workspace_id,
    t1.usage_metadata.job_id                     AS job_id,
    t1.usage_metadata.job_run_id                 AS run_id,
    ROUND(SUM(t1.usage_quantity), 2)             AS run_dbus,
    FIRST(t1.identity_metadata.run_as, TRUE)     AS run_as,
    MIN(t1.usage_start_time)                     AS first_seen,
    MAX(t1.usage_end_time)                       AS last_seen
  FROM system.billing.usage t1
  WHERE t1.billing_origin_product = 'JOBS'
    AND t1.usage_unit = 'DBU'
    AND t1.usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY ALL
),
most_recent_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
),
run_states AS (
  -- State-only (no duration): result_state is set on terminal periods, so
  -- filtering to them is safe here. MAX_BY by period_end_time picks the LATEST
  -- terminal state (a lexicographic MAX is wrong when a run carries several).
  SELECT workspace_id, job_id, run_id,
    MAX_BY(result_state, period_end_time) AS result_state
  FROM system.lakeflow.job_run_timeline
  WHERE result_state IS NOT NULL
  GROUP BY workspace_id, job_id, run_id
)
SELECT
  j.name,
  r.workspace_id,
  r.job_id,
  r.run_id,
  r.run_as,
  rs.result_state,
  r.run_dbus,
  TIMESTAMPDIFF(MINUTE, r.first_seen, r.last_seen) AS duration_mins,
  r.first_seen AS first_seen_in_window,
  r.last_seen
FROM dbu_per_run r
LEFT JOIN most_recent_jobs j  USING (workspace_id, job_id)
LEFT JOIN run_states       rs USING (workspace_id, job_id, run_id)
ORDER BY r.run_dbus DESC
LIMIT 500
"""

C_J03_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt
),
latest_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
),
job_run_durations AS (
  -- ALL timeline periods per run (a long run is sliced ~hourly and only the
  -- terminal slice carries result_state — filtering on it here capped every
  -- runtime at ~60 min). Runtime = wall-clock first-start -> last-end.
  SELECT
    workspace_id,
    job_id,
    run_id,
    DATE(MIN(period_start_time))                                          AS run_date,
    (UNIX_TIMESTAMP(MAX(period_end_time))
       - UNIX_TIMESTAMP(MIN(period_start_time))) / 60.0                  AS duration_mins,
    MAX_BY(result_state,
           IF(result_state IS NOT NULL, period_end_time, NULL))           AS result_state
  FROM system.lakeflow.job_run_timeline, cutoff
  WHERE period_start_time >= cutoff.dt
  GROUP BY workspace_id, job_id, run_id
),
job_dbus AS (
  SELECT
    workspace_id,
    usage_metadata.job_id     AS job_id,
    usage_metadata.job_run_id AS run_id,
    ROUND(SUM(usage_quantity), 2) AS run_dbus
  FROM system.billing.usage, cutoff
  WHERE usage_metadata.job_id IS NOT NULL
    AND billing_origin_product = 'JOBS'
    AND usage_unit = 'DBU'
    AND usage_date >= cutoff.dt            -- partition pruning (G2)
    AND usage_start_time >= cutoff.dt
  GROUP BY ALL
)
SELECT
  j.name,
  jrd.job_id,
  jrd.workspace_id,
  COUNT(*)                                                               AS total_runs,
  ROUND(AVG(jrd.duration_mins), 2)                                      AS avg_runtime_mins,
  ROUND(STDDEV(jrd.duration_mins), 2)                                   AS stddev_runtime_mins,
  ROUND(MIN(jrd.duration_mins), 2)                                      AS min_runtime_mins,
  -- Shortest run of at least 1 minute. Instant-exit runs (~0.02 min) would
  -- otherwise dominate max_min_ratio (e.g. 896x) without indicating real variance.
  ROUND(MIN(CASE WHEN jrd.duration_mins >= 1 THEN jrd.duration_mins END), 2)
                                                                        AS min_nontrivial_runtime_mins,
  -- Full-run wall-clock over ALL timeline periods of the run (see
  -- job_run_durations): the longest complete SUCCEEDED run. CRS-04 uses the same
  -- per-run aggregation (over all terminal states), so the two now agree.
  ROUND(MAX(jrd.duration_mins), 2)                                      AS max_runtime_mins,
  -- Ratio uses the >=1-minute minimum (see min_nontrivial_runtime_mins); NULL when
  -- a job has no run of at least 1 minute.
  ROUND(TRY_DIVIDE(
    MAX(jrd.duration_mins),
    MIN(CASE WHEN jrd.duration_mins >= 1 THEN jrd.duration_mins END)), 2) AS max_min_ratio,
  ROUND(AVG(jd.run_dbus), 2)                                            AS avg_dbus,
  -- 0 (not NULL) when no billing row attributes to the job's runs (e.g. classic
  -- compute billed without job attribution); dbus_attributed says which.
  ROUND(COALESCE(SUM(jd.run_dbus), 0), 2)                               AS total_dbus,
  COUNT(jd.run_dbus) > 0                                                AS dbus_attributed,
  ROUND(AVG(TRY_DIVIDE(jd.run_dbus, jrd.duration_mins)), 4)             AS avg_dbus_per_minute
FROM job_run_durations jrd
LEFT JOIN latest_jobs j  USING (workspace_id, job_id)
LEFT JOIN job_dbus    jd ON jrd.workspace_id = jd.workspace_id
                         AND jrd.job_id      = jd.job_id
                         AND jrd.run_id      = jd.run_id
WHERE jrd.result_state = 'SUCCEEDED'
GROUP BY j.name, jrd.job_id, jrd.workspace_id
HAVING COUNT(*) >= 5
ORDER BY max_min_ratio DESC, stddev_runtime_mins DESC
LIMIT {result_limit}
"""

C_J04_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt
),
latest_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
),
run_summary AS (
  SELECT
    workspace_id,
    job_id,
    run_id,
    -- result_state is set only on a run's terminal period; take the latest one.
    -- (A lexicographic MAX over the state string is wrong across mixed states.)
    MAX_BY(result_state, period_end_time) AS final_result_state
  FROM system.lakeflow.job_run_timeline, cutoff
  WHERE period_start_time >= cutoff.dt
    AND result_state IS NOT NULL
  GROUP BY workspace_id, job_id, run_id
),
job_stats AS (
  SELECT
    workspace_id,
    job_id,
    COUNT(DISTINCT run_id)                                               AS total_runs,
    COUNT(DISTINCT CASE WHEN final_result_state IN @FAILURE_STATES@ THEN run_id END) AS failures,
    COUNT(DISTINCT CASE WHEN final_result_state = 'CANCELLED' THEN run_id END)       AS cancelled_runs
  FROM run_summary
  GROUP BY workspace_id, job_id
),
run_dbus AS (
  SELECT
    workspace_id,
    usage_metadata.job_id     AS job_id,
    usage_metadata.job_run_id AS run_id,
    ROUND(SUM(usage_quantity), 2) AS run_dbus
  FROM system.billing.usage, cutoff
  WHERE billing_origin_product = 'JOBS'
    AND usage_unit = 'DBU'
    AND usage_date >= cutoff.dt            -- partition pruning (G2)
    AND usage_start_time >= cutoff.dt
  GROUP BY workspace_id, usage_metadata.job_id, usage_metadata.job_run_id
),
dbu_by_state AS (
  SELECT
    rs.workspace_id,
    rs.job_id,
    ROUND(SUM(rd.run_dbus), 2)                                                              AS total_dbus,
    ROUND(SUM(CASE WHEN rs.final_result_state IN @FAILURE_STATES@ THEN rd.run_dbus ELSE 0 END), 2) AS failure_dbus,
    ROUND(AVG(rd.run_dbus), 2)                                                              AS avg_dbus_per_run
  FROM run_summary rs
  LEFT JOIN run_dbus rd USING (workspace_id, job_id, run_id)
  GROUP BY rs.workspace_id, rs.job_id
)
SELECT
  j.name                                                                    AS job_name,
  js.job_id,
  js.workspace_id,
  js.total_runs,
  js.failures,
  js.cancelled_runs,
  ROUND(TRY_DIVIDE(js.failures * 100.0, js.total_runs), 1)                 AS failure_rate_pct,
  ds.total_dbus,
  ds.failure_dbus,
  -- "Wasted" DBU = DBU spent on failed runs. The retry/repair signal lives in a
  -- separate query (C-J10) sourced from job_task_run_timeline, so this scorecard
  -- stays on job_run_timeline/jobs/usage and keeps feeding the failure-rate
  -- heuristics even on workspaces without the task-run table.
  ROUND(TRY_DIVIDE(ds.failure_dbus * 100.0, ds.total_dbus), 1)             AS wasted_dbu_pct
FROM job_stats js
LEFT JOIN latest_jobs  j  USING (workspace_id, job_id)
LEFT JOIN dbu_by_state ds USING (workspace_id, job_id)
-- Scorecard lists jobs with reliability signal only (a failure or a cancellation);
-- otherwise the row cap fills with clean/1-run jobs. Signal-first ordering.
WHERE js.failures > 0 OR js.cancelled_runs > 0
ORDER BY ds.failure_dbus DESC NULLS LAST, js.failures DESC, ds.total_dbus DESC NULLS LAST
LIMIT {result_limit}
"""

C_J05_SQL = """\
SELECT
  workspace_id,
  DATE(period_start_time)                                       AS run_date,
  COUNT(DISTINCT run_id)                                        AS total_runs,
  COUNT(DISTINCT CASE WHEN result_state IN @FAILURE_STATES@
                      THEN run_id END)                          AS failed_runs,
  COUNT(DISTINCT CASE WHEN result_state = 'CANCELLED'
                      THEN run_id END)                          AS cancelled_runs,
  ROUND(
    TRY_DIVIDE(
      COUNT(DISTINCT CASE WHEN result_state IN @FAILURE_STATES@ THEN run_id END) * 100.0,
      COUNT(DISTINCT run_id)
    ), 1
  )                                                             AS failure_rate_pct,
  -- Today's row is a partial day (runs still in flight): never trend it as a full day.
  DATE(period_start_time) = CURRENT_DATE()                      AS is_partial_day
FROM system.lakeflow.job_run_timeline
WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND result_state IS NOT NULL
GROUP BY workspace_id, DATE(period_start_time)
ORDER BY run_date DESC
LIMIT {result_limit}
"""

C_J06_SQL = """\
WITH latest_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
),
task_runs AS (
  -- One row per task run over ALL its timeline periods (long tasks are sliced
  -- ~hourly; only the terminal slice carries result_state). Duration is
  -- wall-clock; terminal state is the latest non-NULL one.
  SELECT
    workspace_id,
    job_id,
    run_id,
    task_key,
    MAX_BY(result_state,
           IF(result_state IS NOT NULL, period_end_time, NULL))   AS result_state,
    UNIX_TIMESTAMP(MAX(period_end_time))
      - UNIX_TIMESTAMP(MIN(period_start_time))                    AS duration_secs
  FROM system.lakeflow.job_task_run_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY workspace_id, job_id, run_id, task_key
)
SELECT
  j.name                                                                    AS job_name,
  t.workspace_id,
  t.job_id,
  t.task_key,
  COUNT(*)                                                                  AS total_executions,
  SUM(CASE WHEN t.result_state IN @FAILURE_STATES@ THEN 1 ELSE 0 END)      AS failures,
  SUM(CASE WHEN t.result_state = 'CANCELLED' THEN 1 ELSE 0 END)            AS cancelled_executions,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN t.result_state IN @FAILURE_STATES@ THEN 1 ELSE 0 END) * 100.0,
      COUNT(*)
    ), 1
  )                                                                         AS failure_rate_pct,
  ROUND(AVG(t.duration_secs) / 60.0, 2)                                    AS avg_duration_mins
FROM task_runs t
LEFT JOIN latest_jobs j USING (workspace_id, job_id)
-- Completed task runs only — applied AFTER the per-task-run aggregation.
WHERE t.result_state IS NOT NULL
GROUP BY ALL
HAVING failures > 0
ORDER BY failures DESC
LIMIT {result_limit}
"""

C_J07_SQL = """\
WITH latest_pipelines AS (
  SELECT *
  FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id
                              ORDER BY change_time DESC) = 1
),
update_stats AS (
  SELECT
    workspace_id,
    pipeline_id,
    update_id,
    update_type,
    DATE(MIN(period_start_time))                                  AS update_date,
    CAST(SUM(period_end_time - period_start_time) AS LONG)        AS total_duration_seconds,
    MAX(result_state)                                             AS result_state
  FROM system.lakeflow.pipeline_update_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY workspace_id, pipeline_id, update_id, update_type
)
SELECT
  p.name                                                                AS pipeline_name,
  us.workspace_id,
  us.pipeline_id,
  p.pipeline_type,
  us.update_type,
  COUNT(DISTINCT us.update_id)                                          AS update_count,
  ROUND(AVG(us.total_duration_seconds) / 60.0, 2)                      AS avg_duration_mins,
  ROUND(MAX(us.total_duration_seconds) / 60.0, 2)                      AS max_duration_mins,
  SUM(CASE WHEN us.result_state = 'FAILED'    THEN 1 ELSE 0 END)       AS failed_count,
  SUM(CASE WHEN us.result_state = 'COMPLETED' THEN 1 ELSE 0 END)       AS completed_count,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN us.result_state = 'FAILED' THEN 1 ELSE 0 END) * 100.0,
      COUNT(DISTINCT us.update_id)
    ), 1
  )                                                                     AS failure_rate_pct
FROM update_stats us
LEFT JOIN latest_pipelines p USING (workspace_id, pipeline_id)
GROUP BY ALL
ORDER BY avg_duration_mins DESC
LIMIT {result_limit}
"""

# C-J08 — concurrent overlapping runs of the SAME job (event sweep over per-run
# wall-clock intervals). A scheduled job whose runs outlast its trigger interval
# piles up simultaneous runs, each billing its own compute — invisible in a
# per-run or per-job DBU view.
#
# Grain: (workspace_id, job_id, trigger_type). job_run_timeline.trigger_type
# (CRON / PERIODIC / ONETIME / FILE_ARRIVAL / TABLE / CONTINUOUS / RETRY …)
# separates scheduler overlap (CRON/PERIODIC runs outlasting their interval) from
# manual/API backfill bursts (ONETIME). Blending them misleads twice: hundreds of
# cheap ONETIME backfill runs drag a blended per-run DBU average DOWN while the
# scheduled runs got MORE expensive, and a backfill burst reads as scheduler
# pile-up. So every overlap metric and the per-run DBU are computed WITHIN one
# trigger type; job_max_concurrent_runs / job_total_runs keep the job-level view.
C_J08_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt
),
latest_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
),
runs AS (
  -- One interval per run over ALL its timeline periods (runs are sliced ~hourly).
  SELECT
    workspace_id,
    job_id,
    run_id,
    COALESCE(MAX_BY(trigger_type, period_start_time), 'UNKNOWN')  AS trigger_type,
    MIN(period_start_time)                                        AS run_start,
    MAX(period_end_time)                                          AS run_end
  FROM system.lakeflow.job_run_timeline, cutoff
  WHERE period_start_time >= cutoff.dt
  GROUP BY workspace_id, job_id, run_id
),
events AS (
  SELECT workspace_id, job_id, trigger_type, run_id, run_start AS ts,  1 AS delta FROM runs
  UNION ALL
  SELECT workspace_id, job_id, trigger_type, run_id, run_end   AS ts, -1 AS delta FROM runs
),
sweep AS (
  -- Ends sort before starts at the same instant (delta ASC), so back-to-back
  -- runs do not count as overlapping. Partitioned per trigger type (see header).
  SELECT
    workspace_id,
    job_id,
    trigger_type,
    run_id,
    delta,
    SUM(delta) OVER (PARTITION BY workspace_id, job_id, trigger_type
                     ORDER BY ts, delta
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS concurrent_runs,
    SUM(IF(delta = 1, 1, 0)) OVER (PARTITION BY workspace_id, job_id, trigger_type
                     ORDER BY ts, delta
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS starts_so_far,
    UNIX_TIMESTAMP(LEAD(ts) OVER (PARTITION BY workspace_id, job_id, trigger_type
                                  ORDER BY ts, delta))
      - UNIX_TIMESTAMP(ts)                                        AS seg_secs
  FROM events
),
job_sweep AS (
  -- Job-level sweep across ALL trigger types: the true simultaneous peak.
  SELECT
    workspace_id,
    job_id,
    SUM(delta) OVER (PARTITION BY workspace_id, job_id
                     ORDER BY ts, delta
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS concurrent_runs,
    UNIX_TIMESTAMP(LEAD(ts) OVER (PARTITION BY workspace_id, job_id
                                  ORDER BY ts, delta))
      - UNIX_TIMESTAMP(ts)                                        AS seg_secs
  FROM events
),
job_peak AS (
  SELECT workspace_id, job_id,
    MAX(concurrent_runs)                                          AS job_max_concurrent_runs,
    ROUND(SUM(IF(concurrent_runs > 1, seg_secs, 0)) / 3600.0, 1)  AS job_overlapped_hours
  FROM job_sweep
  GROUP BY workspace_id, job_id
),
per_run_overlap AS (
  -- OTHER runs (same job + trigger type) that overlap this run at any point over
  -- its lifetime = runs already active at its start + runs that start before it
  -- ends. A lifetime count, NOT a simultaneous count: a 10-hour run overlapped
  -- by 40 short hourly runs scores 40 even if only 2 ever ran at once.
  SELECT
    workspace_id,
    job_id,
    trigger_type,
    run_id,
    MAX(IF(delta = 1, concurrent_runs, NULL)) - 1
      + MAX(IF(delta = -1, starts_so_far, NULL))
      - MAX(IF(delta = 1, starts_so_far, NULL))                   AS other_runs_overlapping
  FROM sweep
  GROUP BY workspace_id, job_id, trigger_type, run_id
),
overlap AS (
  SELECT
    workspace_id,
    job_id,
    trigger_type,
    MAX(concurrent_runs)                                          AS max_concurrent_runs,
    -- Time-weighted mean of simultaneous runs while at least one is active.
    ROUND(TRY_DIVIDE(
      SUM(IF(concurrent_runs > 0, concurrent_runs * seg_secs, 0)),
      SUM(IF(concurrent_runs > 0, seg_secs, 0))), 2)              AS avg_concurrent_runs,
    ROUND(SUM(IF(concurrent_runs > 1, seg_secs, 0)) / 3600.0, 1)  AS overlapped_hours,
    COUNT_IF(delta = 1 AND concurrent_runs > 1)                   AS runs_started_while_running
  FROM sweep
  GROUP BY workspace_id, job_id, trigger_type
),
run_dbus AS (
  SELECT
    workspace_id,
    usage_metadata.job_id                                         AS job_id,
    usage_metadata.job_run_id                                     AS run_id,
    SUM(usage_quantity)                                           AS run_dbus
  FROM system.billing.usage, cutoff
  WHERE billing_origin_product = 'JOBS'
    AND usage_unit = 'DBU'
    AND usage_metadata.job_id IS NOT NULL
    AND usage_date >= cutoff.dt
  GROUP BY workspace_id, usage_metadata.job_id, usage_metadata.job_run_id
),
run_stats AS (
  SELECT
    r.workspace_id,
    r.job_id,
    r.trigger_type,
    COUNT(*)                                                      AS total_runs,
    ROUND(AVG(UNIX_TIMESTAMP(r.run_end) - UNIX_TIMESTAMP(r.run_start)) / 60.0, 1)
                                                                  AS avg_run_mins,
    ROUND(AVG(p.other_runs_overlapping), 2)                       AS avg_other_runs_overlapping_each_run,
    MAX(p.other_runs_overlapping)                                 AS max_other_runs_overlapping_one_run,
    ROUND(SUM(d.run_dbus), 2)                                     AS trigger_dbus,
    COUNT(d.run_dbus)                                             AS runs_with_dbus,
    ROUND(AVG(d.run_dbus), 2)                                     AS avg_dbus_per_run
  FROM runs r
  JOIN per_run_overlap p USING (workspace_id, job_id, trigger_type, run_id)
  LEFT JOIN run_dbus d   USING (workspace_id, job_id, run_id)
  GROUP BY r.workspace_id, r.job_id, r.trigger_type
),
job_totals AS (
  SELECT workspace_id, job_id,
    SUM(total_runs)                                               AS job_total_runs
  FROM run_stats
  GROUP BY workspace_id, job_id
),
job_dbus AS (
  SELECT workspace_id, job_id, ROUND(SUM(run_dbus), 2)            AS job_total_dbus
  FROM run_dbus
  GROUP BY workspace_id, job_id
)
SELECT
  j.name                                                          AS job_name,
  o.workspace_id,
  o.job_id,
  o.trigger_type,
  rs.total_runs,
  jt.job_total_runs,
  rs.avg_run_mins,
  o.max_concurrent_runs,
  jp.job_max_concurrent_runs,
  o.avg_concurrent_runs,
  rs.avg_other_runs_overlapping_each_run,
  rs.max_other_runs_overlapping_one_run,
  o.runs_started_while_running,
  o.overlapped_hours,
  jp.job_overlapped_hours,
  COALESCE(rs.trigger_dbus, 0)                                    AS trigger_dbus,
  rs.avg_dbus_per_run,
  rs.runs_with_dbus,
  -- Job-level DBU repeated on each trigger_type row: never sum it across rows
  -- (sum trigger_dbus for a per-trigger split; quote job_total_dbus once per job).
  COALESCE(jd.job_total_dbus, 0)                                  AS job_total_dbus,
  jd.job_total_dbus IS NOT NULL                                   AS dbus_attributed
FROM overlap o
JOIN run_stats rs       USING (workspace_id, job_id, trigger_type)
JOIN job_peak jp        USING (workspace_id, job_id)
JOIN job_totals jt      USING (workspace_id, job_id)
LEFT JOIN latest_jobs j USING (workspace_id, job_id)
LEFT JOIN job_dbus jd   USING (workspace_id, job_id)
WHERE jp.job_max_concurrent_runs > 1
ORDER BY jp.job_overlapped_hours DESC, job_total_dbus DESC, o.job_id, trigger_dbus DESC
LIMIT {result_limit}
"""

# C-J09 — long-running tasks (e.g. polling / "wait_for_*" sensors that hold a
# cluster while idle). Per task run over ALL timeline periods (wall-clock), then
# p50/p95 per (workspace_id, job_id, task_key), ranked by total task-hours
# (duration x runs).
C_J09_SQL = """\
WITH latest_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
),
task_runs AS (
  SELECT
    workspace_id,
    job_id,
    run_id,
    task_key,
    MAX_BY(result_state,
           IF(result_state IS NOT NULL, period_end_time, NULL))   AS result_state,
    UNIX_TIMESTAMP(MAX(period_end_time))
      - UNIX_TIMESTAMP(MIN(period_start_time))                    AS duration_secs
  FROM system.lakeflow.job_task_run_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY workspace_id, job_id, run_id, task_key
)
SELECT
  j.name                                                          AS job_name,
  t.workspace_id,
  t.job_id,
  t.task_key,
  COUNT(*)                                                        AS task_runs,
  ROUND(APPROX_PERCENTILE(t.duration_secs, 0.5) / 60.0, 1)        AS p50_duration_mins,
  ROUND(APPROX_PERCENTILE(t.duration_secs, 0.95) / 60.0, 1)       AS p95_duration_mins,
  ROUND(MAX(t.duration_secs) / 60.0, 1)                           AS max_duration_mins,
  ROUND(SUM(t.duration_secs) / 3600.0, 1)                         AS total_task_hours
FROM task_runs t
LEFT JOIN latest_jobs j USING (workspace_id, job_id)
-- Completed task runs only — applied AFTER the per-task-run aggregation.
WHERE t.result_state IS NOT NULL
GROUP BY ALL
ORDER BY total_task_hours DESC
LIMIT {result_limit}
"""

C_J10_SQL = """\
WITH latest_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
),
task_attempts AS (
  -- Attempts per top-level task within one job run. Each attempt is a distinct
  -- task-level run_id under the same job_run_id; a long attempt is sliced into
  -- several period rows but keeps ONE run_id, so COUNT(DISTINCT run_id) is the
  -- attempt count, not the slice count. parent_run_id = job_run_id keeps this to
  -- top-level tasks and excludes ForEach iterations (parallel fan-out, not retries).
  SELECT
    workspace_id,
    job_id,
    job_run_id,
    task_key,
    COUNT(DISTINCT run_id)                                         AS attempts
  FROM system.lakeflow.job_task_run_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND parent_run_id = job_run_id
  GROUP BY workspace_id, job_id, job_run_id, task_key
),
run_level AS (
  -- One row per job run: did any top-level task retry (attempts > 1)?
  SELECT
    workspace_id,
    job_id,
    job_run_id,
    MAX(CASE WHEN attempts > 1 THEN 1 ELSE 0 END)                  AS retried
  FROM task_attempts
  GROUP BY workspace_id, job_id, job_run_id
)
SELECT
  j.name                                                          AS job_name,
  rl.workspace_id,
  rl.job_id,
  COUNT(DISTINCT rl.job_run_id)                                   AS total_runs,
  SUM(rl.retried)                                                 AS retried_runs,
  -- retried_runs and total_runs share ONE population (job runs seen in the
  -- task-run timeline over the window) and retried runs are a subset, so
  -- retry_rate_pct is always in [0, 100] — no cross-population inflation.
  ROUND(TRY_DIVIDE(SUM(rl.retried) * 100.0, COUNT(DISTINCT rl.job_run_id)), 1) AS retry_rate_pct
FROM run_level rl
LEFT JOIN latest_jobs j USING (workspace_id, job_id)
GROUP BY ALL
-- Signal-first: only jobs that actually retried a task (JOB-002's concern), and
-- only jobs with >= 5 runs: a single ad-hoc run that retried reads as a 100%
-- "retry rate" and is noise, not a pattern (JOB-002 applies the same floor).
HAVING retried_runs > 0 AND total_runs >= 5
-- Order by the retry RATIO JOB-002 keys on (>20%), not absolute count, so the
-- LIMIT keeps low-volume high-ratio jobs (e.g. 4/6 = 67%) instead of evicting
-- them behind high-volume low-ratio jobs (e.g. 50/1000 = 5%). Volume breaks ties.
ORDER BY retry_rate_pct DESC, retried_runs DESC, total_runs DESC
LIMIT {result_limit}
"""

C_J04_SQL = _with_failure_states(C_J04_SQL)
C_J05_SQL = _with_failure_states(C_J05_SQL)
C_J06_SQL = _with_failure_states(C_J06_SQL)

JOBS_PACK = QueryPack(
    pack_id="jobs",
    domain="jobs",
    name="Job Workload & Reliability",
    description="Job DBU consumption, reliability scoring, failure analysis, DLT performance",
    queries=(
        SystemQuery(
            query_id="C-J01",
            name="Job DBU Leaderboard",
            description="Top jobs by DBU consumption and avg DBU per run",
            sql_template=C_J01_SQL,
            required_tables=("system.billing.usage", "system.lakeflow.jobs"),
            domain="jobs",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Job DBU leaderboard ranked by consumption",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="C-J02",
            name="Job Run Detail",
            description="Per-run DBUs and duration for job runs",
            sql_template=C_J02_SQL,
            required_tables=(
                "system.billing.usage",
                "system.lakeflow.jobs",
                "system.lakeflow.job_run_timeline",
            ),
            domain="jobs",

            discovery_mode=DiscoveryMode.DEEP_DIVE,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Detailed job run execution data",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="C-J03",
            name="Runtime Variance + DBU per Minute",
            description=(
                "Job runtime variance and DBU-per-minute for jobs with 5+ successful runs; "
                "runtime is per-run wall-clock across ALL timeline periods; "
                "max_min_ratio ignores instant-exit runs (< 1 min) in the minimum; "
                "total_dbus is 0 with dbus_attributed=false when no billing row "
                "attributes to the job's runs"
            ),
            sql_template=C_J03_SQL,
            required_tables=(
                "system.lakeflow.job_run_timeline",
                "system.lakeflow.jobs",
                "system.billing.usage",
            ),
            domain="jobs",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Runtime variance and DBU efficiency per job",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="C-J04",
            name="Compound Reliability Scorecard",
            description=(
                "Failure rates and failure-attributed DBU for jobs with at least one failure "
                "or cancellation; failures = FAILED + ERROR + TIMED_OUT runs, "
                "CANCELLED reported separately as cancelled_runs"
            ),
            sql_template=C_J04_SQL,
            required_tables=(
                "system.lakeflow.job_run_timeline",
                "system.lakeflow.jobs",
                "system.billing.usage",
            ),
            domain="jobs",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Compound reliability scorecard for jobs",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="C-J05",
            name="Daily Failure Rate Trend",
            description=(
                "Daily job failure rates by workspace; failed_runs = FAILED + ERROR + TIMED_OUT, "
                "CANCELLED reported separately as cancelled_runs"
            ),
            sql_template=C_J05_SQL,
            required_tables=("system.lakeflow.job_run_timeline",),
            domain="jobs",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Daily failure rate trend for jobs",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="C-J06",
            name="Task-Level Failure Analysis",
            description=(
                "Task-level failures and duration by job task; failures = FAILED + ERROR + "
                "TIMED_OUT, CANCELLED reported separately as cancelled_executions"
            ),
            sql_template=C_J06_SQL,
            required_tables=(
                "system.lakeflow.job_task_run_timeline",
                "system.lakeflow.jobs",
            ),
            domain="jobs",

            discovery_mode=DiscoveryMode.DEEP_DIVE,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Task-level failure analysis",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="C-J08",
            name="Concurrent Run Overlap",
            description=(
                "Jobs whose runs overlap each other, one row per (job, trigger_type) "
                "so scheduler overlap (CRON/PERIODIC) is separated from manual/API "
                "backfill bursts (ONETIME). Within the trigger type: true peak "
                "simultaneous runs (max_concurrent_runs) and time-weighted average "
                "(avg_concurrent_runs); runs started while another was still running; "
                "overlapped hours; trigger_dbus and avg_dbus_per_run (per-run DBU of "
                "THIS trigger type — never blend ONETIME backfills into scheduled "
                "per-run cost). avg/max_other_runs_overlapping_* count OTHER runs "
                "touching a run over its whole lifetime — NOT a concurrency figure. "
                "job_max_concurrent_runs / job_overlapped_hours / job_total_runs / "
                "job_total_dbus are job-level across all trigger types (repeated on "
                "each trigger row — never sum them across rows). Run intervals "
                "span ALL timeline periods (wall-clock)"
            ),
            sql_template=C_J08_SQL,
            required_tables=(
                "system.lakeflow.job_run_timeline",
                "system.lakeflow.jobs",
                "system.billing.usage",
            ),
            domain="jobs",
            required=False,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Same-job concurrent run pile-up (overlapping runs)",
                output_hint=(
                    "Jobs with job_max_concurrent_runs > 1, ranked by "
                    "job_overlapped_hours; one row per trigger_type. Quote "
                    "concurrency ONLY from max_concurrent_runs (per trigger type) or "
                    "job_max_concurrent_runs (job) — max_other_runs_overlapping_one_run "
                    "is a lifetime overlap count, not simultaneous runs. Per-run cost: "
                    "use avg_dbus_per_run on the CRON/PERIODIC row, not a blend with "
                    "ONETIME (backfill) rows. job_total_dbus is the job's whole-window DBU, "
                    "repeated on every trigger row — quote it once per job, never sum "
                    "it across rows (trigger_dbus is the per-row split; 0 + "
                    "dbus_attributed=false when no billing row carries the job_id)"
                ),
            ),
        ),
        SystemQuery(
            query_id="C-J09",
            name="Long-Running Tasks",
            description=(
                "Task duration p50/p95/max per job task over completed task runs "
                "(wall-clock across ALL timeline periods), ranked by total task-hours "
                "(duration x runs) — surfaces polling/wait tasks that hold compute"
            ),
            sql_template=C_J09_SQL,
            required_tables=(
                "system.lakeflow.job_task_run_timeline",
                "system.lakeflow.jobs",
            ),
            domain="jobs",
            required=False,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Longest-running job tasks by total task-hours",
                output_hint="Job tasks ranked by total_task_hours with p50/p95 duration",
            ),
        ),
        SystemQuery(
            query_id="C-J10",
            name="Task Retry Ratio",
            description=(
                "Per-job retry signal: retried_runs = job runs that retried a top-level "
                "task (a task_key run more than once within the run; each attempt is a "
                "distinct task-level run_id), total_runs = job runs seen in the task-run "
                "timeline, retry_rate_pct = retried_runs / total_runs (same population, "
                "so always 0-100). ForEach iterations are excluded. Only jobs with at "
                "least one retried run and at least 5 runs are returned (single ad-hoc runs "
                "read as a 100% retry rate). Evidence for heuristic JOB-002"
            ),
            sql_template=C_J10_SQL,
            required_tables=(
                "system.lakeflow.job_task_run_timeline",
                "system.lakeflow.jobs",
            ),
            domain="jobs",
            # required=False: a workspace without the task-run table loses only the
            # retry signal; C-J04's failure-rate evidence (JOB-001) is unaffected.
            required=False,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Per-job task retry ratio",
                output_hint="Jobs ranked by retried_runs; retry_rate_pct is in [0, 100]",
            ),
        ),
        # C-J07 removed — DLT pipeline queries moved to DLT_PIPELINES_PACK
    ),
    gating_products=frozenset({"JOBS"}),
)
