# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Lakehouse Real-Time discovery query pack — first-class strategic SKU.

Routes the ``LAKEHOUSE_REAL_TIME`` SKU to its own domain so real-time spend is
surfaced on its own rather than silently analyzed as zero.

Real-time has no dedicated system table on the public path today, so this pack
is billing-grounded and extensible as real-time system tables land. The DBU
spend trend (RT-01) reads ``system.billing.usage`` (always present, mirrored on
the internal source) and is ``required=True``. The driving-workloads attribution
(RT-02) reads the ``usage_metadata`` entity keys on the same billing table but is
``required=False`` because that attribution signal is sparse — it degrades
honestly (reported skipped, not dropped). DBU-only — any ``$`` is a list-price
estimate at the tool layer.
"""

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
        query_id="RT-01",
        name="Real-Time DBU Spend Trend",
        description=(
            "Daily LAKEHOUSE_REAL_TIME DBU by workspace from system.billing.usage. "
            "Billing is account-scoped so workspace_id is in the grain. DBU-only. "
            "Resolves on the internal mirror (billing.usage is carried)."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT
  u.usage_date,
  u.workspace_id,
  ROUND(SUM(u.usage_quantity), 2) AS total_dbus,
  COUNT(*) AS usage_records
FROM system.billing.usage u, cutoff
WHERE u.billing_origin_product = 'LAKEHOUSE_REAL_TIME'
  AND u.usage_unit = 'DBU'
  AND u.usage_date >= cutoff.dt
GROUP BY u.usage_date, u.workspace_id
ORDER BY u.usage_date DESC, total_dbus DESC NULLS LAST
LIMIT {result_limit}""",
        required_tables=("system.billing.usage",),
        required_columns=(
            "usage_date",
            "workspace_id",
            "billing_origin_product",
            "usage_unit",
            "usage_quantity",
        ),
        domain="realtime",
        required=True,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.BILLING,
        metadata=QueryMetadata(
            summary="Daily LAKEHOUSE_REAL_TIME DBU spend by workspace",
            output_hint="Daily real-time DBU trend",
            tags=("realtime", "billing", "dbu"),
        ),
    ),
    SystemQuery(
        query_id="RT-02",
        name="Real-Time Driving Workloads",
        description=(
            "LAKEHOUSE_REAL_TIME DBU attributed to the driving job / pipeline "
            "entity via usage_metadata (job_id, dlt_pipeline_id). required=False: "
            "the entity signal is sparse on real-time rows, so this degrades "
            "honestly rather than dropping. DBU-only."
        ),
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt)
SELECT
  u.workspace_id,
  u.usage_metadata.job_id AS job_id,
  u.usage_metadata.dlt_pipeline_id AS dlt_pipeline_id,
  COALESCE(
    u.usage_metadata.job_id,
    u.usage_metadata.dlt_pipeline_id,
    '(no entity — unattributed)'
  ) AS entity,
  ROUND(SUM(u.usage_quantity), 2) AS total_dbus,
  COUNT(*) AS usage_records
FROM system.billing.usage u, cutoff
WHERE u.billing_origin_product = 'LAKEHOUSE_REAL_TIME'
  AND u.usage_unit = 'DBU'
  AND u.usage_date >= cutoff.dt
GROUP BY u.workspace_id, u.usage_metadata.job_id, u.usage_metadata.dlt_pipeline_id
ORDER BY total_dbus DESC NULLS LAST
LIMIT {result_limit}""",
        required_tables=("system.billing.usage",),
        required_columns=(
            "usage_date",
            "workspace_id",
            "usage_metadata",
            "billing_origin_product",
            "usage_unit",
            "usage_quantity",
        ),
        domain="realtime",
        required=False,
        discovery_mode=DiscoveryMode.GENERAL,
        category=QueryCategory.BILLING,
        metadata=QueryMetadata(
            summary="Real-time DBU attributed to driving job / pipeline entity",
            output_hint=(
                "Entities ranked by DBU; '(no entity — unattributed)' rows carry "
                "no usage_metadata entity signal"
            ),
            tags=("realtime", "attribution", "billing", "dbu"),
        ),
    ),
]

REALTIME_PACK = QueryPack(
    pack_id="realtime",
    domain="realtime",
    name="Lakehouse Real-Time",
    description=(
        "Lakehouse Real-Time spend and driving workloads: DBU spend trend "
        "(RT-01) and driving job/pipeline attribution (RT-02). Billing-grounded "
        "while real-time system tables are not yet available; the attribution "
        "signal degrades via required=False. Public system.billing.usage only; "
        "DBU-only; workspace-scoped."
    ),
    queries=tuple(_QUERIES),
    gating_products=frozenset({"LAKEHOUSE_REAL_TIME"}),
)
