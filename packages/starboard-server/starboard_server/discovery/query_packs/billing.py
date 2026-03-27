"""Billing and resource consumption query pack for Databricks discovery.

DBU consumption attribution, trends, growth detection, and chargeback.
Always runs (no product gating). All queries use DBU metrics only;
no dollar/cost computations.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery

C_B01_SQL = """\
SELECT
  u.workspace_id,
  u.billing_origin_product,
  u.sku_name,
  u.product_features.is_serverless                AS is_serverless,
  u.identity_metadata.run_as                      AS run_as,
  CASE
    WHEN u.identity_metadata.run_as LIKE '%@%' THEN 'Human User'
    WHEN u.identity_metadata.run_as IS NULL    THEN 'Unattributed'
    ELSE                                            'Service Principal'
  END                                             AS user_type,
  COUNT(DISTINCT u.usage_metadata.job_id)         AS distinct_jobs,
  COUNT(DISTINCT u.usage_metadata.job_run_id)     AS distinct_runs,
  ROUND(SUM(u.usage_quantity), 2)                 AS dbus_consumed
FROM system.billing.usage u
WHERE u.usage_date BETWEEN DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
                       AND CURRENT_DATE()
GROUP BY ALL
ORDER BY dbus_consumed DESC
"""

C_B02_SQL = """\
SELECT
  DATE_TRUNC('MONTH', u.usage_date)  AS year_month,
  u.workspace_id,
  u.billing_origin_product,
  u.sku_name,
  u.product_features.is_serverless   AS is_serverless,
  ROUND(SUM(u.usage_quantity), 2)    AS dbus
FROM system.billing.usage u
WHERE u.usage_date BETWEEN DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
                       AND CURRENT_DATE()
GROUP BY ALL
ORDER BY year_month DESC, dbus DESC
"""

C_B03_SQL = """\
WITH date_bounds AS (
  -- Materialise the four boundary dates once so Spark doesn't recompute
  -- CURRENT_DATE() per row inside the CASE expressions.
  SELECT
    DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS lookback_start,
    DATEADD(DAY, -15, CURRENT_DATE())              AS prior_start,   -- d-15
    DATEADD(DAY,  -8, CURRENT_DATE())              AS boundary,      -- d-8
    DATEADD(DAY,  -1, CURRENT_DATE())              AS last_end       -- d-1
),
job_dbus AS (
  SELECT
    t1.workspace_id,
    t1.sku_name,
    t1.usage_metadata.job_id        AS job_id,
    t1.identity_metadata.run_as     AS run_as,
    t1.usage_quantity               AS dbus,
    t1.usage_end_time
  FROM system.billing.usage t1, date_bounds d
  WHERE t1.billing_origin_product = 'JOBS'
    AND t1.usage_date BETWEEN d.lookback_start AND CURRENT_DATE()
),
most_recent_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                             ORDER BY change_time DESC) = 1
)
SELECT
  t2.name,
  t1.workspace_id,
  t1.job_id,
  t1.sku_name,
  t1.run_as,
  ROUND(SUM(CASE WHEN t1.usage_end_time BETWEEN d.boundary  AND d.last_end   THEN dbus ELSE 0 END), 2) AS last7_dbus,
  ROUND(SUM(CASE WHEN t1.usage_end_time BETWEEN d.prior_start AND d.boundary THEN dbus ELSE 0 END), 2) AS prior7_dbus,
  ROUND(
    SUM(CASE WHEN t1.usage_end_time BETWEEN d.boundary   AND d.last_end   THEN dbus ELSE 0 END)
    - SUM(CASE WHEN t1.usage_end_time BETWEEN d.prior_start AND d.boundary THEN dbus ELSE 0 END),
    2
  )                                                                                                     AS wow_dbu_growth,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN t1.usage_end_time BETWEEN d.boundary   AND d.last_end   THEN dbus ELSE 0 END)
      - SUM(CASE WHEN t1.usage_end_time BETWEEN d.prior_start AND d.boundary THEN dbus ELSE 0 END),
      SUM(CASE WHEN t1.usage_end_time BETWEEN d.prior_start AND d.boundary   THEN dbus ELSE 0 END)
    ) * 100,
    1
  )                                                                                                     AS wow_growth_pct
FROM job_dbus t1
CROSS JOIN date_bounds d
LEFT JOIN most_recent_jobs t2 USING (workspace_id, job_id)
GROUP BY ALL
ORDER BY wow_dbu_growth DESC
LIMIT 100
"""

C_B04_SQL = """\
SELECT
  u.workspace_id,
  u.billing_origin_product,
  u.custom_tags['team']             AS team_tag,
  u.custom_tags['project']          AS project_tag,
  u.custom_tags['environment']      AS environment_tag,
  u.custom_tags['cost_center']      AS cost_center_tag,
  ROUND(SUM(u.usage_quantity), 2)   AS dbus,
  COUNT(DISTINCT u.usage_metadata.job_id) AS distinct_jobs,
  ROUND(SUM(CASE WHEN u.custom_tags IS NULL
                   OR CARDINALITY(u.custom_tags) = 0
                 THEN u.usage_quantity ELSE 0 END), 2) AS untagged_dbus
FROM system.billing.usage u
WHERE u.usage_date BETWEEN DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
                       AND CURRENT_DATE()
GROUP BY ALL
ORDER BY dbus DESC
"""

BILLING_PACK = QueryPack(
    pack_id="billing",
    domain="billing",
    name="Resource Consumption & Attribution",
    description="DBU consumption attribution, trends, growth detection, chargeback",
    queries=(
        SystemQuery(
            query_id="C-B01",
            name="DBU Consumption by Workspace x Product x Identity",
            description="DBU attribution by product, run_as identity, and user type",
            sql_template=C_B01_SQL,
            required_tables=("system.billing.usage",),
            domain="billing",
        ),
        SystemQuery(
            query_id="C-B02",
            name="Monthly SKU Trend",
            description="DBU by month, workspace, product, and SKU",
            sql_template=C_B02_SQL,
            required_tables=("system.billing.usage",),
            domain="billing",
            lookback_override=90,
        ),
        SystemQuery(
            query_id="C-B03",
            name="Week-over-Week DBU Growth by Job",
            description="Job-level WoW DBU growth for top consumers",
            sql_template=C_B03_SQL,
            required_tables=("system.billing.usage", "system.lakeflow.jobs"),
            domain="billing",
            lookback_override=14,
        ),
        SystemQuery(
            query_id="C-B04",
            name="Tag-Based Consumption Attribution",
            description="DBU by custom tags (team, project, environment, cost_center) and untagged usage",
            sql_template=C_B04_SQL,
            required_tables=("system.billing.usage",),
            domain="billing",
        ),
    ),
    gating_products=frozenset(),
)
