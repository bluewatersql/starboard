# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Lakebase expanded discovery query pack.\n\nCovers instance usage, idle detection, cost trends, and growth.\nReplaces the single-query LAKEBASE_PACK from product_surfaces.py.\n\nProduct-name note: Lakebase spend bills under BOTH ``billing_origin_product`` values\n``'LAKEBASE'`` (the bulk — verified 829K DBU/30d in a live estate) and ``'DATABASE'`` (a\nsmall serverless sliver). Every query gates on ``IN ('DATABASE', 'LAKEBASE')`` — filtering\non ``'DATABASE'`` alone silently drops ~99% of the spend. Keep in sync with the pack's\n``gating_products``."""

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
        query_id="P-LB01", name="Instance Usage and Staleness",
        description=(
            "All Lakebase instances with total usage, workspace context, "
            "and staleness metrics. Consolidates former P-LB02 (idle "
            "instance detection) into one query."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
all_time_usage AS (
  SELECT workspace_id, usage_metadata.database_instance_id AS database_instance_id,
    MAX(usage_end_time) AS last_seen_time_all, SUM(usage_quantity) AS total_units_all
  FROM system.billing.usage
  WHERE billing_origin_product IN ('DATABASE', 'LAKEBASE')
    AND usage_date >= DATEADD(DAY, -90, CURRENT_DATE())   -- G4: bound scan to 90d
  GROUP BY workspace_id, usage_metadata.database_instance_id HAVING total_units_all != 0
),
-- Dedupe the workspace-name dim to ONE row per workspace_id BEFORE joining: on
-- the internal fleet mirror it can carry multiple rows per workspace, which
-- would fan out each billing.usage row and inflate SUM(usage_quantity) — a
-- silent N× overcount of total_units (same dim-fan-out family as P-LB04 and the
-- billing_list_prices catalog; here it sums a quantity, so it's the worse case).
wsl AS (
  SELECT workspace_id, ANY_VALUE(workspace_name) AS workspace_name
  FROM system.access.workspaces_latest
  GROUP BY workspace_id
)
SELECT u.account_id, u.workspace_id, w.workspace_name,
  u.usage_metadata.database_instance_id AS database_instance_id,
  -- endpoint_name as secondary attribution: when database_instance_id is null
  -- (seen live on some workspaces), endpoint_name may carry the instance endpoint
  -- identity (usage_metadata.endpoint_name resolves in both public and mirror tables).
  -- Exposed here so null database_instance_id is not the end of attribution (D11).
  u.usage_metadata.endpoint_name       AS endpoint_name,
  -- usage_unit is in the GROUP BY so each row is a single-unit slice (DBU or DSU).
  -- MAX(usage_unit) was removed: it picked one label for a potentially mixed sum,
  -- which surfaced as 1,208.65 "DSU" that was really 1,163.57 DBU + 0.80 DSU (W3).
  u.usage_unit                          AS usage_unit,
  MIN(u.usage_start_time) AS first_seen_time, MAX(u.usage_end_time) AS last_seen_time,
  ROUND(SUM(u.usage_quantity), 4) AS total_units,
  DATEDIFF(DAY, atu.last_seen_time_all, CURRENT_TIMESTAMP()) AS days_since_last_activity
FROM system.billing.usage u, cutoff
LEFT JOIN wsl w USING (workspace_id)
LEFT JOIN all_time_usage atu ON u.workspace_id = atu.workspace_id
  AND u.usage_metadata.database_instance_id = atu.database_instance_id
WHERE u.billing_origin_product IN ('DATABASE', 'LAKEBASE') AND u.usage_date >= cutoff.dt
GROUP BY u.account_id, u.workspace_id, w.workspace_name, u.usage_metadata.database_instance_id,
  u.usage_metadata.endpoint_name, u.usage_unit, atu.last_seen_time_all
HAVING total_units != 0
ORDER BY total_units DESC
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.access.workspaces_latest",), domain="lakebase", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(
            summary="Lakebase instances with usage, workspace context, and staleness",
            output_hint=(
                "Instances ranked by usage with idle detection. "
                "endpoint_name is a secondary attribution key when database_instance_id is null."
            ),
        ),
    ),
    SystemQuery(
        query_id="P-LB03", name="Daily Cost Trend",
        description="Daily Lakebase estimated list-price cost",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT u.usage_date,
  ROUND(SUM(u.usage_quantity * lp.pricing.effective_list.default), 2) AS est_lakebase_list_price
FROM system.billing.usage u, cutoff
JOIN system.billing.list_prices lp ON lp.sku_name = u.sku_name AND lp.cloud = u.cloud
  AND lp.usage_unit = u.usage_unit AND u.usage_end_time >= lp.price_start_time
  AND (lp.price_end_time IS NULL OR u.usage_end_time < lp.price_end_time)
WHERE u.billing_origin_product IN ('DATABASE', 'LAKEBASE') AND u.usage_date >= cutoff.dt
GROUP BY u.usage_date
ORDER BY u.usage_date
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.billing.list_prices",), domain="lakebase", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Daily Lakebase estimated list-price cost", output_hint="Daily cost trend"),
    ),
    SystemQuery(
        query_id="P-LB04", name="Instance Growth (14-Day Comparison)",
        description="Per-instance usage growth comparing last-14 vs prior-14 days",
        sql_template="""\
WITH recent AS (
  SELECT workspace_id, usage_metadata.database_instance_id AS database_instance_id,
    ROUND(SUM(usage_quantity), 4) AS units_last_14
  FROM system.billing.usage
  WHERE billing_origin_product IN ('DATABASE', 'LAKEBASE')
    AND usage_date BETWEEN DATEADD(DAY, -14, CURRENT_DATE()) AND DATEADD(DAY, -1, CURRENT_DATE())
  GROUP BY workspace_id, usage_metadata.database_instance_id
),
prior AS (
  SELECT workspace_id, usage_metadata.database_instance_id AS database_instance_id,
    ROUND(SUM(usage_quantity), 4) AS units_prev_14
  FROM system.billing.usage
  WHERE billing_origin_product IN ('DATABASE', 'LAKEBASE')
    AND usage_date BETWEEN DATEADD(DAY, -28, CURRENT_DATE()) AND DATEADD(DAY, -15, CURRENT_DATE())
  GROUP BY workspace_id, usage_metadata.database_instance_id
),
-- Dedupe the workspace-name dimension to ONE row per workspace_id: on the
-- internal fleet mirror this view can carry multiple rows per workspace, which
-- would fan the result out into duplicate instance rows (same dim-fan-out family
-- as the billing_list_prices catalog). ANY_VALUE keeps a single name per id.
wsl AS (
  SELECT workspace_id, ANY_VALUE(workspace_name) AS workspace_name
  FROM system.access.workspaces_latest
  GROUP BY workspace_id
)
SELECT r.workspace_id, w.workspace_name, r.database_instance_id,
  COALESCE(p.units_prev_14, 0) AS units_prev_14, r.units_last_14,
  ROUND(r.units_last_14 - COALESCE(p.units_prev_14, 0), 4) AS delta_units,
  IF(p.units_prev_14 > 0, ROUND((r.units_last_14 - p.units_prev_14) / p.units_prev_14 * 100, 1), NULL) AS pct_change
-- Null-safe (<=>) join key so a NULL database_instance_id row in `recent` still
-- matches its `prior` counterpart (plain = never matches NULL to NULL).
FROM recent r
LEFT JOIN prior p
  ON r.workspace_id = p.workspace_id
 AND r.database_instance_id <=> p.database_instance_id
LEFT JOIN wsl w ON r.workspace_id = w.workspace_id
ORDER BY pct_change DESC NULLS LAST
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.access.workspaces_latest",), domain="lakebase", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Per-instance usage growth comparing last-14 vs prior-14 days", output_hint="Instances ranked by growth"),
    ),
]

LAKEBASE_PACK = QueryPack(
    pack_id="lakebase", domain="lakebase", name="Lakebase",
    description="Lakebase instance usage, cost, and growth analysis",
    queries=tuple(_QUERIES),
    gating_products=frozenset({"DATABASE", "LAKEBASE"}),
)
