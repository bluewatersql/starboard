# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the warehouse query pack (LogFood metric framings, D2).

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
        assert {"W-W01", "W-W02", "W-W03", "W-W04", "W-W05"}.issubset(ids)


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
    """The 5-band framing: Offline / No-utilization / Under-utilized /
    Optimal / Resource-starved."""

    @pytest.mark.parametrize(
        ("running_seconds", "total_queries", "ratio", "expected"),
        [
            (0, 0, 0.0, "Offline"),
            (None, 0, 0.0, "Offline"),
            (3600, 0, 0.0, "No-utilization"),
            (3600, 5, 0.05, "Under-utilized"),
            (3600, 50, 0.29, "Under-utilized"),
            (3600, 50, 0.30, "Optimal"),
            (3600, 100, 0.55, "Optimal"),
            (3600, 100, 0.80, "Optimal"),
            (3600, 200, 0.81, "Resource-starved"),
            (3600, 500, 0.99, "Resource-starved"),
        ],
    )
    def test_band_classification(
        self, running_seconds, total_queries, ratio, expected
    ):
        assert (
            classify_utilization_band(
                running_seconds=running_seconds,
                total_queries=total_queries,
                utilization_ratio=ratio,
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
            "Resource-starved",
        ):
            assert label in util.sql_template, f"band label {label!r} missing in SQL"

    def test_sql_contains_band_thresholds(self):
        util = next(q for q in WAREHOUSE_PACK.queries if q.query_id == "W-W01")
        assert "0.30" in util.sql_template
        assert "0.80" in util.sql_template


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
    ) -> str:
        """Faithful mirror of the W-W01 SQL CASE branch order (SQL NULL semantics).

        ``COALESCE(running_seconds, 0) = 0`` -> Offline; ``COALESCE(total_queries,
        0) = 0`` -> No-utilization; ``TRY_DIVIDE(...) IS NULL`` -> No-utilization;
        ``< 0.30`` -> Under-utilized; ``<= 0.80`` -> Optimal; else Resource-starved.
        A NULL ratio never satisfies the ``<``/``<=`` comparisons (SQL 3-valued
        logic), so without the explicit IS NULL branch it would fall to ELSE.
        """
        if (running_seconds or 0) == 0:
            return "Offline"
        if (total_queries or 0) == 0:
            return "No-utilization"
        if utilization_ratio is None:
            return "No-utilization"
        if utilization_ratio < UNDER_UTILIZED_MAX:
            return "Under-utilized"
        if utilization_ratio <= OPTIMAL_MAX:
            return "Optimal"
        return "Resource-starved"

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
        ("running_seconds", "total_queries", "ratio"),
        [
            # The disagreement case: running with queries but a NULL ratio.
            (3600, 5, None),
            # A couple of normal band cases (both labelers already agree here).
            (0, 0, None),
            (3600, 0, None),
            (3600, 5, 0.05),
            (3600, 100, 0.55),
            (3600, 200, 0.99),
        ],
    )
    def test_python_and_sql_labelers_agree(
        self, running_seconds, total_queries, ratio
    ):
        python_band = classify_utilization_band(
            running_seconds=running_seconds,
            total_queries=total_queries,
            utilization_ratio=ratio,
        )
        sql_band = self._sql_band(
            running_seconds=running_seconds,
            total_queries=total_queries,
            utilization_ratio=ratio,
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
