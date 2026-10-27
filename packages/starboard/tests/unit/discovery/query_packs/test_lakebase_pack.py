# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the Lakebase query pack.

The load-bearing contract: Lakebase bills under BOTH ``billing_origin_product`` values
``'LAKEBASE'`` (the bulk) and ``'DATABASE'`` (a small serverless sliver). Every query must
gate on ``IN ('DATABASE', 'LAKEBASE')`` — filtering on ``'DATABASE'`` alone drops ~99% of
the spend (verified live: LAKEBASE 829K vs DATABASE 6.7K DBU/30d).
"""

from __future__ import annotations

import collections
import re

import pytest
from starboard.discovery.query_packs.lakebase import LAKEBASE_PACK
from starboard.discovery.query_packs.registry import (
    PRODUCT_TO_DOMAIN_PACKS,
    create_default_registry,
)

_RENDER_PARAMS = {"lookback_days": 30, "result_limit": 50}


def _render(sql_template: str) -> str:
    return sql_template.format_map(collections.defaultdict(str, _RENDER_PARAMS))


class TestProductGate:
    def test_every_billing_query_gates_on_both_product_names(self):
        """No query may filter on 'DATABASE' alone — that catches <1% of Lakebase spend."""
        for q in LAKEBASE_PACK.queries:
            sql = _render(q.sql_template)
            if "billing_origin_product" not in sql:
                continue
            assert "billing_origin_product IN ('DATABASE', 'LAKEBASE')" in sql, (
                f"{q.query_id} must gate on IN ('DATABASE', 'LAKEBASE')"
            )
            # A bare `= 'DATABASE'` equality is the bug this guards against.
            assert not re.search(r"billing_origin_product\s*=\s*'DATABASE'", sql), (
                f"{q.query_id} still filters billing_origin_product = 'DATABASE' (drops LAKEBASE)"
            )

    def test_gating_products_cover_both_names(self):
        assert {"DATABASE", "LAKEBASE"}.issubset(LAKEBASE_PACK.gating_products)


class TestTemplatesRender:
    def test_no_unfilled_placeholders(self):
        for q in LAKEBASE_PACK.queries:
            leftovers = re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", _render(q.sql_template))
            assert not leftovers, f"{q.query_id} unfilled placeholders: {leftovers}"


class TestRegistryWiring:
    def test_pack_in_registry(self):
        assert create_default_registry().get_pack("lakebase") is not None

    @pytest.mark.parametrize("product", ["DATABASE", "LAKEBASE"])
    def test_products_route_to_pack(self, product: str):
        assert "lakebase" in PRODUCT_TO_DOMAIN_PACKS.get(product, []), (
            f"{product} should route to the lakebase pack"
        )


def test_p_lb04_dedupes_workspace_dim_and_null_safe_join() -> None:
    """P-LB04 must not emit duplicate rows: the workspace-name dimension is
    deduped to one row per workspace_id (mirror fan-out guard) and the
    instance-id join is null-safe (<=>) so a NULL database_instance_id row still
    matches its prior-window counterpart."""
    q = next(q for q in LAKEBASE_PACK.queries if q.query_id == "P-LB04")
    sql = _render(q.sql_template)
    assert "wsl AS" in sql, "workspace-name dim must be deduped to 1 row/workspace"
    assert "<=>" in sql, "instance-id join must be null-safe"


def test_p_lb01_exposes_endpoint_name_as_secondary_attribution() -> None:
    """D11: P-LB01 must expose endpoint_name alongside database_instance_id.

    When database_instance_id is null (observed live on some workspaces), endpoint_name
    may carry the Lakebase instance endpoint identity. Both columns must be surfaced so
    null database_instance_id is not the end of attribution.
    """
    q = next(x for x in LAKEBASE_PACK.queries if x.query_id == "P-LB01")
    sql = _render(q.sql_template)
    assert "usage_metadata.endpoint_name" in sql, (
        "P-LB01 must select usage_metadata.endpoint_name as a secondary "
        "attribution key when database_instance_id is null"
    )
    assert "AS endpoint_name" in sql, "P-LB01 must alias endpoint_name in the SELECT"
    # endpoint_name must be in the final GROUP BY (P-LB01 has multiple GROUP BY
    # clauses in CTEs; use the last one which is the grain-defining SELECT-level clause)
    assert "usage_metadata.endpoint_name" in sql.split("GROUP BY")[-1], (
        "P-LB01 GROUP BY must include usage_metadata.endpoint_name"
    )


def test_workspaces_latest_is_always_deduped_before_join() -> None:
    """Governance guard for the mirror dim-fan-out family: any lakebase query that
    reads system.access.workspaces_latest MUST dedupe it to one row per
    workspace_id (ANY_VALUE(workspace_name) + GROUP BY workspace_id) before
    joining — otherwise it fans out billing.usage rows on the internal mirror and
    inflates SUM(usage_quantity). P-LB01 regressed exactly this way once; this
    test prevents the next query from missing the guard silently.
    """
    for q in LAKEBASE_PACK.queries:
        sql = _render(q.sql_template)
        if "system.access.workspaces_latest" in sql:
            assert "ANY_VALUE(workspace_name)" in sql and "GROUP BY workspace_id" in sql, (
                f"{q.query_id} joins workspaces_latest without the one-row-per-"
                f"workspace dedup CTE — it will fan out on the internal mirror."
            )
