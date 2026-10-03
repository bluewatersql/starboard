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
#
# Scope + attribution: only clusters with billed classic usage in the window
# (``usage_metadata.cluster_id`` set), ranked by window DBU (top 4x the row cap
# scored; output ordered by cluster_dbus DESC) — so the capped row set is the clusters that matter, not the first N
# by cluster_id. Each row carries ``cluster_dbus`` (window DBU, list-price $ at
# the tool layer) and the cluster's job (``job_id`` / ``job_name`` from the same
# billing rows' ``usage_metadata``; ``attributed_job_count`` > 1 = a shared
# all-purpose cluster, ``job_id`` is then the highest-DBU job). Join path:
# node_timeline.cluster_id = billing.usage.usage_metadata.cluster_id.
#
# Cost: node_types is pre-aggregated to one row per node_type over ONLY the node
# types seen in ``stats`` (GROUP BY, no window). A multi-account source (the
# internal fleet mirror) carries ~800M node_types rows; the previous
# ``QUALIFY ROW_NUMBER()`` over all of them was ~190 s of a ~200 s query.
CRS_01_SQL = """\
WITH billed AS (
  SELECT
    u.workspace_id,
    u.usage_metadata.cluster_id                                AS cluster_id,
    ROUND(SUM(u.usage_quantity), 2)                            AS cluster_dbus,
    MAX_BY(u.usage_metadata.job_id,
           IF(u.usage_metadata.job_id IS NOT NULL, u.usage_quantity, NULL)) AS job_id,
    MAX_BY(u.usage_metadata.job_name,
           IF(u.usage_metadata.job_id IS NOT NULL, u.usage_quantity, NULL)) AS job_name,
    COUNT(DISTINCT u.usage_metadata.job_id)                    AS attributed_job_count
  FROM system.billing.usage u
  WHERE u.usage_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
    AND u.usage_metadata.cluster_id IS NOT NULL
    AND u.usage_unit = 'DBU'
  GROUP BY u.workspace_id, u.usage_metadata.cluster_id
),
-- Bound the percentile work to the highest-DBU clusters. 4x the row cap leaves
-- headroom for clusters dropped by the >=10-sample floor below (short-lived job
-- clusters) while the final LIMIT still keeps the top rows by cluster_dbus.
top_billed AS (
  SELECT *
  FROM billed
  QUALIFY ROW_NUMBER() OVER (ORDER BY cluster_dbus DESC, workspace_id, cluster_id)
          <= {result_limit} * 4
),
raw AS (
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
  JOIN top_billed tb
    ON n.workspace_id = tb.workspace_id AND n.cluster_id = tb.cluster_id
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
  WHERE cluster_id IN (SELECT cluster_id FROM top_billed)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY workspace_id, cluster_id ORDER BY change_time DESC
  ) = 1
),
-- One row per node_type, restricted to the node types actually sampled. Specs
-- are intrinsic to the type, but a multi-account/region source (the internal
-- fleet mirror) carries many rows per node_type; aggregating (not a window over
-- the whole table) both dedupes the join (no fan-out) and keeps it cheap. A
-- harmless no-op on a single-workspace source.
node_types_latest AS (
  SELECT
    node_type,
    MAX(core_count)                                            AS core_count,
    MAX_BY(memory_mb, core_count)                              AS memory_mb
  FROM system.compute.node_types
  WHERE node_type IN (SELECT node_type FROM stats)
  GROUP BY node_type
)
SELECT
  s.workspace_id,
  s.cluster_id,
  tb.job_id,
  tb.job_name,
  tb.attributed_job_count,
  tb.cluster_dbus,
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
JOIN top_billed tb
  ON s.workspace_id = tb.workspace_id AND s.cluster_id = tb.cluster_id
LEFT JOIN node_types_latest nt ON s.node_type = nt.node_type
LEFT JOIN clusters_latest cl
       ON s.workspace_id = cl.workspace_id AND s.cluster_id = cl.cluster_id
ORDER BY tb.cluster_dbus DESC, s.workspace_id, s.cluster_id, s.node_role
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
-- coverage_pct: per-workspace share of DBU attributable to a specific cluster. The
-- remainder is serverless / non-cluster product usage (no usage_metadata.cluster_id,
-- so nothing to right-size) — a completeness signal for the cost ranking below.
WITH usage AS (
  SELECT
    workspace_id,
    usage_metadata.cluster_id                                  AS cluster_id,
    sku_name,
    usage_quantity,
    usage_start_time,
    usage_end_time
  FROM system.billing.usage
  WHERE usage_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
),
ws_coverage AS (
  SELECT
    workspace_id,
    ROUND(
      SUM(CASE WHEN cluster_id IS NOT NULL THEN usage_quantity ELSE 0 END) * 100.0
        / NULLIF(SUM(usage_quantity), 0),
      1
    )                                                          AS coverage_pct
  FROM usage
  GROUP BY workspace_id
)
SELECT
  u.workspace_id,
  u.cluster_id,
  ARRAY_JOIN(COLLECT_SET(u.sku_name), ', ')                    AS sku_names,
  ROUND(SUM(u.usage_quantity), 2)                              AS total_dbus,
  ROUND(
    SUM(u.usage_quantity)
      / GREATEST(
          DATEDIFF(MAX(u.usage_end_time), MIN(u.usage_start_time)) + 1,
          1
        ),
    2
  )                                                            AS dbus_per_day,
  ANY_VALUE(c.coverage_pct)                                    AS coverage_pct
FROM usage u
JOIN ws_coverage c USING (workspace_id)
WHERE u.cluster_id IS NOT NULL
GROUP BY u.workspace_id, u.cluster_id
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
  MIN(period_start_time)                                       AS first_seen_in_window,
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
-- job_run_timeline slices a long run into ~hourly periods and sets result_state
-- only on the terminal period(s). Collapse to ONE row per run over ALL periods
-- first (wall-clock runtime, latest non-NULL terminal state); filtering on
-- result_state before this step kept only the last slice and capped every
-- runtime at ~60 min. Same per-run convention as jobs/C-J03.
WITH runs AS (
  SELECT
    jrt.workspace_id,
    jrt.job_id,
    jrt.run_id,
    MAX_BY(jrt.result_state,
           IF(jrt.result_state IS NOT NULL, jrt.period_end_time, NULL)) AS result_state,
    UNIX_TIMESTAMP(MAX(jrt.period_end_time))
      - UNIX_TIMESTAMP(MIN(jrt.period_start_time))             AS runtime_secs
  FROM system.lakeflow.job_run_timeline jrt
  WHERE jrt.period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
  GROUP BY jrt.workspace_id, jrt.job_id, jrt.run_id
)
SELECT
  r.workspace_id,
  r.job_id,
  COUNT(*)                                                     AS total_runs,
  COUNT_IF(r.result_state = 'SKIPPED')                         AS skipped_runs,
  COUNT_IF(r.result_state IN ('FAILED','ERROR','TIMED_OUT'))   AS failed_runs,
  COUNT_IF(r.result_state = 'SUCCEEDED')                       AS succeeded_runs,
  COUNT(*) - COUNT_IF(r.result_state = 'SKIPPED')              AS executed_runs,
  ROUND(
    COUNT_IF(r.result_state = 'SUCCEEDED') * 100.0
      / NULLIF(COUNT(*) - COUNT_IF(r.result_state = 'SKIPPED'), 0),
    1
  )                                                            AS success_rate_pct,   -- over EXECUTED runs (excludes SKIPPED)
  ROUND(PERCENTILE(r.runtime_secs, 0.50) / 60.0, 1)           AS runtime_p50_minutes,
  ROUND(PERCENTILE(r.runtime_secs, 0.95) / 60.0, 1)           AS runtime_p95_minutes,
  -- Longest full run (wall-clock across all periods), over ALL terminal states.
  ROUND(MAX(r.runtime_secs) / 60.0, 1)                        AS runtime_max_minutes
FROM runs r
-- Completed runs only — applied AFTER the per-run aggregation.
WHERE r.result_state IS NOT NULL
GROUP BY r.workspace_id, r.job_id
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
  SELECT
    pipeline_id,
    name,
    delete_time,
    settings.continuous                                        AS is_continuous
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
-- Collapse the lifecycle rows to ONE row per update_id first. The timeline
-- carries many rows per update; non-terminal rows carry a NULL result_state, so
-- MAX(result_state) skips the NULLs and surfaces the terminal state (this mirrors
-- the terminal-state pick in dlt_pipelines/P-DLT03; it assumes an update has at
-- most one non-NULL result_state — the established assumption for these
-- lakeflow timelines). Counting raw timeline rows (the old bug) put every
-- lifecycle row in the denominator and produced a misleading ~50% success rate.
per_update AS (
  SELECT
    pipeline_id,
    update_id,
    MAX(result_state)                                          AS result_state
  FROM system.lakeflow.pipeline_update_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
  GROUP BY pipeline_id, update_id
),
run_stats AS (
  SELECT
    pipeline_id,
    COUNT(*)                                                   AS update_count,
    COUNT_IF(result_state = 'COMPLETED')                      AS succeeded_updates,
    COUNT_IF(result_state = 'FAILED')                         AS failed_updates,
    -- Success rate over TERMINAL updates only: an in-flight update (NULL
    -- result_state, common for a long-running CONTINUOUS pipeline) is excluded
    -- from the denominator so it can't drag a healthy pipeline toward 0%.
    ROUND(
      COUNT_IF(result_state = 'COMPLETED') * 100.0
        / NULLIF(COUNT_IF(result_state IS NOT NULL), 0),
      1
    )                                                          AS success_rate_pct
  FROM per_update
  GROUP BY pipeline_id
)
SELECT
  p.pipeline_id,
  p.name                                                       AS pipeline_name,
  t.trigger_type                                               AS latest_trigger_type,
  CASE
    WHEN p.is_continuous IS TRUE                    THEN 'CONTINUOUS'
    WHEN p.is_continuous IS FALSE                   THEN 'TRIGGERED'
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
-- One row per sampled node_type (see CRS-01): a multi-account source carries
-- many node_types rows per type, which would fan out the join (inflating
-- total_samples) and scan the whole table.
node_caps AS (
  SELECT
    node_type,
    MAX(core_count)                                            AS core_count,
    ROUND(MAX_BY(memory_mb, core_count) / 1024.0, 1)           AS memory_gb
  FROM system.compute.node_types
  WHERE node_type IN (SELECT node_type FROM worker_stats)
  GROUP BY node_type
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
  -- DBU consumption per cluster (DBU-only; $ projection applied at tool layer).
  -- total_dbus is the ACTUAL bounded consumption over the window. active_days is the
  -- span of days the cluster actually billed. dbus_per_day = total_dbus / active_days
  -- is an ACTIVE-DAY rate — do NOT multiply it by the lookback window to project a
  -- recoverable figure: a cluster active 1 day has dbus_per_day ≈ total_dbus, so ×30
  -- inflates ~30x. Use total_dbus (× reduction_pct) for a bounded recoverable estimate.
  SELECT
    u.workspace_id,
    u.usage_metadata.cluster_id                                AS cluster_id,
    ROUND(SUM(u.usage_quantity), 2)                            AS total_dbus,
    DATEDIFF(MAX(u.usage_end_time), MIN(u.usage_start_time)) + 1 AS active_days,
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
),
scored AS (
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
  df.total_dbus,
  df.active_days,
  df.dbus_per_day,
  cs.total_samples,
  'SCORED'                                                     AS status,
  CAST(NULL AS STRING)                                         AS reason
FROM cluster_summary cs
LEFT JOIN dbu_features df
       ON cs.workspace_id = df.workspace_id AND cs.cluster_id = df.cluster_id
)
SELECT * FROM scored
UNION ALL
-- Explicit status row (D13) when the window has NO worker-node samples, so an
-- empty verdict set is never read as "nothing to right-size".
SELECT NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
  'NO_WORKER_SAMPLES',
  '@NO_WORKER_SAMPLES_REASON@'
FROM (SELECT COUNT(*) AS n FROM worker_stats) ws
WHERE ws.n = 0
ORDER BY dbus_per_day DESC NULLS LAST, sizing_direction
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
run_rollup AS (
  -- One row per run over ALL timeline periods (see CRS-04): wall-clock runtime,
  -- latest non-NULL terminal state.
  SELECT
    workspace_id,
    job_id,
    run_id,
    MAX_BY(result_state,
           IF(result_state IS NOT NULL, period_end_time, NULL))  AS result_state,
    UNIX_TIMESTAMP(MAX(period_end_time))
      - UNIX_TIMESTAMP(MIN(period_start_time))                   AS runtime_secs
  FROM system.lakeflow.job_run_timeline
  WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
  GROUP BY workspace_id, job_id, run_id
),
job_runs AS (
  SELECT
    workspace_id,
    job_id,
    COUNT(*)                                                    AS total_runs,
    COUNT_IF(result_state = 'SKIPPED')                          AS skipped_runs,
    COUNT_IF(result_state = 'SUCCEEDED')                        AS succeeded_runs,
    COUNT(*) - COUNT_IF(result_state = 'SKIPPED')               AS executed_runs,
    ROUND(
      COUNT_IF(result_state = 'SUCCEEDED') * 100.0
        / NULLIF(COUNT(*) - COUNT_IF(result_state = 'SKIPPED'), 0),
      1
    )                                                           AS success_rate_pct,   -- over EXECUTED runs (excludes SKIPPED)
    ROUND(PERCENTILE(runtime_secs, 0.95) / 60.0, 1)            AS runtime_p95_minutes
  FROM run_rollup
  -- Completed runs only — applied AFTER the per-run aggregation.
  WHERE result_state IS NOT NULL
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
),
scored AS (
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
  jr.skipped_runs,
  jr.succeeded_runs,
  jr.executed_runs,
  jr.success_rate_pct,
  jr.runtime_p95_minutes,
  'SCORED'                                                     AS status,
  CAST(NULL AS STRING)                                         AS reason
FROM job_signals js
LEFT JOIN job_runs jr
       ON js.workspace_id = jr.workspace_id AND js.job_id = jr.job_id
WHERE js.top_sizing_reason IS NOT NULL
)
SELECT * FROM scored
UNION ALL
-- Explicit status row (D13) when the window has NO worker-node samples.
SELECT NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
  'NO_WORKER_SAMPLES',
  '@NO_WORKER_SAMPLES_REASON@'
FROM (SELECT COUNT(*) AS n FROM worker_stats) ws
WHERE ws.n = 0
ORDER BY workspace_id, job_id
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# CRS-08 — Workload right-sizing summary (JOB right-sizing verdict)
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
    e.workspace_id,
    'JOB'                                                      AS workload_type,
    e.job_id                                                   AS workload_id,
    MAX_BY(cd.sizing_direction, cd.priority_score)             AS sizing_direction,
    MAX(cd.priority_score)                                     AS priority_score
  FROM (
    -- Explode the per-task cluster array in a subquery: a LATERAL VIEW cannot be
    -- directly followed by a JOIN in the same FROM clause (PARSE_SYNTAX_ERROR).
    SELECT workspace_id, job_id, cluster_id
    FROM system.lakeflow.job_task_run_timeline
    LATERAL VIEW EXPLODE(compute_ids) ct AS cluster_id
    WHERE period_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
      AND compute_ids IS NOT NULL
  ) e
  JOIN cluster_dir cd
    ON e.workspace_id = cd.workspace_id AND e.cluster_id = cd.cluster_id
  GROUP BY e.workspace_id, e.job_id
),
unified AS (
  -- CRS-08 scores JOBs only: node_timeline utilisation is cluster-grained, so a
  -- pipeline carries no per-pipeline right-sizing signal here. A pipeline row
  -- would always be unscored (priority 0) and dropped by the WHERE below, so it
  -- is not emitted at all rather than surfaced as a zero-signal placeholder.
  -- Kept as a thin wrapper so the WHERE / ORDER BY apply to the scored set.
  SELECT workspace_id, workload_type, workload_id, sizing_direction, priority_score
  FROM job_workloads
)
SELECT workspace_id, workload_type, workload_id, sizing_direction, priority_score,
  'SCORED' AS status, CAST(NULL AS STRING) AS reason
FROM unified
WHERE priority_score > 0
UNION ALL
-- Explicit status row (D13) when the window has NO worker-node samples.
SELECT NULL, NULL, NULL, NULL, NULL,
  'NO_WORKER_SAMPLES',
  '@NO_WORKER_SAMPLES_REASON@'
FROM (SELECT COUNT(*) AS n FROM worker_util) wu
WHERE wu.n = 0
ORDER BY priority_score DESC NULLS LAST, workspace_id, workload_type, workload_id
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# Pack definition
# ---------------------------------------------------------------------------

# CRS-06/07/08 score WORKER-node utilisation only (driver IS NOT TRUE, >=10
# samples per cluster). On a workspace whose classic compute is single-node /
# driver-only (or that is serverless-only) there is nothing to score. Rather than
# return 0 rows (read by models as "nothing to right-size" or "query broken"),
# each emits ONE status row: every column NULL except status = NO_WORKER_SAMPLES
# and reason. Verdict rows carry status = SCORED. Consumers (the right-sizing
# tools) skip non-SCORED rows. The SQL carries the ``@NO_WORKER_SAMPLES_REASON@``
# token (not a ``{...}`` placeholder, so it survives ``format_map``).
NO_WORKER_SAMPLES_STATUS = "NO_WORKER_SAMPLES"
NO_WORKER_SAMPLES_REASON = (
    "No worker-node utilisation samples (>=10 per cluster) in the window, e.g. "
    "single-node/driver-only clusters or serverless-only compute. This is NOT a "
    "no-action verdict: check CRS-01 DRIVER rows and CRS-02 coverage."
)


def _with_status_reason(sql: str) -> str:
    return sql.replace("@NO_WORKER_SAMPLES_REASON@", NO_WORKER_SAMPLES_REASON)


CRS_06_SQL = _with_status_reason(CRS_06_SQL)
CRS_07_SQL = _with_status_reason(CRS_07_SQL)
CRS_08_SQL = _with_status_reason(CRS_08_SQL)

_EMPTY_WORKER_SIGNAL_NOTE = (
    "Rows with status = 'SCORED' are verdicts. When the window has no WORKER-node "
    "utilisation samples (>=10 per cluster), e.g. single-node/driver-only clusters "
    "or serverless-only compute, the query returns ONE row with status = "
    "'NO_WORKER_SAMPLES' (all other columns NULL) and a reason: that is NOT 'no "
    "action needed' — check CRS-01 DRIVER rows and CRS-02 coverage_pct."
)

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
                "AUTOSCALE_MAX_CONSTRAINED, SEVERELY_OVERPROVISIONED, …) for "
                "clusters with billed classic usage in the window, ranked by "
                "window DBU. Each row carries cluster_dbus and the cluster's job "
                "(job_id / job_name / attributed_job_count from "
                "billing.usage.usage_metadata, joined on cluster_id). "
                "Backported from cluster_health notebook 01_setup:cell-28 heuristics."
            ),
            sql_template=CRS_01_SQL,
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
                "usage_quantity",
                "usage_unit",
                "usage_metadata",
            ),
            domain="cluster_right_sizing",
            required=True,
            max_lookback_days=90,  # node_timeline retains ~90 days
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary=(
                    "p50/p95 CPU/memory/IO per cluster role with sizing_reason "
                    "heuristic classification, job-attributed and DBU-ranked"
                ),
                output_hint=(
                    "Per-role utilisation profile; identifies pressure and "
                    "overprovisioning signals. Rows are the highest-DBU billed "
                    "classic clusters (ordered by cluster_dbus DESC = window DBU, "
                    "DBU-only). job_id / job_name name the cluster's job "
                    "(usage_metadata.job_id on the cluster's billing rows; "
                    "attributed_job_count > 1 = shared cluster, job_id is the "
                    "highest-DBU one; NULL = not job-attributed, e.g. all-purpose). "
                    "Clusters with no billed DBU in the window are not listed."
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
                "success rate from system.lakeflow.job_run_timeline. Runtime is "
                "per-run wall-clock across ALL timeline periods (completed runs)."
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
                output_hint=(
                    "Jobs ranked by run volume with reliability metrics; "
                    "success_rate_pct is over EXECUTED runs (excludes SKIPPED — "
                    "SKIPPED runs are approximately free and should not count as failures); "
                    "skipped_runs column surfaces jobs dominated by SKIPPED state"
                ),
                tags=("jobs", "reliability", "lakeflow"),
            ),
        ),
        SystemQuery(
            query_id="CRS-05",
            name="DLT Pipeline Update Reliability & Streaming Class",
            description=(
                "Lakeflow Declarative (DLT) PIPELINE update reliability — one row per "
                "pipeline (NOT jobs): latest update trigger type, streaming class "
                "(CONTINUOUS vs TRIGGERED from settings.continuous), and update "
                "counts / success rate from system.lakeflow.pipelines and "
                "system.lakeflow.pipeline_update_timeline. It carries no job, "
                "serverless performance-mode (performance_target) or compute-tier "
                "column — for the Standard vs Performance mode lever use SVA-03. "
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
                summary="DLT pipeline update success rate and streaming class (pipelines, not jobs)",
                output_hint=(
                    "Active DLT pipelines (pipeline_id grain) with streaming_class and "
                    "update reliability; not a jobs or serverless performance-mode query"
                ),
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
                    "Clusters ranked by dbus_per_day; sizing_direction + "
                    "recommended_action per cluster. Use total_dbus (bounded actual "
                    "over the window) × reduction_pct for recoverable estimates — do "
                    "NOT project dbus_per_day (an active-day rate) across the window; "
                    "active_days shows how many days the cluster actually billed. "
                    + _EMPTY_WORKER_SIGNAL_NOTE
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
                output_hint=(
                    "Jobs ranked by sizing direction with run count and runtime p95. "
                    + _EMPTY_WORKER_SIGNAL_NOTE
                ),
                tags=("right-sizing", "jobs", "lakeflow", "summary"),
            ),
        ),
        SystemQuery(
            query_id="CRS-08",
            name="Workload Right-Sizing Summary",
            description=(
                "Right-sizing verdict for JOB workloads, scored from cluster "
                "utilisation. Grain: (workspace_id, workload_type, workload_id). "
                "Priority score: UNDERPROVISIONED=4, OVERPROVISIONED=2, BALANCED=1. "
                "Pipelines carry no per-pipeline utilisation signal here and are "
                "not scored. Consumed by get_workload_rightsizing tool (Task 09-tools)."
            ),
            sql_template=CRS_08_SQL,
            required_tables=(
                "system.compute.node_timeline",
                "system.lakeflow.job_task_run_timeline",
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
            ),
            domain="cluster_right_sizing",
            required=False,  # lakeflow tables — degrade gracefully if absent
            max_lookback_days=90,  # node_timeline retains ~90 days
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Job right-sizing verdict ranked by priority",
                output_hint=(
                    "JOB workloads ordered by priority_score "
                    "(UNDERPROVISIONED first); workload_type = JOB. "
                    + _EMPTY_WORKER_SIGNAL_NOTE
                ),
                tags=("right-sizing", "jobs", "pipelines", "lakeflow", "summary"),
            ),
        ),
    ),
    gating_products=frozenset({"ALL_PURPOSE_COMPUTE", "JOBS_COMPUTE"}),
)
