# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the Phase-2 D5 query packs.

Covers the two net-new public ``system.*`` packs:
- compute reliability / right-sizing (``compute_reliability``)
- column-level lineage (``column_lineage``)

Verifies: both packs load in ``create_default_registry``; ``required_tables``
name real ``system.*`` tables; templates render with no unfilled placeholders;
Preview tables (``system.compute.instance_events``) are ``required=False``; and
the DBU-only / no-internal-namespace governance guard holds for the new SQL.
"""

from __future__ import annotations

import collections
import re

from starboard.discovery.query_packs.column_lineage import COLUMN_LINEAGE_PACK
from starboard.discovery.query_packs.compute_reliability import (
    COMPUTE_RELIABILITY_PACK,
)
from starboard.discovery.query_packs.registry import (
    PRODUCT_TO_DOMAIN_PACKS,
    create_default_registry,
)
from starboard_core.domain.models.discovery.query import QueryPack

_NEW_PACKS = [COMPUTE_RELIABILITY_PACK, COLUMN_LINEAGE_PACK]

# Real, documented tables the two packs are allowed to read (verified against
# current Databricks system-table docs, 2026-08-26).
_ALLOWED_TABLES = {
    "system.compute.instance_events",  # Public Preview
    "system.compute.node_timeline",
    "system.compute.node_types",
    "system.compute.warehouse_events",
    "system.access.column_lineage",
}

# Internal namespaces / identifiers that must never appear in public packs.
_FORBIDDEN_NAMESPACES = (
    "centralized_system_tables",
    "fin_live_gold",
    "logfood",
    "clickhouse",
    "hmr_stack_hash",
    "go/",
)


def _render(sql_template: str) -> str:
    """Render a template the way the executor does (defaultdict format_map)."""
    params = {"lookback_days": 30, "result_limit": 50}
    return sql_template.format_map(collections.defaultdict(str, params))


class TestPacksConstruct:
    def test_packs_are_query_packs(self):
        assert isinstance(COMPUTE_RELIABILITY_PACK, QueryPack)
        assert isinstance(COLUMN_LINEAGE_PACK, QueryPack)

    def test_pack_ids(self):
        assert COMPUTE_RELIABILITY_PACK.pack_id == "compute_reliability"
        assert COLUMN_LINEAGE_PACK.pack_id == "column_lineage"

    def test_packs_have_queries(self):
        assert len(COMPUTE_RELIABILITY_PACK.queries) >= 2
        assert len(COLUMN_LINEAGE_PACK.queries) >= 2


class TestRequiredTablesAreReal:
    def test_required_tables_are_documented(self):
        for pack in _NEW_PACKS:
            for query in pack.queries:
                assert query.required_tables, f"{query.query_id} has no required_tables"
                for table in query.required_tables:
                    assert table in _ALLOWED_TABLES, (
                        f"{query.query_id} reads undocumented table {table!r}"
                    )

    def test_compute_reliability_covers_intended_tables(self):
        tables = {
            t for q in COMPUTE_RELIABILITY_PACK.queries for t in q.required_tables
        }
        assert "system.compute.instance_events" in tables
        assert "system.compute.node_timeline" in tables
        assert "system.compute.node_types" in tables
        assert "system.compute.warehouse_events" in tables

    def test_column_lineage_reads_column_lineage_table(self):
        tables = {t for q in COLUMN_LINEAGE_PACK.queries for t in q.required_tables}
        assert tables == {"system.access.column_lineage"}


class TestTemplatesRender:
    def test_no_unfilled_placeholders(self):
        for pack in _NEW_PACKS:
            for query in pack.queries:
                rendered = _render(query.sql_template)
                leftovers = re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", rendered)
                assert not leftovers, (
                    f"{query.query_id} has unfilled placeholders: {leftovers}"
                )

    def test_templates_reference_their_tables(self):
        for pack in _NEW_PACKS:
            for query in pack.queries:
                rendered = _render(query.sql_template)
                for table in query.required_tables:
                    assert table in rendered, (
                        f"{query.query_id} declares {table} but does not query it"
                    )


class TestPreviewTablesDegradeGracefully:
    def test_instance_events_queries_are_optional(self):
        """Public Preview ``instance_events`` queries must be required=False."""
        for query in COMPUTE_RELIABILITY_PACK.queries:
            if "system.compute.instance_events" in query.required_tables:
                assert query.required is False, (
                    f"{query.query_id} reads a Preview table and must be "
                    "required=False to degrade gracefully"
                )

    def test_ga_table_queries_stay_required(self):
        """Queries that only read GA tables should remain required=True."""
        for query in COMPUTE_RELIABILITY_PACK.queries:
            if "system.compute.instance_events" not in query.required_tables:
                assert query.required is True, (
                    f"{query.query_id} reads only GA tables; should be required=True"
                )

    def test_lineage_respects_one_year_retention(self):
        """column_lineage retains a rolling 1-year window; lookback must clamp."""
        for query in COLUMN_LINEAGE_PACK.queries:
            assert query.max_lookback_days is not None
            assert query.max_lookback_days <= 365


class TestRegistryRegistration:
    def test_both_packs_registered(self):
        registry = create_default_registry()
        assert registry.get_pack("compute_reliability") is not None
        assert registry.get_pack("column_lineage") is not None

    def test_compute_reliability_route_resolves(self):
        registry = create_default_registry()
        for product in ("ALL_PURPOSE", "INTERACTIVE"):
            selected = {p.pack_id for p in registry.get_packs_for_products({product})}
            assert "compute_reliability" in selected, (
                f"product {product} should select compute_reliability"
            )

    def test_column_lineage_route_resolves(self):
        registry = create_default_registry()
        # Column lineage routes off at least one governance-signalling product.
        lineage_products = [
            p
            for p, packs in PRODUCT_TO_DOMAIN_PACKS.items()
            if "column_lineage" in packs
        ]
        assert lineage_products, "no product routes to column_lineage"
        for product in lineage_products:
            selected = {p.pack_id for p in registry.get_packs_for_products({product})}
            assert "column_lineage" in selected


class TestGovernanceGuard:
    def test_no_dollar_columns_in_new_sql(self):
        """DBU-only policy: no cost_usd/list_cost_usd/pricing.default in new SQL."""
        for pack in _NEW_PACKS:
            for query in pack.queries:
                sql_lower = query.sql_template.lower()
                assert "cost_usd" not in sql_lower, f"{query.query_id} has cost_usd"
                assert "list_cost_usd" not in sql_lower, (
                    f"{query.query_id} has list_cost_usd"
                )
                assert "pricing.default" not in sql_lower, (
                    f"{query.query_id} has pricing.default"
                )

    def test_no_internal_namespaces(self):
        for pack in _NEW_PACKS:
            for query in pack.queries:
                blob = (query.sql_template + query.description + query.name).lower()
                for needle in _FORBIDDEN_NAMESPACES:
                    assert needle not in blob, (
                        f"{query.query_id} contains forbidden namespace {needle!r}"
                    )

    def test_only_public_system_tables(self):
        """Every table referenced is under the public ``system.`` namespace."""
        for pack in _NEW_PACKS:
            for query in pack.queries:
                for table in query.required_tables:
                    assert table.startswith("system."), (
                        f"{query.query_id} reads non-public table {table!r}"
                    )
