# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Product-surface query packs for modern Databricks features."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

from starboard.discovery.query_packs.jobs import _FAILURE_STATES_SQL

# --- DELTA_SHARING_PACK ---
P_DS01_SQL = """\
WITH ds_classified AS (
  SELECT
    workspace_id,
    usage_metadata.sharing_materialization_id     AS sharing_id,
    sku_name,
    CASE
      WHEN sku_name LIKE '%EGRESS%'    THEN 'Data Egress'
      WHEN sku_name LIKE '%LISTING%'   THEN 'Listing / Discovery'
      ELSE                                  'Delta Sharing (other)'
    END                                           AS sharing_type,
    DATE_TRUNC('MONTH', usage_date)               AS year_month,
    usage_quantity,
    usage_unit
  FROM system.billing.usage
  WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND (billing_origin_product = 'DATA_SHARING'
         OR sku_name LIKE '%DELTA_SHARING%'
         OR sku_name LIKE '%DATA_SHARING%')
)
SELECT
  workspace_id,
  sharing_id,
  sku_name,
  sharing_type,
  year_month,
  ROUND(SUM(usage_quantity), 4)                  AS usage_quantity,
  usage_unit
FROM ds_classified
GROUP BY ALL
ORDER BY year_month DESC, usage_quantity DESC
LIMIT {result_limit}
"""

DELTA_SHARING_PACK = QueryPack(
    pack_id="delta_sharing",
    domain="delta_sharing",
    name="Delta Sharing",
    description="Delta Sharing DBU consumption",
    queries=(
        SystemQuery(
            query_id="P-DS01",
            name="Delta Sharing DBU Consumption",
            description="Delta Sharing usage by share, recipient, and type",
            sql_template=P_DS01_SQL,
            required_tables=("system.billing.usage",),
            domain="delta_sharing",
            lookback_override=90,

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Delta sharing DBU consumption",
                output_hint="",
            ),
        ),
    ),
    gating_products=frozenset({"DELTA_SHARING"}),
)

# --- MONITORING_PACK ---
P_LHM01_SQL = """\
SELECT
  workspace_id,
  CONCAT_WS('.', usage_metadata.uc_table_catalog,
                 usage_metadata.uc_table_schema,
                 usage_metadata.uc_table_name)    AS monitored_table,
  sku_name,
  DATE_TRUNC('MONTH', usage_date)                 AS year_month,
  ROUND(SUM(usage_quantity), 2)                   AS usage_quantity,
  usage_unit,
  COUNT(DISTINCT DATE(usage_date))                AS monitored_days
FROM system.billing.usage
WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND (billing_origin_product = 'DATA_QUALITY_MONITORING'
       OR sku_name LIKE '%DATA_QUALITY%')
GROUP BY ALL
ORDER BY usage_quantity DESC
LIMIT {result_limit}
"""

MONITORING_PACK = QueryPack(
    pack_id="monitoring",
    domain="monitoring",
    name="Lakehouse Monitoring",
    description="Lakehouse Monitoring DBU consumption",
    queries=(
        SystemQuery(
            query_id="P-LHM01",
            name="Lakehouse Monitoring DBU Consumption",
            description="Lakehouse Monitoring usage by table",
            sql_template=P_LHM01_SQL,
            required_tables=("system.billing.usage",),
            domain="monitoring",
            lookback_override=90,

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Lakehouse monitoring DBU consumption",
                output_hint="",
            ),
        ),
    ),
    gating_products=frozenset({"LAKEHOUSE_MONITORING"}),
)

# --- SERVERLESS_SQL_PACK ---
P_SQL01_SQL = """\
WITH sql_classified AS (
  SELECT
    workspace_id,
    DATE_TRUNC('MONTH', usage_date)               AS year_month,
    CASE
      WHEN sku_name LIKE '%SERVERLESS%'
       AND billing_origin_product = 'SQL'         THEN 'Serverless SQL'
      WHEN billing_origin_product = 'SQL'         THEN 'Classic SQL Warehouse'
      WHEN billing_origin_product = 'ALL_PURPOSE' THEN 'All-Purpose (interactive)'
      ELSE                                             billing_origin_product
    END                                           AS compute_tier,
    usage_quantity,
    usage_metadata.warehouse_id                   AS warehouse_id
  FROM system.billing.usage
  WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND billing_origin_product IN ('SQL', 'ALL_PURPOSE')
)
SELECT
  workspace_id,
  year_month,
  compute_tier,
  ROUND(SUM(usage_quantity), 2)                   AS dbus,
  COUNT(DISTINCT warehouse_id)                    AS distinct_warehouses
FROM sql_classified
GROUP BY ALL
ORDER BY year_month DESC, dbus DESC
LIMIT {result_limit}
"""

P_SQL02_SQL = """\
SELECT
  workspace_id,
  compute.warehouse_id                            AS warehouse_id,
  DATE(start_time)                                AS query_date,
  COUNT(*)                                        AS total_queries,
  ROUND(AVG(total_duration_ms)        / 1000.0, 2) AS avg_total_secs,
  ROUND(APPROX_PERCENTILE(total_duration_ms, 0.50) / 1000.0, 2) AS p50_total_secs,
  ROUND(APPROX_PERCENTILE(total_duration_ms, 0.95) / 1000.0, 2) AS p95_total_secs,
  ROUND(AVG(compilation_duration_ms)  / 1000.0, 2) AS avg_compile_secs,
  ROUND(AVG(waiting_for_compute_duration_ms) / 1000.0, 2) AS avg_cold_start_secs,
  SUM(CASE WHEN from_result_cache THEN 1 ELSE 0 END) AS cache_hits,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN from_result_cache THEN 1 ELSE 0 END) * 100.0,
      COUNT(*)
    ), 1
  )                                               AS cache_hit_pct,
  SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed_queries
FROM system.query.history
WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND compute.warehouse_id IS NOT NULL
  AND execution_status IN ('FINISHED', 'FAILED')
GROUP BY workspace_id, compute.warehouse_id, DATE(start_time)
HAVING COUNT(*) > 10
ORDER BY warehouse_id, query_date DESC
LIMIT {result_limit}
"""

SERVERLESS_SQL_PACK = QueryPack(
    pack_id="serverless_sql",
    domain="serverless_sql",
    name="Serverless SQL",
    description="Serverless vs classic warehouse comparison and per-query efficiency",
    queries=(
        SystemQuery(
            query_id="P-SQL01",
            name="Serverless vs Classic Warehouse Comparison",
            description="DBU consumption by compute tier (Serverless SQL, Classic, All-Purpose)",
            sql_template=P_SQL01_SQL,
            required_tables=("system.billing.usage",),
            domain="serverless_sql",
            lookback_override=90,

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Serverless vs classic warehouse comparison",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="P-SQL02",
            name="Per-Query Efficiency (Serverless)",
            description="Query performance metrics by warehouse and date",
            sql_template=P_SQL02_SQL,
            required_tables=("system.query.history",),
            domain="serverless_sql",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Per-query efficiency for serverless",
                output_hint="",
            ),
        ),
    ),
    gating_products=frozenset({"SQL"}),
)

# --- WORKFLOW_PACK ---
# P-WF01/P-WF02 read job_task_run_timeline, which slices a long task run into
# ~hourly periods and sets result_state only on the terminal period(s). Each task
# run is first collapsed over ALL its periods (wall-clock duration, latest
# non-NULL terminal state) — see the W1 note in jobs.py. Failures use the shared
# jobs-pack failure-state set (FAILED/ERROR/TIMED_OUT); CANCELLED is separate.
P_WF01_SQL = f"""\
WITH latest_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
),
task_stats AS (
  SELECT
    workspace_id,
    job_id,
    run_id,
    task_key,
    MAX_BY(result_state,
           IF(result_state IS NOT NULL, period_end_time, NULL))   AS result_state,
    (UNIX_TIMESTAMP(MAX(period_end_time))
       - UNIX_TIMESTAMP(MIN(period_start_time))) / 60.0           AS duration_mins
  FROM system.lakeflow.job_task_run_timeline
  WHERE period_start_time >= DATEADD(DAY, -{{lookback_days}}, CURRENT_DATE())
  GROUP BY workspace_id, job_id, run_id, task_key
)
SELECT
  j.name                                          AS job_name,
  ts.job_id,
  ts.workspace_id,
  ts.task_key,
  COUNT(DISTINCT ts.run_id)                       AS runs_with_this_task,
  COUNT(*)                                        AS total_executions,
  ROUND(AVG(ts.duration_mins), 2)                 AS avg_task_duration_mins,
  ROUND(MAX(ts.duration_mins), 2)                 AS max_task_duration_mins,
  SUM(CASE WHEN ts.result_state IN {_FAILURE_STATES_SQL} THEN 1 ELSE 0 END)
                                                  AS total_task_failures,
  SUM(CASE WHEN ts.result_state = 'CANCELLED' THEN 1 ELSE 0 END)
                                                  AS cancelled_executions,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN ts.result_state IN {_FAILURE_STATES_SQL} THEN 1 ELSE 0 END) * 100.0,
      COUNT(*)), 1
  )                                               AS failure_rate_pct
FROM task_stats ts
LEFT JOIN latest_jobs j USING (workspace_id, job_id)
-- Completed task runs only — applied AFTER the per-task-run aggregation.
WHERE ts.result_state IS NOT NULL
GROUP BY ALL
ORDER BY total_task_failures DESC, total_executions DESC
LIMIT 100
"""

# ForEach: each iteration is its own task run whose parent_run_id is the ForEach
# task run (for a top-level task parent_run_id = job_run_id). Iterations are
# collapsed over all their periods, then grouped under their ForEach parent.
P_WF02_SQL = f"""\
WITH iterations AS (
  SELECT
    workspace_id,
    job_id,
    parent_run_id,
    run_id,
    task_key,
    MAX_BY(result_state,
           IF(result_state IS NOT NULL, period_end_time, NULL))   AS result_state,
    MIN(period_start_time)                                        AS iter_start,
    MAX(period_end_time)                                          AS iter_end,
    UNIX_TIMESTAMP(MAX(period_end_time))
      - UNIX_TIMESTAMP(MIN(period_start_time))                    AS duration_secs
  FROM system.lakeflow.job_task_run_timeline
  WHERE period_start_time >= DATEADD(DAY, -{{lookback_days}}, CURRENT_DATE())
    AND parent_run_id IS NOT NULL
    AND parent_run_id <> job_run_id
  GROUP BY workspace_id, job_id, parent_run_id, run_id, task_key
)
SELECT
  workspace_id,
  job_id,
  parent_run_id                                    AS run_id,
  task_key,
  COUNT(*)                                         AS iteration_count,
  ROUND(SUM(duration_secs)         / 60.0, 2)     AS total_cpu_mins,
  ROUND(MAX(duration_secs)         / 60.0, 2)     AS max_iteration_mins,
  ROUND(MIN(duration_secs)         / 60.0, 2)     AS min_iteration_mins,
  ROUND((UNIX_TIMESTAMP(MAX(iter_end))
           - UNIX_TIMESTAMP(MIN(iter_start))) / 60.0, 2) AS wall_clock_mins,
  ROUND(
    TRY_DIVIDE(
      UNIX_TIMESTAMP(MAX(iter_end)) - UNIX_TIMESTAMP(MIN(iter_start)),
      SUM(duration_secs)
    ), 4
  )                                                AS parallelism_ratio,
  SUM(CASE WHEN result_state IN {_FAILURE_STATES_SQL} THEN 1 ELSE 0 END)
                                                   AS failed_iterations
FROM iterations
GROUP BY workspace_id, job_id, parent_run_id, task_key
HAVING COUNT(*) > 1
ORDER BY iteration_count DESC, total_cpu_mins DESC
LIMIT 100
"""

WORKFLOW_PACK = QueryPack(
    pack_id="workflow",
    domain="workflow",
    name="Workflow",
    description="Task type distribution and ForEach task overhead",
    queries=(
        SystemQuery(
            query_id="P-WF01",
            name="Task Type Distribution",
            description=(
                "Per job task: completed task runs, wall-clock duration (all timeline "
                "periods), and failures (FAILED + ERROR + TIMED_OUT); CANCELLED "
                "reported separately as cancelled_executions"
            ),
            sql_template=P_WF01_SQL,
            required_tables=(
                "system.lakeflow.job_task_run_timeline",
                "system.lakeflow.jobs",
            ),
            domain="workflow",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Task type distribution",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="P-WF02",
            name="ForEach Task Overhead",
            description=(
                "ForEach iterations grouped under their parent ForEach task run "
                "(run_id = parent_run_id): iteration count, summed vs wall-clock "
                "duration, parallelism_ratio (wall-clock / summed), failed iterations"
            ),
            sql_template=P_WF02_SQL,
            required_tables=("system.lakeflow.job_task_run_timeline",),
            domain="workflow",

            discovery_mode=DiscoveryMode.DEEP_DIVE,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="ForEach task overhead analysis",
                output_hint="",
            ),
        ),
    ),
    gating_products=frozenset({"JOBS"}),
)
