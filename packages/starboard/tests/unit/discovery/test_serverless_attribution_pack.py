# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the serverless_attribution query pack (SVA-01…03).

Verifies pack construction, public-only tables, required_columns present in SQL,
templates render, governance (no internal namespaces, DBU-only), the workspace-scope
contract (every query carries workspace_id), and registry wiring for serverless products.
"""

from __future__ import annotations

import collections
import re

import pytest
from starboard.discovery.query_packs.registry import (
    PRODUCT_TO_DOMAIN_PACKS,
    create_default_registry,
)
from starboard.discovery.query_packs.serverless_attribution import (
    SERVERLESS_ATTRIBUTION_PACK,
)
from starboard_core.domain.models.discovery.query import QueryPack

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


def _render(sql_template: str) -> str:
    return sql_template.format_map(collections.defaultdict(str, _RENDER_PARAMS))


class TestPackConstruct:
    def test_is_query_pack(self):
        assert isinstance(SERVERLESS_ATTRIBUTION_PACK, QueryPack)

    def test_pack_id(self):
        assert SERVERLESS_ATTRIBUTION_PACK.pack_id == "serverless_attribution"

    def test_query_ids(self):
        ids = tuple(q.query_id for q in SERVERLESS_ATTRIBUTION_PACK.queries)
        assert ids == ("SVA-01", "SVA-02", "SVA-03")


class TestTablesAndColumns:
    def test_only_public_billing_usage(self):
        for q in SERVERLESS_ATTRIBUTION_PACK.queries:
            assert q.required_tables == ("system.billing.usage",), (
                f"{q.query_id} should read only system.billing.usage"
            )
            for t in q.required_tables:
                assert t.startswith("system."), f"{q.query_id} non-public table {t!r}"

    def test_required_columns_appear_in_sql(self):
        for q in SERVERLESS_ATTRIBUTION_PACK.queries:
            rendered = _render(q.sql_template)
            assert q.required_columns, f"{q.query_id} declares no required_columns"
            for col in q.required_columns:
                assert col in rendered, (
                    f"{q.query_id} declares required_column {col!r} not in SQL"
                )

    def test_every_query_is_workspace_scoped(self):
        """Scope contract (PD-2/G5): billing is account-scoped, so carry workspace_id."""
        for q in SERVERLESS_ATTRIBUTION_PACK.queries:
            assert "workspace_id" in _render(q.sql_template), (
                f"{q.query_id} must carry workspace_id (never conflate workspaces)"
            )


_AI_INFRA_IDS = ("SVA-01", "SVA-02")  # scoped by billing_origin_product AI-infra list


class TestTemplatesRender:
    def test_no_unfilled_placeholders(self):
        for q in SERVERLESS_ATTRIBUTION_PACK.queries:
            leftovers = re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", _render(q.sql_template))
            assert not leftovers, f"{q.query_id} unfilled placeholders: {leftovers}"

    def test_gated_on_product_not_is_serverless_flag(self):
        """The pack scopes by billing_origin_product, NOT product_features.is_serverless.

        Live billing leaves ``is_serverless`` NULL on the very rows this pack attributes
        (VECTOR_SEARCH 1.66M, MODEL_SERVING 1.52M, LAKEBASE 829K DBU/30d), so an
        ``is_serverless IS TRUE`` predicate silently drops ~all of the spend. Gate on the
        product list instead.
        """
        for q in SERVERLESS_ATTRIBUTION_PACK.queries:
            if q.query_id not in _AI_INFRA_IDS:
                continue
            sql = _render(q.sql_template)
            assert "billing_origin_product IN (" in sql, (
                f"{q.query_id} must gate on a billing_origin_product IN (...) list"
            )
            for product in ("VECTOR_SEARCH", "MODEL_SERVING", "LAKEBASE"):
                assert product in sql, f"{q.query_id} must include {product} in its gate"
            assert "is_serverless" not in sql, (
                f"{q.query_id} must NOT filter on is_serverless (NULL on the attributed rows)"
            )


class TestD7ColumnNaming:
    """D7: quantity columns must use 'units' not 'dbus' when usage_unit is in the grain.

    SVA-01 and SVA-02 carry usage_unit per row — Lakebase bills in both DBU and DSU.
    Calling the quantity column 'total_dbus' is wrong for DSU rows. The pack must use
    'total_units' (and 'tagged_units', 'endpoint_attributed_units' for SVA-02).
    """

    @pytest.mark.parametrize("qid", ["SVA-01", "SVA-02"])
    def test_quantity_column_is_total_units_not_total_dbus(self, qid: str) -> None:
        q = next(x for x in SERVERLESS_ATTRIBUTION_PACK.queries if x.query_id == qid)
        sql = _render(q.sql_template)
        assert "total_units" in sql, f"{qid}: quantity column must be 'total_units'"
        assert "total_dbus" not in sql, (
            f"{qid}: 'total_dbus' must be renamed to 'total_units' — "
            "DSU rows (Lakebase) would be mislabelled"
        )

    def test_sva02_coverage_columns_use_units(self) -> None:
        q = next(x for x in SERVERLESS_ATTRIBUTION_PACK.queries if x.query_id == "SVA-02")
        sql = _render(q.sql_template)
        for col in ("tagged_units", "endpoint_attributed_units"):
            assert col in sql, f"SVA-02: coverage column must be '{col}'"
        for old in ("tagged_dbus", "endpoint_attributed_dbus"):
            assert old not in sql, f"SVA-02: old column '{old}' must be renamed"


class TestD11LakebaseAttribution:
    """D11: SVA-01/02 must use database_instance_id as an entity signal for Lakebase.

    When database_instance_id is null (observed live on some workspaces),
    endpoint_name is tried as a fallback — so null instance_id is not the end
    of attribution.
    """

    def test_sva01_selects_database_instance_id(self) -> None:
        q = next(x for x in SERVERLESS_ATTRIBUTION_PACK.queries if x.query_id == "SVA-01")
        sql = _render(q.sql_template)
        assert "usage_metadata.database_instance_id" in sql, (
            "SVA-01 must select database_instance_id as a Lakebase attribution key"
        )

    def test_sva01_entity_coalesce_includes_instance_id(self) -> None:
        """entity COALESCE must try endpoint_name, then database_instance_id."""
        q = next(x for x in SERVERLESS_ATTRIBUTION_PACK.queries if x.query_id == "SVA-01")
        sql = _render(q.sql_template)
        # Both keys must appear before the unattributed fallback in the COALESCE
        entity_block = sql[sql.find("COALESCE"):]
        ep_pos = entity_block.find("endpoint_name")
        inst_pos = entity_block.find("database_instance_id")
        unattr_pos = entity_block.find("unattributed")
        assert ep_pos != -1 and inst_pos != -1, (
            "SVA-01 entity COALESCE must include both endpoint_name and database_instance_id"
        )
        assert ep_pos < unattr_pos and inst_pos < unattr_pos, (
            "Both entity keys must appear before the unattributed fallback in COALESCE"
        )

    def test_sva01_groups_by_instance_id(self) -> None:
        """GROUP BY must include database_instance_id for per-instance attribution grain."""
        q = next(x for x in SERVERLESS_ATTRIBUTION_PACK.queries if x.query_id == "SVA-01")
        sql = _render(q.sql_template)
        assert "usage_metadata.database_instance_id" in sql.split("GROUP BY")[1], (
            "SVA-01 GROUP BY must include usage_metadata.database_instance_id"
        )

    def test_sva02_endpoint_attribution_covers_instance_id(self) -> None:
        """SVA-02 endpoint_attributed_units must count database_instance_id rows."""
        q = next(x for x in SERVERLESS_ATTRIBUTION_PACK.queries if x.query_id == "SVA-02")
        sql = _render(q.sql_template)
        # The CASE counting entity-attributed rows must check both signals
        assert "database_instance_id IS NOT NULL" in sql, (
            "SVA-02 must count database_instance_id as an entity attribution signal"
        )


class TestPerformanceModeMix:
    """F21(a): SVA-03 = serverless DBU by product_features.performance_target."""

    @staticmethod
    def _q():
        return next(
            q for q in SERVERLESS_ATTRIBUTION_PACK.queries if q.query_id == "SVA-03"
        )

    def test_reads_performance_target_by_product(self):
        sql = _render(self._q().sql_template)
        assert "product_features.performance_target" in sql
        assert "billing_origin_product" in sql
        assert "pct_of_product_dbus" in sql
        assert "PARTITION BY workspace_id, billing_origin_product" in sql

    def test_scopes_to_serverless_via_is_serverless(self):
        # Unlike SVA-01/02 (AI infra, is_serverless NULL), Jobs/DLT rows carry the flag.
        assert "product_features.is_serverless = TRUE" in _render(self._q().sql_template)

    def test_null_target_is_labelled_not_applicable(self):
        assert "NOT_APPLICABLE" in _render(self._q().sql_template)

    def test_same_full_day_window_as_facts_f07(self):
        """C1: SVA-03 reconciles with data.facts.performance_mode (F-07).

        Live evidence: F-07 JOBS 470,494 vs SVA-03 481,222 DBU — SVA-03 ran on
        the lookback window plus today's partial day. Both now read the fixed
        trailing 30 full days (today excluded), DBU only.
        """
        from starboard.discovery.query_packs.facts import FACTS_PACK

        sql = _render(self._q().sql_template)
        f07 = next(q for q in FACTS_PACK.queries if q.query_id == "F-07").sql_template
        assert "usage_date >= DATEADD(DAY, -30, CURRENT_DATE())" in sql
        assert "usage_date < CURRENT_DATE()" in sql
        assert "usage_unit = 'DBU'" in sql
        assert "{lookback_days}" not in self._q().sql_template
        # F-07 uses the same bounds (aliased u.).
        assert "u.usage_date >= DATEADD(DAY, -30, CURRENT_DATE())" in f07
        assert "u.usage_date < CURRENT_DATE()" in f07
        # Rendering with a different lookback must not move the window.
        other = self._q().sql_template.format(lookback_days=90, result_limit=50)
        assert "DATEADD(DAY, -30, CURRENT_DATE())" in other
        assert "facts" in self._q().description

    def test_public_billing_table_only_and_workspace_grain(self):
        q = self._q()
        assert q.required_tables == ("system.billing.usage",)
        assert "GROUP BY workspace_id, billing_origin_product" in _render(q.sql_template)


class TestGovernance:
    def test_no_internal_namespaces(self):
        for q in SERVERLESS_ATTRIBUTION_PACK.queries:
            blob = (q.sql_template + q.description + q.name).lower()
            for needle in _FORBIDDEN_NAMESPACES:
                assert needle.lower() not in blob, (
                    f"{q.query_id} contains forbidden namespace {needle!r}"
                )

    def test_dbu_only_no_usd_columns(self):
        for q in SERVERLESS_ATTRIBUTION_PACK.queries:
            usd = re.findall(r"\b\w+_usd(?:_per_day)?\b", q.sql_template.lower())
            assert not usd, f"{q.query_id} emits USD column(s) {usd!r}; pack is DBU-only"


class TestRegistryWiring:
    def test_pack_in_registry(self):
        assert create_default_registry().get_pack("serverless_attribution") is not None

    @pytest.mark.parametrize("product", ["JOBS", "DLT"])
    def test_jobs_and_dlt_route_to_pack_for_perf_mode_mix(self, product: str):
        # SVA-03 must be schedulable on estates whose serverless spend is Jobs / Pipelines.
        assert "serverless_attribution" in PRODUCT_TO_DOMAIN_PACKS[product]
        selected = {
            p.pack_id
            for p in create_default_registry().get_packs_for_products({product})
        }
        assert "serverless_attribution" in selected

    @pytest.mark.parametrize("product", ["VECTOR_SEARCH", "MODEL_SERVING", "LAKEBASE"])
    def test_serverless_products_route_to_pack(self, product: str):
        assert "serverless_attribution" in PRODUCT_TO_DOMAIN_PACKS.get(product, []), (
            f"{product} should route to serverless_attribution"
        )

    @pytest.mark.parametrize("product", ["VECTOR_SEARCH", "MODEL_SERVING", "LAKEBASE"])
    def test_registry_selects_pack_for_products(self, product: str):
        registry = create_default_registry()
        selected = {p.pack_id for p in registry.get_packs_for_products({product})}
        assert "serverless_attribution" in selected
