# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the QuerySource port + SystemTablesSource default."""

from __future__ import annotations

import polars as pl
from starboard.discovery.sources import PreparedQuery, SystemTablesSource
from starboard_core.domain.models.discovery.query import SystemQuery


class _FakeExec:
    async def execute_sql(self, sql: str) -> pl.DataFrame:
        return pl.DataFrame({"n": [1]})


def _q() -> SystemQuery:
    return SystemQuery(
        query_id="C-B01", name="n", description="d",
        sql_template="SELECT 1 FROM system.billing.usage",
        required_tables=("system.billing.usage",), domain="billing",
    )


def test_system_tables_source_is_identity():
    src = SystemTablesSource(executor=_FakeExec())
    out = src.prepare(_q(), "SELECT 1 FROM system.billing.usage")
    assert isinstance(out, PreparedQuery)
    assert out.sql == "SELECT 1 FROM system.billing.usage"  # untouched
    assert isinstance(out.executor, _FakeExec)
