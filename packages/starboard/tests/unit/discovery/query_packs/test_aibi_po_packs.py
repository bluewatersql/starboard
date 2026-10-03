"""Metric-honesty regression tests for the AI/BI + Genie query-performance
split (P-AIBI04 dashboard-only / P-GEN02 genie-only) and PO-01.

The former consolidated P-AIBI04 returned BOTH dashboard and genie rows via a
CASE expression. It is now SPLIT: P-AIBI04 (aibi pack) is dashboard-only and
P-GEN02 (genie pack) is genie-only. Each preserves the capacity-wait /
queued-subset population semantics, so the metric-honesty assertions apply to
both halves."""

from __future__ import annotations

import re

from starboard.discovery.query_packs.aibi import AIBI_PACK
from starboard.discovery.query_packs.genie import GENIE_PACK
from starboard.discovery.query_packs.predictive_optimization import (
    PO_01_SQL,
    PREDICTIVE_OPTIMIZATION_PACK,
)


def _query(pack, query_id: str):
    return next(q for q in pack.queries if q.query_id == query_id)


def _strip_comments(sql: str) -> str:
    # Strip SQL line comments so explanatory prose doesn't trip the assertions.
    return re.sub(r"--[^\n]*", "", sql)


def _capacity_wait_cases():
    # (label, pack, query_id) for both halves of the split.
    return (
        ("aibi/P-AIBI04", AIBI_PACK, "P-AIBI04"),
        ("genie/P-GEN02", GENIE_PACK, "P-GEN02"),
    )


class TestQueryPerfCapacityWait:
    def test_avg_capacity_wait_is_population_consistent(self) -> None:
        for _label, pack, qid in _capacity_wait_cases():
            sql = _strip_comments(_query(pack, qid).sql_template)
            # NULL = never queued; the mean must cover all queries (COALESCE to 0).
            assert "AVG(COALESCE(waiting_at_capacity_duration_ms, 0))" in sql
            # No bare AVG over the nullable column (averages only queued rows).
            assert not re.search(r"AVG\(\s*waiting_at_capacity_duration_ms\s*\)", sql)

    def test_queued_subset_metrics_present(self) -> None:
        for _label, pack, qid in _capacity_wait_cases():
            sql = _strip_comments(_query(pack, qid).sql_template)
            for col in ("queued_query_pct", "avg_queued_wait_ms", "p95_queued_wait_ms"):
                assert f"AS {col}" in sql
            assert "COUNT_IF(waiting_at_capacity_duration_ms > 0)" in sql

    def test_columns_documented(self) -> None:
        for _label, pack, qid in _capacity_wait_cases():
            q = _query(pack, qid)
            for col in ("queued_query_pct", "avg_queued_wait_ms", "p95_queued_wait_ms"):
                assert col in q.description


class TestQueryPerfSplitScoping:
    def test_aibi04_is_dashboard_only(self) -> None:
        sql = _strip_comments(_query(AIBI_PACK, "P-AIBI04").sql_template)
        assert "query_source.dashboard_id IS NOT NULL" in sql
        assert "genie_space_id" not in sql

    def test_gen02_is_genie_only(self) -> None:
        sql = _strip_comments(_query(GENIE_PACK, "P-GEN02").sql_template)
        assert "query_source.genie_space_id IS NOT NULL" in sql
        assert "dashboard_id" not in sql

    def test_query_perf_carries_warehouse_id(self) -> None:
        # A queued dashboard / Genie space must map to its OPP-WH-QUEUE target
        # warehouse without a cross-reference: one row per source x warehouse.
        for _label, pack, qid in _capacity_wait_cases():
            sql = _strip_comments(_query(pack, qid).sql_template)
            assert "compute.warehouse_id AS warehouse_id" in sql
            assert re.search(r"GROUP BY query_source\.\w+, compute\.warehouse_id", sql)

    def test_genie_inventory_moved_out_of_aibi(self) -> None:
        aibi_ids = {q.query_id for q in AIBI_PACK.queries}
        assert "P-AIBI03" not in aibi_ids  # moved to genie pack
        genie_ids = {q.query_id for q in GENIE_PACK.queries}
        assert "P-GEN01" in genie_ids  # the moved Genie Space Inventory


class TestPo01TablesOptimized:
    def test_distinct_uses_table_id_not_bare_name(self) -> None:
        assert "COUNT(DISTINCT table_name)" not in PO_01_SQL
        assert "COALESCE(\n    table_id," in PO_01_SQL

    def test_no_identity_is_null_not_zero(self) -> None:
        assert "NULLIF(COUNT(DISTINCT" in PO_01_SQL

    def test_table_id_is_required_column(self) -> None:
        q = PREDICTIVE_OPTIMIZATION_PACK.queries[0]
        assert "table_id" in q.required_columns
