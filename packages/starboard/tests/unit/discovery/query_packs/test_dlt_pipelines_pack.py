# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the dlt_pipelines pack: P-DLT06 ranks pipelines by lookback-total DBU."""

from __future__ import annotations

import collections
import re

from starboard.discovery.query_packs.dlt_pipelines import DLT_PIPELINES_PACK


def _p06():
    return next(q for q in DLT_PIPELINES_PACK.queries if q.query_id == "P-DLT06")


def _render(sql: str) -> str:
    return sql.format_map(
        collections.defaultdict(str, {"lookback_days": 30, "result_limit": 50})
    )


def test_p_dlt06_renders_without_placeholders() -> None:
    assert not re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", _render(_p06().sql_template))


def test_p_dlt06_is_one_row_per_pipeline_ranked_by_total() -> None:
    """Per-pipeline grain: a per-day grain let the 50-row cap cover only ~2 pipelines."""
    sql = _render(_p06().sql_template)
    assert "AS pipeline_total_dbus" in sql
    final = sql.rsplit("FROM daily_cost", 1)[1]
    assert "GROUP BY lp.pipeline_name, dc.workspace_id, dc.pipeline_id" in final
    assert "usage_date" not in final.split("GROUP BY", 1)[1]  # not grouped per day
    assert final.rsplit("ORDER BY", 1)[1].lstrip().startswith("pipeline_total_dbus DESC")
    for col in ("avg_daily_dbus", "peak_daily_dbus", "last_7d_dbus", "avg_dbus_per_update"):
        assert f"AS {col}" in sql


def test_p_dlt06_workspace_scoped_and_dbu_only() -> None:
    sql = _render(_p06().sql_template)
    assert "workspace_id" in sql
    assert "_usd" not in sql.lower()


def test_p_dlt06_on_facts_full_day_window() -> None:
    """Round-6: P-DLT06 shares data.facts.window (30 full days, today excluded)."""
    q = _p06()
    assert q.lookback_override == 30
    sql = _render(q.sql_template)
    daily = sql.split("daily_cost AS", 1)[1].split("SELECT lp.pipeline_name", 1)[0]
    assert "usage_date >= cutoff.dt AND usage_date < CURRENT_DATE()" in daily
    assert "usage_unit = 'DBU'" in daily
