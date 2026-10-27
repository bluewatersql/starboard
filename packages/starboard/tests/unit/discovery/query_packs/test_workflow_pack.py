# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Regression tests for the workflow pack (P-WF01 / P-WF02).

P-WF01 counted only 'FAILED' (missing ERROR / TIMED_OUT), picked the state with a
lexicographic MAX, and averaged the terminal timeline period only — a long task
run is sliced ~hourly and only its last slice carries result_state.
"""

from __future__ import annotations

import collections
import re

import pytest
from starboard.discovery.query_packs.jobs import _FAILURE_STATES_SQL
from starboard.discovery.query_packs.product_surfaces import WORKFLOW_PACK


def _render(sql: str) -> str:
    return sql.format_map(
        collections.defaultdict(str, {"lookback_days": 30, "result_limit": 50})
    )


def _q(query_id: str):
    return next(q for q in WORKFLOW_PACK.queries if q.query_id == query_id)


def _cte_where(sql: str, name: str) -> str:
    body = sql.split(f"{name} AS (", 1)[1]
    m = re.search(r"\bWHERE\b(.*?)\bGROUP BY\b", body, re.S)
    assert m
    return m.group(1)


@pytest.mark.parametrize("qid", ["P-WF01", "P-WF02"])
def test_uses_shared_failure_state_set(qid: str) -> None:
    sql = _render(_q(qid).sql_template)
    assert f"IN {_FAILURE_STATES_SQL}" in sql
    assert not re.search(r"=\s*'FAILED'", sql)
    assert not re.search(r"\{[a-z_]+\}", sql)


@pytest.mark.parametrize(
    ("qid", "cte"), [("P-WF01", "task_stats"), ("P-WF02", "iterations")]
)
def test_task_run_aggregates_all_periods(qid: str, cte: str) -> None:
    sql = _render(_q(qid).sql_template)
    assert "result_state IS NOT NULL" not in _cte_where(sql, cte)
    assert "MAX(result_state)" not in sql
    assert "IF(result_state IS NOT NULL, period_end_time, NULL)" in sql
    assert "CAST(" not in sql


def test_pwf01_reports_cancelled_separately() -> None:
    sql = _render(_q("P-WF01").sql_template)
    assert "cancelled_executions" in sql
    assert "= 'CANCELLED'" in sql
    assert "WHERE ts.result_state IS NOT NULL" in sql


def test_pwf02_groups_iterations_under_foreach_parent() -> None:
    sql = _render(_q("P-WF02").sql_template)
    assert "parent_run_id <> job_run_id" in sql
    assert "GROUP BY workspace_id, job_id, parent_run_id, task_key" in sql
