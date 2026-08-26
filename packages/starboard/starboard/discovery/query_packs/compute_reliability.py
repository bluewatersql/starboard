# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Compute reliability + right-sizing query pack (Phase-2 D5 / N5).

Surfaces reliability and right-sizing signals over public ``system.compute.*``
tables:

- **Instance reliability** — spot vs on-demand churn, termination rate, and mean
  instance lifetime from ``system.compute.instance_events``
  (**Public Preview** → ``required=False`` so a missing table degrades only the
  query, not the domain).
- **Node right-sizing** — join ``system.compute.node_timeline`` utilization to
  ``system.compute.node_types`` capacity to flag oversized/underutilized nodes.
- **Warehouse reliability** — scale/start/stop churn from
  ``system.compute.warehouse_events``.

All queries use utilization/DBU-free operational metrics only; no dollar
computations and no internal namespaces.

Column and table facts verified against current Databricks system-table docs
(2026-08-26):

- ``system.compute.node_timeline`` (utilization; ~90-day retention):
  <https://docs.databricks.com/aws/en/admin/system-tables/compute>
- ``system.compute.instance_events`` (Public Preview; ``availability_type`` ∈
  ON_DEMAND/SPOT/PREEMPTIBLE, ``state`` ∈ INSTANCE_LAUNCHING/READY/PLACED/
  TERMINATED): same page (Compute system tables).
- ``system.compute.node_types`` (``core_count``, ``memory_mb``, ``gpu_count``):
  same page.
- ``system.compute.warehouse_events`` (``event_type`` ∈ SCALED_UP/SCALED_DOWN/
  STARTING/RUNNING/STOPPING/STOPPED, ``cluster_count``):
  <https://docs.databricks.com/aws/en/admin/system-tables/warehouse-events>
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

# CR-01 — Instance reliability by availability type (Public Preview table).
# Aggregates per-instance lifecycle: how many instances of each availability
# type launched, how many terminated, their termination rate, and mean lifetime
# (INSTANCE_PLACED -> INSTANCE_TERMINATED). Spot fleets show shorter lifetimes /
# higher termination rates than on-demand — the reliability signal.
CR_01_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt
),
lifecycle AS (
  SELECT
    ie.workspace_id,
    ie.instance_id,
    ie.availability_type,
    MIN(CASE WHEN ie.state = 'INSTANCE_PLACED'     THEN ie.event_time END) AS placed_at,
    MIN(CASE WHEN ie.state = 'INSTANCE_TERMINATED' THEN ie.event_time END) AS terminated_at
  FROM system.compute.instance_events ie, cutoff
  WHERE ie.event_time >= cutoff.dt
  GROUP BY ie.workspace_id, ie.instance_id, ie.availability_type
)
SELECT
  workspace_id,
  COALESCE(availability_type, 'UNKNOWN')                       AS availability_type,
  COUNT(*)                                                     AS instances,
  COUNT_IF(terminated_at IS NOT NULL)                          AS terminated_instances,
  ROUND(COUNT_IF(terminated_at IS NOT NULL) * 100.0 / COUNT(*), 2) AS termination_rate_pct,
  ROUND(
    AVG(
      CASE
        WHEN placed_at IS NOT NULL AND terminated_at IS NOT NULL
        THEN TIMESTAMPDIFF(MINUTE, placed_at, terminated_at)
      END
    ),
    1
  )                                                            AS avg_lifetime_minutes
FROM lifecycle
GROUP BY workspace_id, COALESCE(availability_type, 'UNKNOWN')
ORDER BY availability_type, instances DESC
LIMIT {result_limit}
"""

# CR-02 — Node right-sizing: utilization vs capacity.
# Joins per-node utilization (node_timeline) to node capacity (node_types) and
# bands each worker node as oversized / underutilized / right-sized. Requires a
# minimum sample so short-lived nodes don't produce noise.
CR_02_SQL = """\
WITH util AS (
  SELECT
    n.workspace_id,
    n.cluster_id,
    n.node_type,
    COUNT(*)                                              AS sample_minutes,
    ROUND(AVG(n.cpu_user_percent + n.cpu_system_percent), 1) AS avg_cpu_pct,
    ROUND(MAX(n.cpu_user_percent + n.cpu_system_percent), 1) AS peak_cpu_pct,
    ROUND(AVG(n.mem_used_percent), 1)                     AS avg_mem_pct,
    ROUND(MAX(n.mem_used_percent), 1)                     AS peak_mem_pct
  FROM system.compute.node_timeline n
  WHERE n.start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND n.driver IS NOT TRUE                              -- workers only (covers NULL + FALSE)
  GROUP BY n.workspace_id, n.cluster_id, n.node_type
)
SELECT
  u.workspace_id,
  u.cluster_id,
  u.node_type,
  nt.core_count,
  ROUND(nt.memory_mb / 1024.0, 1)                         AS memory_gb,
  nt.gpu_count,
  u.sample_minutes,
  u.avg_cpu_pct,
  u.peak_cpu_pct,
  u.avg_mem_pct,
  u.peak_mem_pct,
  CASE
    WHEN u.peak_cpu_pct < 25 AND u.peak_mem_pct < 40 THEN 'OVERSIZED (downsize candidate)'
    WHEN u.avg_cpu_pct  < 15 AND u.avg_mem_pct  < 30 THEN 'UNDERUTILIZED'
    ELSE                                                  'RIGHT-SIZED'
  END                                                     AS sizing_signal
FROM util u
LEFT JOIN system.compute.node_types nt
       ON u.node_type = nt.node_type
WHERE u.sample_minutes >= 30
ORDER BY u.peak_cpu_pct ASC, u.peak_mem_pct ASC
LIMIT {result_limit}
"""

# CR-03 — Warehouse reliability / scaling churn.
# Counts warehouse lifecycle events per warehouse. Frequent scale/stop churn or
# high peak cluster counts flag under-provisioned or thrashing warehouses.
CR_03_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt
)
SELECT
  we.workspace_id,
  we.warehouse_id,
  COUNT_IF(we.event_type = 'SCALED_UP')    AS scale_up_events,
  COUNT_IF(we.event_type = 'SCALED_DOWN')  AS scale_down_events,
  COUNT_IF(we.event_type = 'STARTING')     AS start_events,
  COUNT_IF(we.event_type = 'STOPPED')      AS stop_events,
  MAX(we.cluster_count)                    AS peak_cluster_count,
  COUNT(*)                                 AS total_events
FROM system.compute.warehouse_events we, cutoff
WHERE we.event_time >= cutoff.dt
GROUP BY we.workspace_id, we.warehouse_id
ORDER BY scale_up_events DESC NULLS LAST
LIMIT {result_limit}
"""


COMPUTE_RELIABILITY_PACK = QueryPack(
    pack_id="compute_reliability",
    domain="compute_reliability",
    name="Compute Reliability & Right-Sizing",
    description=(
        "Spot/on-demand reliability, node right-sizing, and warehouse scaling "
        "health over public system.compute.* tables"
    ),
    queries=(
        SystemQuery(
            query_id="CR-01",
            name="Instance Reliability by Availability Type",
            description=(
                "Spot vs on-demand instance churn: termination rate and mean "
                "lifetime from instance lifecycle events"
            ),
            sql_template=CR_01_SQL,
            required_tables=("system.compute.instance_events",),
            domain="compute_reliability",
            # system.compute.instance_events is Public Preview -> optional so a
            # missing table degrades this query, not the whole domain.
            required=False,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Spot vs on-demand reliability (termination rate, lifetime)",
                output_hint="Per-workspace availability-type reliability rollup",
                tags=("reliability", "spot", "preview"),
            ),
        ),
        SystemQuery(
            query_id="CR-02",
            name="Node Right-Sizing (Utilization vs Capacity)",
            description=(
                "Worker nodes banded oversized/underutilized/right-sized by "
                "joining node_timeline utilization to node_types capacity"
            ),
            sql_template=CR_02_SQL,
            required_tables=(
                "system.compute.node_timeline",
                "system.compute.node_types",
            ),
            domain="compute_reliability",
            required=True,
            max_lookback_days=90,  # node_timeline retains ~90 days
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Oversized/underutilized node detection",
                output_hint="Worker nodes ranked by lowest peak utilization",
                tags=("right-sizing", "utilization"),
            ),
        ),
        SystemQuery(
            query_id="CR-03",
            name="Warehouse Reliability & Scaling Churn",
            description=(
                "SQL warehouse scale/start/stop churn and peak cluster count "
                "from warehouse lifecycle events"
            ),
            sql_template=CR_03_SQL,
            required_tables=("system.compute.warehouse_events",),
            domain="compute_reliability",
            required=True,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Warehouse scaling churn and peak cluster count",
                output_hint="Warehouses ranked by scale-up frequency",
                tags=("reliability", "warehouse"),
            ),
        ),
    ),
    gating_products=frozenset(
        {"ALL_PURPOSE_COMPUTE", "JOBS_COMPUTE", "SQL_COMPUTE"}
    ),
)
