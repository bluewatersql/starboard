# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Column-level lineage query pack (Phase-2 D5).

Column-level impact analysis and PII-propagation signals over the public
``system.access.column_lineage`` table:

- **Fan-out / impact** — source columns feeding the most downstream columns and
  tables (change-impact blast radius).
- **PII propagation** — PII-named source columns and how widely they propagate
  into downstream tables/columns (governance signal).
- **Fan-in / provenance** — target columns fed by the most upstream sources
  (provenance complexity).

No dollar computations, no internal namespaces; a single public system table.

Column and retention facts verified against current Databricks docs
(2026-08-26):

- ``system.access.column_lineage`` — columns ``source_table_full_name``,
  ``source_column_name``, ``target_table_full_name``, ``target_column_name``,
  ``event_time``, ``event_date`` (partition), etc. Lineage system tables retain
  a **rolling 1-year window**:
  <https://docs.databricks.com/aws/en/admin/system-tables/lineage>
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

# Lineage tables keep a rolling 1-year window; clamp lookback so a larger
# configured window never silently returns empty results.
_LINEAGE_RETENTION_DAYS = 365

# CL-01 — High fan-out source columns (change-impact blast radius).
CL_01_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt
)
SELECT
  cl.source_table_full_name,
  cl.source_column_name,
  COUNT(DISTINCT CONCAT_WS('.', cl.target_table_full_name, cl.target_column_name)) AS downstream_columns,
  COUNT(DISTINCT cl.target_table_full_name)                                        AS downstream_tables,
  MAX(cl.event_date)                                                               AS last_seen
FROM system.access.column_lineage cl, cutoff
WHERE cl.event_date >= cutoff.dt
  AND cl.source_column_name IS NOT NULL
  AND cl.target_column_name IS NOT NULL
  AND cl.source_table_full_name IS NOT NULL
  AND cl.target_table_full_name IS NOT NULL
GROUP BY cl.source_table_full_name, cl.source_column_name
ORDER BY downstream_columns DESC
LIMIT {result_limit}
"""

# CL-02 — PII propagation: PII-named source columns and their spread.
CL_02_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt
),
pii AS (
  SELECT
    cl.source_table_full_name,
    cl.source_column_name,
    cl.target_table_full_name,
    cl.target_column_name
  FROM system.access.column_lineage cl, cutoff
  WHERE cl.event_date >= cutoff.dt
    AND cl.source_column_name IS NOT NULL
    AND cl.target_column_name IS NOT NULL
    AND cl.target_table_full_name IS NOT NULL
    AND LOWER(cl.source_column_name) RLIKE
      '(email|ssn|social_security|passport|credit_card|card_number|date_of_birth|first_name|last_name|full_name|phone|address|zip|postal|tax_id|national_id|ip_address)'
)
SELECT
  source_table_full_name,
  source_column_name,
  COUNT(DISTINCT target_table_full_name)                                     AS tables_receiving_pii,
  COUNT(DISTINCT CONCAT_WS('.', target_table_full_name, target_column_name)) AS columns_receiving_pii
FROM pii
GROUP BY source_table_full_name, source_column_name
ORDER BY tables_receiving_pii DESC
LIMIT {result_limit}
"""

# CL-03 — High fan-in target columns (provenance complexity).
CL_03_SQL = """\
WITH cutoff AS (
  SELECT DATEADD(DAY, -{lookback_days}, CURRENT_DATE()) AS dt
)
SELECT
  cl.target_table_full_name,
  cl.target_column_name,
  COUNT(DISTINCT CONCAT_WS('.', cl.source_table_full_name, cl.source_column_name)) AS upstream_columns,
  COUNT(DISTINCT cl.source_table_full_name)                                        AS upstream_tables,
  MAX(cl.event_date)                                                               AS last_seen
FROM system.access.column_lineage cl, cutoff
WHERE cl.event_date >= cutoff.dt
  AND cl.target_column_name IS NOT NULL
  AND cl.source_column_name IS NOT NULL
  AND cl.target_table_full_name IS NOT NULL
  AND cl.source_table_full_name IS NOT NULL
GROUP BY cl.target_table_full_name, cl.target_column_name
ORDER BY upstream_columns DESC
LIMIT {result_limit}
"""


COLUMN_LINEAGE_PACK = QueryPack(
    pack_id="column_lineage",
    domain="lineage",
    name="Column Lineage",
    description=(
        "Column-level impact analysis and PII-propagation signals over "
        "system.access.column_lineage"
    ),
    queries=(
        SystemQuery(
            query_id="CL-01",
            name="High Fan-Out Source Columns",
            description=(
                "Source columns feeding the most downstream columns/tables — "
                "change-impact blast radius"
            ),
            sql_template=CL_01_SQL,
            required_tables=("system.access.column_lineage",),
            domain="lineage",
            required=True,
            max_lookback_days=_LINEAGE_RETENTION_DAYS,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.GOVERNANCE,
            metadata=QueryMetadata(
                summary="Columns with the widest downstream impact",
                output_hint="Source columns ranked by downstream column count",
                tags=("lineage", "impact"),
            ),
        ),
        SystemQuery(
            query_id="CL-02",
            name="PII Column Propagation",
            description=(
                "PII-named source columns and how widely they propagate into "
                "downstream tables/columns"
            ),
            sql_template=CL_02_SQL,
            required_tables=("system.access.column_lineage",),
            domain="lineage",
            required=True,
            max_lookback_days=_LINEAGE_RETENTION_DAYS,
            discovery_mode=DiscoveryMode.GENERAL,
            category=QueryCategory.GOVERNANCE,
            metadata=QueryMetadata(
                summary="PII propagation across tables (name-heuristic)",
                output_hint="PII source columns ranked by receiving-table count",
                tags=("lineage", "pii", "governance"),
            ),
        ),
        SystemQuery(
            query_id="CL-03",
            name="High Fan-In Target Columns",
            description=(
                "Target columns fed by the most upstream sources — provenance "
                "complexity"
            ),
            sql_template=CL_03_SQL,
            required_tables=("system.access.column_lineage",),
            domain="lineage",
            required=True,
            max_lookback_days=_LINEAGE_RETENTION_DAYS,
            discovery_mode=DiscoveryMode.DEEP_DIVE,
            category=QueryCategory.GOVERNANCE,
            metadata=QueryMetadata(
                summary="Columns with the most upstream sources",
                output_hint="Target columns ranked by upstream column count",
                tags=("lineage", "provenance"),
            ),
        ),
    ),
    gating_products=frozenset({"FINE_GRAINED_ACCESS_CONTROL", "DATA_CLASSIFICATION"}),
)
