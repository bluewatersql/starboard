# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Compute and cluster health query pack for Databricks discovery.

Cluster utilization, idle detection, SQL warehouse operational health.
Gated on ALL_PURPOSE_COMPUTE and JOB_COMPUTE. All queries use DBU metrics only;
no dollar computations.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

C_C01_SQL = """\
WITH latest_clusters AS (
  SELECT *
  FROM system.compute.clusters
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, cluster_id
                              ORDER BY change_time DESC) = 1
),
node_metrics AS (
  SELECT
    cluster_id,
    COUNT(DISTINCT CASE WHEN NOT driver THEN instance_id END)    AS worker_node_count,
    ROUND(AVG(cpu_user_percent + cpu_system_percent), 1)         AS avg_cpu_pct,
    ROUND(MAX(cpu_user_percent + cpu_system_percent), 1)         AS peak_cpu_pct,
    ROUND(AVG(mem_used_percent), 1)                              AS avg_mem_pct,
    ROUND(MAX(mem_used_percent), 1)                              AS peak_mem_pct,
    ROUND(AVG(cpu_wait_percent), 1)                              AS avg_cpu_wait_pct
  FROM system.compute.node_timeline
  WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY cluster_id
),
billing_summary AS (
  SELECT
    usage_metadata.cluster_id                      AS cluster_id,
    ROUND(SUM(usage_quantity), 2)                  AS total_dbus,
    COUNT(DISTINCT DATE(usage_start_time))         AS active_days,
    MAX(usage_end_time)                            AS last_used
  FROM system.billing.usage
  WHERE usage_metadata.cluster_id IS NOT NULL
    -- Photon/variant SKUs carry suffixes (e.g. ALL_PURPOSE_COMPUTE_PHOTON); LIKE captures all variants
    AND (sku_name LIKE '%ALL_PURPOSE%' OR sku_name LIKE '%JOBS_COMPUTE%' OR sku_name LIKE '%JOBS%COMPUTE%')
    AND usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())        -- partition pruning (G2)
    AND usage_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY usage_metadata.cluster_id
)
SELECT
  c.workspace_id,
  c.cluster_id,
  c.cluster_name,
  CASE WHEN c.min_autoscale_workers IS NOT NULL THEN 'Autoscaling' ELSE 'Fixed Size' END AS cluster_type,
  c.cluster_source,
  c.min_autoscale_workers,
  c.max_autoscale_workers,
  c.worker_count                                   AS fixed_workers,
  c.worker_node_type,
  c.driver_node_type,
  c.auto_termination_minutes,
  c.owned_by,
  nm.worker_node_count,
  nm.avg_cpu_pct,
  nm.peak_cpu_pct,
  nm.avg_mem_pct,
  nm.peak_mem_pct,
  nm.avg_cpu_wait_pct,
  bs.total_dbus,
  bs.active_days,
  bs.last_used,
  DATEDIFF(DAY, bs.last_used, CURRENT_TIMESTAMP()) AS days_since_last_use
FROM latest_clusters c
LEFT JOIN node_metrics  nm ON c.cluster_id = nm.cluster_id
LEFT JOIN billing_summary bs ON c.cluster_id = bs.cluster_id
WHERE c.delete_time IS NULL
ORDER BY bs.total_dbus DESC NULLS LAST
LIMIT {result_limit}
"""

C_C02_SQL = """\
WITH latest_clusters AS (
  SELECT *
  FROM system.compute.clusters
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, cluster_id
                              ORDER BY change_time DESC) = 1
),
idle_time AS (
  SELECT
    cluster_id,
    COUNT(*) AS idle_minutes
  FROM system.compute.node_timeline
  WHERE cpu_user_percent + cpu_system_percent < 5
    AND mem_used_percent < 30
    AND driver IS NOT TRUE                          -- covers NULL and FALSE in one predicate
    AND start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY cluster_id
),
billing_summary AS (
  SELECT
    usage_metadata.cluster_id              AS cluster_id,
    ROUND(SUM(usage_quantity), 2)          AS total_dbus
  FROM system.billing.usage
  WHERE sku_name LIKE '%ALL_PURPOSE%'  -- Photon/variant SKUs carry suffixes; LIKE captures all variants
    AND usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())        -- partition pruning (G2)
    AND usage_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  GROUP BY usage_metadata.cluster_id
)
SELECT
  c.workspace_id,
  c.cluster_id,
  c.cluster_name,
  c.cluster_source,
  c.owned_by,
  c.auto_termination_minutes,
  CASE
    WHEN c.auto_termination_minutes IS NULL   THEN 'NO AUTO-TERMINATE'
    WHEN c.auto_termination_minutes > 120     THEN 'HIGH (>2hr)'
    WHEN c.auto_termination_minutes > 60      THEN 'MEDIUM (1-2hr)'
    ELSE                                           'LOW (<1hr)'
  END                                        AS termination_risk,
  it.idle_minutes,
  bs.total_dbus,
  ROUND(
    it.idle_minutes / ({lookback_days} * 24.0 * 60) * COALESCE(bs.total_dbus, 0),
    2
  )                                          AS est_idle_dbus
FROM latest_clusters c
LEFT JOIN idle_time     it ON c.cluster_id = it.cluster_id
LEFT JOIN billing_summary bs ON c.cluster_id = bs.cluster_id
WHERE c.delete_time IS NULL
  AND c.cluster_source IN ('UI', 'API')
ORDER BY it.idle_minutes DESC NULLS LAST
LIMIT {result_limit}
"""

C_C03_SQL = """\
-- One row per warehouse per DAY (hourly buckets are rolled up before the row
-- cap, so the cap keeps the most recent days of EVERY warehouse instead of the
-- hourly rows of one). The busiest hour survives as peak_hour_queries /
-- peak_hour_avg_queue_secs so an hourly queue spike is not diluted away.
WITH date_floor AS (
  -- Compute the lookback boundary once; avoids re-evaluating CURRENT_DATE()
  -- per row in two separate CTEs.
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS cutoff
),
scale_events AS (
  SELECT
    warehouse_id,
    DATE(event_time)                                            AS event_date,
    SUM(CASE WHEN event_type = 'SCALED_UP'   THEN 1 ELSE 0 END) AS scale_up_events,
    SUM(CASE WHEN event_type = 'SCALED_DOWN' THEN 1 ELSE 0 END) AS scale_down_events,
    MAX(cluster_count)                                          AS peak_cluster_count
  FROM system.compute.warehouse_events, date_floor
  WHERE event_time >= date_floor.cutoff
  GROUP BY warehouse_id, DATE(event_time)
),
hourly AS (
  SELECT
    compute.warehouse_id                                                         AS warehouse_id,
    DATE(start_time)                                                             AS query_date,
    HOUR(start_time)                                                             AS query_hour,
    COUNT(*)                                                                     AS queries,
    SUM(execution_duration_ms)                                                   AS exec_ms,
    COUNT(execution_duration_ms)                                                 AS exec_n,
    APPROX_PERCENTILE(execution_duration_ms, 0.95)                               AS p95_exec_ms,
    SUM(waiting_at_capacity_duration_ms + waiting_for_compute_duration_ms)       AS queue_ms,
    COUNT(waiting_at_capacity_duration_ms + waiting_for_compute_duration_ms)     AS queue_n,
    MAX(waiting_at_capacity_duration_ms + waiting_for_compute_duration_ms)       AS max_queue_ms,
    SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END)                AS failed_queries,
    SUM(CASE WHEN waiting_at_capacity_duration_ms
                + waiting_for_compute_duration_ms > 30000 THEN 1 ELSE 0 END)    AS queries_queued_30s_plus
  FROM system.query.history, date_floor
  WHERE start_time >= date_floor.cutoff
    AND compute.warehouse_id IS NOT NULL
  GROUP BY compute.warehouse_id, DATE(start_time), HOUR(start_time)
),
query_perf AS (
  SELECT
    warehouse_id,
    query_date,
    COUNT(*)                                                  AS active_hours,
    SUM(queries)                                              AS total_queries,
    ROUND(TRY_DIVIDE(SUM(exec_ms), SUM(exec_n)) / 1000.0, 2)  AS avg_execution_secs,
    ROUND(MAX(p95_exec_ms) / 1000.0, 2)                       AS max_hourly_p95_execution_secs,
    ROUND(TRY_DIVIDE(SUM(queue_ms), SUM(queue_n)) / 1000.0, 2) AS avg_queue_secs,
    ROUND(MAX(max_queue_ms) / 1000.0, 2)                      AS max_queue_secs,
    SUM(queries_queued_30s_plus)                              AS queries_queued_30s_plus,
    SUM(failed_queries)                                       AS failed_queries,
    MAX(queries)                                              AS peak_hour_queries,
    ROUND(MAX(TRY_DIVIDE(queue_ms, queue_n)) / 1000.0, 2)     AS peak_hour_avg_queue_secs
  FROM hourly
  GROUP BY warehouse_id, query_date
)
SELECT
  qp.warehouse_id,
  qp.query_date,
  qp.active_hours,
  qp.total_queries,
  qp.avg_execution_secs,
  qp.max_hourly_p95_execution_secs,
  qp.avg_queue_secs,
  qp.max_queue_secs,
  qp.peak_hour_queries,
  qp.peak_hour_avg_queue_secs,
  qp.queries_queued_30s_plus,
  qp.failed_queries,
  se.scale_up_events,
  se.scale_down_events,
  se.peak_cluster_count
FROM query_perf qp
LEFT JOIN scale_events se
       ON qp.warehouse_id = se.warehouse_id
      AND qp.query_date   = se.event_date
-- Most recent days first, every warehouse per day (busiest first), so the row
-- cap trims old days rather than whole warehouses.
ORDER BY qp.query_date DESC, qp.total_queries DESC, qp.warehouse_id
LIMIT {result_limit}
"""

COMPUTE_PACK = QueryPack(
    pack_id="compute",
    domain="compute",
    name="Compute & Cluster Health",
    description="Cluster utilization, idle detection, SQL warehouse operational health",
    queries=(
        SystemQuery(
            query_id="C-C01",
            name="Cluster Utilization + Sizing",
            description="Cluster config, node metrics, and DBU consumption",
            sql_template=C_C01_SQL,
            required_tables=(
                "system.compute.clusters",
                "system.compute.node_timeline",
                "system.billing.usage",
            ),
            domain="compute",
            max_lookback_days=90,  # G5: node_timeline retains ~90 days

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Cluster utilization and sizing analysis",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="C-C02",
            name="Cluster Idle Time and Auto-Termination Gaps",
            description="Idle minutes and termination risk by cluster",
            sql_template=C_C02_SQL,
            required_tables=(
                "system.compute.clusters",
                "system.compute.node_timeline",
                "system.billing.usage",
            ),
            domain="compute",
            max_lookback_days=90,  # G5: node_timeline retains ~90 days

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Cluster idle time and auto-termination gaps",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="C-C03",
            name="SQL Warehouse Health",
            description=(
                "Per warehouse per day: query volume, execution / queue times, the "
                "busiest hour's volume and queue, and scale events"
            ),
            sql_template=C_C03_SQL,
            required_tables=(
                "system.compute.warehouse_events",
                "system.query.history",
            ),
            domain="compute",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="SQL warehouse health overview",
                output_hint="",
            ),
        ),
    ),
    gating_products=frozenset({"ALL_PURPOSE_COMPUTE", "JOB_COMPUTE"}),
)
