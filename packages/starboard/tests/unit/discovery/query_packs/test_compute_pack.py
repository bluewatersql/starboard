# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the compute query pack (C-C01…C-C03).

Structural regression guards — SQL correctness is validated live at next
discovery re-run; these tests protect the filter shape so a stale exact
SKU match cannot silently regress.
"""

from __future__ import annotations

import collections
import re

from starboard.discovery.query_packs.compute import COMPUTE_PACK

_RENDER_PARAMS = {"lookback_days": 30, "result_limit": 50}


def _render(sql_template: str) -> str:
    return sql_template.format_map(collections.defaultdict(str, _RENDER_PARAMS))


class TestSkuFilterBreadth:
    """P3 regression guard: exact SKU strings must not reappear in C-C01 / C-C02.

    Real SKUs carry variant suffixes (e.g. ALL_PURPOSE_COMPUTE_PHOTON, regional
    editions).  The old exact-match filters returned nothing for those variants,
    causing total_dbus / est_idle_dbus to come back NULL even when utilisation
    joined fine.  These tests fail if the broad LIKE filter is ever reverted.
    """

    def _sql(self, query_id: str) -> str:
        q = next(q for q in COMPUTE_PACK.queries if q.query_id == query_id)
        return _render(q.sql_template)

    def test_c_c01_no_exact_sku_in_clause(self):
        """C-C01 must not use the exact IN ('ALL_PURPOSE_COMPUTE','JOBS_COMPUTE') form."""
        sql = self._sql("C-C01")
        assert "IN ('ALL_PURPOSE_COMPUTE'" not in sql, (
            "C-C01 reverted to exact sku_name IN filter — Photon/variant SKUs "
            "will return NULL DBUs.  Use LIKE '%ALL_PURPOSE%' etc."
        )
        assert "IN ('ALL_PURPOSE_COMPUTE','JOBS_COMPUTE')" not in sql

    def test_c_c01_uses_like_filter(self):
        """C-C01 billing_summary must use LIKE-based SKU matching."""
        sql = self._sql("C-C01")
        assert "LIKE '%ALL_PURPOSE%'" in sql or "LIKE '%JOBS_COMPUTE%'" in sql, (
            "C-C01 billing_summary must use LIKE-based SKU filters to capture Photon/variants"
        )

    def test_c_c02_no_exact_sku_equals(self):
        """C-C02 must not use the exact sku_name = 'ALL_PURPOSE_COMPUTE' form."""
        sql = self._sql("C-C02")
        assert "= 'ALL_PURPOSE_COMPUTE'" not in sql, (
            "C-C02 reverted to exact sku_name = filter — Photon/variant SKUs "
            "will return NULL DBUs.  Use LIKE '%ALL_PURPOSE%'."
        )

    def test_c_c02_uses_like_filter(self):
        """C-C02 billing_summary must use LIKE-based SKU matching."""
        sql = self._sql("C-C02")
        assert "LIKE '%ALL_PURPOSE%'" in sql, (
            "C-C02 billing_summary must use LIKE '%ALL_PURPOSE%' to capture Photon/variants"
        )


class TestTemplatesRender:
    def test_no_unfilled_placeholders(self):
        for q in COMPUTE_PACK.queries:
            rendered = _render(q.sql_template)
            leftovers = re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", rendered)
            assert not leftovers, f"{q.query_id} unfilled placeholders: {leftovers}"
