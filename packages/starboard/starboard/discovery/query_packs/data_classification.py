# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Data Classification query pack.

Surfaces PII / sensitive-data classification coverage from
``system.data_classification.results``.

Note: the data-classification system schema is in Public Preview; queries are
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

# NOTE: system.data_classification.results is Public Preview; column names verified
# against current docs (2026-08). The tag column is `class_tag` and the timestamp is
# `latest_detected_time` (`first_detected_time` also available); catalog/schema/table/
# column names are as below. Live-workspace validation still recommended — see
# changes/2026_26_25_agents/impl/phase0_review_findings.md.
DC_01_SQL = """\
SELECT
  catalog_name,
  schema_name,
  table_name,
  COUNT(DISTINCT column_name)       AS classified_columns,
  COUNT(DISTINCT class_tag)         AS distinct_classifications,
  MAX(latest_detected_time)         AS last_classified_at
FROM system.data_classification.results
WHERE latest_detected_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
GROUP BY ALL
ORDER BY classified_columns DESC
LIMIT 200
"""


DATA_CLASSIFICATION_PACK = QueryPack(
    pack_id="data_classification",
    domain="governance",
    name="Data Classification",
    description=(
        "PII and sensitive-data classification coverage from the "
        "data-classification system tables."
    ),
    queries=(
        SystemQuery(
            query_id="DCL-01",
            name="Classified columns by table",
            description=(
                "Classification coverage per table (classified columns and "
                "distinct classifications) over the lookback window."
            ),
            sql_template=DC_01_SQL,
            required_tables=("system.data_classification.results",),
            required_columns=(
                "catalog_name",
                "schema_name",
                "table_name",
                "column_name",
                "class_tag",
                "latest_detected_time",
            ),
            domain="governance",
            required=False,  # Preview table — degrade gracefully if absent
            category=QueryCategory.GOVERNANCE,
            metadata=QueryMetadata(
                summary="Shows sensitive-data classification coverage per table.",
                output_hint="Rows per table with classified-column counts.",
                tags=("data_classification", "pii", "governance"),
            ),
        ),
    ),
    gating_products=frozenset({"DATA_CLASSIFICATION"}),
)
