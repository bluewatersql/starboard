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
