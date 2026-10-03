# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the facts query pack (F-01 … F-11) feeding ``data.facts`` (B1)."""

from __future__ import annotations

import collections
import re

import pytest
from starboard.discovery.query_packs.facts import FACTS_PACK
from starboard.discovery.query_packs.jobs import _FAILURE_STATES_SQL
from starboard.discovery.query_packs.registry import (
    ALWAYS_RUN_PACKS,
    create_default_registry,
)
from starboard_x.discovery._facts import _FIELD_SOURCES

_RENDER_PARAMS = {"lookback_days": 30, "result_limit": 50}

_FORBIDDEN_NAMESPACES = (
    "centralized_system_tables",
    "fin_live_gold",
    "logfood",
    "clickhouse",
    "hmr_stack_hash",
    "go/",
    "gtm_",
    "eng_",
)

_IDS = tuple(f"F-{i:02d}" for i in range(1, 12))


def _render(sql: str) -> str:
    return sql.format_map(collections.defaultdict(str, _RENDER_PARAMS))


@pytest.mark.unit
class TestFactsPack:
    def test_ids(self) -> None:
        assert tuple(q.query_id for q in FACTS_PACK.queries) == _IDS

    def test_builder_reads_only_pack_ids(self) -> None:
        used = {qid for ids in _FIELD_SOURCES.values() for qid in ids}
        assert used == set(_IDS)

    def test_always_run_and_registered(self) -> None:
        assert "facts" in ALWAYS_RUN_PACKS
        registry = create_default_registry()
        assert registry.get_pack("facts") is FACTS_PACK
        selected = registry.get_packs_for_products(set())
        assert "facts" in {p.pack_id for p in selected}
        assert FACTS_PACK.gating_products == frozenset()

    def test_renders_without_placeholders(self) -> None:
        for q in FACTS_PACK.queries:
            sql = _render(q.sql_template)
            assert "{" not in sql and "}" not in sql, q.query_id

    def test_aggregates_are_result_limit_free(self) -> None:
        for q in FACTS_PACK.queries:
            assert "{result_limit}" not in q.sql_template, q.query_id

    def test_workspace_id_in_grain(self) -> None:
        for q in FACTS_PACK.queries:
            assert "workspace_id" in q.sql_template, q.query_id

    def test_governance_no_internal_namespaces_dbu_only(self) -> None:
        for q in FACTS_PACK.queries:
            low = q.sql_template.lower()
            for ns in _FORBIDDEN_NAMESPACES:
                assert ns not in low, f"{q.query_id} contains {ns}"
            assert "cost_usd" not in low and "list_prices" not in low

    def test_usage_quantities_are_dbu_filtered_except_unit_grained_f01(self) -> None:
        for q in FACTS_PACK.queries:
            if "system.billing.usage" not in q.required_tables:
                continue
            if q.query_id == "F-01":
                assert "u.usage_unit" in q.sql_template
                assert "GROUP BY u.workspace_id, u.billing_origin_product, u.usage_unit" in (
                    q.sql_template)
            else:
                assert "usage_unit = 'DBU'" in q.sql_template, q.query_id

    def test_full_day_window_excludes_today(self) -> None:
        for qid in ("F-01", "F-04", "F-05", "F-07", "F-08", "F-11"):
            sql = next(q for q in FACTS_PACK.queries if q.query_id == qid).sql_template
            assert "usage_date >= DATEADD(DAY, -30, CURRENT_DATE())" in sql, qid
            assert "usage_date < CURRENT_DATE()" in sql, qid
        f03 = next(q for q in FACTS_PACK.queries if q.query_id == "F-03").sql_template
        assert "DATEADD(DAY, -37, CURRENT_DATE())" in f03
        assert "usage_date < CURRENT_DATE()" in f03

    def test_reliability_reuses_failure_states(self) -> None:
        f06 = next(q for q in FACTS_PACK.queries if q.query_id == "F-06").sql_template
        assert f"IN {_FAILURE_STATES_SQL}" in f06
        assert "'CANCELLED'" in f06

    def test_dimensions_are_deduplicated(self) -> None:
        by_id = {q.query_id: q.sql_template for q in FACTS_PACK.queries}
        assert "QUALIFY ROW_NUMBER()" in by_id["F-04"]
        assert "QUALIFY ROW_NUMBER()" in by_id["F-05"]
        assert "SELECT DISTINCT" in by_id["F-09"]
        assert "SELECT DISTINCT" in by_id["F-10"]
        assert "SELECT DISTINCT" in by_id["F-11"]
        assert "lw.version_rank = 1" in by_id["F-11"]

    def test_f03_labelled_as_37_days_with_baseline(self) -> None:
        """C3: F-03 returns 37 days (30-day window + 7-day baseline); its
        metadata must say so, so nobody sums it as a 30-day total."""
        f03 = next(q for q in FACTS_PACK.queries if q.query_id == "F-03")
        for text in (f03.name, f03.description, f03.metadata.output_hint):
            assert "37 days" in text
        assert "not a 30-day total" in f03.description
        assert "do NOT sum" in f03.sql_template

    def test_f11_top_warehouses_shape(self) -> None:
        """C2: per-warehouse DBU on the facts window (reconciles with vt-warehouse-dbu)."""
        f11 = next(q for q in FACTS_PACK.queries if q.query_id == "F-11")
        sql = _render(f11.sql_template)
        assert f11.required_tables == ("system.billing.usage", "system.compute.warehouses")
        assert "u.usage_metadata.warehouse_id IS NOT NULL" in sql
        assert "PARTITION BY wd.workspace_id ORDER BY wd.dbus DESC" in sql
        assert "WHERE r.warehouse_rank <= 10" in sql

    def test_every_table_reference_is_aliased(self) -> None:
        # The internal source's scope injector wraps ``FROM/JOIN <table> [alias]``;
        # a bare reference followed by QUALIFY/WINDOW would be misread as an alias.
        for q in FACTS_PACK.queries:
            for m in re.finditer(r"\b(?:FROM|JOIN)\s+(system\.\w+\.\w+)\s+(\w+)", q.sql_template):
                assert m.group(2).upper() not in {"WHERE", "QUALIFY", "WINDOW", "GROUP"}, (
                    f"{q.query_id}: {m.group(1)} has no alias")


def test_f06_matches_vt_job_failures_run_definition() -> None:
    """Round-8 (gpt-6 #4): F-06 = 190 vs vt-job-failures ERROR 184 + TIMED_OUT 5.
    The gap was a run that ERRORed in the window and was repaired/finished
    today: F-06 pre-filtered to terminal rows ending in the window, the verify
    template windows on the run's LAST period. F-06 now uses the template's
    per-run definition (latest period's state; window on MAX(period_end_time))."""
    sql = next(q for q in FACTS_PACK.queries if q.query_id == "F-06").sql_template
    assert "MAX_BY(t.result_state, t.period_end_time) AS final_result_state" in sql
    assert "HAVING MAX(t.period_end_time) >= DATEADD(DAY, -30, CURRENT_DATE())" in sql
    assert "AND MAX(t.period_end_time) < CURRENT_DATE()" in sql
    # Periods from 3 days before the window (vt: DATE_SUB(start, 3)).
    assert "t.period_end_time >= DATEADD(DAY, -33, CURRENT_DATE())" in sql
    # No terminal-row pre-filter before the per-run collapse.
    assert "WHERE t.result_state IS NOT NULL" not in sql
    for col in ("window_start", "window_end", "failed_state_runs", "error_runs",
                "timed_out_runs"):
        assert f"AS {col}" in sql, col
