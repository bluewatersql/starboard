# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the facts query pack (F-01 … F-12) feeding ``data.facts`` (B1)."""

from __future__ import annotations

import re

import pytest
from starboard.discovery.executor import make_render
from starboard.discovery.query_packs.facts import FACTS_PACK
from starboard.discovery.query_packs.registry import (
    ALWAYS_RUN_PACKS,
    create_default_registry,
)
from starboard_core.engagement.jobruns import FAILED_STATES
from starboard_x.discovery._facts import _FIELD_SOURCES

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

_IDS = tuple(f"F-{i:02d}" for i in range(1, 13))
#: The facts window follows --lookback-days (H1(a)): pin a short and the default one.
_LOOKBACKS = (7, 30)


def _render(sql: str, lookback_days: int = 30) -> str:
    return make_render(lookback_days, 50)(sql)


def _f(qid: str, lookback_days: int) -> str:
    return _render(next(q for q in FACTS_PACK.queries if q.query_id == qid).sql_template,
                   lookback_days)


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

    @pytest.mark.parametrize("lookback", _LOOKBACKS)
    def test_renders_without_placeholders(self, lookback: int) -> None:
        for q in FACTS_PACK.queries:
            sql = _render(q.sql_template, lookback)
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

    @pytest.mark.parametrize("lookback", _LOOKBACKS)
    def test_full_day_window_excludes_today(self, lookback: int) -> None:
        for qid in ("F-01", "F-04", "F-05", "F-07", "F-08", "F-11"):
            sql = _f(qid, lookback)
            assert f"usage_date >= DATEADD(DAY, -{lookback}, CURRENT_DATE())" in sql, qid
            assert "usage_date < CURRENT_DATE()" in sql, qid
        f03 = _f("F-03", lookback)
        # The window plus the 7-day step-change baseline before it.
        assert f"DATEADD(DAY, -{lookback + 7}, CURRENT_DATE())" in f03
        assert (f"u.usage_date >= DATEADD(DAY, -{lookback}, CURRENT_DATE()) AS in_window"
                in f03)
        assert "usage_date < CURRENT_DATE()" in f03

    @pytest.mark.parametrize("lookback", _LOOKBACKS)
    def test_window_bounds_columns_follow_the_lookback(self, lookback: int) -> None:
        for qid in ("F-01", "F-06", "F-12"):
            sql = _f(qid, lookback)
            assert re.search(
                rf"DATEADD\(DAY, -{lookback}, CURRENT_DATE\(\)\)\s+AS window_start", sql
            ), qid
            assert re.search(r"DATEADD\(DAY, -1, CURRENT_DATE\(\)\)\s+AS window_end", sql), qid

    def test_window_differs_between_lookbacks(self) -> None:
        for qid in ("F-01", "F-03", "F-04", "F-05", "F-06", "F-07", "F-08", "F-11", "F-12"):
            assert _f(qid, 7) != _f(qid, 30), qid
        # Calendar months and the 7-day config-change list do not follow the lookback.
        for qid in ("F-02", "F-09", "F-10"):
            assert _f(qid, 7) == _f(qid, 30), qid

    def test_reliability_reuses_failure_states(self) -> None:
        f06 = next(q for q in FACTS_PACK.queries if q.query_id == "F-06").sql_template
        failure_sql = "(" + ", ".join(f"'{s}'" for s in FAILED_STATES) + ")"
        assert f"IN {failure_sql}" in f06
        assert "'CANCELLED'" in f06

    def test_dimensions_are_deduplicated(self) -> None:
        by_id = {q.query_id: q.sql_template for q in FACTS_PACK.queries}
        assert "QUALIFY ROW_NUMBER()" in by_id["F-04"]
        assert "QUALIFY ROW_NUMBER()" in by_id["F-05"]
        assert "SELECT DISTINCT" in by_id["F-09"]
        assert "SELECT DISTINCT" in by_id["F-10"]
        assert "SELECT DISTINCT" in by_id["F-11"]
        assert "lw.version_rank = 1" in by_id["F-11"]

    def test_f03_labelled_as_window_plus_baseline(self) -> None:
        """C3: F-03 returns the facts window plus a 7-day baseline; its metadata
        must say so, so nobody sums it as the window total."""
        f03 = next(q for q in FACTS_PACK.queries if q.query_id == "F-03")
        for text in (f03.name, f03.description, f03.metadata.output_hint):
            assert "7-day" in text and "window" in text
        assert "not a window total" in f03.description
        assert "do NOT sum" in f03.sql_template

    def test_no_fixed_thirty_day_wording(self) -> None:
        for q in FACTS_PACK.queries:
            for text in (q.name, q.description, q.metadata.summary, q.metadata.output_hint):
                assert "30" not in text and "37" not in text, (q.query_id, text)
        assert "30" not in FACTS_PACK.description

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


@pytest.mark.parametrize("lookback", _LOOKBACKS)
def test_f06_matches_vt_job_failures_run_definition(lookback: int) -> None:
    """Round-8 (gpt-6 #4): F-06 = 190 vs vt-job-failures ERROR 184 + TIMED_OUT 5.
    The gap was a run that ERRORed in the window and was repaired/finished
    today: F-06 pre-filtered to terminal rows ending in the window, the verify
    template windows on the run's LAST period. F-06 now uses the template's
    per-run definition (latest period's state; window on MAX(period_end_time))."""
    sql = _f("F-06", lookback)
    assert "MAX_BY(t.result_state, t.period_end_time) AS final_result_state" in sql
    assert f"HAVING MAX(t.period_end_time) >= DATEADD(DAY, -{lookback}, CURRENT_DATE())" in sql
    assert "AND MAX(t.period_end_time) < CURRENT_DATE()" in sql
    # Periods from 3 days before the window (vt: DATE_SUB(start, 3)).
    assert f"t.period_end_time >= DATEADD(DAY, -{lookback + 3}, CURRENT_DATE())" in sql
    # F-12 shares the same per-run collapse.
    assert f"DATEADD(DAY, -{lookback + 3}, CURRENT_DATE())" in _f("F-12", lookback)
    # No terminal-row pre-filter before the per-run collapse.
    assert "WHERE t.result_state IS NOT NULL" not in sql
    for col in ("window_start", "window_end", "failed_state_runs", "error_runs",
                "timed_out_runs"):
        assert f"AS {col}" in sql, col
