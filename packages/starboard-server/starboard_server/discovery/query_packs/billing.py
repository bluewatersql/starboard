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
  u.product_features.is_serverless AS is_serverless,
  u.identity_metadata.run_as AS run_as,
  CASE
    WHEN u.identity_metadata.run_as LIKE '%@%' THEN 'Human User'
    WHEN u.identity_metadata.run_as IS NULL   THEN 'Unattributed'
    ELSE 'Service Principal'
  END AS user_type,
  COUNT(DISTINCT u.usage_metadata.job_id) AS distinct_jobs,
  COUNT(DISTINCT u.usage_metadata.job_run_id) AS distinct_runs,
  ROUND(SUM(u.usage_quantity), 2) AS dbus_consumed
FROM system.billing.usage u
WHERE u.usage_date >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
GROUP BY ALL
ORDER BY dbus_consumed DESC
"""

C_B02_SQL = """\
SELECT
  DATE_TRUNC('MONTH', u.usage_date) AS year_month,
  u.workspace_id,
  u.billing_origin_product,
  u.sku_name,
  u.product_features.is_serverless AS is_serverless,
  ROUND(SUM(u.usage_quantity), 2) AS dbus
FROM system.billing.usage u
WHERE u.usage_date >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
GROUP BY ALL
ORDER BY year_month DESC, dbus DESC
"""

C_B03_SQL = """\
WITH job_run_timeline_with_dbus AS (
  SELECT
    t1.*,
    t1.usage_metadata.job_id AS job_id,
    t1.identity_metadata.run_as AS run_as,
    t1.usage_quantity AS dbus
  FROM system.billing.usage t1
  WHERE t1.billing_origin_product = 'JOBS'
    AND t1.usage_date >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
),
most_recent_jobs AS (
  SELECT *, ROW_NUMBER() OVER(PARTITION BY workspace_id, job_id ORDER BY change_time DESC) AS rn
  FROM system.lakeflow.jobs QUALIFY rn = 1
)
SELECT
  t2.name,
  t1.workspace_id,
  t1.job_id,
  t1.sku_name,
  t1.run_as,
  ROUND(SUM(CASE WHEN usage_end_time BETWEEN date_add(current_date(), -8) AND date_add(current_date(), -1) THEN dbus ELSE 0 END), 2) AS last7_dbus,
  ROUND(SUM(CASE WHEN usage_end_time BETWEEN date_add(current_date(), -15) AND date_add(current_date(), -8) THEN dbus ELSE 0 END), 2) AS prior7_dbus,
  ROUND(
    SUM(CASE WHEN usage_end_time BETWEEN date_add(current_date(), -8) AND date_add(current_date(), -1) THEN dbus ELSE 0 END)
    - SUM(CASE WHEN usage_end_time BETWEEN date_add(current_date(), -15) AND date_add(current_date(), -8) THEN dbus ELSE 0 END),
    2
  ) AS wow_dbu_growth,
  ROUND(
    TRY_DIVIDE(
      SUM(CASE WHEN usage_end_time BETWEEN date_add(current_date(), -8) AND date_add(current_date(), -1) THEN dbus ELSE 0 END)
      - SUM(CASE WHEN usage_end_time BETWEEN date_add(current_date(), -15) AND date_add(current_date(), -8) THEN dbus ELSE 0 END),
      NULLIF(SUM(CASE WHEN usage_end_time BETWEEN date_add(current_date(), -15) AND date_add(current_date(), -8) THEN dbus ELSE 0 END), 0)
    ) * 100,
    1
  ) AS wow_growth_pct
FROM job_run_timeline_with_dbus t1
LEFT JOIN most_recent_jobs t2 USING (workspace_id, job_id)
GROUP BY ALL
ORDER BY wow_dbu_growth DESC
LIMIT 100
"""

C_B04_SQL = """\
SELECT
  u.workspace_id,
  u.billing_origin_product,
  u.custom_tags['team'] AS team_tag,
  u.custom_tags['project'] AS project_tag,
  u.custom_tags['environment'] AS environment_tag,
  u.custom_tags['cost_center'] AS cost_center_tag,
  ROUND(SUM(u.usage_quantity), 2) AS dbus,
  COUNT(DISTINCT u.usage_metadata.job_id) AS distinct_jobs,
  ROUND(SUM(CASE WHEN u.custom_tags IS NULL OR SIZE(u.custom_tags) = 0 THEN u.usage_quantity ELSE 0 END), 2) AS untagged_dbus
FROM system.billing.usage u
WHERE u.usage_date >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
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
