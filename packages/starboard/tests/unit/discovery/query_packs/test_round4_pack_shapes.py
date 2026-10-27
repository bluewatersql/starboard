# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Round-4 C8 pack-shape guards: C-C03 per warehouse per day, C-J05
``is_partial_day``, F-03 ``in_window``. (Live-validated on the mirror.)"""

from __future__ import annotations

import re

import pytest
from starboard.discovery.executor import make_render
from starboard.discovery.query_packs.compute import COMPUTE_PACK
from starboard.discovery.query_packs.facts import FACTS_PACK
from starboard.discovery.query_packs.jobs import JOBS_PACK


def _sql(pack, query_id: str, lookback_days: int = 30) -> str:
    q = next(q for q in pack.queries if q.query_id == query_id)
    return make_render(lookback_days, 50)(q.sql_template)


def _final_select(sql: str) -> str:
    return sql[sql.rindex("\nSELECT") :]


def test_c_c03_rolls_hours_up_to_one_row_per_warehouse_day() -> None:
    sql = _sql(COMPUTE_PACK, "C-C03")
    final = _final_select(sql)
    assert "query_hour" not in final
    assert "GROUP BY warehouse_id, query_date" in sql
    for col in ("peak_hour_queries", "peak_hour_avg_queue_secs", "active_hours",
                "avg_queue_secs", "queries_queued_30s_plus"):
        assert col in final
    # Scale events are joined at day grain too (no hour key left in the join).
    assert "event_hour" not in sql
    # Recent days of every warehouse survive the cap (not one warehouse's hours).
    assert re.search(r"ORDER BY qp\.query_date DESC, qp\.total_queries DESC", sql)
    assert sql.rstrip().endswith("LIMIT 50")


def test_c_j05_marks_todays_partial_day() -> None:
    sql = _sql(JOBS_PACK, "C-J05")
    assert re.search(r"DATE\(period_start_time\) = CURRENT_DATE\(\)\s+AS is_partial_day", sql)


@pytest.mark.parametrize("lookback", [7, 30])
def test_f_03_flags_window_vs_baseline_rows(lookback: int) -> None:
    sql = _sql(FACTS_PACK, "F-03", lookback)
    assert re.search(
        rf"u\.usage_date >= DATEADD\(DAY, -{lookback}, CURRENT_DATE\(\)\) AS in_window", sql
    )
    # The scan covers the window plus the 7-day baseline before it.
    assert f"DATEADD(DAY, -{lookback + 7}, CURRENT_DATE())" in sql
