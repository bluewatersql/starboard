# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for QueryPackRegistry and conditional execution logic.

Tests cover:
- Registry construction and pack lookup
- Conditional filtering by active products
- ALWAYS_RUN_PACKS behavior
- Include/exclude overrides
- Default registry factory
"""

import pytest
from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery
from starboard.discovery.query_packs.registry import (
    ALWAYS_RUN_PACKS,
    PRODUCT_TO_DOMAIN_PACKS,
    QueryPackRegistry,
    create_default_registry,
)


def _make_pack(pack_id: str, gating: frozenset[str] = frozenset()) -> QueryPack:
    """Create a minimal QueryPack for testing."""
    return QueryPack(
        pack_id=pack_id,
        domain=pack_id,
        name=f"Test {pack_id}",
        description="Test",
        queries=(
            SystemQuery(
                query_id=f"{pack_id}-01",
                name="Test query",
                description="Test",
                sql_template="SELECT 1",
                required_tables=("system.billing.usage",),
                domain=pack_id,
            ),
        ),
        gating_products=gating,
    )


class TestQueryPackRegistry:
    def test_construction(self):
        r = QueryPackRegistry(packs=(_make_pack("a"), _make_pack("b")))
        assert r.pack_count == 2

    def test_get_pack(self):
        r = QueryPackRegistry(packs=(_make_pack("billing"),))
        assert r.get_pack("billing") is not None
        assert r.get_pack("nonexistent") is None

    def test_all_packs(self):
        packs = (_make_pack("a"), _make_pack("b"), _make_pack("c"))
        r = QueryPackRegistry(packs=packs)
        assert len(r.all_packs) == 3


class TestConditionalFiltering:
    @pytest.fixture()
    def registry(self) -> QueryPackRegistry:
        return QueryPackRegistry(
            packs=(
                _make_pack("audit"),
                _make_pack("billing"),
                _make_pack("governance"),
                _make_pack("migration"),
                _make_pack("jobs", frozenset({"JOBS"})),
                _make_pack("compute", frozenset({"ALL_PURPOSE", "INTERACTIVE"})),
                _make_pack("ml", frozenset({"MODEL_SERVING"})),
                _make_pack("apps", frozenset({"APPS"})),
            )
        )

    def test_always_run_packs_included(self, registry: QueryPackRegistry):
        result = registry.get_packs_for_products(set())
        pack_ids = {p.pack_id for p in result}
        for always_id in ALWAYS_RUN_PACKS:
            if registry.get_pack(always_id):
                assert always_id in pack_ids

    def test_product_gates_jobs(self, registry: QueryPackRegistry):
        result = registry.get_packs_for_products({"JOBS"})
        pack_ids = {p.pack_id for p in result}
        assert "jobs" in pack_ids

    def test_product_gates_compute(self, registry: QueryPackRegistry):
        result = registry.get_packs_for_products({"ALL_PURPOSE"})
        pack_ids = {p.pack_id for p in result}
        assert "compute" in pack_ids

    def test_no_ml_without_product(self, registry: QueryPackRegistry):
        result = registry.get_packs_for_products({"JOBS"})
        pack_ids = {p.pack_id for p in result}
        assert "ml" not in pack_ids

    def test_include_override(self, registry: QueryPackRegistry):
        result = registry.get_packs_for_products(set(), include=["ml"])
        pack_ids = {p.pack_id for p in result}
        assert "ml" in pack_ids

    def test_exclude_override(self, registry: QueryPackRegistry):
        result = registry.get_packs_for_products(set(), exclude=["billing"])
        pack_ids = {p.pack_id for p in result}
        assert "billing" not in pack_ids

    def test_exclude_overrides_always_run(self, registry: QueryPackRegistry):
        result = registry.get_packs_for_products(set(), exclude=["governance"])
        pack_ids = {p.pack_id for p in result}
        assert "governance" not in pack_ids


class TestThresholdFiltering:
    @pytest.fixture()
    def registry(self) -> QueryPackRegistry:
        return QueryPackRegistry(
            packs=(
                _make_pack("audit"),
                _make_pack("billing"),
                _make_pack("governance"),
                _make_pack("migration"),
                _make_pack("jobs", frozenset({"JOBS"})),
                _make_pack("apps", frozenset({"APPS"})),
                _make_pack("ml", frozenset({"MODEL_SERVING"})),
            )
        )

    def test_dict_products_above_threshold(self, registry: QueryPackRegistry):
        """Products above threshold are included."""
        result = registry.get_packs_for_products(
            {"JOBS": 500.0, "APPS": 200.0}, min_dbu_threshold=10.0
        )
        pack_ids = {p.pack_id for p in result}
        assert "jobs" in pack_ids
        assert "apps" in pack_ids

    def test_dict_products_below_threshold_skipped(self, registry: QueryPackRegistry):
        """Products below threshold are excluded from pack selection."""
        result = registry.get_packs_for_products(
            {"JOBS": 500.0, "APPS": 5.0}, min_dbu_threshold=10.0
        )
        pack_ids = {p.pack_id for p in result}
        assert "jobs" in pack_ids
        assert "apps" not in pack_ids

    def test_dict_product_at_exact_threshold(self, registry: QueryPackRegistry):
        """Product exactly at threshold is included."""
        result = registry.get_packs_for_products(
            {"JOBS": 10.0}, min_dbu_threshold=10.0
        )
        pack_ids = {p.pack_id for p in result}
        assert "jobs" in pack_ids

    def test_all_products_below_threshold(self, registry: QueryPackRegistry):
        """All products below threshold still returns always-run packs."""
        result = registry.get_packs_for_products(
            {"JOBS": 1.0, "APPS": 2.0}, min_dbu_threshold=10.0
        )
        pack_ids = {p.pack_id for p in result}
        assert "jobs" not in pack_ids
        assert "apps" not in pack_ids
        for always_id in ALWAYS_RUN_PACKS:
            if registry.get_pack(always_id):
                assert always_id in pack_ids

    def test_threshold_zero_disables_filtering(self, registry: QueryPackRegistry):
        """Threshold of 0 means no filtering."""
        result = registry.get_packs_for_products(
            {"JOBS": 0.001, "APPS": 0.001}, min_dbu_threshold=0.0
        )
        pack_ids = {p.pack_id for p in result}
        assert "jobs" in pack_ids
        assert "apps" in pack_ids

    def test_set_input_ignores_threshold(self, registry: QueryPackRegistry):
        """Legacy set input works and ignores threshold."""
        result = registry.get_packs_for_products(
            {"JOBS", "APPS"}, min_dbu_threshold=99999.0
        )
        pack_ids = {p.pack_id for p in result}
        assert "jobs" in pack_ids
        assert "apps" in pack_ids

    def test_empty_dict_only_always_run(self, registry: QueryPackRegistry):
        """Empty dict returns only always-run packs."""
        result = registry.get_packs_for_products({}, min_dbu_threshold=10.0)
        pack_ids = {p.pack_id for p in result}
        assert "jobs" not in pack_ids
        assert "apps" not in pack_ids


class TestProductMapping:
    def test_all_products_have_packs(self):
        for product, packs in PRODUCT_TO_DOMAIN_PACKS.items():
            assert len(packs) > 0, f"Product {product} maps to empty pack list"

    def test_known_products(self):
        assert "JOBS" in PRODUCT_TO_DOMAIN_PACKS
        assert "SQL" in PRODUCT_TO_DOMAIN_PACKS
        assert "ALL_PURPOSE" in PRODUCT_TO_DOMAIN_PACKS
        assert "MODEL_SERVING" in PRODUCT_TO_DOMAIN_PACKS
        assert "DLT" in PRODUCT_TO_DOMAIN_PACKS
        assert "DATA_SHARING" in PRODUCT_TO_DOMAIN_PACKS
        assert "AI_GATEWAY" in PRODUCT_TO_DOMAIN_PACKS

    def test_always_run_packs_nonempty(self):
        assert len(ALWAYS_RUN_PACKS) >= 3


class TestDefaultRegistry:
    def test_creates_all_packs(self):
        registry = create_default_registry()
        assert registry.pack_count == 20

    def test_audit_pack_present(self):
        registry = create_default_registry()
        audit = registry.get_pack("audit")
        assert audit is not None
        assert len(audit.queries) == 1

    def test_all_queries_have_sql_template(self):
        registry = create_default_registry()
        for pack in registry.all_packs:
            for query in pack.queries:
                assert query.sql_template, f"{query.query_id} has empty SQL template"

    def test_all_queries_have_required_tables(self):
        registry = create_default_registry()
        for pack in registry.all_packs:
            for query in pack.queries:
                assert len(query.required_tables) > 0, (
                    f"{query.query_id} has no required_tables"
                )

    def test_sql_templates_use_lookback_parameter(self):
        """All queries with time-based filtering should use {lookback_days}."""
        registry = create_default_registry()
        skip_ids = {"N-L03", "N-DT01"}
        for pack in registry.all_packs:
            for query in pack.queries:
                if query.query_id in skip_ids:
                    continue
                if "INTERVAL" in query.sql_template:
                    assert "{lookback_days}" in query.sql_template, (
                        f"{query.query_id} uses INTERVAL but not {{lookback_days}}"
                    )

    def test_no_dollar_columns_in_sql(self):
        """Verify DBU-only policy: no cost_usd or list_cost_usd in any SQL."""
        registry = create_default_registry()
        for pack in registry.all_packs:
            for query in pack.queries:
                sql_lower = query.sql_template.lower()
                assert "cost_usd" not in sql_lower, (
                    f"{query.query_id} contains 'cost_usd'"
                )
                assert "list_cost_usd" not in sql_lower, (
                    f"{query.query_id} contains 'list_cost_usd'"
                )
                assert "pricing.default" not in sql_lower, (
                    f"{query.query_id} contains 'pricing.default'"
                )
