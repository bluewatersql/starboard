# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""F-12 per-job reliability (D3-23): shared run_summary CTE with F-06, top-25 cap."""

from __future__ import annotations

import re

import pytest
from starboard.discovery.query_packs.facts import (
    F_06_SQL,
    F_12_SQL,
    FACTS_PACK,
    RUN_SUMMARY_CTE,
)
from starboard_core.domain.models.discovery.query import QueryCategory
from starboard_core.engagement.jobruns import CANCELLED_STATE, F12_CAP, FAILED_STATES
from starboard_x.discovery._facts import _FIELD_SOURCES, build_facts

_FAILED_RUNS_IN = re.compile(r"IN\s*\(([^)]*)\)\s*THEN 1 ELSE 0 END\)\s*AS failed_runs")


def _literals(group: str) -> tuple[str, ...]:
    return tuple(re.findall(r"'([^']*)'", group))


def _f12():
    return next(q for q in FACTS_PACK.queries if q.query_id == "F-12")


@pytest.mark.unit
class TestF12:
    def test_registered_after_f11(self) -> None:
        ids = [q.query_id for q in FACTS_PACK.queries]
        assert ids[-1] == "F-12"
        q = _f12()
        assert q.sql_template == F_12_SQL
        assert q.required_tables == ("system.lakeflow.job_run_timeline",)
        assert q.category == QueryCategory.OPTIMIZATION
        assert "25" in q.description

    def test_shares_run_summary_cte_byte_for_byte(self) -> None:
        assert RUN_SUMMARY_CTE.startswith("run_summary AS (")
        assert f"WITH {RUN_SUMMARY_CTE}" in F_06_SQL
        assert f"WITH {RUN_SUMMARY_CTE}" in F_12_SQL
        # Exactly one definition of the CTE in each query.
        assert F_06_SQL.count("run_summary AS (") == 1
        assert F_12_SQL.count("run_summary AS (") == 1

    def test_failure_literals_equal_kernel_constant(self) -> None:
        for sql in (F_06_SQL, F_12_SQL):
            (group,) = _FAILED_RUNS_IN.findall(sql)
            assert _literals(group) == FAILED_STATES
            assert f"= '{CANCELLED_STATE}'" in sql

    def test_per_job_grain_and_columns(self) -> None:
        sql = F_12_SQL
        assert "GROUP BY rs.workspace_id, rs.job_id" in sql
        for col in (
            "runs",
            "failed_runs",
            "cancelled_runs",
            "window_start",
            "window_end",
        ):
            assert f"AS {col}" in sql or f"jc.{col}" in sql, col
        assert "rs.final_result_state IS NOT NULL" in sql

    def test_top_25_cap_and_ordering(self) -> None:
        assert F12_CAP == 25
        order = "ORDER BY jc.failed_runs DESC, jc.runs DESC, jc.job_id"
        assert f"PARTITION BY jc.workspace_id {order}" in F_12_SQL
        assert f") <= {F12_CAP}" in F_12_SQL
        # Per-workspace cap, never a global LIMIT (multi-workspace scopes stay fair).
        assert "LIMIT" not in F_12_SQL
        assert "{result_limit}" not in F_12_SQL

    def test_facts_field_sources_f12(self) -> None:
        assert _FIELD_SOURCES["job_reliability_by_job"] == ("F-12",)

    def test_build_facts_emits_by_job_field(self) -> None:
        rows = [
            {
                "workspace_id": "123",
                "job_id": "42",
                "runs": 10,
                "failed_runs": 4,
                "cancelled_runs": 1,
            }
        ]
        q = {
            "query_id": "F-12",
            "status": "succeeded",
            "error": None,
            "rows": rows,
            "truncated": False,
        }
        facts = build_facts([q])
        assert facts["sources"]["job_reliability_by_job"] == "F-12"
        (job,) = facts["job_reliability_by_job"]["jobs"]
        assert (job["job_id"], job["failed_runs"], job["failure_rate_pct"]) == (
            "42",
            4,
            40.0,
        )
        assert facts["job_reliability_by_job"]["uncertainty"] == ["per_job_cap_25"]
