# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Platform audit query pack for Databricks discovery.

Determines which product surfaces are active in the workspace by aggregating
DBU consumption by billing_origin_product, sku_name, and serverless flag.
This pack runs first and gates which domain packs execute.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

P_AUDIT01_SQL = """\
-- billing_origin_product surface audit. Grain carries workspace_id because
-- system.billing.usage is ACCOUNT-scoped (spans every workspace the account can see);
-- without workspace_id the top-line silently conflates all workspaces. Pack gating sums
-- per product across workspaces (see engine._extract_products); the host scopes/labels
-- the presented totals to the caller's workspace or all workspaces per the scope prompt.
--
-- usage_unit is in the grain: billing rows can carry multiple units (DBU, DSU, …).
-- Summing across units and labelling the result "DBU" is incorrect — each row is
-- now a single-unit slice so total_usage is always within-unit (W3 fix).
SELECT
  workspace_id,
  billing_origin_product,
  usage_unit,
  ROUND(SUM(usage_quantity), 2)  AS total_usage,
  COUNT(DISTINCT sku_name)       AS distinct_skus,
  MIN(usage_date)                AS first_seen_in_window,
  MAX(usage_date)                AS last_seen
FROM system.billing.usage
WHERE usage_date BETWEEN DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
                     AND CURRENT_DATE()
GROUP BY ALL
ORDER BY workspace_id, total_usage DESC
"""

AUDIT_PACK = QueryPack(
    pack_id="audit",
    domain="audit",
    name="Platform Surface Audit",
    description="Determines which product surfaces are active in the workspace",
    queries=(
        SystemQuery(
            query_id="P-AUDIT01",
            name="Platform Surface Audit",
            description="Full platform DBU map by product — determines which domain packs to run",
            sql_template=P_AUDIT01_SQL,
            required_tables=("system.billing.usage",),
            domain="audit",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.PROFILE,
            metadata=QueryMetadata(
                summary="Billing origin product surface audit",
                output_hint="",
            ),
        ),
    ),
    gating_products=frozenset(),
)
