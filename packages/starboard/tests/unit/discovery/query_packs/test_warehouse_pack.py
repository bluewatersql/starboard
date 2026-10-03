# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the warehouse query pack (expert metric framings, D2).

Covers:
- Pack construction and ``required_tables`` naming real ``system.*`` tables
- Template rendering with test params (no unfilled ``{placeholders}``)
- ``create_default_registry()`` includes the warehouse pack and the SQL/DBSQL
  route resolves to it
- Utilization-band and query-load-bucket CASE logic (via the reference
  classifiers that mirror the SQL) classify fixture rows into the right bands
- Client-app-mix classification
- Governance: no internal namespaces / ``go/`` links / dollar columns / finance
  wording in any query in the pack
"""

from __future__ import annotations

import collections
import re

import pytest
from starboard.discovery.query_packs.registry import (
    PRODUCT_TO_DOMAIN_PACKS,
    create_default_registry,
)
from starboard.discovery.query_packs.warehouse import (
    OPTIMAL_MAX,
    STARVED_QUEUED_PCT_MIN,
    UNDER_UTILIZED_MAX,
    WAREHOUSE_PACK,
    classify_client_app,
    classify_load_bucket,
    classify_utilization_band,
)
from starboard_core.domain.models.discovery.query import QueryCategory


def _render(sql: str, lookback: int = 30, result_limit: int = 50) -> str:
    """Mirror QueryPackExecutor._render_sql (defaultdict format_map)."""
    return sql.format_map(
        collections.defaultdict(
            str, {"lookback_days": lookback, "result_limit": result_limit}
        )
    )


class TestWarehousePackStructure:
    def test_pack_constructs(self):
        assert WAREHOUSE_PACK.pack_id == "warehouse"
        assert WAREHOUSE_PACK.domain == "warehouse"
        assert len(WAREHOUSE_PACK.queries) >= 5

    def test_required_tables_are_real_system_tables(self):
        allowed = {
            "system.compute.warehouse_events",
            "system.query.history",
            "system.compute.warehouses",  # warehouse_type dim (LEFT-joined)
            "system.billing.usage",  # per-warehouse DBU (LEFT-joined)
        }
        for q in WAREHOUSE_PACK.queries:
            assert q.required_tables, f"{q.query_id} has no required_tables"
            for t in q.required_tables:
                assert t in allowed, f"{q.query_id} references unexpected table {t}"

    def test_all_queries_have_metadata_and_category(self):
        for q in WAREHOUSE_PACK.queries:
            assert q.metadata is not None
            assert q.metadata.summary
            assert isinstance(q.category, QueryCategory)

    def test_preview_query_history_is_optional(self):
        # Queries touching only query.history (no GA-guaranteed events table)
        # that could be absent should degrade gracefully. At minimum every
        # query that reads warehouse_events (a table that may be gated) is
        # marked required=False so a missing table degrades the query only.
        for q in WAREHOUSE_PACK.queries:
            if "system.compute.warehouse_events" in q.required_tables:
                assert q.required is False, (
                    f"{q.query_id} reads warehouse_events and must be "
                    "required=False to degrade gracefully"
                )

    def test_expected_framings_present(self):
        ids = {q.query_id for q in WAREHOUSE_PACK.queries}
        # utilization bands, auto-stop waste, load buckets, client-app mix, trends
        assert {"W-W01", "W-W02", "W-W03", "W-W04", "W-W05", "W-W06", "W-W07"}.issubset(
            ids
        )


class TestTemplateRendering:
    def test_all_templates_render_without_unfilled_placeholders(self):
        placeholder = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
        for q in WAREHOUSE_PACK.queries:
            rendered = _render(q.sql_template)
            leftover = placeholder.findall(rendered)
            assert not leftover, f"{q.query_id} has unfilled placeholders: {leftover}"

    def test_time_filtered_queries_use_lookback_param(self):
        # W-W05 uses fixed T7/T28/T91 trend windows (the framing itself), so it
        # is exempt from the shared {lookback_days} window.
        for q in WAREHOUSE_PACK.queries:
            if q.query_id == "W-W05":
                continue
            assert "{lookback_days}" in q.sql_template, (
                f"{q.query_id} must window on {{lookback_days}}"
            )

    def test_trend_query_uses_all_three_windows(self):
        trend = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W05")
        for window in ("7", "28", "91"):
            assert window in trend.sql_template, (
                f"trend query missing T{window} window"
            )


class TestWorkspaceScope:
    """Scope contract: warehouse_events / query.history are account-scoped and a
    warehouse_id is unique only within a workspace, so every query must carry
    workspace_id in its grain (else same-named warehouses across workspaces conflate,
    and a waste finding can't be tied to a workspace)."""

    def test_every_query_selects_and_groups_workspace_id(self):
        for q in WAREHOUSE_PACK.queries:
            sql = _render(q.sql_template)
            assert "workspace_id" in sql, (
                f"{q.query_id} must carry workspace_id (never conflate workspaces)"
            )

    def test_waste_query_groups_by_workspace(self):
        # W-W02 is the auto-stop-waste query the plan keys on; its final grain must be
        # (workspace_id, warehouse_id) so a waste row names its workspace.
        waste = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W02")
        assert "GROUP BY workspace_id, warehouse_id" in _render(waste.sql_template)


class TestRegistryWiring:
    def test_default_registry_includes_warehouse(self):
        registry = create_default_registry()
        assert registry.get_pack("warehouse") is not None

    def test_sql_route_resolves_to_warehouse(self):
        assert "warehouse" in PRODUCT_TO_DOMAIN_PACKS["SQL"]

    def test_selecting_sql_product_includes_warehouse(self):
        registry = create_default_registry()
        selected = registry.get_packs_for_products({"SQL"})
        assert "warehouse" in {p.pack_id for p in selected}


class TestUtilizationBandLogic:
    """The 6-band framing: Offline / No-utilization / Under-utilized / Optimal /
    High-concurrency / Resource-starved. Above Optimal the busy/running ratio only
    measures concurrency; Resource-starved requires measured capacity queueing."""

    @pytest.mark.parametrize(
        ("running_seconds", "total_queries", "ratio", "queued_pct", "expected"),
        [
            (0, 0, 0.0, None, "Offline"),
            (None, 0, 0.0, None, "Offline"),
            (3600, 0, 0.0, None, "No-utilization"),
            (3600, 5, 0.05, None, "Under-utilized"),
            (3600, 50, 0.29, None, "Under-utilized"),
            (3600, 50, 0.30, None, "Optimal"),
            (3600, 100, 0.55, 50.0, "Optimal"),  # queueing alone never lifts the band
            (3600, 100, 0.80, None, "Optimal"),
            # High ratio, no / low measured queueing -> concurrency, not starvation
            (3600, 200, 0.81, None, "High-concurrency"),
            (3600, 500, 2.72, 0.0, "High-concurrency"),
            (3600, 500, 2.72, 9.99, "High-concurrency"),
            # High ratio AND measured capacity queueing -> starved
            (3600, 500, 1.62, 10.0, "Resource-starved"),
            (3600, 500, 1.62, 45.4, "Resource-starved"),
        ],
    )
    def test_band_classification(
        self, running_seconds, total_queries, ratio, queued_pct, expected
    ):
        assert (
            classify_utilization_band(
                running_seconds=running_seconds,
                total_queries=total_queries,
                utilization_ratio=ratio,
                queued_query_pct=queued_pct,
            )
            == expected
        )

    def test_sql_contains_all_band_labels(self):
        util = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W01")
        for label in (
            "Offline",
            "No-utilization",
            "Under-utilized",
            "Optimal",
            "High-concurrency",
            "Resource-starved",
            "Serverless — pay per use",
        ):
            assert label in util.sql_template, f"band label {label!r} missing in SQL"

    def test_serverless_band_not_under_utilized(self):
        """D8: SERVERLESS warehouses must never receive the 'Under-utilized' band.

        A serverless warehouse (e.g. lab-portal with 394K queries/30d) has a low
        utilization ratio because it bills per query — the ratio is not a capacity
        signal. The SQL CASE must route SERVERLESS to 'Serverless — pay per use'
        before the ratio-based band comparisons.
        """
        util = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W01")
        sql = util.sql_template
        # SERVERLESS branches must appear before the Under-utilized threshold line
        srvless_pos = sql.find("warehouse_type = 'SERVERLESS'")
        under_pos = sql.find("THEN 'Under-utilized'")
        assert srvless_pos != -1, "W-W01 must have a SERVERLESS CASE branch"
        assert under_pos != -1, "W-W01 must still have the Under-utilized branch"
        assert srvless_pos < under_pos, (
            "SERVERLESS CASE branch must appear before 'Under-utilized' so it "
            "intercepts SERVERLESS rows before the ratio comparison"
        )

    @pytest.mark.parametrize(
        ("running_seconds", "total_queries", "ratio", "queued_pct", "warehouse_type", "expected"),
        [
            # Serverless — pay per use at any utilization ratio (not Under-utilized)
            (3600, 394932, 0.05, None, "SERVERLESS", "Serverless — pay per use"),
            (3600, 100, 0.29, None, "SERVERLESS", "Serverless — pay per use"),
            (3600, 100, 0.80, None, "SERVERLESS", "Serverless — pay per use"),
            (3600, 100, 2.0, 5.0, "SERVERLESS", "Serverless — pay per use"),
            # Serverless WITH measured queueing → Resource-starved
            (3600, 500, 1.62, 10.0, "SERVERLESS", "Resource-starved"),
            (3600, 500, 1.62, 45.4, "SERVERLESS", "Resource-starved"),
            # Classic/None with low ratio → Under-utilized (unchanged)
            (3600, 5, 0.05, None, "CLASSIC", "Under-utilized"),
            (3600, 5, 0.05, None, None, "Under-utilized"),
            # Offline / No-utilization apply to any warehouse_type
            (0, 0, None, None, "SERVERLESS", "Offline"),
            (3600, 0, None, None, "SERVERLESS", "No-utilization"),
        ],
    )
    def test_serverless_band_classification(
        self, running_seconds, total_queries, ratio, queued_pct, warehouse_type, expected
    ):
        assert (
            classify_utilization_band(
                running_seconds=running_seconds,
                total_queries=total_queries,
                utilization_ratio=ratio,
                queued_query_pct=queued_pct,
                warehouse_type=warehouse_type,
            )
            == expected
        )

    def test_sql_contains_band_thresholds(self):
        util = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W01")
        assert "0.30" in util.sql_template
        assert "0.80" in util.sql_template
        assert f"queued_query_pct, 0) >= {STARVED_QUEUED_PCT_MIN}" in util.sql_template

    def test_sql_measures_capacity_queueing(self):
        util = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W01")
        sql = _render(util.sql_template)
        assert "waiting_at_capacity_duration_ms > 0" in sql
        assert "AS queued_query_pct" in sql
        assert "AS avg_capacity_wait_secs" in sql


class TestSqlPythonBandAgreement:
    """Review fix #4: the W-W01 SQL CASE and the Python ``classify_utilization_band``
    must agree — in particular on the NULL-ratio row.

    A warehouse that was running with queries but whose utilization ratio is
    NULL (e.g. ``busy_seconds`` is NULL so ``TRY_DIVIDE`` yields NULL) must land
    in the same band from both labelers. The Python classifier returns
    ``No-utilization``; the SQL used to fall through to ``Resource-starved``
    because ``NULL < 0.30`` / ``NULL <= 0.80`` are both non-TRUE. The SQL now
    carries an explicit ``... IS NULL THEN 'No-utilization'`` branch.
    """

    @staticmethod
    def _sql_band(
        *,
        running_seconds: float | None,
        total_queries: int,
        utilization_ratio: float | None,
        queued_query_pct: float | None,
        warehouse_type: str | None = None,
    ) -> str:
        """Faithful mirror of the W-W01 SQL CASE branch order (SQL NULL semantics).

        ``COALESCE(running_seconds, 0) = 0`` -> Offline; ``COALESCE(total_queries,
        0) = 0`` -> No-utilization; ``TRY_DIVIDE(...) IS NULL`` -> No-utilization;
        SERVERLESS + queueing -> Resource-starved; SERVERLESS -> Serverless — pay per use;
        ``< 0.30`` -> Under-utilized; ``<= 0.80`` -> Optimal;
        ``COALESCE(queued_query_pct, 0) >= 10`` -> Resource-starved; else
        High-concurrency. A NULL ratio never satisfies the ``<``/``<=`` comparisons
        (SQL 3-valued logic), so without the explicit IS NULL branch it would fall
        through to the top bands.
        """
        if (running_seconds or 0) == 0:
            return "Offline"
        if (total_queries or 0) == 0:
            return "No-utilization"
        if utilization_ratio is None:
            return "No-utilization"
        if warehouse_type == "SERVERLESS":
            if (queued_query_pct if queued_query_pct is not None else 0) >= 10.0:
                return "Resource-starved"
            return "Serverless — pay per use"
        if utilization_ratio < UNDER_UTILIZED_MAX:
            return "Under-utilized"
        if utilization_ratio <= OPTIMAL_MAX:
            return "Optimal"
        if (queued_query_pct if queued_query_pct is not None else 0) >= 10.0:
            return "Resource-starved"
        return "High-concurrency"

    def test_sql_case_has_explicit_null_ratio_branch(self):
        """The W-W01 SQL must map a NULL utilization ratio to 'No-utilization'."""
        util = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W01")
        sql = util.sql_template
        # An explicit IS NULL -> 'No-utilization' branch (COALESCE would also do,
        # but the committed fix uses an IS NULL WHEN clause).
        assert "IS NULL" in sql, "W-W01 CASE must handle the NULL utilization ratio"
        null_branch = re.search(
            r"WHEN\s+TRY_DIVIDE\([^)]*\)\s+IS NULL\s+THEN\s+'No-utilization'",
            sql,
        )
        assert null_branch is not None, (
            "W-W01 must contain a `WHEN TRY_DIVIDE(...) IS NULL THEN 'No-utilization'` "
            "branch so the SQL agrees with classify_utilization_band on the NULL-ratio row"
        )

    @pytest.mark.parametrize(
        ("running_seconds", "total_queries", "ratio", "queued_pct"),
        [
            # The disagreement case: running with queries but a NULL ratio.
            (3600, 5, None, None),
            (3600, 5, None, 50.0),
            # A couple of normal band cases (both labelers already agree here).
            (0, 0, None, None),
            (3600, 0, None, None),
            (3600, 5, 0.05, None),
            (3600, 100, 0.55, None),
            # Top-band split on measured queueing (incl. NULL = unmeasured).
            (3600, 200, 0.99, None),
            (3600, 200, 2.72, 0.0),
            (3600, 200, 2.72, 9.99),
            (3600, 200, 1.62, 10.0),
            (3600, 200, 1.62, 45.4),
        ],
    )
    def test_python_and_sql_labelers_agree(
        self, running_seconds, total_queries, ratio, queued_pct
    ):
        python_band = classify_utilization_band(
            running_seconds=running_seconds,
            total_queries=total_queries,
            utilization_ratio=ratio,
            queued_query_pct=queued_pct,
        )
        sql_band = self._sql_band(
            running_seconds=running_seconds,
            total_queries=total_queries,
            utilization_ratio=ratio,
            queued_query_pct=queued_pct,
        )
        assert python_band == sql_band, (
            f"labelers disagree for running={running_seconds}, "
            f"queries={total_queries}, ratio={ratio}: "
            f"python={python_band!r} sql={sql_band!r}"
        )


class TestLoadBucketLogic:
    @pytest.mark.parametrize(
        ("count", "expected"),
        [
            (0, "0-10"),
            (9, "0-10"),
            (10, "10-100"),
            (99, "10-100"),
            (100, "100-1000"),
            (999, "100-1000"),
            (1000, "1000+"),
            (5000, "1000+"),
        ],
    )
    def test_load_bucket_classification(self, count, expected):
        assert classify_load_bucket(count) == expected

    def test_sql_contains_bucket_labels(self):
        load = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W03")
        for label in ("0-10", "10-100", "100-1000", "1000+"):
            assert label in load.sql_template


class TestClientAppMix:
    @pytest.mark.parametrize(
        ("app", "expected"),
        [
            ("Databricks SQL Dashboard", "Dashboards/BI"),
            ("Databricks Workflows", "Jobs/Workflows"),
            ("dbt", "dbt"),
            ("Databricks Notebook", "Notebooks"),
            ("Power BI", "External BI"),
            ("Tableau Desktop", "External BI"),
            ("Databricks SQL Editor", "SQL Editor"),
            ("python-sql-connector", "API/SDK"),
            (None, "Unknown"),
            ("some-random-thing", "Other"),
        ],
    )
    def test_client_app_classification(self, app, expected):
        assert classify_client_app(app) == expected

    def test_sql_groups_on_client_application(self):
        mix = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W04")
        assert "client_application" in mix.sql_template


class TestGovernance:
    """Hard requirement: harvest methodology, ship public. No internal
    namespaces, no go/ links, no dollar columns, no finance-grade wording."""

    _BANNED = (
        "centralized_system_tables",
        "fin_live_gold",
        "eng_dp_debug_tools",
        "eng_time_series_metrics",
        "eng_lumberjack",
        "eng_qpl",
        "gtm_gold",
        "gtm_silver",
        "sfdc_bronze",
        "logfood",
        "clickhouse",
        "go/",
        "cost_usd",
        "list_cost_usd",
        "pricing.default",
        "finance-grade",
    )

    def test_no_banned_tokens_in_sql(self):
        for q in WAREHOUSE_PACK.queries:
            low = q.sql_template.lower()
            for token in self._BANNED:
                assert token not in low, (
                    f"{q.query_id} SQL contains banned token {token!r}"
                )

    def test_no_banned_tokens_in_metadata_or_descriptions(self):
        for q in WAREHOUSE_PACK.queries:
            blob = " ".join(
                filter(
                    None,
                    [
                        q.name,
                        q.description,
                        q.metadata.summary if q.metadata else "",
                        q.metadata.output_hint if q.metadata else "",
                        " ".join(q.metadata.tags) if q.metadata else "",
                    ],
                )
            ).lower()
            for token in self._BANNED:
                assert token not in blob, (
                    f"{q.query_id} metadata contains banned token {token!r}"
                )

    def test_no_eng_namespace_regex(self):
        # main.eng_* internal namespaces
        pat = re.compile(r"\beng_[a-z]", re.IGNORECASE)
        for q in WAREHOUSE_PACK.queries:
            assert not pat.search(q.sql_template), (
                f"{q.query_id} references an eng_* internal namespace"
            )


def test_warehouse_findings_carry_warehouse_type() -> None:
    """W-W01 / W-W02 must expose warehouse_type so an idle finding self-qualifies
    classic-vs-serverless (idle only costs money on classic/pro — serverless
    auto-suspends). Joined from system.compute.warehouses (LEFT, so it degrades)."""
    for qid in ("W-W01", "W-W02"):
        q = next(q for q in WAREHOUSE_PACK.queries if q.query_id == qid)
        sql = _render(q.sql_template)
        assert "warehouse_type" in sql, f"{qid} must select warehouse_type"
        assert "system.compute.warehouses" in sql, f"{qid} must join the warehouse dim"


class TestPerWarehouseDbu:
    """F16: W-W01 / W-W02 must attach the warehouse's own billed DBU."""

    @staticmethod
    def _q(qid: str):
        return next(q for q in WAREHOUSE_PACK.queries if q.query_id == qid)

    @pytest.mark.parametrize("qid", ["W-W01", "W-W02"])
    def test_joins_billing_usage_by_warehouse_id(self, qid: str) -> None:
        q = self._q(qid)
        sql = _render(q.sql_template)
        assert "system.billing.usage" in q.required_tables
        assert "usage_metadata.warehouse_id IS NOT NULL" in sql
        assert "AS warehouse_dbus" in sql
        assert "LEFT JOIN wh_dbus" in sql
        # workspace-scoped: the DBU CTE must group by workspace as well as warehouse
        assert "GROUP BY workspace_id, usage_metadata.warehouse_id" in sql
        # billing lookback uses the shared window
        assert "usage_date >= DATEADD(DAY, -30, CURRENT_DATE())" in sql

    @pytest.mark.parametrize("qid", ["W-W01", "W-W02"])
    def test_full_day_window_excludes_today(self, qid: str) -> None:
        """C2: W-W01 warehouse_dbus included today's partial day (35,771.91 vs
        vt-warehouse-dbu 34,820.7 on the same 30 full days). Every source in
        W-W01 / W-W02 now stops at midnight, DBU only."""
        sql = _render(self._q(qid).sql_template)
        dbus_cte = sql.split("wh_dbus AS (", 1)[1].split(")\nSELECT", 1)[0]
        assert "usage_date <  CURRENT_DATE()" in dbus_cte
        assert "usage_unit = 'DBU'" in dbus_cte
        events_cte = sql.split("FROM system.compute.warehouse_events", 1)[1].split("),", 1)[0]
        assert "event_time <  CURRENT_DATE()" in events_cte
        assert "start_time <  CURRENT_DATE()" in sql
        # Open intervals close at midnight, not "now".
        assert "CURRENT_TIMESTAMP()" not in sql

    @pytest.mark.parametrize("qid", ["W-W01", "W-W02"])
    def test_billing_dependency_degrades_gracefully(self, qid: str) -> None:
        assert self._q(qid).required is False

    def test_waste_query_emits_estimated_idle_dbus(self) -> None:
        sql = _render(self._q("W-W02").sql_template)
        assert "AS est_idle_dbus" in sql
        # honest labelling: it is an estimate, list-price DBU, not a measurement
        assert "ESTIMATE" in sql
        assert "TRY_DIVIDE" in sql  # no divide-by-zero on zero running seconds

    def test_est_idle_dbus_capped_and_null_for_serverless(self) -> None:
        sql = _render(self._q("W-W02").sql_template)
        # serverless auto-suspends: no apportioned idle DBU
        # NULL unless the type is CONFIRMED classic/pro: an unknown type (LEFT-joined
        # dim row missing) must not fall through to an estimate.
        assert (
            "WHEN w.warehouse_type IS NULL OR w.warehouse_type NOT IN ('CLASSIC', 'PRO') THEN NULL"
            in sql
        )
        # never exceeds the warehouse's own billed DBU
        assert "LEAST(\n        MAX(d.warehouse_dbus)," in sql

    def test_no_dollar_columns(self) -> None:
        for qid in ("W-W01", "W-W02", "W-W07"):
            assert "_usd" not in _render(self._q(qid).sql_template).lower()


class TestRunningIntervals:
    """W2: running intervals must be bounded by the NEXT event of ANY type.

    Filtering to running-state events before ``LEAD`` stretched each interval across
    STOPPING/STOPPED time to the next start, so every warehouse showed ~the whole
    window as running and est_idle_dbus exceeded the warehouse's billed DBU.
    """

    @staticmethod
    def _q(qid: str):
        return next(q for q in WAREHOUSE_PACK.queries if q.query_id == qid)

    @pytest.mark.parametrize("qid", ["W-W01", "W-W02"])
    def test_lead_runs_over_all_events_before_state_filter(self, qid: str) -> None:
        sql = _render(self._q(qid).sql_template)
        events_cte = sql.split("FROM system.compute.warehouse_events", 1)[1]
        events_cte = events_cte.split("),", 1)[0]
        # The CTE that computes LEAD only windows on time — no event_type filter.
        assert "event_type IN" not in events_cte, (
            f"{qid}: event_type must not be filtered before LEAD(event_time)"
        )
        assert "LEAD(event_time)" in sql.split("FROM system.compute.warehouse_events", 1)[0]
        # ...and the running-state filter is applied after, on the paired intervals.
        assert "'STARTING', 'RUNNING', 'SCALED_UP', 'SCALED_DOWN'" in sql

    def test_w02_intervals_start_on_running_states_from_events_cte(self) -> None:
        sql = _render(self._q("W-W02").sql_template)
        ri = sql.split("running_intervals AS (", 1)[1].split("),", 1)[0]
        assert "FROM events" in ri
        assert "next_event_time AS interval_end" in ri
        assert "event_type IN ('STARTING', 'RUNNING', 'SCALED_UP', 'SCALED_DOWN')" in ri


class TestConfigHistory:
    """W31: W-W07 reports current warehouse config + change history."""

    @staticmethod
    def _q():
        return next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W07")

    def test_reads_only_warehouse_dim_and_degrades(self) -> None:
        q = self._q()
        assert q.required_tables == ("system.compute.warehouses",)
        assert q.required is False
        assert q.domain == "warehouse"

    def test_dedupes_versions_and_picks_latest(self) -> None:
        sql = _render(self._q().sql_template)
        assert "SELECT DISTINCT" in sql  # replicated identical versions collapse
        assert "tags" not in sql  # MAP column can't be DISTINCT-ed
        assert "ROW_NUMBER() OVER" in sql
        assert "ORDER BY change_time DESC" in sql
        assert "version_rank = 1" in sql
        assert "GROUP BY workspace_id, warehouse_id" in sql

    def test_emits_config_and_change_counts(self) -> None:
        sql = _render(self._q().sql_template)
        for col in (
            "AS warehouse_name",
            "AS warehouse_type",
            "AS warehouse_size",
            "AS min_clusters",
            "AS max_clusters",
            "AS auto_stop_minutes",
            "AS last_change_time",
            "AS size_changes_in_window",
            "AS cluster_changes_in_window",
            "AS auto_stop_changes_in_window",
            "AS recent_changes",
        ):
            assert col in sql, f"W-W07 missing {col!r}"
        # change detection compares to the previous version, NULL-safe
        assert "LAG(warehouse_size)" in sql
        assert "IS DISTINCT FROM prev_size" in sql
        assert "change_time >= DATEADD(DAY, -30, CURRENT_DATE())" in sql


class TestWorkloadDrivers:
    """F21(b): W-W06 names the sources/apps driving each warehouse (bounded scan)."""

    @staticmethod
    def _q():
        return next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W06")

    def test_registered_and_reads_only_query_history(self) -> None:
        q = self._q()
        assert q.required_tables == ("system.query.history",)
        assert q.domain == "warehouse"

    def test_per_warehouse_grain_with_workspace(self) -> None:
        sql = _render(self._q().sql_template)
        assert "workspace_id" in sql and "compute.warehouse_id" in sql
        assert "PARTITION BY workspace_id, warehouse_id" in sql

    def test_exposes_source_and_client_app_and_metrics(self) -> None:
        sql = _render(self._q().sql_template)
        for token in (
            "query_source.job_info.job_id",
            "query_source.dashboard_id",
            "query_source.genie_space_id",
            "query_source.notebook_id",
            "client_application",
            "read_bytes",
            "total_duration_ms",
            "AS query_count",
            "AS total_read_bytes",
            "AS total_duration_secs",
            "AS pct_of_warehouse_duration",
        ):
            assert token in sql, f"W-W06 missing {token!r}"

    def test_scan_bounded_to_seven_days(self) -> None:
        # W21: the bound is declarative (executor clamps {lookback_days} to
        # min(lookback, 7)) so the effective window is reported, not hidden in SQL.
        q = self._q()
        assert q.max_lookback_days == 7
        assert "LEAST(" not in q.sql_template
        assert "DATEADD(DAY, -{lookback_days}, CURRENT_DATE())" in q.sql_template

    def test_emits_effective_window_days(self) -> None:
        sql = _render(self._q().sql_template, lookback=7)
        assert "7                                AS window_days" in sql
        assert "  window_days,\n" in sql

    def test_no_user_identity_columns(self) -> None:
        sql = _render(self._q().sql_template).lower()
        for col in ("executed_by", "executed_as", "user_name", "run_as"):
            assert col not in sql, f"W-W06 must not read identity column {col!r}"

    def test_top_n_per_warehouse(self) -> None:
        sql = _render(self._q().sql_template)
        assert "ROW_NUMBER() OVER" in sql and "driver_rank <= 5" in sql

    def test_exec_share_and_scan_intensity_columns(self) -> None:
        # Round-7 (OPP-WH-SCAN): execution time excludes capacity wait, so a queue
        # victim cannot read as the driver; drivers are ranked by it.
        sql = _render(self._q().sql_template)
        assert "total_duration_ms - COALESCE(waiting_at_capacity_duration_ms, 0)" in sql
        for token in (
            "AS total_exec_secs",
            "AS pct_of_warehouse_exec",
            "AS read_gb_per_query",
            "AS avg_read_gb_per_query",  # the catalog's canonical OPP-WH-SCAN metric name
            "total_read_bytes / 1e9 / NULLIF(query_count, 0)",
            "ORDER BY total_exec_secs DESC NULLS LAST",
        ):
            assert token in sql, f"W-W06 missing {token!r}"

    def test_per_warehouse_tenancy_and_queueing_columns(self) -> None:
        # distinct_sources is computed over every source on the warehouse (window over
        # agg, before the top-5 cut) so a single-tenant ingestion warehouse reads 1.
        sql = _render(self._q().sql_template)
        assert "SIZE(COLLECT_SET(" in sql and ") OVER w) AS distinct_sources" in sql
        assert "WINDOW w AS (PARTITION BY workspace_id, warehouse_id)" in sql
        assert sql.index("AS distinct_sources") < sql.index("WHERE driver_rank <= 5")
        assert "COUNT_IF(waiting_at_capacity_duration_ms > 0)" in sql
        assert "AS warehouse_queued_pct" in sql
        # material_sources discounts idle saved queries next to a single connector.
        assert "COUNT_IF(pct_of_warehouse_exec >= 5) OVER (" in sql
        assert "AS material_sources" in sql
        assert sql.index("AS material_sources") < sql.index("WHERE driver_rank <= 5")
        final_select = sql.rsplit("FROM ctx", 1)[0].rsplit("SELECT", 1)[1]
        for col in (
            "distinct_sources",
            "material_sources",
            "warehouse_queued_pct",
            "pct_of_warehouse_exec",
            "read_gb_per_query",
            "pct_of_warehouse_duration",
        ):
            assert col in final_select, f"W-W06 row missing {col!r}"


class TestW02FullDayWindow:
    """D9: W-W02 must use a full-day window to make est_idle_dbus deterministic.

    The 22/96/103 instability came from:
    (a) partial-today billing rows growing throughout the day (warehouse_dbus fluctuates)
    (b) COALESCE(interval_end, CURRENT_TIMESTAMP()) stretching open intervals by
        seconds elapsed since the query ran (running_seconds fluctuates).
    Fix: cap all three sides at CURRENT_DATE() so the query covers exactly N full days.
    """

    @staticmethod
    def _q():
        return next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W02")

    def test_events_filter_excludes_today(self) -> None:
        """Events CTE must filter event_time < CURRENT_DATE() (full-day window)."""
        sql = _render(self._q().sql_template)
        assert "AND event_time <  CURRENT_DATE()" in sql, (
            "W-W02 events CTE must exclude today's events to make running_seconds "
            "deterministic (full-day window)"
        )

    def test_no_current_timestamp_in_w02(self) -> None:
        """W-W02 must not use CURRENT_TIMESTAMP() for interval or billing windows.

        CURRENT_TIMESTAMP() causes est_idle_dbus to change with every query run
        (open intervals grow by seconds elapsed). CURRENT_DATE() closes them at
        midnight, which is the same value for all runs on the same day.
        """
        sql = _render(self._q().sql_template)
        assert "CURRENT_TIMESTAMP()" not in sql, (
            "W-W02 must use CURRENT_DATE() (not CURRENT_TIMESTAMP()) so "
            "est_idle_dbus is deterministic across multiple runs on the same day"
        )

    def test_interval_datediff_uses_current_date(self) -> None:
        """Open-interval DATEDIFF must cap at CURRENT_DATE(), not CURRENT_TIMESTAMP()."""
        sql = _render(self._q().sql_template)
        assert "COALESCE(ri.interval_end, CURRENT_DATE())" in sql, (
            "W-W02 interval_seconds must use COALESCE(interval_end, CURRENT_DATE()) "
            "so the open-interval cap is deterministic"
        )

    def test_billing_excludes_today(self) -> None:
        """wh_dbus CTE must add AND usage_date < CURRENT_DATE() (full-day billing)."""
        sql = _render(self._q().sql_template)
        assert "AND usage_date <  CURRENT_DATE()" in sql, (
            "W-W02 billing CTE must exclude today's partial usage_date rows so "
            "warehouse_dbus covers the same N full days as running_seconds"
        )

    def test_query_join_excludes_today(self) -> None:
        """Queries counted in interval_activity must be bounded to < CURRENT_DATE()."""
        sql = _render(self._q().sql_template)
        assert "AND qh.start_time <  CURRENT_DATE()" in sql, (
            "W-W02 interval_activity LEFT JOIN must exclude today's queries to "
            "match the events-side day boundary"
        )

    def test_order_by_has_deterministic_tiebreaker(self) -> None:
        """ORDER BY must include warehouse_id for deterministic row ordering."""
        sql = _render(self._q().sql_template)
        assert "ORDER BY est_idle_dbus DESC NULLS LAST, idle_running_hours DESC, warehouse_id" in sql, (
            "W-W02 ORDER BY must end with warehouse_id as a tiebreaker so rows "
            "with equal est_idle_dbus / idle_running_hours are in stable order"
        )
