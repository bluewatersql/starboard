"""Governance and data management pack."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery

N_L01_SQL = """\
SELECT
  source_table_catalog,
  source_table_schema,
  source_table_name,
  target_table_catalog,
  target_table_schema,
  target_table_name,
  COUNT(DISTINCT entity_run_id) AS pipeline_references,
  MAX(event_time)               AS last_referenced
FROM system.access.table_lineage
WHERE event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
GROUP BY ALL
ORDER BY pipeline_references DESC
LIMIT 5000
"""

N_L02_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt
)
SELECT
  request_params.table_full_name           AS table_full_name,
  action_name,
  COUNT(*)                                 AS access_count,
  COUNT(DISTINCT user_identity.email)      AS distinct_users,
  COUNT(DISTINCT service_name)             AS distinct_services,
  MIN(event_time)                          AS first_access,
  MAX(event_time)                          AS last_access,
  DATEDIFF(DAY, MAX(event_time), CURRENT_TIMESTAMP()) AS days_since_last_access
FROM system.access.audit, cutoff
WHERE event_time >= cutoff.dt
  AND action_name IN ('getTable', 'queryTable', 'createTableAsSelect')
  AND request_params.table_full_name IS NOT NULL
GROUP BY ALL
ORDER BY days_since_last_access DESC, access_count DESC
LIMIT 5000
"""

N_DT01_SQL = """\
WITH now AS (
  SELECT CURRENT_TIMESTAMP() AS ts
)
SELECT
  table_catalog,
  table_schema,
  table_name,
  table_type,
  data_source_format,
  created,
  last_altered,
  DATEDIFF(DAY, last_altered, now.ts)      AS days_since_modified,
  CASE
    WHEN DATEDIFF(DAY, last_altered, now.ts) > 30 THEN 'Stale (>30d)'
    WHEN DATEDIFF(DAY, last_altered, now.ts) > 7  THEN 'Recent (7-30d)'
    ELSE 'Active'
  END                                      AS freshness_status
FROM system.information_schema.tables, now
WHERE table_catalog NOT IN ('system', '__databricks_internal')
  AND data_source_format = 'DELTA'
ORDER BY days_since_modified DESC
LIMIT 5000
"""

N_NB01_SQL = """\
SELECT
  workspace_id,
  identity_metadata.run_as            AS user,
  CASE
    WHEN usage_metadata.job_id IS NULL THEN 'Interactive/Notebook'
    ELSE                                    'All-Purpose Job Compute'
  END                                 AS compute_context,
  ROUND(SUM(usage_quantity), 2)       AS dbus
FROM system.billing.usage
WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND billing_origin_product = 'ALL_PURPOSE'
  AND identity_metadata.run_as LIKE '%@%'
GROUP BY ALL
ORDER BY dbus DESC
"""

N_ST01_SQL = """\
SELECT
  workspace_id,
  sku_name,
  billing_origin_product,
  DATE_TRUNC('MONTH', usage_date)      AS year_month,
  ROUND(SUM(usage_quantity), 2)        AS usage_quantity,
  usage_unit
FROM system.billing.usage
WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND (
    billing_origin_product = 'DELTA_CACHE'
    OR sku_name LIKE '%STORAGE%'
  )
GROUP BY ALL
ORDER BY usage_quantity DESC
"""

GOVERNANCE_PACK = QueryPack(
    pack_id="governance",
    domain="governance",
    name="Governance & Data Management",
    description="Lineage, access patterns, permission sprawl, Delta health, storage attribution",
    queries=(
        SystemQuery(
            query_id="N-L01",
            name="Table Lineage — Downstream Impact",
            description="Source-to-target lineage and pipeline references",
            sql_template=N_L01_SQL,
            required_tables=("system.access.table_lineage",),
            domain="governance",
            required=False,
            lookback_override=90,
        ),
        SystemQuery(
            query_id="N-L02",
            name="Table Access Frequency",
            description="Table access counts, users, and recency",
            sql_template=N_L02_SQL,
            required_tables=("system.access.audit",),
            domain="governance",
            required=False,
            lookback_override=90,
        ),
        # N-L03 disabled — see comment above N_L03_SQL
        SystemQuery(
            query_id="N-DT01",
            name="Delta Table Health & Freshness",
            description="Delta tables with staleness and freshness status",
            sql_template=N_DT01_SQL,
            required_tables=("system.information_schema.tables",),
            domain="governance",
            required=False,
        ),
        SystemQuery(
            query_id="N-NB01",
            name="Notebook/Interactive Compute Attribution",
            description="DBU consumption by interactive vs job compute context",
            sql_template=N_NB01_SQL,
            required_tables=("system.billing.usage",),
            domain="governance",
            required=False,
        ),
        SystemQuery(
            query_id="N-ST01",
            name="Storage I/O Attribution",
            description="Storage and Delta Cache usage by workspace and SKU",
            sql_template=N_ST01_SQL,
            required_tables=("system.billing.usage",),
            domain="governance",
            required=False,
            lookback_override=90,
        ),
    ),
    gating_products=frozenset(),
)
