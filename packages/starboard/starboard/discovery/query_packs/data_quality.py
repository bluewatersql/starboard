# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Data Quality Monitoring query pack.

Surfaces failing data-quality checks, drift, and freshness violations from
``system.data_quality_monitoring.table_results``.

Note: the data-quality-monitoring system schema is in Public Preview; queries
are marked ``required=False`` so a missing table degrades the individual query
rather than the whole domain.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

# NOTE: system.data_quality_monitoring.table_results is Public Preview; columns
# verified against current docs (2026-08). The result is a per-snapshot table-level
# health row: `status` domain is Healthy/Unhealthy/Unknown (NOT 'FAIL'), the
# timestamp is `event_time` (no `evaluated_at`), and rows key on `table_id`. We
# count Unhealthy snapshots rather than "failed checks". Live-workspace validation
# recommended — see changes/2026_26_25_agents/impl/phase0_review_findings.md.
DQ_01_SQL = """\
SELECT
  table_id,
  COUNT(*)                                                AS snapshots,
  SUM(CASE WHEN status = 'Unhealthy' THEN 1 ELSE 0 END)   AS unhealthy_snapshots,
  MAX(event_time)                                         AS last_evaluated_at
FROM system.data_quality_monitoring.table_results
WHERE event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
GROUP BY ALL
HAVING unhealthy_snapshots > 0
ORDER BY unhealthy_snapshots DESC
LIMIT 200
"""


DATA_QUALITY_PACK = QueryPack(
    pack_id="data_quality",
    domain="monitoring",
    name="Data Quality Monitoring",
    description=(
        "Failing data-quality checks and freshness/drift incidents from the "
        "data-quality-monitoring system tables."
    ),
    queries=(
        SystemQuery(
            query_id="DQ-01",
            name="Tables with failing quality checks",
            description=(
                "Tables ranked by failed data-quality checks over the lookback "
                "window."
            ),
            sql_template=DQ_01_SQL,
            required_tables=("system.data_quality_monitoring.table_results",),
            required_columns=(
                "table_id",
                "status",
                "event_time",
            ),
            domain="monitoring",
            required=False,  # Preview table — degrade gracefully if absent
            category=QueryCategory.GOVERNANCE,
            metadata=QueryMetadata(
                summary="Identifies tables with failing data-quality checks.",
                output_hint="Rows per table with evaluation and failure counts.",
                tags=("data_quality", "monitoring", "reliability"),
            ),
        ),
    ),
    gating_products=frozenset({"DATA_QUALITY_MONITORING"}),
)
