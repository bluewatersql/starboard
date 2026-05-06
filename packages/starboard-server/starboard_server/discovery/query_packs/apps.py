"""Apps expanded discovery query pack.\n\nCovers app inventory, start/stop history, costs, and per-user efficiency.\nReplaces the 2-query APPS_PACK from product_surfaces.py."""

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
        query_id="P-APP01", name="App Inventory (Active Apps)",
        description="Active non-deleted apps from audit logs",
        sql_template="""\
SELECT app_name, workspace_id, last_action
FROM (
  SELECT get_json_object(request_params.app, '$.name') AS app_name, workspace_id,
    MAX_BY(action_name, event_time) AS last_action
  FROM system.access.audit
  WHERE service_name = 'apps' AND action_name IN ('createApp', 'installTemplateApp', 'deleteApp')
  GROUP BY get_json_object(request_params.app, '$.name'), workspace_id
)
WHERE last_action != 'deleteApp'
ORDER BY app_name, workspace_id
LIMIT {result_limit}""",
        required_tables=("system.access.audit",), domain="apps", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Active non-deleted apps from audit logs", output_hint="Active apps inventory"),
    ),
    SystemQuery(
        query_id="P-APP02", name="App Start/Stop Activity",
        description=(
            "Per-app start/stop event counts with high-churn flag. "
            "Consolidates former P-APP03 (frequently restarted apps) "
            "into one query."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT get_json_object(request_params.name, '$') AS app_name, workspace_id,
  COUNT_IF(action_name = 'startApp') AS starts,
  COUNT_IF(action_name = 'stopApp') AS stops,
  IF(COUNT_IF(action_name = 'startApp') >= 5 OR COUNT_IF(action_name = 'stopApp') >= 5, true, false) AS high_churn,
  MAX(event_date) AS last_event_date,
  MAX_BY(user_identity.email, event_time) AS last_actor
FROM system.access.audit, cutoff
WHERE service_name = 'apps' AND action_name IN ('startApp', 'stopApp') AND event_date >= cutoff.dt
GROUP BY get_json_object(request_params.name, '$'), workspace_id
ORDER BY GREATEST(starts, stops) DESC
LIMIT {result_limit}""",
        required_tables=("system.access.audit",), domain="apps", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Per-app start/stop counts with high-churn flag", output_hint="Apps ranked by activity with churn detection"),
    ),
    SystemQuery(
        query_id="P-APP04", name="App Cost Summary",
        description=(
            "Per-app DBU consumption with estimated list-price dollars. "
            "Consolidates former P-APP05 (top expensive apps) into one query."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT us.usage_metadata.app_id AS app_id, us.usage_metadata.app_name AS app_name,
  ROUND(SUM(us.usage_quantity), 2) AS dbus,
  ROUND(SUM(us.usage_quantity * lp.pricing.effective_list.default), 2) AS est_list_dollars,
  MIN(us.usage_date) AS first_usage, MAX(us.usage_date) AS last_usage,
  COUNT(DISTINCT us.usage_date) AS active_days
FROM system.billing.usage us, cutoff
LEFT JOIN system.billing.list_prices lp ON lp.sku_name = us.sku_name
  AND us.usage_start_time BETWEEN lp.price_start_time AND COALESCE(lp.price_end_time, CURRENT_TIMESTAMP())
WHERE us.billing_origin_product = 'APPS' AND us.usage_unit = 'DBU' AND us.usage_date >= cutoff.dt
GROUP BY us.usage_metadata.app_id, us.usage_metadata.app_name
ORDER BY dbus DESC
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.billing.list_prices",), domain="apps", required=True,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Per-app DBU and estimated dollar cost summary", output_hint="Apps ranked by cost with dollar estimates"),
    ),
    SystemQuery(
        query_id="P-APP06", name="Cost per Active User",
        description="Cost per distinct active user per app",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
app_cost AS (
  SELECT usage_metadata.app_name AS app_name, workspace_id,
    ROUND(SUM(us.usage_quantity * lp.pricing.effective_list.default), 2) AS est_dollars
  FROM system.billing.usage us, cutoff
  JOIN system.billing.list_prices lp ON lp.sku_name = us.sku_name
    AND us.usage_start_time BETWEEN lp.price_start_time AND COALESCE(lp.price_end_time, CURRENT_TIMESTAMP())
  WHERE us.billing_origin_product = 'APPS' AND us.usage_unit = 'DBU' AND us.usage_date >= cutoff.dt
  GROUP BY usage_metadata.app_name, workspace_id HAVING est_dollars > 0
),
app_users AS (
  SELECT get_json_object(request_params.app, '$.name') AS app_name, workspace_id,
    COUNT(DISTINCT user_identity.email) AS active_users
  FROM system.access.audit, cutoff
  WHERE service_name = 'apps' AND action_name IN ('createApp', 'deployApp', 'startApp', 'stopApp', 'updateApp')
    AND event_date >= cutoff.dt
  GROUP BY get_json_object(request_params.app, '$.name'), workspace_id
)
SELECT ac.workspace_id, ac.app_name, ac.est_dollars, COALESCE(au.active_users, 0) AS active_users,
  IF(au.active_users > 0, ROUND(ac.est_dollars / au.active_users, 2), NULL) AS dollars_per_user
FROM app_cost ac LEFT JOIN app_users au ON ac.workspace_id = au.workspace_id AND ac.app_name = au.app_name
ORDER BY dollars_per_user DESC NULLS LAST
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.billing.list_prices", "system.access.audit",), domain="apps", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(summary="Cost per distinct active user per app", output_hint="Apps ranked by cost per user"),
    ),
]

APPS_PACK = QueryPack(
    pack_id="apps", domain="apps", name="Databricks Apps",
    description="App inventory, cost analysis, and usage efficiency",
    queries=tuple(_QUERIES),
    gating_products=frozenset({"APPS"}),
)
