# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""AI/BI expanded discovery query pack.\n\nCovers dashboard audit, stale dashboards, Genie spaces, and query performance.\nReplaces the 2-query AIBI_PACK from product_surfaces.py."""

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
        query_id="P-AIBI03", name="Genie Space Inventory",
        description="Genie spaces with conversation and message counts",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT request_params.space_id AS space_id,
  MIN(event_time) AS first_seen_at, MAX(event_time) AS last_seen_at,
  ANY_VALUE(user_identity.email) AS any_actor_email,
  COUNT_IF(action_name = 'createSpace') AS create_events,
  COUNT_IF(action_name = 'getSpace') AS open_events,
  COUNT_IF(action_name = 'createConversation') AS conversations_started,
  COUNT_IF(action_name IN ('createConversationMessage', 'genieCreateConversationMessage')) AS messages_created
FROM system.access.audit, cutoff
WHERE service_name = 'aibiGenie' AND event_date >= cutoff.dt
GROUP BY request_params.space_id
ORDER BY last_seen_at DESC
LIMIT {result_limit}""",
        required_tables=("system.access.audit",), domain="aibi", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Genie spaces with conversation and message counts", output_hint="Genie spaces ranked by activity"),
    ),
    SystemQuery(
        query_id="P-AIBI04", name="AI/BI Query Performance",
        description=(
            "Query latency metrics aggregated per dashboard and Genie space. "
            "Consolidates former P-AIBI05 (per-Genie space) into one query."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt)
SELECT
  CASE WHEN query_source.dashboard_id IS NOT NULL THEN 'dashboard' ELSE 'genie' END AS source_type,
  COALESCE(query_source.dashboard_id, query_source.genie_space_id) AS source_id,
  COUNT(*) AS query_count,
  COUNT_IF(execution_status = 'FAILED') AS failed_queries,
  ROUND(AVG(total_duration_ms), 0) AS avg_total_ms,
  ROUND(APPROX_PERCENTILE(total_duration_ms, 0.50), 0) AS p50_total_ms,
  ROUND(APPROX_PERCENTILE(total_duration_ms, 0.95), 0) AS p95_total_ms,
  ROUND(AVG(waiting_at_capacity_duration_ms), 0) AS avg_queue_wait_ms,
  ROUND(AVG(execution_duration_ms), 0) AS avg_exec_ms,
  ROUND(AVG(read_rows), 0) AS avg_rows_read, ROUND(AVG(read_bytes / 1048576.0), 2) AS avg_read_mb
FROM system.query.history, cutoff
WHERE (query_source.dashboard_id IS NOT NULL OR query_source.genie_space_id IS NOT NULL) AND start_time >= cutoff.dt
GROUP BY
  CASE WHEN query_source.dashboard_id IS NOT NULL THEN 'dashboard' ELSE 'genie' END,
  COALESCE(query_source.dashboard_id, query_source.genie_space_id)
ORDER BY p95_total_ms DESC
LIMIT {result_limit}""",
        required_tables=("system.query.history",), domain="aibi", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Query performance per dashboard and Genie space", output_hint="AI/BI sources ranked by p95 latency"),
    ),
]

AIBI_PACK = QueryPack(
    pack_id="aibi", domain="aibi", name="AI/BI Dashboards and Genie",
    description="AI/BI dashboard audit, Genie space inventory, and query performance",
    queries=tuple(_QUERIES),
    gating_products=frozenset({"AI_FUNCTIONS", "SQL"}),
)
