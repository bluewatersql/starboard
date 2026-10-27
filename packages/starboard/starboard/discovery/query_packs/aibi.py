# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""AI/BI dashboard discovery query pack.\n\nCovers dashboard audit, stale dashboards, and dashboard query performance.\nGenie signals (space inventory + per-space query performance) moved to the\ndedicated genie pack (P-GEN01/P-GEN02) so each AI/BI source has one owner."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

_QUERIES = [
    SystemQuery(
        query_id="P-AIBI01", name="Dashboard Audit Log Activity",
        description="Dashboards with authoring, view, and publish event counts",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT request_params.dashboard_id AS dashboard_id,
  ANY_VALUE(user_identity.email) AS last_actor_email,
  MIN(event_time) AS first_seen_at, MAX(event_time) AS last_seen_at,
  COUNT_IF(action_name IN ('createDashboard', 'cloneDashboard', 'migrateDashboard')) AS authoring_events,
  COUNT_IF(action_name IN ('getDashboard', 'getPublishedDashboard')) AS view_events,
  COUNT_IF(action_name = 'publishDashboard') AS publish_events
FROM system.access.audit, cutoff
WHERE service_name = 'dashboards' AND event_date >= cutoff.dt
GROUP BY request_params.dashboard_id
ORDER BY last_seen_at DESC
LIMIT {result_limit}""",
        required_tables=("system.access.audit",), domain="aibi", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Dashboards with authoring, view, and publish event counts", output_hint="Dashboards ranked by activity"),
    ),
    SystemQuery(
        query_id="P-AIBI02", name="Stale Published Dashboards",
        description="Published dashboards with no views in last 60 days",
        sql_template="""\
WITH published AS (
  SELECT DISTINCT request_params.dashboard_id AS dashboard_id
  FROM system.access.audit
  WHERE service_name = 'dashboards' AND action_name = 'publishDashboard'
    AND event_date >= DATEADD(DAY, -365, CURRENT_DATE())
)
SELECT p.dashboard_id
FROM published p
WHERE NOT EXISTS (
  SELECT 1 FROM system.access.audit v
  WHERE v.service_name = 'dashboards' AND v.action_name = 'getPublishedDashboard'
    AND v.event_date >= DATEADD(DAY, -60, CURRENT_DATE())
    AND v.request_params.dashboard_id = p.dashboard_id
)
ORDER BY p.dashboard_id
LIMIT {result_limit}""",
        required_tables=("system.access.audit",), domain="aibi", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(summary="Published dashboards with no views in last 60 days", output_hint="Stale published dashboards"),
    ),
    SystemQuery(
        query_id="P-AIBI04", name="AI/BI Dashboard Query Performance",
        description=(
            "Query latency metrics aggregated per dashboard and warehouse "
            "(warehouse_id = compute.warehouse_id; a dashboard on two warehouses "
            "has two rows). Dashboard-scoped "
            "only — the Genie branch of the former consolidated query now lives "
            "in the genie pack (P-GEN02), so each AI/BI source has exactly one "
            "owner. "
            "avg_capacity_wait_ms is the mean of waiting_at_capacity_duration_ms "
            "(time a query spent QUEUED waiting for warehouse capacity) over ALL "
            "queries, treating NULL (never queued) as 0 — so it is population-"
            "consistent with avg_total_ms and can never exceed it. "
            "queued_query_pct is the share of queries with a capacity wait > 0; "
            "avg_queued_wait_ms / p95_queued_wait_ms are the mean / p95 wait among "
            "ONLY the queued queries (NULL when none queued). These are signals of "
            "an over-subscribed / undersized warehouse, not per-query latency "
            "overhead."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt)
SELECT
  query_source.dashboard_id AS dashboard_id,
  -- One row per dashboard x warehouse, so a queued source maps straight to its
  -- OPP-WH-QUEUE target warehouse (query history attributes by compute.warehouse_id).
  compute.warehouse_id AS warehouse_id,
  COUNT(*) AS query_count,
  COUNT_IF(execution_status = 'FAILED') AS failed_queries,
  ROUND(AVG(total_duration_ms), 0) AS avg_total_ms,
  ROUND(APPROX_PERCENTILE(total_duration_ms, 0.50), 0) AS p50_total_ms,
  ROUND(APPROX_PERCENTILE(total_duration_ms, 0.95), 0) AS p95_total_ms,
  -- Capacity wait: NULL means "never queued", so average over ALL queries with
  -- COALESCE(..., 0). A bare AVG(waiting_at_capacity_duration_ms) averages only
  -- the queued rows and can exceed avg_total_ms (different populations).
  ROUND(AVG(COALESCE(waiting_at_capacity_duration_ms, 0)), 0) AS avg_capacity_wait_ms,
  ROUND(100.0 * COUNT_IF(waiting_at_capacity_duration_ms > 0) / COUNT(*), 1) AS queued_query_pct,
  ROUND(AVG(CASE WHEN waiting_at_capacity_duration_ms > 0 THEN waiting_at_capacity_duration_ms END), 0) AS avg_queued_wait_ms,
  ROUND(APPROX_PERCENTILE(CASE WHEN waiting_at_capacity_duration_ms > 0 THEN waiting_at_capacity_duration_ms END, 0.95), 0) AS p95_queued_wait_ms,
  ROUND(AVG(execution_duration_ms), 0) AS avg_exec_ms,
  ROUND(AVG(read_rows), 0) AS avg_rows_read, ROUND(AVG(read_bytes / 1048576.0), 2) AS avg_read_mb
FROM system.query.history, cutoff
WHERE query_source.dashboard_id IS NOT NULL AND start_time >= cutoff.dt
GROUP BY query_source.dashboard_id, compute.warehouse_id
ORDER BY p95_total_ms DESC
LIMIT {result_limit}""",
        required_tables=("system.query.history",), domain="aibi", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Query performance per dashboard", output_hint="Dashboard x warehouse rows ranked by p95 latency (warehouse_id maps a queued dashboard to its warehouse); avg_capacity_wait_ms = mean capacity wait over all queries (never-queued = 0, so <= avg_total_ms); queued_query_pct / avg_queued_wait_ms / p95_queued_wait_ms describe only the queued subset (undersized-warehouse signal)"),
    ),
]

AIBI_PACK = QueryPack(
    pack_id="aibi", domain="aibi", name="AI/BI Dashboards",
    description="AI/BI dashboard audit, stale dashboards, and dashboard query performance",
    queries=tuple(_QUERIES),
    gating_products=frozenset({"AI_FUNCTIONS", "SQL"}),
)
