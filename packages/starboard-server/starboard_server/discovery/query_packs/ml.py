
"""Machine learning and model serving pack."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

C_ML01_SQL = """\
WITH endpoint_classified AS (
  -- Classify endpoint_name and sku_name once per row rather than re-evaluating
  -- the same LIKE expressions in SELECT after GROUP BY.
  SELECT
    workspace_id,
    usage_metadata.endpoint_name                                     AS endpoint_name,
    usage_quantity,
    usage_start_time,
    usage_end_time,
    CASE
      WHEN usage_metadata.endpoint_name LIKE '%test%'
        OR usage_metadata.endpoint_name LIKE '%demo%'   THEN 'Test/Demo (cleanup candidate)'
      WHEN usage_metadata.endpoint_name LIKE '%vector%'
        OR usage_metadata.endpoint_name LIKE '%vs-%'    THEN 'Vector Search'
      WHEN usage_metadata.endpoint_name LIKE '%llama%'
        OR usage_metadata.endpoint_name LIKE '%databricks-%' THEN 'Foundation Model / FMAPI'
      ELSE                                                   'Custom Model'
    END                                                              AS endpoint_type,
    CASE
      WHEN sku_name LIKE '%REAL_TIME_INFERENCE%' THEN 'Real-Time Inference'
      WHEN sku_name LIKE '%VECTOR_SEARCH%'       THEN 'Vector Search'
      WHEN sku_name LIKE '%FOUNDATION_MODEL%'    THEN 'Foundation Model API'
      ELSE                                            sku_name
    END                                                              AS serving_tier
  FROM system.billing.usage
  WHERE usage_start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND billing_origin_product IN ('MODEL_SERVING', 'VECTOR_SEARCH', 'INFERENCE_TABLES')
    AND usage_metadata.endpoint_name IS NOT NULL
)
SELECT
  workspace_id,
  endpoint_name,
  endpoint_type,
  serving_tier,
  ROUND(SUM(usage_quantity), 2)  AS total_dbus,
  MIN(usage_start_time)          AS first_seen,
  MAX(usage_end_time)            AS last_seen
FROM endpoint_classified
GROUP BY ALL
ORDER BY total_dbus DESC
LIMIT 50
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

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Model serving DBU consumption by endpoint",
                output_hint="",
            ),
        ),
    ),
    gating_products=frozenset({"MODEL_SERVING", "FEATURE_ENGINEERING"}),
)
