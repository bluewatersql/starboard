# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
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
from starboard.discovery.executor import QueryPackExecutor
from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery


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
        # Dummy queries share identical "SELECT 1" SQL; disable caching so this
        # test exercises multi-pack fan-out rather than scan dedup.
        qpe = QueryPackExecutor(
            executor,
            max_parallelism=4,
            default_lookback_days=30,
            enable_cache=False,
        )

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
        # Identical dummy SQL would coalesce under caching; disable it so all
        # six queries actually execute and exercise the semaphore.
        qpe = QueryPackExecutor(
            executor,
            max_parallelism=2,
            default_lookback_days=30,
            enable_cache=False,
        )

        queries = tuple(_query(f"Q{i}") for i in range(6))
        pack = _pack("test", queries)
        await qpe.execute_pack(pack)

        assert executor.max_concurrent <= 2
        assert len(executor.calls) == 6


# Class NAME matches the internal fleet timeout the executor keys on (it matches
# by ``type(exc).__name__``, so no cross-package import is needed).
class FleetStatementTimeout(TimeoutError):
    pass


class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_fleet_timeout_retried_with_backoff_then_unavailable(self, monkeypatch):
        # Round-4 B1 policy: a fleet poll-deadline timeout is retried a bounded
        # number of times (default 2) with ~30s then ~60s back-off; if every
        # attempt times out it is reported unavailable (skipped), not failed.
        import starboard.discovery.executor as ex

        sleeps: list[float] = []

        async def _record_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(ex.asyncio, "sleep", _record_sleep)
        executor = MockSQLExecutor(
            errors={"SELECT 1": FleetStatementTimeout("did not finish within 300s")}
        )
        qpe = QueryPackExecutor(
            executor,
            max_parallelism=4,
            default_lookback_days=30,
            max_retries=3,
            enable_cache=False,
        )
        results = await qpe.execute_packs([_pack("p", (_query("Q1"),))])
        qr = results[0].results[0]
        assert qr.status == "skipped"
        assert "unavailable" in (qr.error or "")
        assert "after 3 attempts" in (qr.error or "")
        assert executor.calls.count("SELECT 1") == 3  # 1 + 2 bounded retries
        assert qr.attempts == 3
        assert len(qr.attempt_elapsed_ms) == 3
        assert sleeps == [30.0, 60.0]

    @pytest.mark.asyncio
    async def test_fleet_timeout_retry_can_succeed(self, monkeypatch):
        import starboard.discovery.executor as ex

        async def _no_sleep(_seconds):
            return None

        monkeypatch.setattr(ex.asyncio, "sleep", _no_sleep)

        class FlakyExecutor:
            def __init__(self) -> None:
                self.calls = 0

            async def execute_sql(self, sql: str) -> pl.DataFrame:  # noqa: ARG002
                self.calls += 1
                if self.calls == 1:
                    raise FleetStatementTimeout("did not finish within 300s")
                return pl.DataFrame({"x": [1, 2]})

        flaky = FlakyExecutor()
        qpe = QueryPackExecutor(flaky, enable_cache=False)
        qr = (await qpe.execute_packs([_pack("p", (_query("Q1"),))]))[0].results[0]
        assert qr.succeeded
        assert qr.row_count == 2
        assert qr.attempts == 2
        assert len(qr.attempt_elapsed_ms) == 2
        assert flaky.calls == 2

    @pytest.mark.asyncio
    async def test_timeout_retries_zero_submits_once(self, monkeypatch):
        import starboard.discovery.executor as ex

        async def _no_sleep(_seconds):
            raise AssertionError("no back-off expected")

        monkeypatch.setattr(ex.asyncio, "sleep", _no_sleep)
        executor = MockSQLExecutor(
            errors={"SELECT 1": FleetStatementTimeout("did not finish within 300s")}
        )
        qpe = QueryPackExecutor(executor, enable_cache=False, timeout_retries=0)
        qr = (await qpe.execute_packs([_pack("p", (_query("Q1"),))]))[0].results[0]
        assert qr.status == "skipped"
        assert executor.calls.count("SELECT 1") == 1
        assert qr.attempts == 1
        assert "after" not in (qr.error or "")

    @pytest.mark.asyncio
    async def test_sql_error_is_never_retried(self, monkeypatch):
        import starboard.discovery.executor as ex

        async def _no_sleep(_seconds):
            raise AssertionError("SQL errors must not back off / retry")

        monkeypatch.setattr(ex.asyncio, "sleep", _no_sleep)
        executor = MockSQLExecutor(errors={"SELECT 1": RuntimeError("PARSE_SYNTAX_ERROR")})
        qpe = QueryPackExecutor(executor, enable_cache=False)
        qr = (await qpe.execute_packs([_pack("p", (_query("Q1"),))]))[0].results[0]
        assert qr.status == "failed"
        assert executor.calls.count("SELECT 1") == 1
        assert qr.attempts == 1

    @pytest.mark.asyncio
    async def test_backoff_runs_outside_the_concurrency_slot(self, monkeypatch):
        # While Q1 waits out its timeout back-off, Q2 must be able to run even
        # with max_parallelism=1 (the slot is released during the sleep).
        import starboard.discovery.executor as ex

        order: list[str] = []
        real_sleep = asyncio.sleep

        async def _short_sleep(_seconds):
            order.append("backoff")
            await real_sleep(0.01)

        monkeypatch.setattr(ex.asyncio, "sleep", _short_sleep)

        class Exec:
            def __init__(self) -> None:
                self.q1 = 0

            async def execute_sql(self, sql: str) -> pl.DataFrame:
                order.append(sql)
                if sql == "SELECT 1":
                    self.q1 += 1
                    if self.q1 == 1:
                        raise FleetStatementTimeout("deadline")
                return pl.DataFrame({"x": [1]})

        qpe = QueryPackExecutor(Exec(), max_parallelism=1, enable_cache=False)
        pack = _pack("p", (_query("Q1", "SELECT 1"), _query("Q2", "SELECT 2")))
        results = (await qpe.execute_packs([pack]))[0].results
        assert all(r.succeeded for r in results)
        # Q2 ran between Q1's first (timed-out) attempt and its retry.
        assert order.index("SELECT 2") < len(order) - 1
        assert order[-1] == "SELECT 1"

    @pytest.mark.asyncio
    async def test_external_timeout_is_failure_not_unavailable(self, monkeypatch):
        # REGRESSION (Isaac Review): a bare TimeoutError on the EXTERNAL customer
        # path must remain a hard FAILURE — never silently masked as a coverage
        # gap. It keeps its original transient-retry behavior.
        import starboard.discovery.executor as ex

        async def _no_sleep(_seconds):
            return None

        monkeypatch.setattr(ex.asyncio, "sleep", _no_sleep)  # skip backoff waits

        executor = MockSQLExecutor(
            errors={"SELECT 1": TimeoutError("customer query exceeded wait timeout")}
        )
        qpe = QueryPackExecutor(
            executor,
            max_parallelism=4,
            default_lookback_days=30,
            max_retries=3,
            enable_cache=False,
        )
        results = await qpe.execute_packs([_pack("p", (_query("Q1"),))])
        qr = results[0].results[0]
        assert qr.status == "failed"  # NOT skipped/unavailable
        assert executor.calls.count("SELECT 1") == 3  # external timeout still retried

    @pytest.mark.asyncio
    async def test_network_transient_is_retried_to_cap(self, monkeypatch):
        # A genuine network transient IS still retried up to the cap.
        import starboard.discovery.executor as ex

        async def _no_sleep(_seconds):
            return None

        monkeypatch.setattr(ex.asyncio, "sleep", _no_sleep)  # skip backoff waits

        class ConnectError(Exception):
            pass

        executor = MockSQLExecutor(errors={"SELECT 1": ConnectError("dropped")})
        qpe = QueryPackExecutor(
            executor,
            max_parallelism=4,
            default_lookback_days=30,
            max_retries=3,
            enable_cache=False,
        )
        results = await qpe.execute_packs([_pack("p", (_query("Q1"),))])
        qr = results[0].results[0]
        assert not qr.succeeded
        assert executor.calls.count("SELECT 1") == 3  # retried to the cap


class TestResultLimitAndEligibility:
    @pytest.mark.asyncio
    async def test_result_limit_is_the_sql_trailing_limit(self):
        df = pl.DataFrame({"x": list(range(5))})
        executor = MockSQLExecutor(results={"SELECT": df})
        qpe = QueryPackExecutor(executor, default_result_limit=5)

        pack = _pack(
            "test",
            (
                _query("Q1", "SELECT x FROM t LIMIT {result_limit}"),
                _query("Q2", "SELECT x FROM t"),
                # Literal caps count too, not only the {result_limit} placeholder.
                _query("Q3", "SELECT x FROM t\nLIMIT 500\n"),
                # A LIMIT inside a subquery is not the statement's row cap.
                _query("Q4", "SELECT x FROM (SELECT x FROM t LIMIT 3) s"),
            ),
        )
        result = await qpe.execute_pack(pack)

        by_id = {r.query_id: r for r in result.results}
        assert by_id["Q1"].result_limit == 5
        assert by_id["Q1"].row_count == 5  # filled the SQL LIMIT -> capped
        assert by_id["Q2"].result_limit is None
        assert by_id["Q3"].result_limit == 500
        assert by_id["Q4"].result_limit is None

    def test_eligible_queries_excludes_deep_dive_in_general_mode(self):
        from dataclasses import replace

        from starboard_core.domain.models.discovery.query import DiscoveryMode

        general = _query("G1")
        deep = replace(_query("D1"), discovery_mode=DiscoveryMode.DEEP_DIVE)
        pack = _pack("test", (general, deep))

        qpe = QueryPackExecutor(MockSQLExecutor())
        assert [q.query_id for q in qpe.eligible_queries(pack)] == ["G1"]

        qpe_deep = QueryPackExecutor(
            MockSQLExecutor(), discovery_mode=DiscoveryMode.DEEP_DIVE
        )
        assert [q.query_id for q in qpe_deep.eligible_queries(pack)] == ["G1", "D1"]


class TestInFlightIdsAndServedLookback:
    @pytest.mark.asyncio
    async def test_in_flight_ids_name_running_queries(self):
        seen: list[tuple[str, ...]] = []
        qpe: QueryPackExecutor

        class Exec:
            async def execute_sql(self, sql: str) -> pl.DataFrame:  # noqa: ARG002
                await asyncio.sleep(0.01)
                seen.append(qpe.in_flight_ids)
                return pl.DataFrame({"x": [1]})

        qpe = QueryPackExecutor(Exec(), max_parallelism=2, enable_cache=False)
        pack = _pack("p", (_query("Q1", "SELECT 1"), _query("Q2", "SELECT 2")))
        await qpe.execute_packs([pack])
        assert any(set(ids) == {"Q1", "Q2"} for ids in seen)
        assert qpe.in_flight_ids == ()
        assert qpe.in_flight == 0

    @pytest.mark.asyncio
    async def test_source_served_lookback_is_reported(self):
        from starboard.discovery.sources import PreparedQuery

        inner = MockSQLExecutor(results={"SELECT": pl.DataFrame({"x": [1]})})

        class CappingSource:
            def prepare(self, query, rendered_sql, render=None):  # noqa: ARG002
                return PreparedQuery(sql=rendered_sql, executor=inner, lookback_days=14)

        qpe = QueryPackExecutor(
            inner, default_lookback_days=30, enable_cache=False, source=CappingSource()
        )
        qr = (await qpe.execute_packs([_pack("p", (_query("Q1"),))]))[0].results[0]
        assert qr.succeeded
        assert qr.lookback_days == 14
        assert qr.attempts == 1
