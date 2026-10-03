# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Serverless attribution query pack (SVA-01…03).

Serverless AI infrastructure — Vector Search, Model Serving, Lakebase — is often the
largest share of an estate's DBU, but its billing rows carry **no ``run_as``**, so the
standard cost packs report it as "Unattributed". This pack makes serverless spend
*attributable where the data allows* and *honest where it does not*:

- SVA-01 breaks serverless spend down by workspace × product × endpoint/entity. For
  Vector Search and Model Serving, ``usage_metadata.endpoint_name`` is the entity key;
  for Lakebase/DATABASE, ``usage_metadata.database_instance_id`` is tried first, then
  ``endpoint_name`` — both are surfaced so a null ``database_instance_id`` is not the
  end of attribution. Column ``total_units`` carries usage_unit in its grain (DBU or
  DSU per row) — never folded into a misleading ``total_dbus``.
- SVA-02 measures attribution **coverage** — how much serverless spend carries an owner
  signal (``custom_tags`` / an endpoint name or instance id) versus none — an honest
  "how actionable is this yet" number.
- SVA-03 breaks serverless DBU down by ``product_features.performance_target``
  (PERFORMANCE_OPTIMIZED vs STANDARD) x product — the serverless performance-mode mix.
  STANDARD is the cheaper mode for latency-tolerant Jobs / Pipelines, so a fleet that is
  ~100% PERFORMANCE_OPTIMIZED has a large, low-risk lever. Unlike SVA-01/02 it scopes to
  ``product_features.is_serverless = TRUE`` (the flag IS populated on Jobs / DLT rows).
  SVA-03 runs on the **same fixed window as the facts block** (``F-07``): the trailing 30
  FULL days, excluding today (``usage_date >= CURRENT_DATE() - 30 AND usage_date <
  CURRENT_DATE()``), DBU only — independent of ``--lookback-days`` — so its serverless
  JOBS / DLT DBU per ``performance_target`` reconciles exactly with
  ``data.facts.performance_mode`` (an earlier lookback-plus-today window drifted ~2%).

All queries use public ``system.billing.usage`` only, are DBU-only (list-price ``$`` is a
tool-layer concern), and carry ``workspace_id`` in their grain: ``system.billing.usage``
is account-scoped, so without ``workspace_id`` the totals silently conflate workspaces.

Serverless gate: the pack scopes to serverless AI infra purely by
``billing_origin_product IN ('VECTOR_SEARCH', 'MODEL_SERVING', 'LAKEBASE', 'DATABASE')``.
It deliberately does NOT filter on ``product_features.is_serverless`` — that flag is left
NULL on the very rows this pack exists to attribute (verified live: VECTOR_SEARCH 1.66M,
MODEL_SERVING 1.52M, LAKEBASE 829K DBU/30d all carry ``is_serverless = NULL``), so an
``is_serverless IS TRUE`` predicate would silently drop ~all of the spend.

Column facts verified against Databricks system-table docs (system.billing.usage):
``usage_metadata.endpoint_name``, ``custom_tags`` (MAP), ``billing_origin_product``,
``product_features.is_serverless``, ``product_features.performance_target``
(PERFORMANCE_OPTIMIZED / STANDARD; NULL = not applicable to the product).
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

# Serverless AI products this pack attributes (billing_origin_product values), inlined
# into each query's IN (...) list. Keep in sync with gating_products below.

# ---------------------------------------------------------------------------
# SVA-01 — Serverless spend by workspace × product × endpoint/entity
# ---------------------------------------------------------------------------
# Grain: (workspace_id, billing_origin_product, usage_unit, endpoint_name,
#         database_instance_id) — both entity keys in grain so per-entity rows
#         are distinct and null instance_id rows (Lakebase on some workspaces)
#         appear separately from rows with a populated instance.
SVA_01_SQL = """\
-- Serverless spend attribution: which workspace / product / endpoint or instance
-- carries the spend. Serverless rows have no run_as; the entity signal differs by
-- product:
--   VS / Model Serving : usage_metadata.endpoint_name
--   Lakebase / DATABASE: usage_metadata.database_instance_id (primary);
--                        usage_metadata.endpoint_name as fallback when instance_id
--                        is null — so null database_instance_id is not the end of
--                        attribution.
-- usage_unit is in the grain (D7): Lakebase bills in both DBU and DSU; summing across
-- units under a single "DBU" label is incorrect. Column is total_units (not a DBU-only
-- name) to reflect that it may contain DSU rows when billing_origin_product = LAKEBASE.
SELECT
  workspace_id,
  billing_origin_product,
  usage_unit,
  usage_metadata.endpoint_name                                 AS endpoint_name,
  usage_metadata.database_instance_id                         AS database_instance_id,
  COALESCE(
    usage_metadata.endpoint_name,
    usage_metadata.database_instance_id,
    '(no endpoint — unattributed)'
  )                                                            AS entity,
  ROUND(SUM(usage_quantity), 2)                                AS total_units,
  COUNT(*)                                                     AS usage_records
FROM system.billing.usage
WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND billing_origin_product IN ('VECTOR_SEARCH', 'MODEL_SERVING', 'LAKEBASE', 'DATABASE')
GROUP BY workspace_id, billing_origin_product, usage_unit, usage_metadata.endpoint_name,
  usage_metadata.database_instance_id
ORDER BY total_units DESC NULLS LAST
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# SVA-02 — Serverless attribution coverage (tagged vs unattributed)
# ---------------------------------------------------------------------------
# Grain: (workspace_id, billing_origin_product)
# The honest "how much of this can we act on yet" signal.
SVA_02_SQL = """\
-- Attribution coverage for serverless spend, per workspace × product × unit.
-- Serverless has no run_as; custom_tags (owner/cost-center) is the tagging lever.
-- Entity attribution: endpoint_name (VS / Model Serving) OR database_instance_id
-- (Lakebase) — either one counts as "entity-attributed". High total_units with low
-- tagged_pct = enforce tagging/ownership before any remediation.
-- usage_unit is in the grain (D7): Lakebase bills in both DBU and DSU; column names
-- use _units (not _dbus) to reflect that rows may contain DSU.
SELECT
  workspace_id,
  billing_origin_product,
  usage_unit,
  ROUND(SUM(usage_quantity), 2)                                AS total_units,
  ROUND(SUM(CASE WHEN custom_tags IS NOT NULL AND SIZE(custom_tags) > 0
                 THEN usage_quantity ELSE 0 END), 2)           AS tagged_units,
  ROUND(
    SUM(CASE WHEN custom_tags IS NOT NULL AND SIZE(custom_tags) > 0
             THEN usage_quantity ELSE 0 END) * 100.0
      / NULLIF(SUM(usage_quantity), 0),
    1
  )                                                            AS tagged_pct,
  -- endpoint_name (VS/MS) or database_instance_id (Lakebase): either is an entity
  -- signal; null on both = fully unattributed.
  ROUND(SUM(CASE WHEN usage_metadata.endpoint_name IS NOT NULL
                   OR usage_metadata.database_instance_id IS NOT NULL
                 THEN usage_quantity ELSE 0 END), 2)           AS endpoint_attributed_units
FROM system.billing.usage
WHERE usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND billing_origin_product IN ('VECTOR_SEARCH', 'MODEL_SERVING', 'LAKEBASE', 'DATABASE')
GROUP BY workspace_id, billing_origin_product, usage_unit
ORDER BY total_units DESC NULLS LAST
LIMIT {result_limit}
"""

# ---------------------------------------------------------------------------
# SVA-03 — Serverless performance-mode mix (PERFORMANCE_OPTIMIZED vs STANDARD)
# ---------------------------------------------------------------------------
# Grain: (workspace_id, billing_origin_product, performance_target)
# performance_target is only set on serverless Jobs / Pipelines / notebooks; NULL means the
# product has no performance mode (SQL warehouses, predictive optimization, ...) and is
# reported as NOT_APPLICABLE so the share-of-product denominator stays honest.
SVA_03_SQL = """\
-- Serverless performance-mode mix: DBU by product_features.performance_target per product.
-- PERFORMANCE_OPTIMIZED is the higher-rate default; STANDARD trades start-up latency for a
-- lower rate. A high PERFORMANCE_OPTIMIZED share on latency-tolerant Jobs/DLT is the lever.
-- DBU-only (list-price DBU); any $ view is a list-price estimate at the tool layer.
-- Window = data.facts.window (F-07): trailing 30 FULL days, today excluded, fixed
-- (not the run lookback), so JOBS/DLT figures reconcile with facts.performance_mode.
SELECT
  workspace_id,
  billing_origin_product,
  COALESCE(product_features.performance_target, 'NOT_APPLICABLE') AS performance_target,
  ROUND(SUM(usage_quantity), 2)                                   AS total_dbus,
  ROUND(
    SUM(usage_quantity) * 100.0
      / NULLIF(SUM(SUM(usage_quantity)) OVER (PARTITION BY workspace_id, billing_origin_product), 0),
    1
  )                                                               AS pct_of_product_dbus
FROM system.billing.usage
WHERE usage_date >= DATEADD(DAY, -30, CURRENT_DATE())
  AND usage_date < CURRENT_DATE()
  AND usage_unit = 'DBU'
  AND product_features.is_serverless = TRUE
GROUP BY workspace_id, billing_origin_product, product_features.performance_target
ORDER BY total_dbus DESC NULLS LAST
LIMIT {result_limit}
"""


# SVA-01 attributes by endpoint_name (VS/MS) and database_instance_id (Lakebase).
_SVA01_COLUMNS = (
    "workspace_id",
    "billing_origin_product",
    "usage_unit",
    "usage_metadata",       # struct: .endpoint_name + .database_instance_id
    "usage_quantity",
    "usage_date",
    "database_instance_id", # Lakebase primary attribution key (via usage_metadata)
)
# SVA-02 adds the custom_tags coverage signal.
_SVA02_COLUMNS = (*_SVA01_COLUMNS, "custom_tags")
# SVA-03 reads the performance_target / is_serverless product_features fields.
_SVA03_COLUMNS = (
    "workspace_id",
    "billing_origin_product",
    "usage_unit",
    "product_features",
    "usage_quantity",
    "usage_date",
)


SERVERLESS_ATTRIBUTION_PACK = QueryPack(
    pack_id="serverless_attribution",
    domain="serverless_attribution",
    name="Serverless Attribution",
    description=(
        "Attributes serverless AI spend (Vector Search, Model Serving, Lakebase/"
        "DATABASE) that the standard packs report as Unattributed: spend by "
        "workspace × product × endpoint or instance (SVA-01) with both endpoint_name "
        "(VS/MS) and database_instance_id (Lakebase) as entity signals; attribution "
        "coverage — tagged vs untagged share (SVA-02); and the serverless "
        "performance-mode mix — PERFORMANCE_OPTIMIZED vs STANDARD per product "
        "(SVA-03). Public system.billing.usage only; unit-aware (total_units); "
        "workspace-scoped."
    ),
    queries=(
        SystemQuery(
            query_id="SVA-01",
            name="Serverless Spend by Endpoint or Instance",
            description=(
                "Serverless spend by (workspace_id, billing_origin_product, "
                "usage_unit, endpoint_name, database_instance_id). Surfaces which "
                "Vector Search index, Model Serving endpoint, or Lakebase instance "
                "carries the spend so an owner can be identified. "
                "endpoint_name is the entity key for VS/MS; database_instance_id is "
                "the entity key for Lakebase/DATABASE — both are surfaced so a null "
                "database_instance_id is not the end of attribution. "
                "Column total_units (not total_dbus) reflects that Lakebase rows "
                "may carry usage_unit = 'DSU'."
            ),
            sql_template=SVA_01_SQL,
            required_tables=("system.billing.usage",),
            required_columns=_SVA01_COLUMNS,
            domain="serverless_attribution",
            required=True,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary=(
                    "Serverless spend per endpoint/instance entity, per workspace and product"
                ),
                output_hint=(
                    "Entities ranked by total_units; '(no endpoint — unattributed)' rows "
                    "have no entity signal (endpoint_name AND database_instance_id both "
                    "null) — needs a tagging pass"
                ),
                tags=("serverless", "attribution", "cost", "dbu"),
            ),
        ),
        SystemQuery(
            query_id="SVA-02",
            name="Serverless Attribution Coverage",
            description=(
                "Per (workspace_id, billing_origin_product, usage_unit): total "
                "serverless spend, the share carrying a custom_tags owner signal "
                "(tagged_pct), and the share tied to an entity "
                "(endpoint_name for VS/MS or database_instance_id for Lakebase). "
                "An honest measure of how much is actionable yet. "
                "Column names use _units (not _dbus) because Lakebase rows may be DSU."
            ),
            sql_template=SVA_02_SQL,
            required_tables=("system.billing.usage",),
            required_columns=_SVA02_COLUMNS,
            domain="serverless_attribution",
            required=True,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Tagged vs unattributed share of serverless spend per product",
                output_hint=(
                    "High total_units with low tagged_pct = enforce tagging/ownership "
                    "before any serverless remediation"
                ),
                tags=("serverless", "attribution", "governance", "dbu"),
            ),
        ),
        SystemQuery(
            query_id="SVA-03",
            name="Serverless Performance-Mode Mix",
            description=(
                "Serverless DBU by (workspace_id, billing_origin_product, "
                "product_features.performance_target) with each mode's share of the "
                "product's DBU. Surfaces fleets running ~100% PERFORMANCE_OPTIMIZED "
                "on Jobs / Pipelines where STANDARD is a lower-rate option. Window: "
                "the trailing 30 full days excluding today (the data.facts.window, "
                "same as F-07), DBU only — fixed, not --lookback-days — so JOBS / DLT "
                "rows reconcile with data.facts.performance_mode."
            ),
            sql_template=SVA_03_SQL,
            required_tables=("system.billing.usage",),
            required_columns=_SVA03_COLUMNS,
            domain="serverless_attribution",
            required=True,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.BILLING,
            metadata=QueryMetadata(
                summary="Serverless DBU by performance mode (PERFORMANCE_OPTIMIZED / STANDARD) per product",
                output_hint=(
                    "pct_of_product_dbus near 100 for PERFORMANCE_OPTIMIZED on JOBS/DLT = "
                    "candidate to move latency-tolerant workloads to STANDARD; "
                    "NOT_APPLICABLE rows are products with no performance mode"
                ),
                tags=("serverless", "performance_target", "cost", "dbu"),
            ),
        ),
    ),
    gating_products=frozenset(
        {"VECTOR_SEARCH", "MODEL_SERVING", "LAKEBASE", "DATABASE", "JOBS", "DLT"}
    ),
)
