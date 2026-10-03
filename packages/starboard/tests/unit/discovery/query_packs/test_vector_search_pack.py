# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the Vector Search query pack.

Scope contract: ``system.billing.usage`` is account-scoped and a Vector Search
``endpoint_name`` is NOT globally unique — the same name (e.g. ``dbdemos_vs_endpoint``)
exists in multiple workspaces. Endpoint-billing / idle-detection queries must carry
``workspace_id`` in their grain, else cross-workspace endpoints of the same name collapse
into one mislabeled row (and idle detection gets cross-workspace false negatives).
"""

from __future__ import annotations

import collections
import re

import pytest
from starboard.discovery.query_packs.registry import (
    PRODUCT_TO_DOMAIN_PACKS,
    create_default_registry,
)
from starboard.discovery.query_packs.vector_search import VECTOR_SEARCH_PACK

_RENDER_PARAMS = {"lookback_days": 30, "result_limit": 50}


def _render(sql_template: str) -> str:
    return sql_template.format_map(collections.defaultdict(str, _RENDER_PARAMS))


class TestEndpointGrainIsWorkspaceScoped:
    # Queries whose grain is per-endpoint (or per-endpoint idle detection) — these must
    # carry workspace_id because endpoint_name is not unique across workspaces.
    _ENDPOINT_GRAIN_IDS = ("P-VS01", "P-VS03")

    @pytest.mark.parametrize("query_id", _ENDPOINT_GRAIN_IDS)
    def test_endpoint_query_carries_workspace_id(self, query_id: str):
        q = next(q for q in VECTOR_SEARCH_PACK.queries if q.query_id == query_id)
        assert "workspace_id" in _render(q.sql_template), (
            f"{query_id} must carry workspace_id (endpoint_name is not workspace-unique)"
        )

    def test_billing_history_groups_by_workspace_and_endpoint(self):
        q = next(q for q in VECTOR_SEARCH_PACK.queries if q.query_id == "P-VS01")
        assert "GROUP BY workspace_id, usage_metadata.endpoint_name" in _render(q.sql_template)

    def test_idle_detection_correlates_on_workspace(self):
        # P-VS03's NOT EXISTS against system.access.audit must match workspace_id too,
        # else a query in workspace B suppresses an idle finding in workspace A.
        q = next(q for q in VECTOR_SEARCH_PACK.queries if q.query_id == "P-VS03")
        sql = _render(q.sql_template)
        assert re.search(r"a\.workspace_id\s*=\s*eb\.workspace_id", sql), (
            "P-VS03 must correlate the audit NOT EXISTS on workspace_id"
        )


class TestTemplatesRender:
    def test_no_unfilled_placeholders(self):
        for q in VECTOR_SEARCH_PACK.queries:
            leftovers = re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", _render(q.sql_template))
            assert not leftovers, f"{q.query_id} unfilled placeholders: {leftovers}"


class TestVS06SprawlSummary:
    """P-VS06 Endpoint Sprawl Summary — structural regression guards.

    Verifies the query exists in the pack and its SQL has the shape required
    to reconcile VS spend regardless of the per-endpoint row cap in P-VS01.
    """

    def _q(self):
        matches = [q for q in VECTOR_SEARCH_PACK.queries if q.query_id == "P-VS06"]
        assert matches, "P-VS06 not found in VECTOR_SEARCH_PACK"
        return matches[0]

    def test_p_vs06_in_pack(self):
        ids = {q.query_id for q in VECTOR_SEARCH_PACK.queries}
        assert "P-VS06" in ids

    def test_sql_contains_endpoint_count(self):
        assert "endpoint_count" in _render(self._q().sql_template)

    def test_sql_contains_near_idle(self):
        assert "near_idle" in _render(self._q().sql_template)

    def test_sql_groups_by_workspace_id(self):
        assert "GROUP BY workspace_id" in _render(self._q().sql_template)

    def test_no_unfilled_placeholders(self):
        rendered = _render(self._q().sql_template)
        leftovers = re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", rendered)
        assert not leftovers, f"P-VS06 unfilled placeholders: {leftovers}"

    def test_required_and_optimization_category(self):
        q = self._q()
        assert q.required is True
        from starboard_core.domain.models.discovery.query import QueryCategory
        assert q.category == QueryCategory.OPTIMIZATION


class TestRegistryWiring:
    def test_pack_in_registry(self):
        assert create_default_registry().get_pack("vector_search") is not None

    def test_product_routes_to_pack(self):
        assert "vector_search" in PRODUCT_TO_DOMAIN_PACKS.get("VECTOR_SEARCH", [])
