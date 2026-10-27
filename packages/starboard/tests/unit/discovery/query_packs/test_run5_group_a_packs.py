# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 5 (group A): C-B01 window + attribution, W-W02 carries delete_time."""

from __future__ import annotations

import re

import pytest
from starboard.discovery.query_packs.billing import C_B01_SQL
from starboard.discovery.query_packs.facts import F_01_SQL
from starboard.discovery.query_packs.warehouse import W_W02_SQL

pytestmark = pytest.mark.unit


def _flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_c_b01_uses_the_f01_full_day_window() -> None:
    sql = _flat(C_B01_SQL)
    assert "BETWEEN" not in sql  # today's partial day is excluded, as in F-01
    assert "u.usage_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())" in sql
    assert "u.usage_date < CURRENT_DATE()" in sql
    assert "< CURRENT_DATE()" in _flat(F_01_SQL)


def test_c_b01_unattributed_needs_no_identity_and_no_resource() -> None:
    sql = _flat(C_B01_SQL)
    case = sql[sql.index("CASE") : sql.index("AS user_type")]
    for col in ("identity_metadata.owned_by", "identity_metadata.created_by",
                "usage_metadata.job_id", "usage_metadata.warehouse_id",
                "usage_metadata.endpoint_name", "usage_metadata.app_id",
                "usage_metadata.database_instance_id"):
        assert col in case, col
    labels = re.findall(r"'([A-Z][A-Za-z ]+)'", case)
    assert labels[-1] == "Unattributed"  # the ELSE: none of the above
    assert {"Human User", "Service Principal", "Owner Attributed",
            "Resource Attributed"} <= set(labels)
    assert "run_as IS NULL THEN 'Unattributed'" not in case


def test_w_w02_carries_the_latest_delete_time() -> None:
    sql = _flat(W_W02_SQL)
    assert "MAX_BY(delete_time, change_time) AS delete_time" in sql
    assert "w.delete_time AS delete_time" in sql
    assert re.search(r"GROUP BY [^;]*w\.delete_time HAVING", sql)
