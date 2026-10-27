# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""DQ-01 / DCL-01 against the real (metastore-grained) system-table schema (run-4 D2-1).

``system.data_quality_monitoring.table_results`` and
``system.data_classification.results`` have no ``workspace_id`` column (they are
keyed by catalog / schema / table). An authorized run wrapped them in
``WHERE workspace_id IN (...)`` and both failed with an unresolved
``workspace_id``. They are scoped by catalog visibility instead: only catalogs
the connected workspace can see (``system.information_schema.catalogs``).
"""

from __future__ import annotations

import re

import pytest
from starboard.discovery.executor import make_render
from starboard.discovery.query_packs.data_classification import (
    DATA_CLASSIFICATION_PACK,
)
from starboard.discovery.query_packs.data_quality import DATA_QUALITY_PACK

_CATALOG_SCOPE = (
    "catalog_name IN (SELECT catalog_name FROM system.information_schema.catalogs)"
)

# Real columns (DESCRIBE on a live workspace, 2026-10-13).
_DQ_COLUMNS = {
    "event_time",
    "catalog_name",
    "schema_name",
    "table_name",
    "catalog_id",
    "schema_id",
    "table_id",
    "status",
    "freshness",
    "completeness",
    "downstream_impact",
    "root_cause_analysis",
}
_DCL_COLUMNS = {
    "catalog_id",
    "table_id",
    "latest_detected_time",
    "first_detected_time",
    "catalog_name",
    "schema_name",
    "table_name",
    "column_name",
    "data_type",
    "class_tag",
    "samples",
    "confidence",
    "frequency",
    "exclusion_state",
    "class_tag_value",
}

_CASES = [
    (DATA_QUALITY_PACK.queries[0], _DQ_COLUMNS),
    (DATA_CLASSIFICATION_PACK.queries[0], _DCL_COLUMNS),
]


def _render(sql: str) -> str:
    return make_render(30, 200)(sql)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "columns"), _CASES, ids=lambda x: getattr(x, "query_id", "")
)
def test_no_workspace_id_reference(query, columns) -> None:
    sql = _render(query.sql_template)
    assert "workspace_id" not in sql
    assert "workspace_id" not in columns
    assert not re.search(r"\{[a-z_]+\}", sql)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "columns"), _CASES, ids=lambda x: getattr(x, "query_id", "")
)
def test_scoped_to_visible_catalogs(query, columns) -> None:
    sql = _render(query.sql_template)
    assert _CATALOG_SCOPE in sql
    assert "catalog_name" in columns


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "columns"), _CASES, ids=lambda x: getattr(x, "query_id", "")
)
def test_required_columns_exist_in_real_schema(query, columns) -> None:
    assert set(query.required_columns) <= columns


@pytest.mark.unit
def test_dq01_names_the_table() -> None:
    """DQ-01 rows carry catalog/schema/table names, not only an opaque table_id."""
    sql = _render(DATA_QUALITY_PACK.queries[0].sql_template)
    for col in ("catalog_name", "schema_name", "table_name"):
        assert f"MAX_BY({col}, event_time)" in sql
        assert re.search(rf"\bAS {col}\b", sql)
    assert "GROUP BY table_id" in sql
    assert "DATEADD(DAY, -30, CURRENT_DATE())" in sql
