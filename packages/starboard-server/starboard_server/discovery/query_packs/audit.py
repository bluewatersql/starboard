"""Platform audit query pack for Databricks discovery.

Determines which product surfaces are active in the workspace by aggregating
DBU consumption by billing_origin_product, sku_name, and serverless flag.
This pack runs first and gates which domain packs execute.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery

P_AUDIT01_SQL = """\
SELECT
  billing_origin_product,
  ROUND(SUM(usage_quantity), 2)  AS total_dbus,
  COUNT(DISTINCT sku_name)       AS distinct_skus,
  MIN(usage_date)                AS first_seen,
  MAX(usage_date)                AS last_seen
FROM system.billing.usage
WHERE usage_date BETWEEN DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
                     AND CURRENT_DATE()
GROUP BY ALL
ORDER BY total_dbus DESC
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
        ),
    ),
    gating_products=frozenset(),
)
