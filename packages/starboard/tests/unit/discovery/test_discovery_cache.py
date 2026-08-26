# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for discovery result caching.

Covers ``DiscoveryQueryCache`` (in-run dedup + cross-run TTL) and its wiring
into ``QueryPackExecutor``:

- two identical scans within a run execute the SQL client only once
- distinct SQL misses (executes each)
- ``--no-cache`` (enable_cache=False) bypasses the cache entirely
- TTL / freshness-floor expiry forces a re-run
- concurrent identical scans coalesce to a single execution
"""

from __future__ import annotations

import asyncio

import polars as pl
import pytest
from starboard.discovery.executor import QueryPackExecutor
from starboard.discovery.query_cache import DiscoveryQueryCache
from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery


class SpySQLExecutor:
    """SQL executor that records every distinct call."""

    def __init__(self, delay: float = 0.0) -> None:
        self.calls: list[str] = []
        self.delay = delay

    async def execute_sql(self, sql: str) -> pl.DataFrame:
        self.calls.append(sql)
        if self.delay:
            await asyncio.sleep(self.delay)
        return pl.DataFrame({"n": [len(self.calls)]})


def _query(query_id: str, sql: str) -> SystemQuery:
    return SystemQuery(
        query_id=query_id,
        name=f"Query {query_id}",
        description="Test",
        sql_template=sql,
        required_tables=("system.billing.usage",),
        domain="test",
    )


def _pack(queries: tuple[SystemQuery, ...]) -> QueryPack:
    return QueryPack(
        pack_id="test",
        domain="test",
        name="Test",
        description="Test",
        queries=queries,
    )


class TestDiscoveryQueryCacheUnit:
    def test_make_key_is_deterministic(self):
        k1 = DiscoveryQueryCache.make_key("SELECT 1", "ws-1")
        k2 = DiscoveryQueryCache.make_key("SELECT 1", "ws-1")
        assert k1 == k2

    def test_make_key_varies_by_sql_and_workspace(self):
        base = DiscoveryQueryCache.make_key("SELECT 1", "ws-1")
        assert DiscoveryQueryCache.make_key("SELECT 2", "ws-1") != base
        assert DiscoveryQueryCache.make_key("SELECT 1", "ws-2") != base

    @pytest.mark.asyncio
    async def test_get_or_execute_dedupes_same_key(self):
        cache = DiscoveryQueryCache()
        calls = {"n": 0}

        async def loader() -> pl.DataFrame:
            calls["n"] += 1
            return pl.DataFrame({"x": [1]})

        key = DiscoveryQueryCache.make_key("SELECT 1", None)
        await cache.get_or_execute(key, loader)
        await cache.get_or_execute(key, loader)
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_distinct_keys_miss(self):
        cache = DiscoveryQueryCache()
        calls = {"n": 0}

        async def loader() -> pl.DataFrame:
            calls["n"] += 1
            return pl.DataFrame({"x": [1]})

        await cache.get_or_execute(DiscoveryQueryCache.make_key("A", None), loader)
        await cache.get_or_execute(DiscoveryQueryCache.make_key("B", None), loader)
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_concurrent_identical_scans_coalesce(self):
        cache = DiscoveryQueryCache()
        calls = {"n": 0}

        async def loader() -> pl.DataFrame:
            calls["n"] += 1
            await asyncio.sleep(0.02)
            return pl.DataFrame({"x": [1]})

        key = DiscoveryQueryCache.make_key("SELECT 1", None)
        await asyncio.gather(
            cache.get_or_execute(key, loader),
            cache.get_or_execute(key, loader),
            cache.get_or_execute(key, loader),
        )
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_ttl_expiry_reruns(self, monkeypatch):
        import starboard.adapters.state.inmemory.cache_store as cs_mod

        clock = {"t": 1000.0}
        monkeypatch.setattr(cs_mod.time, "time", lambda: clock["t"])

        cache = DiscoveryQueryCache(freshness_floor_s=60)
        calls = {"n": 0}

        async def loader() -> pl.DataFrame:
            calls["n"] += 1
            return pl.DataFrame({"x": [1]})

        key = DiscoveryQueryCache.make_key("SELECT 1", None)
        await cache.get_or_execute(key, loader)
        assert calls["n"] == 1

        # Within the freshness floor: still a hit.
        clock["t"] += 30
        await cache.get_or_execute(key, loader)
        assert calls["n"] == 1

        # Past the freshness floor: re-run.
        clock["t"] += 60
        await cache.get_or_execute(key, loader)
        assert calls["n"] == 2


class TestExecutorCaching:
    @pytest.mark.asyncio
    async def test_identical_queries_hit_cache_once(self):
        spy = SpySQLExecutor()
        qpe = QueryPackExecutor(
            spy, max_parallelism=4, default_lookback_days=30, enable_cache=True
        )
        # Two queries whose rendered SQL is byte-for-byte identical.
        sql = "SELECT * FROM system.billing.usage WHERE d > {lookback_days}"
        pack = _pack((_query("Q1", sql), _query("Q2", sql)))
        result = await qpe.execute_pack(pack)

        assert result.success_count == 2
        assert len(spy.calls) == 1, "identical scans should execute SQL once"

    @pytest.mark.asyncio
    async def test_no_cache_bypasses(self):
        spy = SpySQLExecutor()
        qpe = QueryPackExecutor(
            spy, max_parallelism=4, default_lookback_days=30, enable_cache=False
        )
        sql = "SELECT * FROM system.billing.usage WHERE d > {lookback_days}"
        pack = _pack((_query("Q1", sql), _query("Q2", sql)))
        result = await qpe.execute_pack(pack)

        assert result.success_count == 2
        assert len(spy.calls) == 2, "--no-cache must bypass dedup"

    @pytest.mark.asyncio
    async def test_distinct_queries_all_execute(self):
        spy = SpySQLExecutor()
        qpe = QueryPackExecutor(
            spy, max_parallelism=4, default_lookback_days=30, enable_cache=True
        )
        pack = _pack(
            (
                _query("Q1", "SELECT a FROM system.billing.usage"),
                _query("Q2", "SELECT b FROM system.billing.usage"),
            )
        )
        await qpe.execute_pack(pack)
        assert len(spy.calls) == 2

    @pytest.mark.asyncio
    async def test_workspace_id_in_cache_key(self):
        # Same SQL, different workspace -> distinct executors, no cross-talk.
        spy = SpySQLExecutor()
        qpe = QueryPackExecutor(
            spy,
            max_parallelism=4,
            default_lookback_days=30,
            enable_cache=True,
            workspace_id="ws-123",
        )
        sql = "SELECT * FROM system.billing.usage WHERE d > {lookback_days}"
        pack = _pack((_query("Q1", sql), _query("Q2", sql)))
        await qpe.execute_pack(pack)
        assert len(spy.calls) == 1
