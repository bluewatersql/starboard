# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for discovery query domain models.

Tests cover:
- SystemQuery immutability and field access
- QueryPack gating products and query aggregation
- QueryResult success/failure state
- PackResult aggregation properties
"""

import polars as pl
import pytest
from starboard_core.domain.models.discovery.query import (
    PackResult,
    QueryPack,
    QueryResult,
    SystemQuery,
)


class TestSystemQuery:
    """Tests for SystemQuery dataclass."""

    def test_minimal_construction(self):
        q = SystemQuery(
            query_id="C-B01",
            name="Billing overview",
            description="Summarizes billing by product.",
            sql_template="SELECT 1 WHERE date > DATE_SUB(NOW(), {lookback_days})",
            required_tables=("system.billing.usage",),
            domain="billing",
        )
        assert q.query_id == "C-B01"
        assert q.required is True
        assert q.lookback_override is None
        assert q.output_columns is None

    def test_all_fields(self):
        q = SystemQuery(
            query_id="P-AUDIT01",
            name="Platform audit",
            description="Full audit.",
            sql_template="SELECT *",
            required_tables=("system.billing.usage", "system.billing.list_prices"),
            domain="audit",
            required=False,
            lookback_override=90,
            output_columns=("product", "dbu_total"),
        )
        assert q.required is False
        assert q.lookback_override == 90
        assert q.output_columns == ("product", "dbu_total")

    def test_frozen(self):
        q = SystemQuery(
            query_id="X",
            name="X",
            description="X",
            sql_template="SELECT 1",
            required_tables=(),
            domain="test",
        )
        with pytest.raises(AttributeError):
            q.query_id = "Y"  # type: ignore[misc]


class TestQueryPack:
    """Tests for QueryPack dataclass."""

    @pytest.fixture()
    def sample_queries(self) -> tuple[SystemQuery, SystemQuery]:
        q1 = SystemQuery(
            query_id="A",
            name="A",
            description="A",
            sql_template="SELECT 1",
            required_tables=("t1",),
            domain="billing",
        )
        q2 = SystemQuery(
            query_id="B",
            name="B",
            description="B",
            sql_template="SELECT 2",
            required_tables=("t2",),
            domain="billing",
        )
        return q1, q2

    def test_construction(self, sample_queries: tuple[SystemQuery, SystemQuery]):
        pack = QueryPack(
            pack_id="billing",
            domain="billing",
            name="Billing Pack",
            description="Billing queries.",
            queries=sample_queries,
        )
        assert len(pack.queries) == 2
        assert pack.gating_products == frozenset()

    def test_gating_products(self, sample_queries: tuple[SystemQuery, SystemQuery]):
        pack = QueryPack(
            pack_id="ml",
            domain="ml",
            name="ML Pack",
            description="ML queries.",
            queries=sample_queries,
            gating_products=frozenset({"MLFLOW", "MODEL_SERVING"}),
        )
        assert "MLFLOW" in pack.gating_products
        assert len(pack.gating_products) == 2


class TestQueryResult:
    """Tests for QueryResult dataclass."""

    def test_success(self):
        df = pl.DataFrame({"col": [1, 2, 3]})
        r = QueryResult(
            query_id="C-B01",
            domain="billing",
            data=df,
            row_count=3,
            execution_time_ms=150.0,
        )
        assert r.succeeded is True
        assert r.row_count == 3

    def test_failure(self):
        r = QueryResult(
            query_id="C-B01",
            domain="billing",
            data=None,
            error="Table not found",
        )
        assert r.succeeded is False
        assert r.error == "Table not found"

    def test_data_with_error_counts_as_failure(self):
        df = pl.DataFrame({"col": [1]})
        r = QueryResult(
            query_id="X",
            domain="test",
            data=df,
            error="Partial failure",
        )
        assert r.succeeded is False


class TestPackResult:
    """Tests for PackResult dataclass."""

    def test_aggregation(self):
        r1 = QueryResult(
            query_id="A",
            domain="billing",
            data=pl.DataFrame({"x": [1]}),
            execution_time_ms=100.0,
            row_count=1,
        )
        r2 = QueryResult(
            query_id="B",
            domain="billing",
            data=None,
            error="timeout",
            execution_time_ms=200.0,
        )
        pack = PackResult(pack_id="billing", domain="billing", results=(r1, r2))
        assert pack.total_execution_time_ms == 300.0
        assert pack.success_count == 1
        assert pack.failure_count == 1

    def test_empty_results(self):
        pack = PackResult(pack_id="empty", domain="test", results=())
        assert pack.total_execution_time_ms == 0.0
        assert pack.success_count == 0
        assert pack.failure_count == 0
