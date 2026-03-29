"""Product-surface query packs for modern Databricks features."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery

# --- APPS_PACK ---
P_APP01_SQL = """\
WITH now AS (SELECT CURRENT_TIMESTAMP() AS ts)
SELECT
  workspace_id,
  COALESCE(usage_metadata.app_name,
           usage_metadata.endpoint_name)  AS app_name,
  sku_name,
  ROUND(SUM(usage_quantity), 2)           AS dbus,
  COUNT(DISTINCT DATE(usage_date))        AS active_days,
  MIN(usage_start_time)                   AS first_seen,
  MAX(usage_end_time)                     AS last_seen,
  DATEDIFF(DAY, MAX(usage_end_time), now.ts) AS days_since_last_activity
FROM system.billing.usage, now
WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND (
    billing_origin_product = 'APPS'
    OR sku_name LIKE '%DATABRICKS_APPS%'
    OR sku_name LIKE '%APPS_SERVERLESS%'
  )
GROUP BY workspace_id, usage_metadata.app_name, usage_metadata.endpoint_name, sku_name, usage_date, usage_start_time, usage_end_time, ts
ORDER BY dbus DESC
LIMIT 50
"""

P_APP02_SQL = """\
WITH cutoff AS (
  SELECT
    DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt,
    CURRENT_TIMESTAMP()                            AS ts
),
app_billing AS (
  SELECT
    workspace_id,
    COALESCE(usage_metadata.app_name,
             usage_metadata.endpoint_name)         AS app_identifier,
    ROUND(SUM(usage_quantity), 2)                  AS total_dbus
  FROM system.billing.usage, cutoff
  WHERE (billing_origin_product = 'APPS'
         OR sku_name LIKE '%DATABRICKS_APPS%')
    AND usage_date >= cutoff.dt
  GROUP BY workspace_id,
           COALESCE(usage_metadata.app_name, usage_metadata.endpoint_name)
),
app_access AS (
  SELECT
    workspace_id,
    request_params['appName']                      AS app_identifier,
    COUNT(*)                                       AS access_events,
    COUNT(DISTINCT user_identity.email)            AS distinct_users,
    MAX(event_time)                                AS last_user_access
  FROM system.access.audit, cutoff
  WHERE event_time >= cutoff.dt
    AND action_name IN ('appAccessed', 'getApp', 'openApp')
    AND service_name = 'apps'
  GROUP BY workspace_id, request_params['appName']
)
SELECT
  ab.workspace_id,
  ab.app_identifier,
  ab.total_dbus,
  COALESCE(aa.access_events, 0)                   AS user_access_events,
  COALESCE(aa.distinct_users, 0)                  AS distinct_users,
  aa.last_user_access,
  DATEDIFF(DAY, aa.last_user_access, c.ts)        AS days_since_accessed,
  CASE
    WHEN aa.access_events IS NULL
         THEN 'ZOMBIE: Never accessed'
    WHEN DATEDIFF(DAY, aa.last_user_access, c.ts) > 14
         THEN 'IDLE: No access > 14 days'
    WHEN DATEDIFF(DAY, aa.last_user_access, c.ts) > 7
         THEN 'STALE: No access > 7 days'
    ELSE 'ACTIVE'
  END                                             AS status
FROM app_billing ab
CROSS JOIN cutoff c
LEFT JOIN app_access aa
       ON ab.workspace_id    = aa.workspace_id
      AND ab.app_identifier  = aa.app_identifier
ORDER BY ab.total_dbus DESC
LIMIT 50
"""

APPS_PACK = QueryPack(
    pack_id="apps",
    domain="apps",
    name="Apps",
    description="Apps DBU usage and idle detection",
    queries=(
        SystemQuery(
            query_id="P-APP01",
            name="Apps DBU Leaderboard",
            description="Apps ranked by DBU consumption",
            sql_template=P_APP01_SQL,
            required_tables=("system.billing.usage",),
            domain="apps",
        ),
        SystemQuery(
            query_id="P-APP02",
            name="Apps Idle Detection",
            description="Apps with billing but no recent user access (requires audit)",
            sql_template=P_APP02_SQL,
            required_tables=("system.billing.usage", "system.access.audit"),
            domain="apps",
            required=False,
        ),
    ),
    gating_products=frozenset({"APPS"}),
)

# --- LAKEBASE_PACK ---
P_LB01_SQL = """\
WITH lakebase_classified AS (
  SELECT
    workspace_id,
    COALESCE(usage_metadata.database_instance_id,
             usage_metadata.endpoint_name,
             'unknown')                            AS lakebase_instance,
    sku_name,
    CASE
      WHEN sku_name LIKE '%COMPUTE%'
        OR sku_name LIKE '%CU%'                   THEN 'Compute (CUs)'
      WHEN sku_name LIKE '%STORAGE%'              THEN 'Storage'
      WHEN sku_name LIKE '%IO%'
        OR sku_name LIKE '%READ%'
        OR sku_name LIKE '%WRITE%'                THEN 'I/O Operations'
      ELSE                                             'Other'
    END                                           AS dimension,
    usage_unit,
    DATE_TRUNC('MONTH', usage_date)               AS year_month,
    usage_quantity
  FROM system.billing.usage
  WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND (billing_origin_product = 'LAKEBASE'
         OR sku_name LIKE '%LAKEBASE%'
         OR sku_name LIKE '%MANAGED_POSTGRES%')
)
SELECT
  workspace_id,
  lakebase_instance,
  sku_name,
  dimension,
  usage_unit,
  year_month,
  ROUND(SUM(usage_quantity), 4)                  AS usage_quantity
FROM lakebase_classified
GROUP BY ALL
ORDER BY year_month DESC, usage_quantity DESC
LIMIT 50
"""

LAKEBASE_PACK = QueryPack(
    pack_id="lakebase",
    domain="lakebase",
    name="Lakebase",
    description="Lakebase DBU consumption by dimension",
    queries=(
        SystemQuery(
            query_id="P-LB01",
            name="Lakebase DBU by Dimension",
            description="Lakebase usage by compute, storage, and I/O",
            sql_template=P_LB01_SQL,
            required_tables=("system.billing.usage",),
            domain="lakebase",
            lookback_override=90,
        ),
    ),
    gating_products=frozenset({"LAKEBASE"}),
)

# --- VECTOR_SEARCH_PACK ---
P_VS01_SQL = """\
WITH vs_classified AS (
  SELECT
    workspace_id,
    usage_metadata.endpoint_name                  AS endpoint_name,
    CASE
      WHEN sku_name LIKE '%VECTOR_SEARCH_INDEX_CREATION%'
        OR sku_name LIKE '%VECTOR_SEARCH_SYNC%'   THEN 'Index Creation / Sync'
      WHEN sku_name LIKE '%VECTOR_SEARCH_SERVING%'
        OR sku_name LIKE '%VECTOR_SEARCH_QUERY%'  THEN 'Index Serving / Queries'
      WHEN sku_name LIKE '%VECTOR_SEARCH%'        THEN 'Vector Search (unclassified)'
      ELSE                                             sku_name
    END                                           AS operation_type,
    sku_name,
    DATE_TRUNC('MONTH', usage_date)               AS year_month,
    usage_quantity,
    usage_unit,
    usage_date
  FROM system.billing.usage
  WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND (billing_origin_product = 'VECTOR_SEARCH'
         OR sku_name LIKE '%VECTOR_SEARCH%')
)
SELECT
  workspace_id,
  endpoint_name,
  operation_type,
  sku_name,
  year_month,
  ROUND(SUM(usage_quantity), 4)                  AS usage_quantity,
  usage_unit,
  COUNT(DISTINCT DATE(usage_date))               AS active_days
FROM vs_classified
GROUP BY ALL
ORDER BY year_month DESC, usage_quantity DESC
LIMIT 50
"""

VECTOR_SEARCH_PACK = QueryPack(
    pack_id="vector_search",
    domain="vector_search",
    name="Vector Search",
    description="Vector Search DBU consumption by index and operation",
    queries=(
        SystemQuery(
            query_id="P-VS01",
            name="Vector Search DBU by Index and Operation",
            description="Vector Search usage by operation type",
            sql_template=P_VS01_SQL,
            required_tables=("system.billing.usage",),
            domain="vector_search",
            lookback_override=90,
        ),
    ),
    gating_products=frozenset({"VECTOR_SEARCH"}),
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
        ),
        SystemQuery(
            query_id="P-SQL02",
            name="Per-Query Efficiency (Serverless)",
            description="Query performance metrics by warehouse and date",
            sql_template=P_SQL02_SQL,
            required_tables=("system.query.history",),
            domain="serverless_sql",
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
        ),
        SystemQuery(
            query_id="P-WF02",
            name="ForEach Task Overhead",
            description="ForEach iterations with parallelism and wall-clock analysis",
            sql_template=P_WF02_SQL,
            required_tables=("system.lakeflow.job_task_run_timeline",),
            domain="workflow",
        ),
    ),
    gating_products=frozenset({"JOBS"}),
)

# --- AIBI_PACK ---
P_AIBI01_SQL = """\
SELECT
  workspace_id,
  compute.warehouse_id                            AS warehouse_id,
  executed_by,
  DATE(start_time)                                AS query_date,
  COUNT(*)                                        AS genie_queries,
  ROUND(AVG(total_duration_ms)        / 1000.0, 2) AS avg_duration_secs,
  ROUND(SUM(total_duration_ms)        / 1000.0, 2) AS total_duration_secs,
  ROUND(PERCENTILE(total_duration_ms, 0.95) / 1000.0, 2) AS p95_duration_secs,
  SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed_queries,
  SUM(CASE WHEN from_result_cache = 'true'  THEN 1 ELSE 0 END) AS cache_hits,
  ROUND(SUM(read_bytes) / (1024.0 * 1024 * 1024), 2) AS total_read_gb
FROM system.query.history
WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND compute.warehouse_id IS NOT NULL
  AND (
    executed_by LIKE '%genie%'
    OR executed_by LIKE '%ai-bi%'
    OR executed_by LIKE '%aibi%'
    OR client_application LIKE '%Genie%'
  )
GROUP BY ALL
ORDER BY query_date DESC, genie_queries DESC
LIMIT 50
"""

P_AIBI02_SQL = """\
WITH now AS (SELECT CURRENT_TIMESTAMP() AS ts)
SELECT
  workspace_id,
  request_params['dashboardId']                   AS dashboard_id,
  request_params['dashboardName']                 AS dashboard_name,
  DATE(event_time)                                AS access_date,
  COUNT(*)                                        AS access_events,
  COUNT(DISTINCT user_identity.email)             AS distinct_viewers,
  MAX(event_time)                                 AS last_accessed,
  DATEDIFF(DAY, MAX(event_time), any_value(now.ts)) AS days_since_accessed
FROM system.access.audit, now
WHERE event_time >= DATEADD(DAY, -30, CURRENT_DATE())
  AND service_name IN ('dashboards', 'sql/dashboards', 'lakeview')
  AND action_name IN ('getDashboard', 'viewDashboard',
                      'runDashboard', 'refreshDashboard')
GROUP BY ALL
ORDER BY access_events DESC
LIMIT 50
"""

AIBI_PACK = QueryPack(
    pack_id="aibi",
    domain="aibi",
    name="AI/BI",
    description="Genie query activity and dashboard usage patterns",
    queries=(
        SystemQuery(
            query_id="P-AIBI01",
            name="Genie Query Activity",
            description="Genie/AI-BI query volume and performance",
            sql_template=P_AIBI01_SQL,
            required_tables=("system.query.history",),
            domain="aibi",
        ),
        SystemQuery(
            query_id="P-AIBI02",
            name="AI/BI Dashboard Usage Patterns",
            description="Dashboard access patterns (requires audit)",
            sql_template=P_AIBI02_SQL,
            required_tables=("system.access.audit",),
            domain="aibi",
            required=False,
        ),
    ),
    gating_products=frozenset({"SQL"}),
)

__all__ = [
    "AIBI_PACK",
    "APPS_PACK",
    "DELTA_SHARING_PACK",
    "LAKEBASE_PACK",
    "MONITORING_PACK",
    "SERVERLESS_SQL_PACK",
    "VECTOR_SEARCH_PACK",
    "WORKFLOW_PACK",
]
