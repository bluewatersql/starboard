# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Predictive Optimization query pack.

Surfaces what Predictive Optimization (PO) has compacted/clustered/vacuumed and
how often, from ``system.storage.predictive_optimization_operations_history``.

Note: the PO operations-history system table is in Public Preview; queries are
marked ``required=False`` so a missing table degrades the individual query
rather than the whole domain.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

PO_01_SQL = """\
SELECT
  operation_type,
  catalog_name,
  schema_name,
  COUNT(*)                     AS operation_count,
  -- table_id is the reliably populated identity; the 3-part name can be NULL
  -- (e.g. masked/mirrored sources). NULL (not a false 0) if no identity at all.
  NULLIF(COUNT(DISTINCT COALESCE(
    table_id,
    NULLIF(CONCAT_WS('.', catalog_name, schema_name, table_name), '')
  )), 0)                       AS tables_optimized,
  MAX(start_time)              AS last_operation_at
FROM system.storage.predictive_optimization_operations_history
WHERE start_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
GROUP BY ALL
ORDER BY operation_count DESC
LIMIT 200
"""


PREDICTIVE_OPTIMIZATION_PACK = QueryPack(
    pack_id="predictive_optimization",
    domain="governance",
    name="Predictive Optimization",
    description=(
        "What Predictive Optimization compacted, clustered, and vacuumed, and "
        "which tables benefit — from the PO operations-history system table."
    ),
    queries=(
        SystemQuery(
            query_id="PO-01",
            name="PO operations by type",
            description=(
                "Predictive Optimization operations grouped by operation type, "
                "catalog, and schema over the lookback window. tables_optimized "
                "counts distinct table_id (falling back to the 3-part name); it is "
                "NULL, not 0, when no table identity is available. catalog_name / "
                "schema_name may be NULL on sources that mask them."
            ),
            sql_template=PO_01_SQL,
            required_tables=(
                "system.storage.predictive_optimization_operations_history",
            ),
            required_columns=(
                "operation_type",
                "catalog_name",
                "schema_name",
                "table_name",
                "table_id",
                "start_time",
            ),
            domain="governance",
            required=False,  # Preview table — degrade gracefully if absent
            category=QueryCategory.GOVERNANCE,
            metadata=QueryMetadata(
                summary=(
                    "Shows Predictive Optimization activity (compaction, "
                    "clustering, vacuum) per operation type and schema."
                ),
                output_hint="Rows per operation type with counts and last-run time.",
                tags=("predictive_optimization", "storage", "maintenance"),
            ),
        ),
    ),
    gating_products=frozenset({"PREDICTIVE_OPTIMIZATION"}),
)
