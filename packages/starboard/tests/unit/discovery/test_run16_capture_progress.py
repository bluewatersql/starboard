"""Live customer run 2026-10-22: a stopped capture's progress counts only reusable work.

The first capture stopped at its budget reporting "76 done, 0 remaining", but the
resume re-ran 14 queries: the statements cancelled at the deadline were recorded as
failed and counted as done. A resume reuses only succeeded/skipped entries, so only
those (and source-unavailable queries) are done.
"""

from __future__ import annotations

import asyncio

import polars as pl
import pytest
from starboard.discovery.capture import CaptureLog
from starboard_core.domain.models.discovery.query import QueryResult
from starboard_core.engagement.sink import MemorySink

pytestmark = pytest.mark.unit


def _qr(qid: str, *, ok: bool) -> QueryResult:
    return QueryResult(
        query_id=qid,
        domain="jobs",
        data=pl.DataFrame({"a": [1]}) if ok else None,
        error=None if ok else "cancelled at the capture budget",
        execution_time_ms=1.0,
        row_count=1 if ok else 0,
    )


def test_failed_queries_are_not_done() -> None:
    async def go() -> tuple[int, int]:
        log = await CaptureLog.open(MemorySink(), {"window": "30d"})
        await log.record(_qr("A", ok=True), "d1")
        await log.record(_qr("B", ok=False), "d2")  # cancelled at the deadline
        log.note_finished("C")  # unavailable on the source: nothing to re-run
        return log.done, len({"A", "B", "C"}) - log.done

    done, remaining = asyncio.run(go())
    assert (done, remaining) == (2, 1)


def test_a_failed_then_succeeded_query_is_done_once() -> None:
    async def go() -> int:
        log = await CaptureLog.open(MemorySink(), {"window": "30d"})
        await log.record(_qr("A", ok=False), "d1")
        await log.record(_qr("A", ok=True), "d1")
        return log.done

    assert asyncio.run(go()) == 1
