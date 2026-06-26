# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""DLT Pipelines discovery query pack.

Covers pipeline health, failure rates, serverless candidates,
cost attribution, and lifecycle management."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

_QUERIES: list[SystemQuery] = []

# Read SQL from spec - but we'll define inline for reliability
_QUERIES = [
    SystemQuery(
        query_id="P-DLT01",
        name="Stale Pipelines (No Recent Updates)",
        description="Pipelines with no updates in lookback period — cleanup candidates",
        sql_template="""\
WITH latest_pipelines AS (
  SELECT workspace_id, pipeline_id, name AS pipeline_name, created_by, delete_time
  FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
),
last_updates AS (
  SELECT workspace_id, pipeline_id, MAX(period_start_time) AS last_update_start
  FROM system.lakeflow.pipeline_update_timeline
  GROUP BY workspace_id, pipeline_id
)
SELECT p.workspace_id, p.pipeline_id, p.pipeline_name, p.created_by,
  u.last_update_start, DATEDIFF(DAY, u.last_update_start, CURRENT_TIMESTAMP()) AS days_since_last_update
FROM latest_pipelines p
LEFT JOIN last_updates u USING (workspace_id, pipeline_id)
WHERE p.delete_time IS NULL
  AND (u.last_update_start IS NULL OR u.last_update_start < DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()))
ORDER BY u.last_update_start NULLS FIRST
LIMIT {result_limit}""",
        required_tables=(
            "system.lakeflow.pipelines",
            "system.lakeflow.pipeline_update_timeline",
        ),
        domain="dlt_pipelines",
        required=True,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(
            summary="Pipelines with no updates in 30+ days — cleanup candidates",
            output_hint="Top pipelines ranked by staleness",
        ),
    ),
    SystemQuery(
        query_id="P-DLT02",
        name="Pipeline Node Utilization",
        description="CPU/memory utilization of pipeline compute nodes",
        sql_template="""\
WITH pipeline_clusters AS (
  SELECT workspace_id, cluster_id
  FROM system.compute.clusters
  WHERE cluster_source IN ('PIPELINE', 'PIPELINE_MAINTENANCE')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, cluster_id ORDER BY change_time DESC) = 1
)
SELECT n.workspace_id, n.cluster_id, n.driver,
  ROUND(AVG(n.cpu_user_percent + n.cpu_system_percent), 1) AS avg_cpu_pct,
  ROUND(MAX(n.cpu_user_percent + n.cpu_system_percent), 1) AS peak_cpu_pct,
  ROUND(AVG(n.mem_used_percent), 1) AS avg_mem_pct,
  ROUND(MAX(n.mem_used_percent), 1) AS peak_mem_pct
FROM system.compute.node_timeline n
INNER JOIN pipeline_clusters pc ON n.workspace_id = pc.workspace_id AND n.cluster_id = pc.cluster_id
WHERE n.start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
GROUP BY n.workspace_id, n.cluster_id, n.driver
ORDER BY avg_cpu_pct DESC
LIMIT {result_limit}""",
        required_tables=("system.compute.node_timeline", "system.compute.clusters"),
        domain="dlt_pipelines",
        required=False,
        discovery_mode=DiscoveryMode.DEEP_DIVE,
        category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(
            summary="CPU/memory utilization of pipeline compute nodes",
            output_hint="Nodes ranked by CPU utilization",
        ),
    ),
    SystemQuery(
        query_id="P-DLT03",
        name="Pipeline Health Scorecard",
        description=(
            "Per-pipeline failure rate, duration percentiles, and consecutive "
            "failure count in a single pass over pipeline_update_timeline. "
            "Consolidates former P-DLT09 (p90/p95 duration) and P-DLT10 "
            "(frequent failures) into one query."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt),
updates AS (
  SELECT workspace_id, pipeline_id, update_id, MAX(result_state) AS result_state,
    MIN(period_start_time) AS start_time, MAX(period_end_time) AS end_time
  FROM system.lakeflow.pipeline_update_timeline, cutoff
  WHERE period_start_time >= cutoff.dt
  GROUP BY workspace_id, pipeline_id, update_id
),
latest_pipelines AS (
  SELECT workspace_id, pipeline_id, name AS pipeline_name
  FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
)
SELECT lp.pipeline_name, u.workspace_id, u.pipeline_id,
  COUNT(*) AS total_updates,
  COUNT_IF(u.result_state = 'COMPLETED') AS completed,
  COUNT_IF(u.result_state IS NULL OR u.result_state != 'COMPLETED') AS failed_or_incomplete,
  ROUND(COUNT_IF(u.result_state IS NULL OR u.result_state != 'COMPLETED') * 100.0 / COUNT(*), 2) AS failure_rate_pct,
  ROUND(AVG(TIMESTAMPDIFF(SECOND, u.start_time, u.end_time)), 1) AS avg_duration_sec,
  ROUND(PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY TIMESTAMPDIFF(SECOND, u.start_time, u.end_time)), 1) AS p90_duration_sec,
  ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY TIMESTAMPDIFF(SECOND, u.start_time, u.end_time)), 1) AS p95_duration_sec
FROM updates u LEFT JOIN latest_pipelines lp USING (workspace_id, pipeline_id)
GROUP BY lp.pipeline_name, u.workspace_id, u.pipeline_id
ORDER BY failure_rate_pct DESC, total_updates DESC
LIMIT {result_limit}""",
        required_tables=("system.lakeflow.pipeline_update_timeline",),
        domain="dlt_pipelines",
        required=True,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.PROFILE,
        metadata=QueryMetadata(
            summary="Per-pipeline failure rate, duration percentiles, and failure counts",
            output_hint="Pipelines ranked by failure rate with p90/p95 durations",
        ),
    ),
    SystemQuery(
        query_id="P-DLT04",
        name="Slowest Pipelines by Target Table",
        description="Pipelines ranked by p95 update duration per target table",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
pipeline_tables AS (
  SELECT entity_metadata.dlt_pipeline_info.dlt_pipeline_id AS pipeline_id,
    target_table_catalog, target_table_schema, target_table_name, COUNT(*) AS write_events
  FROM system.access.table_lineage, cutoff
  WHERE entity_type = 'PIPELINE' AND event_date >= cutoff.dt AND target_table_name IS NOT NULL
  GROUP BY 1, 2, 3, 4
),
pipeline_perf AS (
  SELECT pipeline_id, COUNT(*) AS total_updates,
    ROUND(AVG(duration_sec), 1) AS avg_duration_sec,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_sec), 1) AS p95_duration_sec
  FROM (
    SELECT pipeline_id, update_id, TIMESTAMPDIFF(SECOND, MIN(period_start_time), MAX(period_end_time)) AS duration_sec
    FROM system.lakeflow.pipeline_update_timeline, cutoff WHERE period_start_time >= cutoff.dt
    GROUP BY pipeline_id, update_id
  ) GROUP BY pipeline_id
),
latest_pipelines AS (
  SELECT workspace_id, pipeline_id, name AS pipeline_name
  FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
)
SELECT lp.pipeline_name, t.pipeline_id,
  CONCAT_WS('.', t.target_table_catalog, t.target_table_schema, t.target_table_name) AS target_table,
  t.write_events, p.total_updates, p.avg_duration_sec AS avg_update_sec, p.p95_duration_sec AS p95_update_sec
FROM pipeline_tables t JOIN pipeline_perf p USING (pipeline_id)
LEFT JOIN latest_pipelines lp USING (pipeline_id)
ORDER BY p.p95_duration_sec DESC
LIMIT {result_limit}""",
        required_tables=(
            "system.access.table_lineage",
            "system.lakeflow.pipeline_update_timeline",
        ),
        domain="dlt_pipelines",
        required=False,
        discovery_mode=DiscoveryMode.DEEP_DIVE,
        category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(
            summary="Pipelines ranked by p95 update duration per target table",
            output_hint="Slowest pipelines with target table context",
        ),
    ),
    SystemQuery(
        query_id="P-DLT05",
        name="Serverless Migration Candidates",
        description="Pipelines on classic compute that could migrate to serverless",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
pipeline_billing AS (
  SELECT workspace_id, usage_metadata.dlt_pipeline_id AS pipeline_id,
    product_features.is_serverless AS is_serverless_billing,
    ROUND(SUM(usage_quantity), 2) AS dbus, MIN(usage_date) AS first_usage, MAX(usage_date) AS last_usage
  FROM system.billing.usage, cutoff
  WHERE usage_metadata.dlt_pipeline_id IS NOT NULL AND usage_date >= cutoff.dt AND product_features.is_serverless = false
  GROUP BY workspace_id, usage_metadata.dlt_pipeline_id, product_features.is_serverless
),
latest_pipelines AS (
  SELECT workspace_id, pipeline_id, name AS pipeline_name, created_by, settings.edition AS edition,settings.serverless AS is_serverless_config, settings.photon AS photon_enabled
  FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
)
SELECT lp.pipeline_name, pb.workspace_id, pb.pipeline_id, lp.created_by, lp.edition,
  lp.is_serverless_config, pb.is_serverless_billing, lp.photon_enabled, pb.dbus, pb.first_usage, pb.last_usage
FROM pipeline_billing pb LEFT JOIN latest_pipelines lp USING (workspace_id, pipeline_id)
ORDER BY pb.dbus DESC
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.lakeflow.pipelines"),
        domain="dlt_pipelines",
        required=False,
        discovery_mode=DiscoveryMode.DEEP_DIVE,
        category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(
            summary="Pipelines on classic compute that could migrate to serverless",
            output_hint="Classic pipelines ranked by DBU consumption",
        ),
    ),
    SystemQuery(
        query_id="P-DLT06",
        name="Pipeline Billing Summary",
        description=(
            "Daily DBU consumption per pipeline plus per-update cost breakdown. "
            "Consolidates former P-DLT08 (daily DBU trend) into one query."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
latest_pipelines AS (
  SELECT workspace_id, pipeline_id, name AS pipeline_name
  FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
),
daily_cost AS (
  SELECT workspace_id, usage_metadata.dlt_pipeline_id AS pipeline_id, usage_date,
    ROUND(SUM(usage_quantity), 2) AS daily_dbus,
    COUNT(DISTINCT usage_metadata.dlt_update_id) AS updates_billed
  FROM system.billing.usage, cutoff
  WHERE usage_metadata.dlt_pipeline_id IS NOT NULL AND usage_date >= cutoff.dt
  GROUP BY workspace_id, usage_metadata.dlt_pipeline_id, usage_date
)
SELECT lp.pipeline_name, dc.workspace_id, dc.pipeline_id, dc.usage_date,
  dc.daily_dbus, dc.updates_billed,
  ROUND(dc.daily_dbus / NULLIF(dc.updates_billed, 0), 2) AS avg_dbus_per_update
FROM daily_cost dc
LEFT JOIN latest_pipelines lp USING (workspace_id, pipeline_id)
ORDER BY dc.pipeline_id, dc.usage_date
LIMIT {result_limit}""",
        required_tables=(
            "system.billing.usage",
            "system.lakeflow.pipelines",
        ),
        domain="dlt_pipelines",
        required=True,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.BILLING,
        metadata=QueryMetadata(
            summary="Daily DBU per pipeline with per-update cost averages",
            output_hint="Daily pipeline cost trend with update counts",
        ),
    ),
    SystemQuery(
        query_id="P-DLT07",
        name="Pipeline Cost with Metadata",
        description="Daily pipeline cost with edition, serverless, and Photon metadata",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt),
pipeline_billing AS (
  SELECT workspace_id, usage_metadata.dlt_pipeline_id AS pipeline_id, usage_date, billing_origin_product,
    product_features.dlt_tier AS dlt_tier, product_features.is_serverless AS is_serverless,
    product_features.is_photon AS is_photon, ROUND(SUM(usage_quantity), 2) AS dbus
  FROM system.billing.usage, cutoff
  WHERE usage_metadata.dlt_pipeline_id IS NOT NULL AND usage_date >= cutoff.dt
  GROUP BY workspace_id, usage_metadata.dlt_pipeline_id, usage_date, billing_origin_product,
    product_features.dlt_tier, product_features.is_serverless, product_features.is_photon
),
latest_pipelines AS (
  SELECT workspace_id, pipeline_id, name AS pipeline_name, edition,
    settings.continuous AS is_continuous, settings.photon AS photon_enabled
  FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
)
SELECT lp.pipeline_name, pb.workspace_id, pb.pipeline_id, lp.edition, lp.is_continuous, lp.photon_enabled,
  pb.billing_origin_product, pb.dlt_tier, pb.is_serverless, pb.is_photon, pb.usage_date, pb.dbus
FROM pipeline_billing pb LEFT JOIN latest_pipelines lp USING (workspace_id, pipeline_id)
ORDER BY pb.workspace_id, pb.pipeline_id, pb.usage_date
LIMIT {result_limit}""",
        required_tables=("system.billing.usage", "system.lakeflow.pipelines"),
        domain="dlt_pipelines",
        required=True,
        discovery_mode=DiscoveryMode.DEEP_DIVE,
        category=QueryCategory.BILLING,
        metadata=QueryMetadata(
            summary="Daily pipeline cost with edition, serverless, and Photon metadata",
            output_hint="Daily cost breakdown per pipeline",
        ),
    ),
    SystemQuery(
        query_id="P-DLT11",
        name="Continuous vs Triggered Pipeline Counts",
        description="Count of continuous vs triggered pipelines per workspace",
        sql_template="""\
WITH latest_pipelines AS (
  SELECT workspace_id, pipeline_id, name AS pipeline_name, settings.continuous AS is_continuous
  FROM system.lakeflow.pipelines
  WHERE delete_time IS NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
)
SELECT workspace_id, is_continuous, COUNT(*) AS pipeline_count
FROM latest_pipelines
GROUP BY workspace_id, is_continuous
ORDER BY workspace_id, is_continuous
LIMIT {result_limit}""",
        required_tables=("system.lakeflow.pipelines",),
        domain="dlt_pipelines",
        required=True,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.PROFILE,
        metadata=QueryMetadata(
            summary="Count of continuous vs triggered pipelines per workspace",
            output_hint="Pipeline type breakdown by workspace",
        ),
    ),
]


DLT_PIPELINES_PACK = QueryPack(
    pack_id="dlt_pipelines",
    domain="dlt_pipelines",
    name="DLT Pipelines",
    description="Delta Live Tables pipeline health, cost, and optimization",
    queries=tuple(_QUERIES),
    gating_products=frozenset({"DLT"}),
)
