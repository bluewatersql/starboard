# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Migration prioritization pack."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

C_MG01_SQL = """\
WITH cluster_usage AS (
  SELECT
    workspace_id,
    usage_metadata.cluster_id AS cluster_id,
    ROUND(SUM(usage_quantity), 2) AS total_dbus,
    MAX(usage_end_time) AS last_used
  FROM
    system.billing.usage
  WHERE
    usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND sku_name IN ('ENTERPRISE_ALL_PURPOSE_COMPUTE', 'ENTERPRISE_JOBS_COMPUTE')
  GROUP BY
    workspace_id,
    usage_metadata.cluster_id
),
latest_clusters AS (
  SELECT
    *
  FROM
    system.compute.clusters
  QUALIFY
    ROW_NUMBER() OVER (PARTITION BY workspace_id, cluster_id ORDER BY change_time DESC) = 1
)
SELECT
  c.workspace_id,
  c.cluster_id,
  c.cluster_name,
  c.cluster_source,
  c.worker_node_type,
  cu.total_dbus AS non_photon_dbus,
  cu.last_used,
  CASE
    WHEN cu.total_dbus > 1000 THEN 'HIGH: >1000 DBUs on non-Photon'
    WHEN cu.total_dbus > 100 THEN 'MEDIUM: 100-1000 DBUs on non-Photon'
    ELSE 'LOW: <100 DBUs'
  END AS migration_priority
FROM
  cluster_usage cu LEFT JOIN latest_clusters c USING (workspace_id, cluster_id)
WHERE
  c.delete_time IS NULL
ORDER BY
  cu.total_dbus DESC
LIMIT {result_limit}
"""

C_MG02_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt
),
job_usage AS (
  SELECT
    workspace_id,
    usage_metadata.job_id                                          AS job_id,
    ROUND(SUM(CASE WHEN sku_name NOT LIKE '%SERVERLESS%'
                   THEN usage_quantity ELSE 0 END), 2)             AS classic_dbus,
    ROUND(SUM(CASE WHEN sku_name LIKE '%SERVERLESS%'
                   THEN usage_quantity ELSE 0 END), 2)             AS serverless_dbus,
    -- BOOL_OR is a single-pass boolean aggregation; avoids MAX(CASE...) integer trick
    BOOL_OR(sku_name LIKE '%SERVERLESS%')                          AS already_serverless
  FROM system.billing.usage, cutoff
  WHERE billing_origin_product = 'JOBS'
    AND usage_date >= cutoff.dt            -- partition pruning (G2)
    AND usage_start_time >= cutoff.dt
  GROUP BY workspace_id, usage_metadata.job_id
),
latest_jobs AS (
  SELECT *
  FROM system.lakeflow.jobs
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id
                              ORDER BY change_time DESC) = 1
),
user_usage AS (
  SELECT
    workspace_id,
    identity_metadata.run_as                                       AS run_as,
    ROUND(SUM(CASE WHEN billing_origin_product = 'ALL_PURPOSE'
                    AND sku_name NOT LIKE '%SERVERLESS%'
                   THEN usage_quantity ELSE 0 END), 2)             AS classic_all_purpose_dbus
  FROM system.billing.usage, cutoff
  WHERE usage_date >= cutoff.dt            -- partition pruning (G2)
    AND usage_start_time >= cutoff.dt
    AND identity_metadata.run_as LIKE '%@%'
  GROUP BY workspace_id, identity_metadata.run_as
)
SELECT
  'JOB'                                                            AS scope,
  j.name                                                           AS entity_name,
  ju.workspace_id,
  ju.classic_dbus                                                  AS classic_compute_dbus,
  ju.serverless_dbus,
  CASE
    WHEN ju.already_serverless                    THEN 'Already Serverless'
    WHEN ju.classic_dbus < 3000.0                 THEN 'Serverless Candidate (low volume)'
    WHEN ju.classic_dbus < 30000.0                THEN 'Serverless Candidate (medium volume)'
    ELSE                                               'Evaluate (high volume)'
  END                                                              AS recommendation,
  ROUND(ju.classic_dbus * 0.4, 0)                                 AS est_serverless_savings_dbus
FROM job_usage ju
LEFT JOIN latest_jobs j USING (workspace_id, job_id)
WHERE ju.classic_dbus > 0

UNION ALL

SELECT
  'USER'                                                           AS scope,
  uu.run_as                                                        AS entity_name,
  uu.workspace_id,
  uu.classic_all_purpose_dbus                                      AS classic_compute_dbus,
  0                                                                AS serverless_dbus,
  CASE
    WHEN uu.classic_all_purpose_dbus > 500 THEN 'Serverless SQL Candidate'
    ELSE                                        'Low Priority'
  END                                                              AS recommendation,
  ROUND(uu.classic_all_purpose_dbus * 0.5, 0)                     AS est_serverless_savings_dbus
FROM user_usage uu
WHERE uu.classic_all_purpose_dbus > 0
ORDER BY est_serverless_savings_dbus DESC
LIMIT {result_limit}
"""

MIGRATION_PACK = QueryPack(
    pack_id="migration",
    domain="migration",
    name="Migration Prioritization",
    description="Photon and serverless migration candidates ranked by DBU savings potential",
    queries=(
        SystemQuery(
            query_id="C-MG01",
            name="Photon Migration Priority List",
            description="Non-Photon clusters ranked by DBU consumption for migration prioritization",
            sql_template=C_MG01_SQL,
            required_tables=("system.billing.usage", "system.compute.clusters"),
            domain="migration",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Photon migration priority list",
                output_hint="",
            ),
        ),
        SystemQuery(
            query_id="C-MG02",
            name="Serverless Migration Candidates",
            description="Jobs and users ranked by classic-to-serverless DBU savings potential",
            sql_template=C_MG02_SQL,
            required_tables=("system.billing.usage", "system.lakeflow.jobs"),
            domain="migration",

            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.OPTIMIZATION,
            metadata=QueryMetadata(
                summary="Serverless migration candidates",
                output_hint="",
            ),
        ),
    ),
    gating_products=frozenset(),
)
