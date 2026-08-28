# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the cluster_right_sizing query pack (CRS-01…08).

Verifies:
- All 8 CRS queries construct and carry required metadata.
- ``required_tables``/``required_columns`` name the intended ``system.*`` objects.
- Templates render with test params (no unfilled ``{placeholders}``).
- Preview/lakeflow-dependent queries carry ``required=False`` (degrade, don't fail).
- Registry wires the pack to compute/jobs/DLT product surfaces.
- Governance: no internal namespaces; only public ``system.*`` tables; cost
  columns use the ``list_`` naming convention (list-price DBU estimate).
- Complementarity: CRS does NOT re-implement CR-01…03 (instance reliability,
  warehouse churn); it adds right-sizing depth, cost features, and workload
  attribution that CR-01…03 intentionally omit.
"""

from __future__ import annotations

import collections
import re

import pytest
from starboard.discovery.query_packs.cluster_right_sizing import (
    CLUSTER_RIGHT_SIZING_PACK,
)
from starboard.discovery.query_packs.compute_reliability import (
    COMPUTE_RELIABILITY_PACK,
)
from starboard.discovery.query_packs.registry import (
    PRODUCT_TO_DOMAIN_PACKS,
    create_default_registry,
)
from starboard_core.domain.models.discovery.query import QueryPack

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RENDER_PARAMS = {"lookback_days": 30, "result_limit": 50}


def _render(sql_template: str) -> str:
    """Render a SQL template the way the executor does (defaultdict format_map)."""
    return sql_template.format_map(
        collections.defaultdict(str, _RENDER_PARAMS)
    )


# Tables the CRS pack is allowed to read (all public ``system.*``).
_ALLOWED_CRS_TABLES: frozenset[str] = frozenset(
    {
        "system.compute.clusters",
        "system.compute.node_types",
        "system.compute.node_timeline",
        "system.billing.usage",
        "system.billing.list_prices",
        "system.lakeflow.jobs",
        "system.lakeflow.job_run_timeline",
        "system.lakeflow.job_task_run_timeline",
        "system.lakeflow.pipelines",
        "system.lakeflow.pipeline_update_timeline",
    }
)

# Tables owned exclusively by compute_reliability — CRS must NOT read these.
_COMPUTE_RELIABILITY_EXCLUSIVE_TABLES: frozenset[str] = frozenset(
    {
        "system.compute.instance_events",   # CR-01: spot/on-demand reliability
        "system.compute.warehouse_events",  # CR-03: warehouse scaling churn
    }
)

# Internal namespaces that must never appear in public packs.
_FORBIDDEN_NAMESPACES: tuple[str, ...] = (
    "centralized_system_tables",
    "fin_live_gold",
    "logfood",
    "clickhouse",
    "hmr_stack_hash",
    "go/",
    "gtm_",
    "eng_",
)

# Expected CRS query IDs (ordered).
_EXPECTED_QUERY_IDS: tuple[str, ...] = (
    "CRS-01",
    "CRS-02",
    "CRS-03",
    "CRS-04",
    "CRS-05",
    "CRS-06",
    "CRS-07",
    "CRS-08",
)

# lakeflow-dependent queries — must be required=False (degrade gracefully).
_LAKEFLOW_QUERY_IDS: frozenset[str] = frozenset(
    {"CRS-03", "CRS-04", "CRS-05", "CRS-07", "CRS-08"}
)


# ---------------------------------------------------------------------------
# Pack construction
# ---------------------------------------------------------------------------


class TestCRSPackConstruct:
    def test_is_query_pack(self):
        assert isinstance(CLUSTER_RIGHT_SIZING_PACK, QueryPack)

    def test_pack_id(self):
        assert CLUSTER_RIGHT_SIZING_PACK.pack_id == "cluster_right_sizing"

    def test_has_all_eight_queries(self):
        assert len(CLUSTER_RIGHT_SIZING_PACK.queries) == 8

    def test_query_ids_are_crs_series(self):
        ids = tuple(q.query_id for q in CLUSTER_RIGHT_SIZING_PACK.queries)
        assert ids == _EXPECTED_QUERY_IDS


# ---------------------------------------------------------------------------
# required_tables — must name real public system.* objects
# ---------------------------------------------------------------------------


class TestRequiredTables:
    def test_all_tables_are_public_system_tables(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            assert query.required_tables, f"{query.query_id} has no required_tables"
            for table in query.required_tables:
                assert table.startswith("system."), (
                    f"{query.query_id} references non-public table {table!r}"
                )

    def test_all_tables_in_allowed_set(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            for table in query.required_tables:
                assert table in _ALLOWED_CRS_TABLES, (
                    f"{query.query_id} reads undocumented table {table!r}. "
                    f"Add it to _ALLOWED_CRS_TABLES if it is a real system.* table."
                )

    def test_node_timeline_present(self):
        """Core right-sizing signal comes from node_timeline."""
        all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.compute.node_timeline" in all_tables

    def test_billing_tables_present(self):
        """DBU cost features require billing.usage (DBU-only; no list_prices join)."""
        all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.billing.usage" in all_tables

    def test_lakeflow_attribution_tables_present(self):
        """Workload attribution needs lakeflow job/pipeline tables."""
        all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.lakeflow.job_task_run_timeline" in all_tables
        assert "system.lakeflow.job_run_timeline" in all_tables
        assert "system.lakeflow.pipelines" in all_tables


# ---------------------------------------------------------------------------
# required_columns — must name the intended source columns
# ---------------------------------------------------------------------------


class TestRequiredColumns:
    def test_all_queries_declare_required_columns(self):
        """Phase-0 contract: every CRS query must declare required_columns."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            assert query.required_columns, (
                f"{query.query_id} has no required_columns — "
                "add them for the schema-drift guard."
            )

    def test_required_columns_appear_in_sql(self):
        """Every declared column must be referenced in the SQL template."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            rendered = _render(query.sql_template)
            for col in query.required_columns:
                assert col in rendered, (
                    f"{query.query_id} declares required_column {col!r} "
                    "but it does not appear in the SQL template."
                )


# ---------------------------------------------------------------------------
# Template rendering — no unfilled placeholders; tables present in SQL
# ---------------------------------------------------------------------------


class TestTemplatesRender:
    def test_no_unfilled_placeholders(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            rendered = _render(query.sql_template)
            leftovers = re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", rendered)
            assert not leftovers, (
                f"{query.query_id} has unfilled placeholders after render: {leftovers}"
            )

    def test_templates_reference_their_declared_tables(self):
        """Each required_table must appear verbatim in the SQL."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            rendered = _render(query.sql_template)
            for table in query.required_tables:
                assert table in rendered, (
                    f"{query.query_id} declares required_table {table!r} "
                    "but does not reference it in the SQL."
                )


# ---------------------------------------------------------------------------
# Optional queries — lakeflow-dependent must be required=False
# ---------------------------------------------------------------------------


class TestOptionalQueries:
    def test_lakeflow_queries_are_optional(self):
        """Workspaces without lakeflow tables must degrade gracefully."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            if query.query_id in _LAKEFLOW_QUERY_IDS:
                assert query.required is False, (
                    f"{query.query_id} reads lakeflow tables and must be "
                    "required=False so a missing table degrades the query, "
                    "not the whole pack."
                )

    def test_non_lakeflow_queries_are_required(self):
        """Queries over GA compute+billing tables should be required=True."""
        ga_queries = {
            q.query_id
            for q in CLUSTER_RIGHT_SIZING_PACK.queries
            if q.query_id not in _LAKEFLOW_QUERY_IDS
        }
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            if query.query_id in ga_queries:
                assert query.required is True, (
                    f"{query.query_id} reads only GA tables and should be required=True."
                )

    def test_lakeflow_queries_read_lakeflow_tables(self):
        """Every query in _LAKEFLOW_QUERY_IDS should reference at least one lakeflow table."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            if query.query_id in _LAKEFLOW_QUERY_IDS:
                has_lakeflow = any(
                    "lakeflow" in t for t in query.required_tables
                )
                # CRS-07 and CRS-08 may inline node_timeline plus lakeflow
                # but they should still read at least one lakeflow table.
                assert has_lakeflow, (
                    f"{query.query_id} is marked as lakeflow-dependent "
                    "but declares no lakeflow tables in required_tables."
                )


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistryRegistration:
    def test_pack_in_registry(self):
        registry = create_default_registry()
        assert registry.get_pack("cluster_right_sizing") is not None

    @pytest.mark.parametrize("product", ["ALL_PURPOSE", "INTERACTIVE", "BASE_ENVIRONMENTS"])
    def test_compute_products_route_to_crs(self, product: str):
        registry = create_default_registry()
        selected = {p.pack_id for p in registry.get_packs_for_products({product})}
        assert "cluster_right_sizing" in selected, (
            f"product {product!r} should select cluster_right_sizing"
        )

    def test_jobs_product_routes_to_crs(self):
        registry = create_default_registry()
        selected = {p.pack_id for p in registry.get_packs_for_products({"JOBS"})}
        assert "cluster_right_sizing" in selected

    def test_dlt_product_routes_to_crs(self):
        registry = create_default_registry()
        selected = {p.pack_id for p in registry.get_packs_for_products({"DLT"})}
        assert "cluster_right_sizing" in selected

    def test_product_to_domain_packs_wired(self):
        """PRODUCT_TO_DOMAIN_PACKS should list cluster_right_sizing for expected products."""
        products_that_should_route = {"ALL_PURPOSE", "INTERACTIVE", "JOBS", "DLT"}
        for product in products_that_should_route:
            packs = PRODUCT_TO_DOMAIN_PACKS.get(product, [])
            assert "cluster_right_sizing" in packs, (
                f"PRODUCT_TO_DOMAIN_PACKS[{product!r}] should include "
                "'cluster_right_sizing'"
            )


# ---------------------------------------------------------------------------
# Governance guard
# ---------------------------------------------------------------------------


class TestGovernanceGuard:
    def test_no_internal_namespaces(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            blob = (
                query.sql_template + query.description + query.name
            ).lower()
            for needle in _FORBIDDEN_NAMESPACES:
                assert needle.lower() not in blob, (
                    f"{query.query_id} contains forbidden namespace {needle!r}"
                )

    def test_only_public_system_tables_in_required_tables(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            for table in query.required_tables:
                assert table.startswith("system."), (
                    f"{query.query_id} references non-public table {table!r}"
                )

    def test_no_usd_columns_in_sql(self):
        """DBU-only pack policy: no _usd columns; list-price $ is a tool-layer concern."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            sql_lower = query.sql_template.lower()
            usd_cols = re.findall(r'\b\w+_usd(?:_per_day)?\b', sql_lower)
            assert not usd_cols, (
                f"{query.query_id} emits USD column(s) {usd_cols!r}. "
                "This pack is DBU-only; move $ projection to the tool layer."
            )

    def test_no_list_prices_join_in_sql(self):
        """DBU-only policy: pack SQL must not join system.billing.list_prices."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            assert "system.billing.list_prices" not in query.sql_template, (
                f"{query.query_id} joins list_prices, violating the DBU-only pack policy."
            )
            assert "pricing.effective_list" not in query.sql_template, (
                f"{query.query_id} references pricing.effective_list, violating the DBU-only pack policy."
            )


# ---------------------------------------------------------------------------
# Complementarity with compute_reliability (CR-01…03)
# ---------------------------------------------------------------------------


class TestComplementarity:
    def test_crs_does_not_read_compute_reliability_exclusive_tables(self):
        """CRS must NOT overlap with the instance/warehouse lifecycle domain of CR-01/03."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            for table in query.required_tables:
                assert table not in _COMPUTE_RELIABILITY_EXCLUSIVE_TABLES, (
                    f"{query.query_id} reads {table!r} which belongs to "
                    "compute_reliability (CR-01/03). Keep the packs complementary."
                )

    def test_crs_query_ids_do_not_overlap_cr_ids(self):
        cr_ids = {q.query_id for q in COMPUTE_RELIABILITY_PACK.queries}
        crs_ids = {q.query_id for q in CLUSTER_RIGHT_SIZING_PACK.queries}
        overlap = cr_ids & crs_ids
        assert not overlap, (
            f"Query IDs overlap between compute_reliability and "
            f"cluster_right_sizing: {overlap}"
        )

    def test_crs_adds_cost_features_absent_from_cr(self):
        """CRS-02/06 should reference billing tables that CR-01…03 never use."""
        cr_all_tables = {
            t for q in COMPUTE_RELIABILITY_PACK.queries for t in q.required_tables
        }
        assert "system.billing.usage" not in cr_all_tables, (
            "compute_reliability already references billing.usage — "
            "verify CRS is still adding new capability."
        )
        crs_all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.billing.usage" in crs_all_tables

    def test_crs_adds_workload_attribution_absent_from_cr(self):
        """CRS-03…05/07/08 surface workload attribution that CR does not provide."""
        crs_all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.lakeflow.job_task_run_timeline" in crs_all_tables

    def test_downstream_tool_query_ids_present(self):
        """get_cluster_rightsizing (CRS-06) and get_workload_rightsizing (CRS-07/08)
        must exist so the 09-tools task has stable query_ids to consume."""
        ids = {q.query_id for q in CLUSTER_RIGHT_SIZING_PACK.queries}
        for expected in ("CRS-06", "CRS-07", "CRS-08"):
            assert expected in ids, (
                f"Downstream tool query {expected!r} not found in pack."
            )
