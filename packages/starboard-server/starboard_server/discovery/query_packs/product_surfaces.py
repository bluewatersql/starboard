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
LIMIT 50
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
  AND (billing_origin_product = 'LAKEHOUSE_MONITORING'
       OR sku_name LIKE '%LAKEHOUSE_MONITORING%')
GROUP BY ALL
ORDER BY usage_quantity DESC
LIMIT 50
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
LIMIT 50
"""

P_SQL02_SQL = """\
SELECT
  workspace_id,
  compute.warehouse_id                            AS warehouse_id,
  DATE(start_time)                                AS query_date,
  COUNT(*)                                        AS total_queries,
  ROUND(AVG(total_duration_ms)        / 1000.0, 2) AS avg_total_secs,
  ROUND(PERCENTILE(total_duration_ms, 0.50) / 1000.0, 2) AS p50_total_secs,
  ROUND(PERCENTILE(total_duration_ms, 0.95) / 1000.0, 2) AS p95_total_secs,
  ROUND(AVG(compilation_duration_ms)  / 1000.0, 2) AS avg_compile_secs,
  ROUND(AVG(waiting_for_compute_duration_ms) / 1000.0, 2) AS avg_cold_start_secs,
  SUM(CASE WHEN from_result_cache = 'true' THEN 1 ELSE 0 END) AS cache_hits,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN from_result_cache = 'true' THEN 1 ELSE 0 END) * 100.0,
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
LIMIT 50
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
P_WF01_SQL = """\
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
    MAX(result_state)                             AS result_state,
    COUNT(*)                                      AS execution_count,
    ROUND(AVG(CAST(period_end_time - period_start_time AS LONG)) / 60.0, 2) AS avg_duration_mins,
    SUM(CASE WHEN result_state = 'FAILED' THEN 1 ELSE 0 END) AS failure_count
  FROM system.lakeflow.job_task_run_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND result_state IS NOT NULL
  GROUP BY workspace_id, job_id, run_id, task_key
)
SELECT
  j.name                                          AS job_name,
  ts.job_id,
  ts.workspace_id,
  ts.task_key,
  COUNT(DISTINCT ts.run_id)                       AS runs_with_this_task,
  SUM(ts.execution_count)                         AS total_executions,
  ROUND(AVG(ts.avg_duration_mins), 2)             AS avg_task_duration_mins,
  ROUND(MAX(ts.avg_duration_mins), 2)             AS max_task_duration_mins,
  SUM(ts.failure_count)                           AS total_task_failures,
  ROUND(
    TRY_DIVIDE(SUM(ts.failure_count) * 100.0,
               SUM(ts.execution_count)), 1
  )                                               AS failure_rate_pct
FROM task_stats ts
LEFT JOIN latest_jobs j USING (workspace_id, job_id)
GROUP BY ALL
ORDER BY total_task_failures DESC, total_executions DESC
LIMIT 100
"""

P_WF02_SQL = """\
WITH duration_base AS (
  SELECT
    workspace_id,
    job_id,
    run_id,
    task_key,
    result_state,
    CAST(period_end_time - period_start_time AS LONG) AS duration_secs,
    period_end_time,
    period_start_time
  FROM system.lakeflow.job_task_run_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND result_state IS NOT NULL
)
SELECT
  workspace_id,
  job_id,
  run_id,
  task_key,
  COUNT(*)                                         AS iteration_count,
  ROUND(SUM(duration_secs)         / 60.0, 2)     AS total_cpu_mins,
  ROUND(MAX(duration_secs)         / 60.0, 2)     AS max_iteration_mins,
  ROUND(MIN(duration_secs)         / 60.0, 2)     AS min_iteration_mins,
  ROUND(CAST(MAX(period_end_time) - MIN(period_start_time) AS LONG) / 60.0, 2) AS wall_clock_mins,
  ROUND(
    TRY_DIVIDE(
      CAST(MAX(period_end_time) - MIN(period_start_time) AS LONG),
      SUM(duration_secs)
    ), 4
  )                                                AS parallelism_ratio,
  SUM(CASE WHEN result_state = 'FAILED' THEN 1 ELSE 0 END) AS failed_iterations
FROM duration_base
GROUP BY workspace_id, job_id, run_id, task_key
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
            description="Task types per job with duration and failure stats",
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
            description="ForEach iterations with parallelism and wall-clock analysis",
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
