# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for QueryPackExecutor consulting a QuerySource (identity regression)."""

from __future__ import annotations

import polars as pl
import pytest
from starboard.discovery.executor import QueryPackExecutor
from starboard.discovery.sources import Unavailable
from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery


class _Exec:
    async def execute_sql(self, sql: str) -> pl.DataFrame:
        return pl.DataFrame({"n": [1]})


class _SkipSource:
    def prepare(self, query: SystemQuery, rendered_sql: str, render=None) -> Unavailable:  # noqa: ANN001, ARG002
        return Unavailable(reason="table not mirrored")


def _pack() -> QueryPack:
    q = SystemQuery(
        query_id="Q1", name="n", description="d",
        sql_template="SELECT 1", required_tables=("system.x.y",), domain="d",
    )
    return QueryPack(pack_id="p", domain="d", name="n", description="d", queries=(q,))


@pytest.mark.asyncio
async def test_unavailable_query_is_skipped_with_reason():
    ex = QueryPackExecutor(sql_executor=_Exec(), enable_cache=False, source=_SkipSource())
    res = await ex.execute_pack(_pack())
    r = res.results[0]
    assert r.data is None and "not mirrored" in (r.error or "")


@pytest.mark.asyncio
async def test_default_source_still_executes():
    ex = QueryPackExecutor(sql_executor=_Exec(), enable_cache=False)  # source=None
    res = await ex.execute_pack(_pack())
    assert res.results[0].row_count == 1


class _RecordingExec:
    def __init__(self) -> None:
        self.order: list[str] = []

    async def execute_sql(self, sql: str) -> pl.DataFrame:
        self.order.append(sql.split("'")[1])
        return pl.DataFrame({"n": [1]})


class _OrderSource:
    """Identity source flagging B2 as a long pole."""

    schedule_first = ("B2",)

    def __init__(self, executor: _RecordingExec) -> None:
        self._executor = executor

    def prepare(self, query: SystemQuery, rendered_sql: str, render=None):  # noqa: ANN001, ANN201, ARG002
        from starboard.discovery.sources import PreparedQuery

        return PreparedQuery(sql=rendered_sql, executor=self._executor)


def _q(qid: str, domain: str) -> SystemQuery:
    return SystemQuery(query_id=qid, name="n", description="d", sql_template=f"SELECT '{qid}'",
                       required_tables=("system.x.y",), domain=domain)


@pytest.mark.asyncio
async def test_schedule_first_starts_long_pole_first_and_keeps_result_order():
    """Round-6: a source's long-pole query (e.g. CRS-01 on the mirror) takes a
    slot first so it overlaps the run instead of extending its tail; everything
    else keeps its order."""
    packs = [
        QueryPack(pack_id="a", domain="a", name="n", description="d",
                  queries=(_q("A1", "a"), _q("A2", "a"))),
        QueryPack(pack_id="b", domain="b", name="n", description="d",
                  queries=(_q("B1", "b"), _q("B2", "b"))),
    ]
    rec = _RecordingExec()
    ex = QueryPackExecutor(sql_executor=rec, enable_cache=False, source=_OrderSource(rec),
                           max_parallelism=1)
    results = await ex.execute_packs(packs)
    assert rec.order == ["B2", "A1", "A2", "B1"]
    assert [r.pack_id for r in results] == ["a", "b"]
    assert [q.query_id for q in results[1].results] == ["B1", "B2"]
