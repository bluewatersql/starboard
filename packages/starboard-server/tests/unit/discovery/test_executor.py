"""Tests for QueryPackExecutor.

Tests cover:
- Single query execution (success and failure)
- Pack execution with multiple queries
- Multi-pack execution
- Semaphore-bounded concurrency
- SQL template rendering with {lookback_days}
"""

from __future__ import annotations

import asyncio

import polars as pl
import pytest
from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery
from starboard_server.discovery.executor import QueryPackExecutor


class MockSQLExecutor:
    """Mock SQL executor that records calls and returns configurable results."""

    def __init__(
        self,
        results: dict[str, pl.DataFrame] | None = None,
        errors: dict[str, Exception] | None = None,
        delay: float = 0.0,
    ) -> None:
        self.results = results or {}
        self.errors = errors or {}
        self.calls: list[str] = []
        self.delay = delay
        self.max_concurrent = 0
        self._current_concurrent = 0
        self._lock = asyncio.Lock()

    async def execute_sql(self, sql: str) -> pl.DataFrame:
        async with self._lock:
            self._current_concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self._current_concurrent)

        self.calls.append(sql)

        try:
            if self.delay:
                await asyncio.sleep(self.delay)

            for pattern, error in self.errors.items():
                if pattern in sql:
                    raise error

            for pattern, df in self.results.items():
                if pattern in sql:
                    return df

            return pl.DataFrame()
        finally:
            async with self._lock:
                self._current_concurrent -= 1


def _query(query_id: str, sql: str = "SELECT 1") -> SystemQuery:
    return SystemQuery(
        query_id=query_id,
        name=f"Query {query_id}",
        description="Test",
        sql_template=sql,
        required_tables=("system.test",),
        domain="test",
    )


def _pack(pack_id: str, queries: tuple[SystemQuery, ...]) -> QueryPack:
    return QueryPack(
        pack_id=pack_id,
        domain="test",
        name=f"Pack {pack_id}",
        description="Test",
        queries=queries,
    )


class TestQueryExecution:
    @pytest.mark.asyncio
    async def test_successful_query(self):
        df = pl.DataFrame({"col": [1, 2, 3]})
        executor = MockSQLExecutor(results={"SELECT 1": df})
        qpe = QueryPackExecutor(executor, max_parallelism=4, default_lookback_days=30)

        pack = _pack("test", (_query("Q1"),))
        result = await qpe.execute_pack(pack)

        assert result.success_count == 1
        assert result.failure_count == 0
        assert result.results[0].row_count == 3

    @pytest.mark.asyncio
    async def test_failed_query(self):
        executor = MockSQLExecutor(errors={"SELECT": RuntimeError("Table not found")})
        qpe = QueryPackExecutor(executor, max_parallelism=4, default_lookback_days=30)

        pack = _pack("test", (_query("Q1"),))
        result = await qpe.execute_pack(pack)

        assert result.success_count == 0
        assert result.failure_count == 1
        assert "Table not found" in (result.results[0].error or "")

    @pytest.mark.asyncio
    async def test_mixed_results(self):
        df = pl.DataFrame({"x": [1]})
        executor = MockSQLExecutor(
            results={"good": df},
            errors={"bad": ValueError("fail")},
        )
        qpe = QueryPackExecutor(executor, max_parallelism=4, default_lookback_days=30)

        pack = _pack(
            "test",
            (_query("Q1", "SELECT good"), _query("Q2", "SELECT bad")),
        )
        result = await qpe.execute_pack(pack)

        assert result.success_count == 1
        assert result.failure_count == 1


class TestTemplateRendering:
    @pytest.mark.asyncio
    async def test_lookback_days_rendering(self):
        executor = MockSQLExecutor()
        qpe = QueryPackExecutor(executor, max_parallelism=4, default_lookback_days=60)

        q = _query("Q1", "SELECT * WHERE date > INTERVAL {lookback_days} DAYS")
        pack = _pack("test", (q,))
        await qpe.execute_pack(pack)

        assert "INTERVAL 60 DAYS" in executor.calls[0]

    @pytest.mark.asyncio
    async def test_lookback_override(self):
        executor = MockSQLExecutor()
        qpe = QueryPackExecutor(executor, max_parallelism=4, default_lookback_days=30)

        q = SystemQuery(
            query_id="Q1",
            name="Test",
            description="Test",
            sql_template="SELECT * WHERE date > INTERVAL {lookback_days} DAYS",
            required_tables=("system.test",),
            domain="test",
            lookback_override=90,
        )
        pack = _pack("test", (q,))
        await qpe.execute_pack(pack)

        assert "INTERVAL 90 DAYS" in executor.calls[0]


class TestMultiPackExecution:
    @pytest.mark.asyncio
    async def test_execute_multiple_packs(self):
        executor = MockSQLExecutor()
        qpe = QueryPackExecutor(executor, max_parallelism=4, default_lookback_days=30)

        packs = [
            _pack("p1", (_query("Q1"),)),
            _pack("p2", (_query("Q2"), _query("Q3"))),
        ]
        results = await qpe.execute_packs(packs)

        assert len(results) == 2
        assert results[0].pack_id == "p1"
        assert results[1].pack_id == "p2"
        assert len(executor.calls) == 3


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        executor = MockSQLExecutor(delay=0.05)
        qpe = QueryPackExecutor(executor, max_parallelism=2, default_lookback_days=30)

        queries = tuple(_query(f"Q{i}") for i in range(6))
        pack = _pack("test", queries)
        await qpe.execute_pack(pack)

        assert executor.max_concurrent <= 2
        assert len(executor.calls) == 6
