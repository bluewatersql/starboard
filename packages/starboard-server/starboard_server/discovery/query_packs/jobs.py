"""Job workload and reliability query pack for Databricks discovery.

Job DBU consumption, reliability scoring, failure analysis, DLT pipeline performance.
Gated on JOBS product. All queries use DBU metrics only; no dollar computations.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery

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
ORDER BY avg_dbus_per_run DESC
LIMIT 50
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
  -- MAX is cheaper than FIRST(..., TRUE) for a low-cardinality string column
  -- and avoids the internal sort that FIRST with ignoreNulls requires.
  SELECT workspace_id, job_id, run_id,
    MAX(result_state) AS result_state
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
  r.first_seen,
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
  SELECT
    workspace_id,
    job_id,
    run_id,
    DATE(MIN(period_start_time))                                          AS run_date,
    CAST(SUM(period_end_time - period_start_time) AS LONG) / 60.0        AS duration_mins,
    MAX(result_state)                                                     AS result_state
  FROM system.lakeflow.job_run_timeline, cutoff
  WHERE period_start_time >= cutoff.dt
    AND result_state IS NOT NULL
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
  ROUND(MAX(jrd.duration_mins), 2)                                      AS max_runtime_mins,
  ROUND(TRY_DIVIDE(MAX(jrd.duration_mins), MIN(jrd.duration_mins)), 2)  AS max_min_ratio,
  ROUND(AVG(jd.run_dbus), 2)                                            AS avg_dbus,
  ROUND(SUM(jd.run_dbus), 2)                                            AS total_dbus,
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
LIMIT 50
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
    COUNT(*) - 1      AS repairs,
    MAX(result_state) AS final_result_state
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
    COUNT(DISTINCT CASE WHEN final_result_state = 'FAILED' THEN run_id END) AS failures,
    COUNT(DISTINCT CASE WHEN repairs > 0 THEN run_id END)               AS retried_runs,
    SUM(repairs)                                                         AS total_repairs
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
    AND usage_start_time >= cutoff.dt
  GROUP BY workspace_id, usage_metadata.job_id, usage_metadata.job_run_id
),
dbu_by_state AS (
  SELECT
    rs.workspace_id,
    rs.job_id,
    ROUND(SUM(rd.run_dbus), 2)                                                              AS total_dbus,
    ROUND(SUM(CASE WHEN rs.final_result_state = 'FAILED' THEN rd.run_dbus ELSE 0 END), 2)  AS failure_dbus,
    ROUND(SUM(CASE WHEN rs.repairs > 0            THEN rd.run_dbus ELSE 0 END), 2)          AS retry_dbus,
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
  js.retried_runs,
  js.total_repairs,
  ROUND(TRY_DIVIDE(js.failures * 100.0, js.total_runs), 1)                 AS failure_rate_pct,
  ROUND(TRY_DIVIDE(js.total_repairs * 1.0, js.total_runs), 2)              AS avg_repairs_per_run,
  ds.total_dbus,
  ds.failure_dbus,
  ds.retry_dbus,
  ROUND(TRY_DIVIDE((ds.failure_dbus + ds.retry_dbus) * 100.0, ds.total_dbus), 1) AS wasted_dbu_pct
FROM job_stats js
LEFT JOIN latest_jobs  j  USING (workspace_id, job_id)
LEFT JOIN dbu_by_state ds USING (workspace_id, job_id)
ORDER BY (ds.failure_dbus + ds.retry_dbus) DESC
LIMIT 50
"""

C_J05_SQL = """\
SELECT
  workspace_id,
  DATE(period_start_time)                                       AS run_date,
  COUNT(DISTINCT run_id)                                        AS total_runs,
  COUNT(DISTINCT CASE WHEN result_state = 'FAILED'
                      THEN run_id END)                          AS failed_runs,
  ROUND(
    TRY_DIVIDE(
      COUNT(DISTINCT CASE WHEN result_state = 'FAILED' THEN run_id END) * 100.0,
      COUNT(DISTINCT run_id)
    ), 1
  )                                                             AS failure_rate_pct
FROM system.lakeflow.job_run_timeline
WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND result_state IS NOT NULL
GROUP BY workspace_id, DATE(period_start_time)
ORDER BY run_date DESC
LIMIT 50
"""

C_J06_SQL = """\
WITH latest_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
)
SELECT
  j.name                                                                    AS job_name,
  t.workspace_id,
  t.job_id,
  t.task_key,
  COUNT(*)                                                                  AS total_executions,
  SUM(CASE WHEN t.result_state = 'FAILED' THEN 1 ELSE 0 END)               AS failures,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN t.result_state = 'FAILED' THEN 1 ELSE 0 END) * 100.0,
      COUNT(*)
    ), 1
  )                                                                         AS failure_rate_pct,
  ROUND(AVG(CAST(t.period_end_time - t.period_start_time AS LONG)) / 60.0, 2) AS avg_duration_mins
FROM system.lakeflow.job_task_run_timeline t
LEFT JOIN latest_jobs j USING (workspace_id, job_id)
WHERE t.period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND t.result_state IS NOT NULL
GROUP BY ALL
HAVING failures > 0
ORDER BY failures DESC
LIMIT 50
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
LIMIT 50
"""

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
        ),
        SystemQuery(
            query_id="C-J03",
            name="Runtime Variance + DBU per Minute",
            description="Job runtime variance and DBU-per-minute for jobs with 5+ runs",
            sql_template=C_J03_SQL,
            required_tables=(
                "system.lakeflow.job_run_timeline",
                "system.lakeflow.jobs",
                "system.billing.usage",
            ),
            domain="jobs",
        ),
        SystemQuery(
            query_id="C-J04",
            name="Compound Reliability Scorecard",
            description="Failure rates, retries, and wasted DBU by job",
            sql_template=C_J04_SQL,
            required_tables=(
                "system.lakeflow.job_run_timeline",
                "system.lakeflow.jobs",
                "system.billing.usage",
            ),
            domain="jobs",
        ),
        SystemQuery(
            query_id="C-J05",
            name="Daily Failure Rate Trend",
            description="Daily job failure rates by workspace",
            sql_template=C_J05_SQL,
            required_tables=("system.lakeflow.job_run_timeline",),
            domain="jobs",
        ),
        SystemQuery(
            query_id="C-J06",
            name="Task-Level Failure Analysis",
            description="Task-level failures and duration by job task",
            sql_template=C_J06_SQL,
            required_tables=(
                "system.lakeflow.job_task_run_timeline",
                "system.lakeflow.jobs",
            ),
            domain="jobs",
        ),
        SystemQuery(
            query_id="C-J07",
            name="DLT Pipeline Performance",
            description="DLT pipeline update counts, duration, and failure rates",
            sql_template=C_J07_SQL,
            required_tables=(
                "system.lakeflow.pipeline_update_timeline",
                "system.lakeflow.pipelines",
            ),
            domain="jobs",
        ),
    ),
    gating_products=frozenset({"JOBS"}),
)
