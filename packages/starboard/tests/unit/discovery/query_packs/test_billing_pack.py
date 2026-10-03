# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shape guards for the billing query pack (C-B01..C-B04)."""

from __future__ import annotations

from starboard.discovery.query_packs.billing import BILLING_PACK


def _q(qid: str):
    return next(q for q in BILLING_PACK.queries if q.query_id == qid)


def _render(sql: str) -> str:
    return sql.format_map({"lookback_days": 30, "result_limit": 50})


def test_every_dbus_alias_is_dbu_filtered() -> None:
    """D7: no DSU (or other non-DBU unit) quantity is summed into a *dbus column."""
    for q in BILLING_PACK.queries:
        sql = q.sql_template
        reads = sql.count("FROM system.billing.usage")
        assert reads >= 1, q.query_id
        assert sql.count("usage_unit = 'DBU'") >= reads, q.query_id


def test_cb01_carries_usage_unit() -> None:
    q = _q("C-B01")
    sql = _render(q.sql_template)
    assert "u.usage_unit," in sql
    assert "AS dbus_consumed" in sql  # column name kept for heuristics/detectors
    assert "DSU" in q.description and "DSU" in q.metadata.output_hint


def test_cb04_per_job_step_and_shape() -> None:
    """D12: each contributing job gets its own step date + RAMP/STEP label."""
    q = _q("C-B04")
    sql = _render(q.sql_template)
    # Workspace-level columns kept (heuristics + existing consumers).
    for col in ("step_date", "step_dbu_lift", "job_dbu_lift"):
        assert col in sql
    for col in (
        "job_step_date",
        "job_step_dbu_lift",
        "job_transition_days",
        "job_change_shape",
    ):
        assert f"AS {col}" in sql or f"js.{col}" in sql, col
    # Zero-filled daily series so idle days count toward the 7-day averages.
    assert "EXPLODE(SEQUENCE(d.win_start, d.win_end))" in sql
    assert "COALESCE(ju.dbus, 0)" in sql
    # Own change point needs full 7-day windows on both sides.
    assert "WHERE n_before = 7 AND n_after = 7" in sql
    # Ramp = lift spread over more than 3 mid-transition days.
    assert "WHEN js.job_transition_days > 3 THEN 'RAMP'" in sql
    assert "'STEP'" in sql
    assert "job_change_shape" in q.metadata.output_hint
    assert "LIMIT 50" in sql
