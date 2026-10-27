# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Feature Store discovery query pack — first-class strategic SKU.

Routes the ``FEATURE_STORE`` SKU (replacing the stale, invalid
``FEATURE_ENGINEERING`` routing key) to its own domain so feature-store spend is
surfaced on its own rather than silently analyzed as zero.

The feature-store system-table surface is thin today: there is no dedicated
feature-table freshness/usage system table on the public path, so this pack is
billing-grounded. The DBU spend trend (FS-01) reads ``system.billing.usage``
(always present, mirrored on the internal source) and is ``required=True``. The
online-serving / usage-detail breakdown (FS-02) is ``required=False`` so it
degrades honestly (reported skipped, not dropped) wherever the product-specific
signal is sparse. DBU-only — any ``$`` is a list-price estimate at the tool
layer.
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
        query_id="FS-01",
        name="Feature Store DBU Spend Trend",
        description=(
            "Daily FEATURE_STORE DBU by workspace from system.billing.usage. "
            "Billing is account-scoped so workspace_id is in the grain. DBU-only. "
            "Resolves on the internal mirror (billing.usage is carried)."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT
  u.usage_date,
  u.workspace_id,
  ROUND(SUM(u.usage_quantity), 2) AS total_dbus,
  COUNT(*) AS usage_records
FROM system.billing.usage u, cutoff
WHERE u.billing_origin_product = 'FEATURE_STORE'
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
        domain="feature_store",
        required=True,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.BILLING,
        metadata=QueryMetadata(
            summary="Daily FEATURE_STORE DBU spend by workspace",
            output_hint="Daily feature-store DBU trend",
            tags=("feature_store", "billing", "dbu"),
        ),
    ),
    SystemQuery(
        query_id="FS-02",
        name="Online Feature Serving Spend",
        description=(
            "Feature-store online-serving DBU by workspace and SKU "
            "(sku_name grain) from system.billing.usage — surfaces which "
            "feature-serving SKU drives the spend. required=False: the "
            "feature-serving signal is sparse / preview on many estates, so this "
            "degrades honestly rather than dropping. DBU-only."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT
  u.workspace_id,
  u.sku_name,
  ROUND(SUM(u.usage_quantity), 2) AS total_dbus,
  MIN(u.usage_date) AS first_usage,
  MAX(u.usage_date) AS last_usage,
  COUNT(DISTINCT u.usage_date) AS active_days
FROM system.billing.usage u, cutoff
WHERE u.billing_origin_product = 'FEATURE_STORE'
  AND u.usage_unit = 'DBU'
  AND u.usage_date >= cutoff.dt
GROUP BY u.workspace_id, u.sku_name
ORDER BY total_dbus DESC NULLS LAST
LIMIT {result_limit}""",
        required_tables=("system.billing.usage",),
        required_columns=(
            "usage_date",
            "workspace_id",
            "sku_name",
            "billing_origin_product",
            "usage_unit",
            "usage_quantity",
        ),
        domain="feature_store",
        required=False,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.BILLING,
        metadata=QueryMetadata(
            summary="Feature-store online-serving DBU by workspace and SKU",
            output_hint="Feature-serving SKUs ranked by DBU; sparse/preview on many estates",
            tags=("feature_store", "online_serving", "billing", "dbu"),
        ),
    ),
]

FEATURE_STORE_PACK = QueryPack(
    pack_id="feature_store",
    domain="feature_store",
    name="Feature Store",
    description=(
        "Feature Store spend and online-serving usage: DBU spend trend (FS-01) "
        "and online-serving spend by SKU (FS-02). Billing-grounded while the "
        "feature-store system-table surface remains thin; non-billing signals "
        "degrade via required=False. Public system.billing.usage only; DBU-only; "
        "workspace-scoped."
    ),
    queries=tuple(_QUERIES),
    gating_products=frozenset({"FEATURE_STORE"}),
)
