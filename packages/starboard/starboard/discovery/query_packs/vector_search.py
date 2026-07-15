# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Vector Search expanded discovery query pack.\n\nCovers endpoint billing, usage patterns, idle detection, and indexing costs.\nReplaces the single-query VECTOR_SEARCH_PACK from product_surfaces.py."""

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
        query_id="P-VS01", name="Endpoint Billing History",
        description="All Vector Search endpoints with first/last billed dates",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT usage_metadata.endpoint_name AS endpoint_name, MIN(usage_date) AS first_billed_date,
  MAX(usage_date) AS last_billed_date, COUNT(*) AS num_usage_records, ROUND(SUM(usage_quantity), 2) AS total_dbus
FROM system.billing.usage, cutoff
WHERE billing_origin_product = 'VECTOR_SEARCH' AND usage_metadata.endpoint_name IS NOT NULL AND usage_date >= cutoff.dt
GROUP BY usage_metadata.endpoint_name
ORDER BY last_billed_date DESC
LIMIT {result_limit}""",
        required_tables=("system.billing.usage",), domain="vector_search", required=True,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="All Vector Search endpoints with first/last billed dates", output_hint="Endpoints ranked by last billed date"),
    ),
    SystemQuery(
        query_id="P-VS02", name="Usage by Workload Type and Month",
        description=(
            "Daily and monthly usage broken down by serving, ingest, and storage. "
            "Consolidates former P-VS06 (monthly cost trend) into one query."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT workspace_id, usage_date,
  DATE_TRUNC('MONTH', usage_date) AS year_month,
  usage_metadata.endpoint_name AS endpoint_name,
  CASE WHEN usage_metadata.endpoint_name IS NULL THEN 'ingest' WHEN usage_type = 'STORAGE_SPACE' THEN 'storage' ELSE 'serving' END AS workload_type,
  ROUND(SUM(usage_quantity), 4) AS total_quantity,
  usage_unit
FROM system.billing.usage, cutoff
WHERE (billing_origin_product = 'VECTOR_SEARCH' OR sku_name LIKE '%VECTOR_SEARCH%') AND usage_date >= cutoff.dt
GROUP BY workspace_id, usage_date, DATE_TRUNC('MONTH', usage_date), usage_metadata.endpoint_name,
  CASE WHEN usage_metadata.endpoint_name IS NULL THEN 'ingest' WHEN usage_type = 'STORAGE_SPACE' THEN 'storage' ELSE 'serving' END, usage_unit
ORDER BY usage_date DESC, endpoint_name, workload_type
LIMIT {result_limit}""",
        required_tables=("system.billing.usage",), domain="vector_search", required=True,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Daily and monthly usage by workload type per endpoint", output_hint="Daily usage with monthly rollup columns"),
    ),
    SystemQuery(
        query_id="P-VS03", name="Idle Endpoints (No Queries)",
        description="Endpoints with billing but no query activity",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
endpoint_billing AS (
  SELECT usage_metadata.endpoint_name AS endpoint_name,
    ROUND(SUM(IF(usage_type = 'STORAGE_SPACE', usage_quantity, 0)), 4) AS storage_quantity,
    ROUND(SUM(IF(usage_type != 'STORAGE_SPACE', usage_quantity, 0)), 4) AS serving_quantity
  FROM system.billing.usage, cutoff
  WHERE billing_origin_product = 'VECTOR_SEARCH' AND usage_date >= cutoff.dt AND usage_metadata.endpoint_name IS NOT NULL
  GROUP BY usage_metadata.endpoint_name HAVING storage_quantity > 0 OR serving_quantity > 0
)
SELECT eb.endpoint_name, eb.storage_quantity, eb.serving_quantity
FROM endpoint_billing eb
WHERE NOT EXISTS (
  SELECT 1 FROM system.access.audit a
  WHERE a.service_name = 'vectorSearch'
    AND a.action_name IN ('queryVectorIndex', 'queryVectorIndexRouteOptimized')
    AND a.event_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND a.event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP())
    AND a.request_params['endpoint_name'] = eb.endpoint_name
)
ORDER BY eb.serving_quantity DESC, eb.storage_quantity DESC
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.access.audit",), domain="vector_search", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(summary="Endpoints with billing but no query activity (requires audit)", output_hint="Idle endpoints ranked by cost"),
    ),
    SystemQuery(
        query_id="P-VS04", name="Endpoint Daily DBUs and DSUs",
        description="Daily DBU and DSU breakdown per endpoint",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT workspace_id, usage_date, usage_metadata.endpoint_name AS endpoint_name,
  CASE WHEN usage_metadata.endpoint_name IS NULL THEN 'ingest' WHEN usage_type = 'STORAGE_SPACE' THEN 'storage' ELSE 'serving' END AS workload_type,
  ROUND(IF(usage_type != 'STORAGE_SPACE', SUM(usage_quantity), NULL), 4) AS dbus,
  ROUND(IF(usage_type = 'STORAGE_SPACE', SUM(usage_quantity), NULL), 4) AS dsus
FROM system.billing.usage, cutoff
WHERE billing_origin_product = 'VECTOR_SEARCH' AND usage_date >= cutoff.dt
GROUP BY workspace_id, usage_date, usage_metadata.endpoint_name,
  CASE WHEN usage_metadata.endpoint_name IS NULL THEN 'ingest' WHEN usage_type = 'STORAGE_SPACE' THEN 'storage' ELSE 'serving' END, usage_type
ORDER BY usage_date DESC, endpoint_name, workload_type
LIMIT {result_limit}""",
        required_tables=("system.billing.usage",), domain="vector_search", required=True,
        discovery_mode=DiscoveryMode.DEEP_DIVE, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Daily DBU and DSU breakdown per endpoint", output_hint="Daily DBU/DSU per endpoint"),
    ),
    SystemQuery(
        query_id="P-VS05", name="Indexing Cost by DLT Pipeline",
        description="Index sync cost attributed to DLT pipelines",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
pipeline_usage AS (
  SELECT usage_metadata.dlt_pipeline_id AS dlt_pipeline_id, usage_date, ROUND(SUM(usage_quantity), 4) AS total_quantity
  FROM system.billing.usage, cutoff
  WHERE billing_origin_product = 'VECTOR_SEARCH' AND usage_metadata.dlt_pipeline_id IS NOT NULL AND usage_date >= cutoff.dt
  GROUP BY usage_metadata.dlt_pipeline_id, usage_date
),
latest_pipelines AS (
  SELECT pipeline_id, name AS pipeline_name FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
)
SELECT lp.pipeline_name, pu.dlt_pipeline_id, MIN(pu.usage_date) AS first_usage_date,
  MAX(pu.usage_date) AS last_usage_date, ROUND(SUM(pu.total_quantity), 4) AS total_quantity
FROM pipeline_usage pu LEFT JOIN latest_pipelines lp ON pu.dlt_pipeline_id = lp.pipeline_id
GROUP BY lp.pipeline_name, pu.dlt_pipeline_id
ORDER BY total_quantity DESC
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.lakeflow.pipelines",), domain="vector_search", required=False,
        discovery_mode=DiscoveryMode.DEEP_DIVE, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Index sync cost attributed to DLT pipelines", output_hint="Pipelines ranked by indexing cost"),
    ),
]

VECTOR_SEARCH_PACK = QueryPack(
    pack_id="vector_search", domain="vector_search", name="Vector Search",
    description="Vector Search endpoint billing, usage, and optimization",
    queries=tuple(_QUERIES),
    gating_products=frozenset({"VECTOR_SEARCH"}),
)
