"""Machine learning and model serving pack."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery

C_ML01_SQL = """\
SELECT
  workspace_id,
  usage_metadata.endpoint_name AS endpoint_name,
  CASE
    WHEN usage_metadata.endpoint_name LIKE '%test%'
      OR usage_metadata.endpoint_name LIKE '%demo%' THEN 'Test/Demo (cleanup candidate)'
    WHEN usage_metadata.endpoint_name LIKE '%vector%'
      OR usage_metadata.endpoint_name LIKE '%vs-%' THEN 'Vector Search'
    WHEN usage_metadata.endpoint_name LIKE '%llama%'
      OR usage_metadata.endpoint_name LIKE '%databricks-%' THEN 'Foundation Model / FMAPI'
    ELSE 'Custom Model'
  END AS endpoint_type,
  CASE
    WHEN sku_name LIKE '%REAL_TIME_INFERENCE%' THEN 'Real-Time Inference'
    WHEN sku_name LIKE '%VECTOR_SEARCH%' THEN 'Vector Search'
    WHEN sku_name LIKE '%FOUNDATION_MODEL%' THEN 'Foundation Model API'
    ELSE sku_name
  END AS serving_tier,
  ROUND(SUM(usage_quantity), 2) AS total_dbus,
  MIN(usage_start_time) AS first_seen,
  MAX(usage_end_time) AS last_seen
FROM system.billing.usage
WHERE usage_start_time >= CURRENT_DATE() - INTERVAL {lookback_days} DAYS
  AND billing_origin_product IN ('MODEL_SERVING', 'VECTOR_SEARCH', 'INFERENCE_TABLES')
  AND usage_metadata.endpoint_name IS NOT NULL
GROUP BY ALL
ORDER BY total_dbus DESC
"""

ML_PACK = QueryPack(
    pack_id="ml",
    domain="ml",
    name="ML & Model Serving",
    description="Model serving DBU consumption, endpoint classification, cleanup candidates",
    queries=(
        SystemQuery(
            query_id="C-ML01",
            name="Model Serving DBU Consumption and Endpoint Classification",
            description="DBU consumption by endpoint, type, and serving tier",
            sql_template=C_ML01_SQL,
            required_tables=("system.billing.usage",),
            domain="ml",
        ),
    ),
    gating_products=frozenset({"MODEL_SERVING", "FEATURE_ENGINEERING"}),
)
