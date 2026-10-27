# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Genie (AI/BI Genie) discovery query pack — first-class strategic SKU.

Genie is routed as its own domain so ``GENIE`` spend is never bucketed into a
generic attribution pack. This pack is the SOLE owner of the Genie-space
inventory and per-space query-performance signals (previously P-AIBI03 and the
Genie branch of the consolidated P-AIBI04 in ``aibi.py``); ``aibi`` now keeps
only the dashboard-scoped queries, so there is exactly one owner and no
double-count.

Coverage honesty / internal-mirror notes:
- P-GEN01 (space inventory) and P-GEN02 (per-space query performance) read
  ``system.access.audit`` / ``system.query.history`` activity signals and are
  ``required=False`` so a workspace with no Genie activity — or the internal
  mirror, which does not carry ``system.access.audit`` — degrades the query
  (reported skipped) rather than failing the domain.
- P-GEN03 (``GENIE`` DBU spend trend) reads ``system.billing.usage`` only, which
  is always present (and mirrored on the internal source), so it is
  ``required=True`` and gives real coverage for the SKU on both sources. DBU-only
  — any ``$`` is a list-price estimate at the tool layer.
"""

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
        query_id="P-GEN01",
        name="Genie Space Inventory",
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
        required_tables=("system.access.audit",),
        domain="genie",
        required=False,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.PROFILE,
        metadata=QueryMetadata(
            summary="Genie spaces with conversation and message counts",
            output_hint="Genie spaces ranked by activity",
            tags=("genie", "aibi", "adoption"),
        ),
    ),
    SystemQuery(
        query_id="P-GEN02",
        name="Genie Query Performance",
        description=(
            "Query latency metrics aggregated per Genie space and warehouse "
            "(warehouse_id = compute.warehouse_id; a space on two warehouses has "
            "two rows; split out of the "
            "former consolidated P-AIBI04; the dashboard side stays in aibi). "
            "avg_capacity_wait_ms is the mean of waiting_at_capacity_duration_ms "
            "(time a query spent QUEUED waiting for warehouse capacity) over ALL "
            "queries, treating NULL (never queued) as 0 — so it is population-"
            "consistent with avg_total_ms and can never exceed it. "
            "queued_query_pct is the share of queries with a capacity wait > 0; "
            "avg_queued_wait_ms / p95_queued_wait_ms are the mean / p95 wait among "
            "ONLY the queued queries (NULL when none queued). These are signals of "
            "an over-subscribed / undersized shared Genie warehouse, not per-query "
            "latency overhead."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt)
SELECT
  query_source.genie_space_id AS genie_space_id,
  -- One row per genie space x warehouse, so a queued source maps straight to its
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
WHERE query_source.genie_space_id IS NOT NULL AND start_time >= cutoff.dt
GROUP BY query_source.genie_space_id, compute.warehouse_id
ORDER BY p95_total_ms DESC
LIMIT {result_limit}""",
        required_tables=("system.query.history",),
        domain="genie",
        required=False,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.PROFILE,
        metadata=QueryMetadata(
            summary="Query performance per Genie space",
            output_hint=(
                "Genie space x warehouse rows ranked by p95 latency (warehouse_id "
                "maps a queued space to its warehouse); avg_capacity_wait_ms = mean "
                "capacity wait over all queries (never-queued = 0, so <= avg_total_ms); "
                "queued_query_pct / avg_queued_wait_ms / p95_queued_wait_ms describe "
                "only the queued subset (undersized-warehouse signal)"
            ),
            tags=("genie", "aibi", "query_performance"),
        ),
    ),
    SystemQuery(
        query_id="P-GEN03",
        name="Genie DBU Spend Trend",
        description=(
            "Daily GENIE DBU by workspace from system.billing.usage. Billing is "
            "account-scoped so workspace_id is in the grain (without it the totals "
            "silently conflate workspaces). DBU-only — any $ view is a list-price "
            "estimate at the tool layer. The one query in this pack that resolves "
            "on the internal mirror (billing.usage is carried), so GENIE produces "
            "real coverage on both sources."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT
  u.usage_date,
  u.workspace_id,
  ROUND(SUM(u.usage_quantity), 2) AS total_dbus,
  COUNT(*) AS usage_records
FROM system.billing.usage u, cutoff
WHERE u.billing_origin_product = 'GENIE'
  AND u.usage_unit = 'DBU'
  AND u.usage_date >= cutoff.dt
GROUP BY u.usage_date, u.workspace_id
ORDER BY u.usage_date DESC, total_dbus DESC NULLS LAST
LIMIT {result_limit}""",
        required_tables=("system.billing.usage",),
        required_columns=(
            "usage_date",
            "workspace_id",
            "billing_origin_product",
            "usage_unit",
            "usage_quantity",
        ),
        domain="genie",
        required=True,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.BILLING,
        metadata=QueryMetadata(
            summary="Daily GENIE DBU spend by workspace",
            output_hint="Daily GENIE DBU trend; rising trend = growing Genie adoption/cost",
            tags=("genie", "billing", "dbu"),
        ),
    ),
]

GENIE_PACK = QueryPack(
    pack_id="genie",
    domain="genie",
    name="AI/BI Genie",
    description=(
        "Genie-space inventory and adoption (P-GEN01), per-space query "
        "performance (P-GEN02), and GENIE DBU spend trend (P-GEN03). Sole owner "
        "of the Genie signals formerly in the aibi pack. Public system tables "
        "only; DBU-only billing; workspace-scoped."
    ),
    queries=tuple(_QUERIES),
    gating_products=frozenset({"GENIE", "SQL"}),
)
