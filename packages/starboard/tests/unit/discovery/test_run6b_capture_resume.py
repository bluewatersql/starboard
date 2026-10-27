# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run-6b: discovery capture resume + wall-clock budget.

* With ``EngineConfig(capture=True)`` and a run sink, every finished query is
  recorded (``capture/discovery-progress.json`` + its rows), and a later run with
  the same run, source/scope, window and pack selection reuses it.
* Statement timeouts carry across runs, so a query that keeps timing out ends up
  skipped; a query abandoned by the budget does not count as a failed attempt.
* ``EngineConfig(deadline=...)`` stops the capture at the deadline: in-flight work
  is cancelled (best-effort), progress is saved, and :class:`CaptureIncomplete`
  carries the done/remaining counts.
* ``enable_cache=False`` (``--no-cache``) does not disable resume.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any

import polars as pl
import pytest
from starboard.discovery.capture import CaptureLog
from starboard.discovery.engine import DiscoveryEngine, EngineConfig
from starboard_core.domain.models.discovery.capture import (
    PROGRESS_PATH,
    CaptureIncomplete,
)
from starboard_core.domain.models.discovery.query import (
    QueryPack,
    QueryResult,
    SystemQuery,
)
from starboard_core.engagement.sink import MemorySink


class FleetStatementTimeout(TimeoutError):
    """Stands in for the internal adapter's timeout (matched by type name)."""


def _q(qid: str) -> SystemQuery:
    return SystemQuery(
        query_id=qid,
        name=qid,
        description=qid,
        sql_template=f"SELECT '{qid}' AS q, {{lookback_days}} AS d FROM system.t",
        required_tables=(),
        domain="billing",
    )


class _Registry:
    """Audit pack + one billing pack of ``ids``."""

    def __init__(self, ids: tuple[str, ...] = ("Q-A", "Q-B", "Q-SLOW")) -> None:
        from starboard.discovery.query_packs.audit import AUDIT_PACK

        self._audit = AUDIT_PACK
        self.pack = QueryPack(
            pack_id="billing",
            domain="billing",
            name="Billing",
            description="t",
            queries=tuple(_q(i) for i in ids),
            gating_products=frozenset(),
        )

    @property
    def all_packs(self) -> list[QueryPack]:
        return [self._audit]

    def get_packs_for_products(self, *a: Any, **k: Any) -> list[QueryPack]:
        return [self.pack]

    def products_without_coverage(self, *a: Any, **k: Any) -> list[str]:
        return []


def _qid(sql: str) -> str:
    if "usage_unit" in sql:
        return "P-AUDIT01"
    return sql.split("'")[1]


class _Exec:
    """Counts submissions per query; ``slow`` ids block, ``timeout`` ids time out."""

    def __init__(
        self,
        *,
        slow: frozenset[str] = frozenset(),
        timeout: frozenset[str] = frozenset(),
        timeout_then_slow: frozenset[str] = frozenset(),
    ) -> None:
        self.calls: list[str] = []
        self._slow = slow
        self._timeout = timeout
        self._timeout_then_slow = timeout_then_slow

    async def execute_sql(self, sql: str) -> pl.DataFrame:
        qid = _qid(sql)
        self.calls.append(qid)
        if qid == "P-AUDIT01":
            return pl.DataFrame(
                {"billing_origin_product": ["JOBS"], "total_dbus": [1000.0]}
            )
        if qid in self._timeout:
            raise FleetStatementTimeout(f"{qid} did not finish within 300s")
        if qid in self._timeout_then_slow:
            if self.calls.count(qid) == 1:
                raise FleetStatementTimeout(f"{qid} did not finish within 300s")
            await asyncio.sleep(60)
        if qid in self._slow:
            await asyncio.sleep(60)
        return pl.DataFrame(
            {
                "q": [qid],
                "n": pl.Series([7], dtype=pl.Int64),
                "x": [1.5],
                "ts": [datetime(2026, 10, 1, 12, 0)],
                "none": pl.Series([None], dtype=pl.Utf8),
            }
        )


def _engine(
    executor: _Exec,
    sink: MemorySink,
    *,
    registry: _Registry | None = None,
    deadline: float | None = None,
    lookback_days: int = 30,
    timeout_retries: int = 1,
    enable_cache: bool = False,
) -> DiscoveryEngine:
    engine = DiscoveryEngine(
        sql_executor=executor,
        llm_client=None,
        config=EngineConfig(
            data_only=True,
            lookback_days=lookback_days,
            enable_cache=enable_cache,
            timeout_retries=timeout_retries,
            sink=sink,
            capture=True,
            deadline=deadline,
        ),
        query_registry=registry or _Registry(),  # type: ignore[arg-type]
    )
    engine._pack_executor._timeout_backoff_s = (0.0,)
    return engine


def _results(result: Any) -> dict[str, QueryResult]:
    return {qr.query_id: qr for pr in result.pack_results for qr in pr.results}


def _progress(sink: MemorySink) -> dict[str, Any]:
    return json.loads(sink.get_bytes(PROGRESS_PATH))


# --- resume ---------------------------------------------------------------------


@pytest.mark.unit
async def test_a_finished_capture_is_reused_by_the_same_command() -> None:
    sink = MemorySink(run_id="run-1")
    first = await _engine(_Exec(), sink).run()
    assert first.resumed == {"queries_reused": 0}
    record = _progress(sink)
    assert record["key"]["run_id"] == "run-1"
    assert record["queries"]["Q-A"]["status"] == "succeeded"

    again = _Exec()
    second = await _engine(again, sink).run()
    assert again.calls == []
    assert second.resumed == {"queries_reused": 4}
    reused = _results(second)["Q-A"]
    original = _results(first)["Q-A"]
    assert reused.succeeded
    assert reused.data is not None and original.data is not None
    assert reused.data.equals(original.data)
    assert reused.data.schema == original.data.schema
    assert reused.attempts == original.attempts


@pytest.mark.unit
async def test_no_cache_does_not_disable_resume() -> None:
    sink = MemorySink(run_id="run-1")
    await _engine(_Exec(), sink, enable_cache=False).run()
    again = _Exec()
    await _engine(again, sink, enable_cache=False).run()
    assert again.calls == []


@pytest.mark.unit
async def test_a_changed_window_starts_fresh_and_says_so() -> None:
    sink = MemorySink(run_id="run-1")
    await _engine(_Exec(), sink, lookback_days=30).run()
    again = _Exec()
    second = await _engine(again, sink, lookback_days=7).run()
    assert sorted(again.calls) == ["P-AUDIT01", "Q-A", "Q-B", "Q-SLOW"]
    assert second.resumed is not None
    assert second.resumed["queries_reused"] == 0
    assert "lookback_days" in second.resumed["fresh_reason"]
    assert _progress(sink)["key"]["lookback_days"] == 7


@pytest.mark.unit
async def test_a_query_whose_sql_changed_is_run_again() -> None:
    sink = MemorySink(run_id="run-1")
    await _engine(_Exec(), sink).run()
    registry = _Registry()
    changed = SystemQuery(
        query_id="Q-B",
        name="Q-B",
        description="Q-B",
        sql_template="SELECT 'Q-B' AS q, 2 AS v FROM system.t",
        required_tables=(),
        domain="billing",
    )
    registry.pack = QueryPack(
        pack_id="billing",
        domain="billing",
        name="Billing",
        description="t",
        queries=(_q("Q-A"), changed, _q("Q-SLOW")),
        gating_products=frozenset(),
    )
    again = _Exec()
    second = await _engine(again, sink, registry=registry).run()
    assert again.calls == ["Q-B"]
    assert second.resumed == {"queries_reused": 3}


@pytest.mark.unit
async def test_capture_off_writes_no_progress() -> None:
    sink = MemorySink(run_id="run-1")
    engine = DiscoveryEngine(
        sql_executor=_Exec(),
        llm_client=None,
        config=EngineConfig(data_only=True, sink=sink),
        query_registry=_Registry(),  # type: ignore[arg-type]
    )
    result = await engine.run()
    assert result.resumed is None
    assert sink.list("capture") == ()


# --- budget ---------------------------------------------------------------------


@pytest.mark.unit
async def test_the_budget_stops_the_capture_and_saves_progress() -> None:
    sink = MemorySink(run_id="run-1")
    engine = _engine(
        _Exec(slow=frozenset({"Q-SLOW"})), sink, deadline=time.monotonic() + 0.5
    )
    cancelled: list[bool] = []
    engine._pack_executor._source.cancel_in_flight = lambda: cancelled.append(True)  # type: ignore[attr-defined]
    started = time.monotonic()
    with pytest.raises(CaptureIncomplete) as info:
        await engine.run()
    assert time.monotonic() - started < 5
    assert info.value.progress() == {"done": 3, "remaining": 1, "reused": 0}
    assert cancelled == [True]
    queries = _progress(sink)["queries"]
    assert queries["Q-A"]["status"] == "succeeded"
    # Abandoned by the budget: not a failed attempt, nothing recorded.
    assert "Q-SLOW" not in queries or queries["Q-SLOW"].get("status") is None
    assert queries.get("Q-SLOW", {}).get("timeout_attempt_ms", []) == []

    # The same command again finishes the remaining query only.
    again = _Exec()
    second = await _engine(again, sink).run()
    assert again.calls == ["Q-SLOW"]
    assert second.resumed == {"queries_reused": 3}
    assert all(qr.succeeded for qr in _results(second).values())


@pytest.mark.unit
async def test_a_budget_spent_during_the_audit_reports_remaining_unknown() -> None:
    sink = MemorySink(run_id="run-1")
    engine = _engine(_Exec(), sink, deadline=time.monotonic() - 1)
    with pytest.raises(CaptureIncomplete) as info:
        await engine.run()
    assert info.value.progress() == {"done": 0, "remaining": None, "reused": 0}


@pytest.mark.unit
async def test_timeouts_carry_across_runs_until_the_query_is_skipped() -> None:
    sink = MemorySink(run_id="run-1")
    # Run 1: Q-SLOW times out once, its retry is abandoned by the budget.
    first = _engine(
        _Exec(timeout_then_slow=frozenset({"Q-SLOW"})),
        sink,
        deadline=time.monotonic() + 0.5,
        timeout_retries=1,
    )
    with pytest.raises(CaptureIncomplete):
        await first.run()
    entry = _progress(sink)["queries"]["Q-SLOW"]
    assert entry.get("status") is None
    assert len(entry["timeout_attempt_ms"]) == 1

    # Run 2: one timeout left (1 + timeout_retries = 2 in total) -> skipped.
    again = _Exec(timeout=frozenset({"Q-SLOW"}))
    second = await _engine(again, sink, timeout_retries=1).run()
    assert again.calls == ["Q-SLOW"]
    slow = _results(second)["Q-SLOW"]
    assert slow.skipped and not slow.succeeded
    assert slow.attempts == 2
    assert len(slow.attempt_elapsed_ms) == 2

    # Run 3: the skip is final; nothing is submitted.
    third_exec = _Exec()
    third = await _engine(third_exec, sink, timeout_retries=1).run()
    assert third_exec.calls == []
    assert _results(third)["Q-SLOW"].skipped


@pytest.mark.unit
async def test_failed_queries_are_attempted_again_on_resume() -> None:
    class _Failing(_Exec):
        async def execute_sql(self, sql: str) -> pl.DataFrame:
            if _qid(sql) == "Q-B":
                self.calls.append("Q-B")
                raise ValueError("PARSE_SYNTAX_ERROR")
            return await super().execute_sql(sql)

    sink = MemorySink(run_id="run-1")
    await _engine(_Failing(), sink).run()
    assert _progress(sink)["queries"]["Q-B"]["status"] == "failed"
    again = _Exec()
    await _engine(again, sink).run()
    assert again.calls == ["Q-B"]


# --- CaptureLog ------------------------------------------------------------------


@pytest.mark.unit
async def test_rows_that_cannot_be_stored_are_not_marked_finished() -> None:
    sink = MemorySink(run_id="run-1")
    log = await CaptureLog.open(sink, {"run_id": "run-1"})
    qr = QueryResult(
        query_id="Q-OBJ",
        domain="billing",
        data=pl.DataFrame({"o": pl.Series([object()], dtype=pl.Object)}),
        row_count=1,
    )
    await log.record(qr, "digest")
    await log.flush()
    reopened = await CaptureLog.open(sink, {"run_id": "run-1"})
    assert await reopened.reuse("Q-OBJ", "billing", "digest") is None


@pytest.mark.unit
async def test_an_unreadable_progress_record_starts_fresh() -> None:
    sink = MemorySink(run_id="run-1")
    sink.put_bytes(PROGRESS_PATH, b"{not json", "application/json")
    log = await CaptureLog.open(sink, {"run_id": "run-1"})
    assert log.fresh_reason is not None
    assert "unreadable" in log.fresh_reason
