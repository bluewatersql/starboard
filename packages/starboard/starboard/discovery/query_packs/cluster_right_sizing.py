# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Cluster right-sizing query pack (CRS-01…08) — Phase-2 Task 09.

Provides right-sizing *depth* over public ``system.compute.*``,
``system.billing.*``, and ``system.lakeflow.*`` tables.  It is **complementary
to** — not a replacement for — the ``compute_reliability`` pack (CR-01…03),
which covers instance lifecycle reliability and warehouse scaling churn.

Division of responsibility
--------------------------
``compute_reliability`` (CR-01…03):
  - Spot/on-demand instance termination rate and lifetime.
  - Node utilisation bands (oversized / underutilised / right-sized).
  - Warehouse scaling churn and peak cluster count.

``cluster_right_sizing`` (CRS-01…08):
  - **Role-feature percentiles** (p50/p95 CPU/memory/IO per driver/worker role).
  - **DBU cost features** (``dbus_per_day`` from ``system.billing.usage``;
    list-price ``$`` projection is applied at the tool layer, not in this pack).
  - **Workload attribution** (job→cluster via ``job_task_run_timeline``).
  - **Job/pipeline reliability** (runs, runtime percentiles, success rate).
  - **Pipeline streaming classification** (CONTINUOUS vs TRIGGERED trigger type).
  - **Cluster, job, and workload right-sizing summaries** (sizing direction,
    recommended action, target cores, cost exposure).

``system.lakeflow.*``-dependent queries (CRS-03…05, CRS-07, CRS-08) are marked
``required=False`` so a workspace without those tables degrades the individual
query, not the whole pack.

All queries use public ``system.*`` tables only.  No internal namespaces.

Column and table facts verified against current Databricks system-table docs
(2026-08-27):

- ``system.compute.node_timeline`` (~90-day retention):
  <https://docs.databricks.com/aws/en/admin/system-tables/compute>
- ``system.compute.node_types``, ``system.compute.clusters``: same page.
- ``system.billing.usage``:
  <https://docs.databricks.com/aws/en/admin/system-tables/billing>
- ``system.lakeflow.*`` (jobs, pipelines, run timelines):
  <https://docs.databricks.com/aws/en/admin/system-tables/lakeflow>
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

# ---------------------------------------------------------------------------
# CRS-01 — Cluster role features (p50/p95 utilisation per driver/worker role)
# ---------------------------------------------------------------------------
# Grain: (workspace_id, cluster_id, node_role, node_type)
# Complementary to CR-02 (node bands): CR-02 emits simple oversized/right-sized
# bands; CRS-01 emits heuristic-classified sizing_reason (DRIVER_MEMORY_PRESSURE,
# WORKER_CPU_PRESSURE, AUTOSCALE_MIN_TOO_HIGH, SEVERELY_OVERPROVISIONED, …)
# using the full p50/p95 + swap + io_wait signal set.
# Heuristics backported from cluster_health notebook 01_setup:cell-28.
CRS_01_SQL = """\
WITH raw AS (
  SELECT
    n.workspace_id,
    n.cluster_id,
    CASE WHEN n.driver IS TRUE THEN 'DRIVER' ELSE 'WORKER' END AS node_role,
    n.node_type,
    n.cpu_user_percent + n.cpu_system_percent                  AS cpu_pct,
    n.mem_used_percent,
    n.cpu_wait_percent,
    n.mem_swap_percent
  FROM system.compute.node_timeline n
  WHERE n.start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
),
stats AS (
  SELECT
    workspace_id,
    cluster_id,
    node_role,
    node_type,
    COUNT(*)                                                    AS sample_count,
    ROUND(PERCENTILE(cpu_pct, 0.50), 1)                        AS cpu_p50_pct,
    ROUND(PERCENTILE(cpu_pct, 0.95), 1)                        AS cpu_p95_pct,
    ROUND(AVG(cpu_pct), 1)                                     AS cpu_avg_pct,
    ROUND(PERCENTILE(mem_used_percent, 0.50), 1)               AS memory_p50_pct,
    ROUND(PERCENTILE(mem_used_percent, 0.95), 1)               AS memory_p95_pct,
    ROUND(PERCENTILE(cpu_wait_percent, 0.95), 1)               AS io_wait_p95_pct,
    ROUND(PERCENTILE(mem_swap_percent, 0.95), 1)               AS swap_p95_pct
  FROM raw
  GROUP BY workspace_id, cluster_id, node_role, node_type
  HAVING COUNT(*) >= 10
),
clusters_latest AS (
  SELECT workspace_id, cluster_id, min_autoscale_workers, max_autoscale_workers
  FROM system.compute.clusters
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY workspace_id, cluster_id ORDER BY change_time DESC
  ) = 1
)
SELECT
  s.workspace_id,
  s.cluster_id,
  s.node_role,
  s.node_type,
  nt.core_count,
  ROUND(nt.memory_mb / 1024.0, 1)                              AS memory_gb,
  cl.min_autoscale_workers,
  cl.max_autoscale_workers,
  s.sample_count,
  s.cpu_p50_pct,
  s.cpu_p95_pct,
  s.cpu_avg_pct,
  s.memory_p50_pct,
  s.memory_p95_pct,
  s.io_wait_p95_pct,
  s.swap_p95_pct,
  CASE
    WHEN s.node_role = 'DRIVER' AND (
      s.memory_p95_pct >= 90
      OR (s.swap_p95_pct >= 10 AND s.memory_p95_pct >= 60)
      OR (s.swap_p95_pct >= 2  AND s.memory_p95_pct >= 75)
    ) THEN 'DRIVER_MEMORY_PRESSURE'
    WHEN s.node_role = 'DRIVER'
      AND s.cpu_p95_pct >= 90 AND s.cpu_avg_pct >= 50
      THEN 'DRIVER_CPU_PRESSURE'
    WHEN s.node_role = 'WORKER' AND s.io_wait_p95_pct >= 25
      THEN 'WORKER_IO_BOUND'
    WHEN s.node_role = 'WORKER' AND (
      s.memory_p95_pct >= 90
      OR (s.swap_p95_pct >= 10 AND s.memory_p95_pct >= 70)
      OR (s.swap_p95_pct >= 2  AND s.memory_p95_pct >= 80)
    ) THEN 'WORKER_MEMORY_PRESSURE'
    WHEN s.node_role = 'WORKER'
      AND s.cpu_p95_pct >= 90 AND s.cpu_avg_pct >= 50
      THEN 'WORKER_CPU_PRESSURE'
    WHEN cl.max_autoscale_workers IS NOT NULL
      AND GREATEST(s.cpu_p95_pct, s.memory_p95_pct) >= 80
      THEN 'AUTOSCALE_MAX_CONSTRAINED'
    WHEN cl.min_autoscale_workers IS NOT NULL
      AND s.cpu_p95_pct < 40 AND s.memory_p95_pct < 50
      THEN 'AUTOSCALE_MIN_TOO_HIGH'
    WHEN s.cpu_p95_pct < 30 AND s.memory_p95_pct < 40 AND s.cpu_avg_pct < 20
      THEN 'SEVERELY_OVERPROVISIONED'
    WHEN s.cpu_p95_pct < 50 AND s.memory_p95_pct < 60 AND s.cpu_avg_pct < 30
      THEN 'OVERPROVISIONED'
    ELSE 'RIGHT_SIZED'
  END                                                          AS sizing_reason
FROM stats s
LEFT JOIN system.compute.node_types nt ON s.node_type = nt.node_type
LEFT JOIN clusters_latest cl
       ON s.workspace_id = cl.workspace_id AND s.cluster_id = cl.cluster_id
ORDER BY s.workspace_id, s.cluster_id, s.node_role
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# CRS-02 — Cluster DBU cost features (DBU-only; $ projection at tool layer)
# ---------------------------------------------------------------------------
# Grain: (workspace_id, cluster_id)
# Emits DBU consumption only. List-price $ conversion is applied downstream
# at the tool layer (get_cluster_rightsizing), not here.
# Source: cluster_health notebook 01_setup:cell-29 billing queries.
CRS_02_SQL = """\
-- DBU cost features per cluster (DBU-only).
-- List-price $ projection is applied at the tool layer, not in this pack.
SELECT
  u.workspace_id,
  u.usage_metadata.cluster_id                                  AS cluster_id,
  ARRAY_JOIN(COLLECT_SET(u.sku_name), ', ')                    AS sku_names,
  ROUND(SUM(u.usage_quantity), 2)                              AS total_dbus,
  ROUND(
    SUM(u.usage_quantity)
      / GREATEST(
          DATEDIFF(MAX(u.usage_end_time), MIN(u.usage_start_time)) + 1,
          1
        ),
    2
  )                                                            AS dbus_per_day
FROM system.billing.usage u
WHERE u.usage_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
  AND u.usage_metadata.cluster_id IS NOT NULL
GROUP BY u.workspace_id, u.usage_metadata.cluster_id
ORDER BY dbus_per_day DESC NULLS LAST
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# CRS-03 — Job cluster attribution (job_id → cluster_id via task timeline)
# ---------------------------------------------------------------------------
# Grain: (workspace_id, job_id, cluster_id)
# required=False — system.lakeflow.job_task_run_timeline may be absent.
CRS_03_SQL = """\
WITH attribution AS (
  SELECT
    t.workspace_id,
    t.job_id,
    cv.cluster_id,
    t.period_start_time,
    t.period_end_time
  FROM system.lakeflow.job_task_run_timeline t
  LATERAL VIEW EXPLODE(t.compute_ids) cv AS cluster_id
  WHERE t.period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
)
SELECT
  workspace_id,
  job_id,
  cluster_id,
  COUNT(*)                                                     AS attributed_task_runs,
  MIN(period_start_time)                                       AS first_seen,
  MAX(period_end_time)                                         AS last_seen
FROM attribution
GROUP BY workspace_id, job_id, cluster_id
ORDER BY workspace_id, job_id, attributed_task_runs DESC
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# CRS-04 — Job reliability features (run counts, runtime percentiles)
# ---------------------------------------------------------------------------
# Grain: (workspace_id, job_id)
# required=False — system.lakeflow.job_run_timeline may be absent.
CRS_04_SQL = """\
SELECT
  jrt.workspace_id,
  jrt.job_id,
  COUNT(*)                                                     AS total_runs,
  COUNT_IF(jrt.result_state = 'SUCCEEDED')                    AS succeeded_runs,
  ROUND(
    COUNT_IF(jrt.result_state = 'SUCCEEDED') * 100.0
      / NULLIF(COUNT(*), 0),
    1
  )                                                            AS success_rate_pct,
  ROUND(
    PERCENTILE(
      UNIX_TIMESTAMP(jrt.period_end_time)
        - UNIX_TIMESTAMP(jrt.period_start_time),
      0.50
    ) / 60.0,
    1
  )                                                            AS runtime_p50_minutes,
  ROUND(
    PERCENTILE(
      UNIX_TIMESTAMP(jrt.period_end_time)
        - UNIX_TIMESTAMP(jrt.period_start_time),
      0.95
    ) / 60.0,
    1
  )                                                            AS runtime_p95_minutes,
  ROUND(
    MAX(
      UNIX_TIMESTAMP(jrt.period_end_time)
        - UNIX_TIMESTAMP(jrt.period_start_time)
    ) / 60.0,
    1
  )                                                            AS runtime_max_minutes
FROM system.lakeflow.job_run_timeline jrt
WHERE jrt.period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
  AND jrt.result_state IS NOT NULL
GROUP BY jrt.workspace_id, jrt.job_id
ORDER BY total_runs DESC
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# CRS-05 — Pipeline stream features (trigger type, update success rate)
# ---------------------------------------------------------------------------
# Grain: (pipeline_id)
# required=False — system.lakeflow.pipelines/pipeline_update_timeline optional.
# Uses public system.lakeflow.* only; no streaming event store (pipeline events
# are not yet in system tables — see research/09 §1 for the PipelineEventsClient
# pattern that powers deeper stream SLA analysis, deferred to a future wave).
CRS_05_SQL = """\
WITH latest_pipeline AS (
  SELECT pipeline_id, name, delete_time
  FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pipeline_id ORDER BY create_time DESC
  ) = 1
),
trigger_latest AS (
  SELECT
    pipeline_id,
    MAX_BY(trigger_type, period_start_time)                    AS trigger_type
  FROM system.lakeflow.pipeline_update_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
  GROUP BY pipeline_id
),
run_stats AS (
  SELECT
    pipeline_id,
    COUNT(*)                                                   AS update_count,
    COUNT_IF(state = 'COMPLETED')                             AS succeeded_updates,
    COUNT_IF(state = 'FAILED')                                AS failed_updates,
    ROUND(
      COUNT_IF(state = 'COMPLETED') * 100.0
        / NULLIF(COUNT(*), 0),
      1
    )                                                          AS success_rate_pct
  FROM system.lakeflow.pipeline_update_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
  GROUP BY pipeline_id
)
SELECT
  p.pipeline_id,
  p.name                                                       AS pipeline_name,
  t.trigger_type                                               AS latest_trigger_type,
  CASE
    WHEN t.trigger_type = 'CONTINUOUS'              THEN 'CONTINUOUS'
    WHEN t.trigger_type IN ('MANUAL', 'CRON')       THEN 'TRIGGERED'
    ELSE                                                 'UNKNOWN'
  END                                                          AS streaming_class,
  r.update_count,
  r.succeeded_updates,
  r.failed_updates,
  r.success_rate_pct
FROM latest_pipeline p
LEFT JOIN trigger_latest t  ON p.pipeline_id = t.pipeline_id
LEFT JOIN run_stats r       ON p.pipeline_id = r.pipeline_id
WHERE p.delete_time IS NULL
ORDER BY r.failed_updates DESC NULLS LAST, r.update_count DESC NULLS LAST
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# CRS-06 — Cluster right-sizing summary (per cluster verdict + cost exposure)
# ---------------------------------------------------------------------------
# Grain: (workspace_id, cluster_id)
# Inlines CRS-01 + CRS-02 logic; uses only GA compute + billing tables.
# Downstream: get_cluster_rightsizing tool (Task 09-tools) consumes this query.
# $ values are list-price DBU estimates; actual cost differs under contracted rates.
CRS_06_SQL = """\
-- Cluster right-sizing summary.
-- All $ values are list-price DBU estimates; actual billed cost
-- may differ under contracted rates.
WITH raw_util AS (
  SELECT
    n.workspace_id,
    n.cluster_id,
    n.node_type,
    n.cpu_user_percent + n.cpu_system_percent                  AS cpu_pct,
    n.mem_used_percent,
    n.cpu_wait_percent,
    n.mem_swap_percent
  FROM system.compute.node_timeline n
  WHERE n.start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
    AND n.driver IS NOT TRUE
),
worker_stats AS (
  SELECT
    workspace_id,
    cluster_id,
    node_type,
    COUNT(*)                                                    AS sample_count,
    ROUND(PERCENTILE(cpu_pct, 0.95), 1)                        AS cpu_p95_pct,
    ROUND(AVG(cpu_pct), 1)                                     AS cpu_avg_pct,
    ROUND(PERCENTILE(mem_used_percent, 0.95), 1)               AS memory_p95_pct,
    ROUND(PERCENTILE(cpu_wait_percent, 0.95), 1)               AS io_wait_p95_pct,
    ROUND(PERCENTILE(mem_swap_percent, 0.95), 1)               AS swap_p95_pct
  FROM raw_util
  GROUP BY workspace_id, cluster_id, node_type
  HAVING COUNT(*) >= 10
),
cluster_caps AS (
  SELECT workspace_id, cluster_id, min_autoscale_workers, max_autoscale_workers
  FROM system.compute.clusters
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY workspace_id, cluster_id ORDER BY change_time DESC
  ) = 1
),
node_caps AS (
  SELECT node_type, core_count, ROUND(memory_mb / 1024.0, 1) AS memory_gb
  FROM system.compute.node_types
),
signals AS (
  SELECT
    w.workspace_id,
    w.cluster_id,
    w.node_type,
    nc.core_count,
    nc.memory_gb,
    w.sample_count,
    w.cpu_p95_pct,
    w.cpu_avg_pct,
    w.memory_p95_pct,
    w.io_wait_p95_pct,
    w.swap_p95_pct,
    cc.min_autoscale_workers,
    cc.max_autoscale_workers,
    CASE
      WHEN w.io_wait_p95_pct >= 25
        THEN 'WORKER_IO_BOUND'
      WHEN w.memory_p95_pct >= 90
        OR (w.swap_p95_pct >= 10 AND w.memory_p95_pct >= 70)
        OR (w.swap_p95_pct >= 2  AND w.memory_p95_pct >= 80)
        THEN 'WORKER_MEMORY_PRESSURE'
      WHEN w.cpu_p95_pct >= 90 AND w.cpu_avg_pct >= 50
        THEN 'WORKER_CPU_PRESSURE'
      WHEN cc.max_autoscale_workers IS NOT NULL
        AND GREATEST(w.cpu_p95_pct, w.memory_p95_pct) >= 80
        THEN 'AUTOSCALE_MAX_CONSTRAINED'
      WHEN cc.min_autoscale_workers IS NOT NULL
        AND w.cpu_p95_pct < 40 AND w.memory_p95_pct < 50
        THEN 'AUTOSCALE_MIN_TOO_HIGH'
      WHEN w.cpu_p95_pct < 30 AND w.memory_p95_pct < 40 AND w.cpu_avg_pct < 20
        THEN 'SEVERELY_OVERPROVISIONED'
      WHEN w.cpu_p95_pct < 50 AND w.memory_p95_pct < 60 AND w.cpu_avg_pct < 30
        THEN 'OVERPROVISIONED'
      ELSE 'RIGHT_SIZED'
    END                                                        AS sizing_reason
  FROM worker_stats w
  LEFT JOIN node_caps nc ON w.node_type = nc.node_type
  LEFT JOIN cluster_caps cc
         ON w.workspace_id = cc.workspace_id AND w.cluster_id = cc.cluster_id
),
cluster_summary AS (
  SELECT
    workspace_id,
    cluster_id,
    MAX_BY(sizing_reason, CASE sizing_reason
      WHEN 'WORKER_IO_BOUND'           THEN 9
      WHEN 'WORKER_CPU_PRESSURE'       THEN 8
      WHEN 'WORKER_MEMORY_PRESSURE'    THEN 7
      WHEN 'AUTOSCALE_MAX_CONSTRAINED' THEN 6
      WHEN 'AUTOSCALE_MIN_TOO_HIGH'    THEN 3
      WHEN 'SEVERELY_OVERPROVISIONED'  THEN 2
      WHEN 'OVERPROVISIONED'           THEN 1
      ELSE 0
    END)                                                       AS top_sizing_reason,
    MAX(cpu_p95_pct)                                           AS max_cpu_p95_pct,
    MAX(memory_p95_pct)                                        AS max_memory_p95_pct,
    AVG(cpu_avg_pct)                                           AS avg_cpu_pct,
    MAX(core_count)                                            AS core_count,
    MAX(memory_gb)                                             AS memory_gb,
    SUM(sample_count)                                          AS total_samples
  FROM signals
  GROUP BY workspace_id, cluster_id
),
dbu_features AS (
  -- DBU consumption per cluster (DBU-only; $ projection applied at tool layer)
  SELECT
    u.workspace_id,
    u.usage_metadata.cluster_id                                AS cluster_id,
    ROUND(SUM(u.usage_quantity), 2)                            AS total_dbus,
    ROUND(
      SUM(u.usage_quantity)
        / GREATEST(
            DATEDIFF(MAX(u.usage_end_time), MIN(u.usage_start_time)) + 1,
            1
          ),
      2
    )                                                          AS dbus_per_day
  FROM system.billing.usage u
  WHERE u.usage_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
    AND u.usage_metadata.cluster_id IS NOT NULL
  GROUP BY u.workspace_id, u.usage_metadata.cluster_id
)
SELECT
  cs.workspace_id,
  cs.cluster_id,
  cs.top_sizing_reason                                         AS sizing_reason,
  CASE
    WHEN cs.top_sizing_reason IN (
      'WORKER_CPU_PRESSURE', 'WORKER_MEMORY_PRESSURE',
      'WORKER_IO_BOUND', 'AUTOSCALE_MAX_CONSTRAINED'
    )                                                          THEN 'UNDERPROVISIONED'
    WHEN cs.top_sizing_reason IN (
      'OVERPROVISIONED', 'SEVERELY_OVERPROVISIONED',
      'AUTOSCALE_MIN_TOO_HIGH'
    )                                                          THEN 'OVERPROVISIONED'
    WHEN cs.top_sizing_reason = 'RIGHT_SIZED'                  THEN 'BALANCED'
    ELSE                                                            'REVIEW'
  END                                                          AS sizing_direction,
  CASE
    WHEN cs.top_sizing_reason = 'AUTOSCALE_MAX_CONSTRAINED'
                                                               THEN 'RAISE_AUTOSCALE_MAX'
    WHEN cs.top_sizing_reason = 'WORKER_CPU_PRESSURE'
                                                               THEN 'UPSIZE_OR_COMPUTE_OPTIMIZED_SKU'
    WHEN cs.top_sizing_reason = 'WORKER_MEMORY_PRESSURE'
                                                               THEN 'MEMORY_OPTIMIZED_SKU_OR_UPSIZE'
    WHEN cs.top_sizing_reason = 'WORKER_IO_BOUND'
                                                               THEN 'ADD_LOCAL_DISK_OR_IO_OPTIMIZED_SKU'
    WHEN cs.top_sizing_reason = 'AUTOSCALE_MIN_TOO_HIGH'
                                                               THEN 'LOWER_AUTOSCALE_MIN'
    WHEN cs.top_sizing_reason IN (
      'OVERPROVISIONED', 'SEVERELY_OVERPROVISIONED'
    )                                                          THEN 'DOWNSIZE_WORKERS'
    ELSE                                                            'NO_ACTION'
  END                                                          AS recommended_action,
  -- Target cores per node at p95 utilisation / 0.70 headroom (list-price estimate)
  CASE
    WHEN cs.core_count IS NOT NULL
      AND cs.max_cpu_p95_pct IS NOT NULL
      AND cs.max_cpu_p95_pct < 70
    THEN LEAST(
      cs.core_count,
      GREATEST(
        CEIL(cs.core_count * cs.max_cpu_p95_pct / 100.0 / 0.7),
        CEIL(cs.core_count * 0.25)
      )
    )
    ELSE cs.core_count
  END                                                          AS target_cores_per_node,
  CASE
    WHEN cs.core_count > 0 AND cs.max_cpu_p95_pct < 70
    THEN ROUND(
      100.0 * (
        cs.core_count - GREATEST(
          CEIL(cs.core_count * cs.max_cpu_p95_pct / 100.0 / 0.7),
          CEIL(cs.core_count * 0.25)
        )
      ) / cs.core_count,
      1
    )
    ELSE 0.0
  END                                                          AS reduction_pct,
  df.dbus_per_day,
  cs.total_samples
FROM cluster_summary cs
LEFT JOIN dbu_features df
       ON cs.workspace_id = df.workspace_id AND cs.cluster_id = df.cluster_id
ORDER BY df.dbus_per_day DESC NULLS LAST, cs.sizing_direction
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# CRS-07 — Job right-sizing summary (per job sizing direction + reliability)
# ---------------------------------------------------------------------------
# Grain: (workspace_id, job_id)
# required=False — uses lakeflow tables.
# Downstream: get_workload_rightsizing tool (Task 09-tools) consumes this query.
CRS_07_SQL = """\
WITH worker_stats AS (
  SELECT
    n.workspace_id,
    n.cluster_id,
    COUNT(*)                                                    AS sample_count,
    ROUND(PERCENTILE(n.cpu_user_percent + n.cpu_system_percent, 0.95), 1)
                                                                AS cpu_p95_pct,
    ROUND(AVG(n.cpu_user_percent + n.cpu_system_percent), 1)   AS cpu_avg_pct,
    ROUND(PERCENTILE(n.mem_used_percent, 0.95), 1)             AS memory_p95_pct,
    ROUND(PERCENTILE(n.cpu_wait_percent, 0.95), 1)             AS io_wait_p95_pct
  FROM system.compute.node_timeline n
  WHERE n.start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
    AND n.driver IS NOT TRUE
  GROUP BY n.workspace_id, n.cluster_id
  HAVING COUNT(*) >= 10
),
cluster_signal AS (
  SELECT
    workspace_id,
    cluster_id,
    CASE
      WHEN io_wait_p95_pct >= 25                               THEN 'WORKER_IO_BOUND'
      WHEN memory_p95_pct >= 90                                THEN 'WORKER_MEMORY_PRESSURE'
      WHEN cpu_p95_pct >= 90 AND cpu_avg_pct >= 50             THEN 'WORKER_CPU_PRESSURE'
      WHEN cpu_p95_pct < 30 AND memory_p95_pct < 40
        AND cpu_avg_pct < 20                                   THEN 'SEVERELY_OVERPROVISIONED'
      WHEN cpu_p95_pct < 50 AND memory_p95_pct < 60
        AND cpu_avg_pct < 30                                   THEN 'OVERPROVISIONED'
      ELSE 'RIGHT_SIZED'
    END                                                        AS sizing_reason
  FROM worker_stats
),
job_attribution AS (
  SELECT
    t.workspace_id,
    t.job_id,
    cv.cluster_id
  FROM system.lakeflow.job_task_run_timeline t
  LATERAL VIEW EXPLODE(t.compute_ids) cv AS cluster_id
  WHERE t.period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
  GROUP BY t.workspace_id, t.job_id, cv.cluster_id
),
job_runs AS (
  SELECT
    workspace_id,
    job_id,
    COUNT(*)                                                    AS total_runs,
    COUNT_IF(result_state = 'SUCCEEDED')                       AS succeeded_runs,
    ROUND(
      COUNT_IF(result_state = 'SUCCEEDED') * 100.0
        / NULLIF(COUNT(*), 0),
      1
    )                                                           AS success_rate_pct,
    ROUND(
      PERCENTILE(
        UNIX_TIMESTAMP(period_end_time) - UNIX_TIMESTAMP(period_start_time),
        0.95
      ) / 60.0,
      1
    )                                                           AS runtime_p95_minutes
  FROM system.lakeflow.job_run_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
    AND result_state IS NOT NULL
  GROUP BY workspace_id, job_id
),
job_signals AS (
  SELECT
    ja.workspace_id,
    ja.job_id,
    MAX_BY(cs.sizing_reason, CASE cs.sizing_reason
      WHEN 'WORKER_IO_BOUND'          THEN 6
      WHEN 'WORKER_CPU_PRESSURE'      THEN 5
      WHEN 'WORKER_MEMORY_PRESSURE'   THEN 4
      WHEN 'SEVERELY_OVERPROVISIONED' THEN 2
      WHEN 'OVERPROVISIONED'          THEN 1
      ELSE 0
    END)                                                        AS top_sizing_reason
  FROM job_attribution ja
  LEFT JOIN cluster_signal cs
         ON ja.workspace_id = cs.workspace_id AND ja.cluster_id = cs.cluster_id
  GROUP BY ja.workspace_id, ja.job_id
)
SELECT
  js.workspace_id,
  js.job_id,
  js.top_sizing_reason                                         AS cluster_sizing_reason,
  CASE
    WHEN js.top_sizing_reason IN (
      'WORKER_CPU_PRESSURE', 'WORKER_MEMORY_PRESSURE', 'WORKER_IO_BOUND'
    )                                                          THEN 'UNDERPROVISIONED'
    WHEN js.top_sizing_reason IN (
      'OVERPROVISIONED', 'SEVERELY_OVERPROVISIONED'
    )                                                          THEN 'OVERPROVISIONED'
    WHEN js.top_sizing_reason = 'RIGHT_SIZED'                  THEN 'BALANCED'
    ELSE                                                            'REVIEW'
  END                                                          AS job_sizing_direction,
  jr.total_runs,
  jr.succeeded_runs,
  jr.success_rate_pct,
  jr.runtime_p95_minutes
FROM job_signals js
LEFT JOIN job_runs jr
       ON js.workspace_id = jr.workspace_id AND js.job_id = jr.job_id
WHERE js.top_sizing_reason IS NOT NULL
ORDER BY js.workspace_id, js.job_id
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# CRS-08 — Workload right-sizing summary (PIPELINE + JOB unified verdict)
# ---------------------------------------------------------------------------
# Grain: (workspace_id, workload_type, workload_id)
# required=False — uses lakeflow tables.
# Downstream: get_workload_rightsizing tool (Task 09-tools) consumes this query.
# Priority score: UNDERPROVISIONED=4, OVERPROVISIONED=2, BALANCED=1, REVIEW=0.
CRS_08_SQL = """\
WITH worker_util AS (
  SELECT
    n.workspace_id,
    n.cluster_id,
    COUNT(*)                                                    AS sample_count,
    ROUND(PERCENTILE(n.cpu_user_percent + n.cpu_system_percent, 0.95), 1)
                                                                AS cpu_p95_pct,
    ROUND(AVG(n.cpu_user_percent + n.cpu_system_percent), 1)   AS cpu_avg_pct,
    ROUND(PERCENTILE(n.mem_used_percent, 0.95), 1)             AS memory_p95_pct
  FROM system.compute.node_timeline n
  WHERE n.start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
    AND n.driver IS NOT TRUE
  GROUP BY n.workspace_id, n.cluster_id
  HAVING COUNT(*) >= 10
),
cluster_dir AS (
  SELECT
    workspace_id,
    cluster_id,
    CASE
      WHEN cpu_p95_pct >= 90 AND cpu_avg_pct >= 50             THEN 'UNDERPROVISIONED'
      WHEN memory_p95_pct >= 90                                THEN 'UNDERPROVISIONED'
      WHEN cpu_p95_pct < 30 AND memory_p95_pct < 40
        AND cpu_avg_pct < 20                                   THEN 'OVERPROVISIONED'
      WHEN cpu_p95_pct < 50 AND memory_p95_pct < 60
        AND cpu_avg_pct < 30                                   THEN 'OVERPROVISIONED'
      ELSE 'BALANCED'
    END                                                        AS sizing_direction,
    CASE
      WHEN cpu_p95_pct >= 90 AND cpu_avg_pct >= 50             THEN 4
      WHEN memory_p95_pct >= 90                                THEN 3
      WHEN cpu_p95_pct < 30 AND memory_p95_pct < 40           THEN 2
      WHEN cpu_p95_pct < 50 AND memory_p95_pct < 60           THEN 1
      ELSE 0
    END                                                        AS priority_score
  FROM worker_util
),
job_workloads AS (
  SELECT
    t.workspace_id,
    'JOB'                                                      AS workload_type,
    t.job_id                                                   AS workload_id,
    MAX(cd.sizing_direction)                                   AS sizing_direction,
    MAX(cd.priority_score)                                     AS priority_score
  FROM system.lakeflow.job_task_run_timeline t
  LATERAL VIEW EXPLODE(t.compute_ids) cv AS cluster_id
  JOIN cluster_dir cd
    ON t.workspace_id = cd.workspace_id AND cv.cluster_id = cd.cluster_id
  WHERE t.period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
  GROUP BY t.workspace_id, t.job_id
),
pipeline_workloads AS (
  SELECT
    CAST(NULL AS STRING)                                       AS workspace_id,
    'PIPELINE'                                                 AS workload_type,
    p.pipeline_id                                              AS workload_id,
    CAST(NULL AS STRING)                                       AS sizing_direction,
    0                                                          AS priority_score
  FROM system.lakeflow.pipelines p
  WHERE p.delete_time IS NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY p.pipeline_id ORDER BY p.create_time DESC
  ) = 1
)
SELECT workspace_id, workload_type, workload_id, sizing_direction, priority_score
FROM job_workloads
UNION ALL
SELECT workspace_id, workload_type, workload_id, sizing_direction, priority_score
FROM pipeline_workloads
ORDER BY priority_score DESC NULLS LAST, workspace_id, workload_type, workload_id
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# Pack definition
# ---------------------------------------------------------------------------

CLUSTER_RIGHT_SIZING_PACK = QueryPack(
    pack_id="cluster_right_sizing",
    domain="cluster_right_sizing",
    name="Cluster Right-Sizing",
    description=(
        "Right-sizing depth over public system.compute.* / system.billing.* / "
        "system.lakeflow.*: role-feature percentiles, list-price cost features, "
        "workload attribution, job/pipeline reliability, and cluster/job/workload "
        "right-sizing summaries. Complements compute_reliability (CR-01…03) which "
        "covers instance lifecycle and warehouse churn."
    ),
    queries=(
        SystemQuery(
            query_id="CRS-01",
            name="Cluster Role Features",
            description=(
                "Per-(workspace_id, cluster_id, node_role, node_type) utilisation "
                "percentiles (p50/p95 CPU/memory/IO/swap) and heuristic sizing_reason "
                "classification (DRIVER_MEMORY_PRESSURE, WORKER_CPU_PRESSURE, "
                "AUTOSCALE_MAX_CONSTRAINED, SEVERELY_OVERPROVISIONED, …). "
                "Backported from cluster_health notebook 01_setup:cell-28 heuristics."
            ),
            sql_template=CRS_01_SQL,
            required_tables=(
                "system.compute.node_timeline",
                "system.compute.node_types",
                "system.compute.clusters",
            ),
            required_columns=(
                "workspace_id",
                "cluster_id",
                "driver",
                "node_type",
                "start_time",
                "cpu_user_percent",
                "cpu_system_percent",
                "mem_used_percent",
                "cpu_wait_percent",
                "mem_swap_percent",
                "core_count",
                "memory_mb",
                "min_autoscale_workers",
                "max_autoscale_workers",
                "change_time",
            ),
            domain="cluster_right_sizing",
            required=True,
            max_lookback_days=90,  # node_timeline retains ~90 days
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary=(
                    "p50/p95 CPU/memory/IO per cluster role with sizing_reason "
                    "heuristic classification"
                ),
                output_hint=(
                    "Per-role utilisation profile; identifies pressure and "
                    "overprovisioning signals"
                ),
                tags=("right-sizing", "utilization", "heuristics"),
            ),
        ),
        SystemQuery(
            query_id="CRS-02",
            name="Cluster DBU Cost Features",
            description=(
                "DBU consumption per cluster from system.billing.usage. "
                "Outputs total_dbus and dbus_per_day (DBU-only). "
                "List-price $ projection is applied at the tool layer."
            ),
            sql_template=CRS_02_SQL,
            required_tables=("system.billing.usage",),
            required_columns=(
                "workspace_id",
                "sku_name",
                "usage_start_time",
                "usage_end_time",
                "usage_quantity",
                "usage_metadata",
            ),
            domain="cluster_right_sizing",
            required=True,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="DBU consumption per cluster (total_dbus and dbus_per_day)",
                output_hint="Clusters ranked by dbus_per_day; feeds CRS-06 sizing summary",
                tags=("cost", "billing", "dbu"),
            ),
        ),
        SystemQuery(
            query_id="CRS-03",
            name="Job Cluster Attribution",
            description=(
                "Explicit job→cluster mapping via EXPLODE of compute_ids in "
                "system.lakeflow.job_task_run_timeline. Grain: "
                "(workspace_id, job_id, cluster_id)."
            ),
            sql_template=CRS_03_SQL,
            required_tables=("system.lakeflow.job_task_run_timeline",),
            required_columns=(
                "workspace_id",
                "job_id",
                "compute_ids",
                "period_start_time",
                "period_end_time",
            ),
            domain="cluster_right_sizing",
            required=False,  # lakeflow table — degrade gracefully if absent
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Job→cluster attribution via task run timeline",
                output_hint="Job IDs with their associated cluster IDs and task run counts",
                tags=("jobs", "attribution", "lakeflow"),
            ),
        ),
        SystemQuery(
            query_id="CRS-04",
            name="Job Reliability Features",
            description=(
                "Per-job run counts, runtime percentiles (p50/p95/max), and "
                "success rate from system.lakeflow.job_run_timeline."
            ),
            sql_template=CRS_04_SQL,
            required_tables=("system.lakeflow.job_run_timeline",),
            required_columns=(
                "workspace_id",
                "job_id",
                "period_start_time",
                "period_end_time",
                "result_state",
            ),
            domain="cluster_right_sizing",
            required=False,  # lakeflow table — degrade gracefully if absent
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Job run counts, runtime p50/p95, and success rate",
                output_hint="Jobs ranked by run volume with reliability metrics",
                tags=("jobs", "reliability", "lakeflow"),
            ),
        ),
        SystemQuery(
            query_id="CRS-05",
            name="Pipeline Stream Features",
            description=(
                "Pipeline trigger type (CONTINUOUS vs TRIGGERED) and update "
                "success rate from system.lakeflow.pipelines and "
                "system.lakeflow.pipeline_update_timeline. "
                "Deeper stream SLA signals (backlog, watermark lag) are deferred "
                "to a future wave once system tables expose stream metrics directly."
            ),
            sql_template=CRS_05_SQL,
            required_tables=(
                "system.lakeflow.pipelines",
                "system.lakeflow.pipeline_update_timeline",
            ),
            required_columns=(
                "pipeline_id",
                "name",
                "delete_time",
                "create_time",
                "trigger_type",
                "period_start_time",
                "state",
            ),
            domain="cluster_right_sizing",
            required=False,  # lakeflow table — degrade gracefully if absent
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Pipeline trigger type and update success rate",
                output_hint="Active pipelines with streaming classification and reliability",
                tags=("pipelines", "streaming", "lakeflow"),
            ),
        ),
        SystemQuery(
            query_id="CRS-06",
            name="Cluster Right-Sizing Summary",
            description=(
                "Per-cluster right-sizing verdict: sizing_direction "
                "(UNDERPROVISIONED / OVERPROVISIONED / BALANCED / REVIEW), "
                "recommended_action, target_cores_per_node (at p95/0.70 headroom), "
                "reduction_pct, and dbus_per_day (DBU cost signal; list-price $ "
                "projection applied at the tool layer). "
                "Inlines CRS-01 + CRS-02 logic; uses only GA compute + billing tables. "
                "Consumed by get_cluster_rightsizing tool (Task 09-tools)."
            ),
            sql_template=CRS_06_SQL,
            required_tables=(
                "system.compute.node_timeline",
                "system.compute.node_types",
                "system.compute.clusters",
                "system.billing.usage",
            ),
            required_columns=(
                "workspace_id",
                "cluster_id",
                "driver",
                "node_type",
                "start_time",
                "cpu_user_percent",
                "cpu_system_percent",
                "mem_used_percent",
                "cpu_wait_percent",
                "mem_swap_percent",
                "core_count",
                "memory_mb",
                "min_autoscale_workers",
                "max_autoscale_workers",
                "change_time",
                "usage_start_time",
                "usage_end_time",
                "usage_quantity",
                "usage_metadata",
            ),
            domain="cluster_right_sizing",
            required=True,
            max_lookback_days=90,  # node_timeline retains ~90 days
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary=(
                    "Cluster right-sizing verdict with recommended action, "
                    "target cores, and DBU cost signal"
                ),
                output_hint=(
                    "Clusters ranked by dbus_per_day; "
                    "sizing_direction + recommended_action per cluster"
                ),
                tags=("right-sizing", "cost", "dbu", "summary"),
            ),
        ),
        SystemQuery(
            query_id="CRS-07",
            name="Job Right-Sizing Summary",
            description=(
                "Per-job sizing direction (via attributed cluster worker signals) "
                "joined to job reliability stats (run count, runtime p95, success "
                "rate). Grain: (workspace_id, job_id). "
                "Consumed by get_workload_rightsizing tool (Task 09-tools)."
            ),
            sql_template=CRS_07_SQL,
            required_tables=(
                "system.compute.node_timeline",
                "system.lakeflow.job_task_run_timeline",
                "system.lakeflow.job_run_timeline",
            ),
            required_columns=(
                "workspace_id",
                "cluster_id",
                "driver",
                "start_time",
                "cpu_user_percent",
                "cpu_system_percent",
                "mem_used_percent",
                "cpu_wait_percent",
                "job_id",
                "compute_ids",
                "period_start_time",
                "period_end_time",
                "result_state",
            ),
            domain="cluster_right_sizing",
            required=False,  # lakeflow tables — degrade gracefully if absent
            max_lookback_days=90,  # node_timeline retains ~90 days
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Job sizing direction with reliability metrics",
                output_hint="Jobs ranked by sizing direction with run count and runtime p95",
                tags=("right-sizing", "jobs", "lakeflow", "summary"),
            ),
        ),
        SystemQuery(
            query_id="CRS-08",
            name="Workload Right-Sizing Summary",
            description=(
                "Unified workload right-sizing verdict across JOB and PIPELINE "
                "workload types. Grain: (workspace_id, workload_type, workload_id). "
                "Priority score: UNDERPROVISIONED=4, OVERPROVISIONED=2, BALANCED=1. "
                "Consumed by get_workload_rightsizing tool (Task 09-tools)."
            ),
            sql_template=CRS_08_SQL,
            required_tables=(
                "system.compute.node_timeline",
                "system.lakeflow.job_task_run_timeline",
                "system.lakeflow.pipelines",
            ),
            required_columns=(
                "workspace_id",
                "cluster_id",
                "driver",
                "start_time",
                "cpu_user_percent",
                "cpu_system_percent",
                "mem_used_percent",
                "job_id",
                "compute_ids",
                "period_start_time",
                "pipeline_id",
                "delete_time",
                "create_time",
            ),
            domain="cluster_right_sizing",
            required=False,  # lakeflow tables — degrade gracefully if absent
            max_lookback_days=90,  # node_timeline retains ~90 days
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Unified job + pipeline right-sizing verdict ranked by priority",
                output_hint=(
                    "All workloads ordered by priority_score "
                    "(UNDERPROVISIONED first); workload_type ∈ {JOB, PIPELINE}"
                ),
                tags=("right-sizing", "jobs", "pipelines", "lakeflow", "summary"),
            ),
        ),
    ),
    gating_products=frozenset({"ALL_PURPOSE_COMPUTE", "JOBS_COMPUTE"}),
)
