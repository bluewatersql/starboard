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
        query_id="P-APP02", name="Start/Stop History",
        description="Start/stop events per app with actor identity",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT event_date, workspace_id, get_json_object(request_params.name, '$') AS app_name,
  action_name AS app_action, user_identity.email AS actor
FROM system.access.audit, cutoff
WHERE service_name = 'apps' AND action_name IN ('startApp', 'stopApp') AND event_date >= cutoff.dt
ORDER BY event_date DESC
LIMIT {result_limit}""",
        required_tables=("system.access.audit",), domain="apps", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Start/stop events per app with actor identity", output_hint="Recent app start/stop events"),
    ),
    SystemQuery(
        query_id="P-APP03", name="Frequently Restarted Apps",
        description="Apps with 5+ start or stop events in lookback period",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT get_json_object(request_params.name, '$') AS app_name, workspace_id,
  COUNT_IF(action_name = 'startApp') AS starts, COUNT_IF(action_name = 'stopApp') AS stops
FROM system.access.audit, cutoff
WHERE service_name = 'apps' AND action_name IN ('startApp', 'stopApp') AND event_date >= cutoff.dt
GROUP BY get_json_object(request_params.name, '$'), workspace_id
HAVING starts >= 5 OR stops >= 5
ORDER BY GREATEST(starts, stops) DESC
LIMIT {result_limit}""",
        required_tables=("system.access.audit",), domain="apps", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(summary="Apps with 5+ start or stop events in lookback period", output_hint="Frequently restarted apps"),
    ),
    SystemQuery(
        query_id="P-APP04", name="Daily App Cost (DBUs)",
        description="Daily DBU consumption per app",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT usage_date, usage_metadata.app_id AS app_id, usage_metadata.app_name AS app_name,
  ROUND(SUM(usage_quantity), 2) AS dbus
FROM system.billing.usage, cutoff
WHERE billing_origin_product = 'APPS' AND usage_unit = 'DBU' AND usage_date >= cutoff.dt
GROUP BY usage_date, usage_metadata.app_id, usage_metadata.app_name
ORDER BY usage_date DESC, dbus DESC
LIMIT {result_limit}""",
        required_tables=("system.billing.usage",), domain="apps", required=True,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Daily DBU consumption per app", output_hint="Daily app cost trend"),
    ),
    SystemQuery(
        query_id="P-APP05", name="Top 20 Most Expensive Apps",
        description="Top 20 apps by estimated list-price cost",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT usage_metadata.app_id AS app_id, usage_metadata.app_name AS app_name,
  ROUND(SUM(us.usage_quantity), 2) AS dbus,
  ROUND(SUM(us.usage_quantity * lp.pricing.effective_list.default), 2) AS est_list_dollars
FROM system.billing.usage us, cutoff
JOIN system.billing.list_prices lp ON lp.sku_name = us.sku_name
  AND us.usage_start_time BETWEEN lp.price_start_time AND COALESCE(lp.price_end_time, CURRENT_TIMESTAMP())
WHERE us.billing_origin_product = 'APPS' AND us.usage_unit = 'DBU' AND us.usage_date >= cutoff.dt
GROUP BY usage_metadata.app_id, usage_metadata.app_name
ORDER BY est_list_dollars DESC
LIMIT 20""",
        required_tables=("system.billing.usage", "system.billing.list_prices",), domain="apps", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Top 20 apps by estimated list-price cost", output_hint="Most expensive apps"),
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
