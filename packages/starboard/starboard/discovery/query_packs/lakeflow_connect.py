# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Lakeflow Connect discovery query pack.\n\nCovers ingestion pipeline usage, cost, and connector types."""

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
        query_id="P-LC01", name="Usage by Day, Workspace, and Connector Type",
        description=(
            "Daily DBU consumption by workspace and connector pipeline type. "
            "Consolidates former P-LC03 (usage by connector type) into one query."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
latest_pipelines AS (
  SELECT workspace_id, pipeline_id, pipeline_type
  FROM system.lakeflow.pipelines
  WHERE pipeline_type IN ('INGESTION_PIPELINE', 'INGESTION_GATEWAY', 'DATABASE_TABLE_SYNC')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
)
SELECT u.usage_date, u.workspace_id,
  COALESCE(lp.pipeline_type, 'UNKNOWN') AS connector_type,
  ROUND(SUM(u.usage_quantity), 2) AS dbus
FROM system.billing.usage u, cutoff
LEFT JOIN latest_pipelines lp ON u.workspace_id = lp.workspace_id AND u.usage_metadata.dlt_pipeline_id = lp.pipeline_id
WHERE u.billing_origin_product = 'LAKEFLOW_CONNECT' AND u.usage_date >= cutoff.dt
GROUP BY u.usage_date, u.workspace_id, COALESCE(lp.pipeline_type, 'UNKNOWN')
ORDER BY u.usage_date DESC, u.workspace_id
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.lakeflow.pipelines",), domain="lakeflow_connect", required=True,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Daily DBU by workspace and connector type", output_hint="Daily DBU trend with connector type breakdown"),
    ),
    SystemQuery(
        query_id="P-LC02", name="Usage by Pipeline",
        description="Per-pipeline DBU consumption with metadata",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
latest_pipelines AS (
  SELECT workspace_id, pipeline_id, name AS pipeline_name, created_by
  FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
)
SELECT lp.pipeline_name, u.usage_date, lp.created_by, ROUND(SUM(u.usage_quantity), 2) AS dbus
FROM system.billing.usage u, cutoff
LEFT JOIN latest_pipelines lp ON u.workspace_id = lp.workspace_id AND u.usage_metadata.dlt_pipeline_id = lp.pipeline_id
WHERE u.billing_origin_product = 'LAKEFLOW_CONNECT' AND u.usage_date >= cutoff.dt
GROUP BY lp.pipeline_name, u.usage_date, lp.created_by
ORDER BY usage_date DESC, pipeline_name
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.lakeflow.pipelines",), domain="lakeflow_connect", required=True,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Per-pipeline DBU consumption with pipeline metadata", output_hint="Pipelines ranked by DBU"),
    ),
]

LAKEFLOW_CONNECT_PACK = QueryPack(
    pack_id="lakeflow_connect", domain="lakeflow_connect", name="Lakeflow Connect",
    description="Lakeflow Connect ingestion pipeline usage and cost",
    queries=tuple(_QUERIES),
    gating_products=frozenset({"LAKEFLOW_CONNECT"}),
)
