"""Lakebase expanded discovery query pack.\n\nCovers instance usage, idle detection, cost trends, and growth.\nReplaces the single-query LAKEBASE_PACK from product_surfaces.py."""

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
        query_id="P-LB01", name="Usage by Instance",
        description="All Lakebase instances with total usage and workspace context",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT u.account_id, u.workspace_id, w.workspace_name,
  u.usage_metadata.database_instance_id AS database_instance_id,
  MIN(u.usage_start_time) AS first_seen_time, MAX(u.usage_end_time) AS last_seen_time,
  ROUND(SUM(u.usage_quantity), 4) AS total_units, MAX(u.usage_unit) AS usage_unit
FROM system.billing.usage u, cutoff
LEFT JOIN system.access.workspaces_latest w USING (workspace_id)
WHERE u.billing_origin_product = 'DATABASE' AND u.usage_date >= cutoff.dt
GROUP BY u.account_id, u.workspace_id, w.workspace_name, u.usage_metadata.database_instance_id
HAVING total_units != 0
ORDER BY total_units DESC
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.access.workspaces_latest",), domain="lakebase", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="All Lakebase instances with total usage and workspace context", output_hint="Instances ranked by usage"),
    ),
    SystemQuery(
        query_id="P-LB02", name="Idle Instance Detection",
        description="Instances ranked by staleness (oldest activity first)",
        sql_template="""\
SELECT p.workspace_id, w.workspace_name, p.database_instance_id, p.last_seen_time,
  ROUND(p.total_units, 4) AS total_units,
  DATEDIFF(DAY, p.last_seen_time, CURRENT_TIMESTAMP()) AS days_since_last_activity
FROM (
  SELECT workspace_id, usage_metadata.database_instance_id AS database_instance_id,
    MAX(usage_end_time) AS last_seen_time, SUM(usage_quantity) AS total_units
  FROM system.billing.usage WHERE billing_origin_product = 'DATABASE'
  GROUP BY workspace_id, usage_metadata.database_instance_id HAVING total_units != 0
) p
LEFT JOIN system.access.workspaces_latest w USING (workspace_id)
ORDER BY last_seen_time ASC
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.access.workspaces_latest",), domain="lakebase", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(summary="Instances ranked by staleness (oldest activity first)", output_hint="Idle instances ranked by staleness"),
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
WHERE u.billing_origin_product = 'DATABASE' AND u.usage_date >= cutoff.dt
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
  WHERE billing_origin_product = 'DATABASE'
    AND usage_date BETWEEN DATEADD(DAY, -14, CURRENT_DATE()) AND DATEADD(DAY, -1, CURRENT_DATE())
  GROUP BY workspace_id, usage_metadata.database_instance_id
),
prior AS (
  SELECT workspace_id, usage_metadata.database_instance_id AS database_instance_id,
    ROUND(SUM(usage_quantity), 4) AS units_prev_14
  FROM system.billing.usage
  WHERE billing_origin_product = 'DATABASE'
    AND usage_date BETWEEN DATEADD(DAY, -28, CURRENT_DATE()) AND DATEADD(DAY, -15, CURRENT_DATE())
  GROUP BY workspace_id, usage_metadata.database_instance_id
)
SELECT r.workspace_id, w.workspace_name, r.database_instance_id,
  COALESCE(p.units_prev_14, 0) AS units_prev_14, r.units_last_14,
  ROUND(r.units_last_14 - COALESCE(p.units_prev_14, 0), 4) AS delta_units,
  IF(p.units_prev_14 > 0, ROUND((r.units_last_14 - p.units_prev_14) / p.units_prev_14 * 100, 1), NULL) AS pct_change
FROM recent r LEFT JOIN prior p USING (workspace_id, database_instance_id)
LEFT JOIN system.access.workspaces_latest w ON r.workspace_id = w.workspace_id
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
