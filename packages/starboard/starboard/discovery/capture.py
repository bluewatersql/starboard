# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery capture log: per-query progress kept in the run sink for resume.

A ``--run-folder`` capture records every finished query in
:data:`~starboard_core.domain.models.discovery.capture.PROGRESS_PATH` (rows of a
succeeded query under ``capture/queries/<id>.arrow``) so re-running the same
command reuses that work. The record is keyed by the run, source/scope, window and
pack selection; a different key starts fresh and says why. Each entry also holds
the digest of the SQL it ran, so a query whose SQL changed runs again.

Entry states: ``succeeded`` (rows reused), ``skipped`` (replayed as-is) and
``failed`` (attempted again). An entry with no state has only its statement
timeouts so far (``timeout_attempt_ms``); they count against the query's timeout
retries on the next run.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import polars as pl
from starboard_core.domain.models.discovery.capture import (
    CAPTURE_DIR,
    PROGRESS_PATH,
    PROGRESS_SCHEMA,
)
from starboard_core.domain.models.discovery.query import QueryResult
from starboard_core.ports.engagement_storage import StorageNotFoundError

from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_core.engagement.sink import ArtifactSink

logger = get_logger(__name__)

_JSON_MIME = "application/json"
_ARROW_MIME = "application/vnd.apache.arrow.file"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_TERMINAL = ("succeeded", "skipped", "failed")


def sql_digest(sql: str) -> str:
    """Digest of the SQL a query ran (a changed statement is not reused)."""
    return hashlib.sha256(sql.encode()).hexdigest()


def _data_path(query_id: str) -> str:
    return f"{CAPTURE_DIR}/queries/{_UNSAFE.sub('_', query_id)}.arrow"


class CaptureLog:
    """The capture's progress record in a run sink (open with :meth:`open`).

    All sink I/O runs off the event loop. Progress writes are coalesced: callers
    that arrive while one is in progress are covered by the next single write.

    Attributes:
        reused: Queries this run took from the record instead of running them.
        fresh_reason: Why an existing record was not used, else ``None``.
    """

    def __init__(
        self,
        sink: ArtifactSink,
        key: Mapping[str, Any],
        queries: dict[str, dict[str, Any]],
        fresh_reason: str | None,
    ) -> None:
        self._sink = sink
        self._key = dict(key)
        self._queries = queries
        self.fresh_reason = fresh_reason
        self.reused = 0
        self._finished: set[str] = set()
        self._lock = asyncio.Lock()
        self._dirty = False

    @classmethod
    async def open(cls, sink: ArtifactSink, key: Mapping[str, Any]) -> CaptureLog:
        """Load the record for ``key`` from ``sink``; a missing or other record is fresh."""
        try:
            raw = await asyncio.to_thread(sink.get_bytes, PROGRESS_PATH)
        except StorageNotFoundError:
            return cls(sink, key, {}, None)
        try:
            record = json.loads(raw)
            stored_key = record["key"]
            queries = record["queries"]
            if not isinstance(stored_key, dict) or not isinstance(queries, dict):
                raise TypeError("key/queries are not objects")
        except (ValueError, KeyError, TypeError) as exc:
            return cls(
                sink, key, {}, f"the saved progress record is unreadable ({exc})"
            )
        differs = sorted(
            name
            for name in set(stored_key) | set(key)
            if stored_key.get(name) != key.get(name)
        )
        if differs:
            return cls(
                sink,
                key,
                {},
                f"the saved progress is for a different capture ({', '.join(differs)} "
                "changed); starting fresh",
            )
        return cls(sink, key, queries, None)

    @property
    def done(self) -> int:
        """Queries a resume will not run again: succeeded, skipped or unavailable on
        the source, reused ones included. A failed query (a statement cancelled at
        the budget) is re-run on resume, so it is not done."""
        return len(self._finished)

    def prior_timeouts(self, query_id: str, digest: str) -> tuple[float, ...]:
        """Wall-clock ms of the earlier runs' timed-out attempts of this statement."""
        entry = self._queries.get(query_id)
        if entry is None or entry.get("sql_digest") != digest:
            return ()
        return tuple(float(ms) for ms in entry.get("timeout_attempt_ms", ()))

    def note_finished(self, query_id: str) -> None:
        """Count a query that finished without a record (unavailable on the source)."""
        self._finished.add(query_id)

    async def reuse(
        self, query_id: str, domain: str, digest: str
    ) -> QueryResult | None:
        """The recorded result of this statement, or ``None`` when it must run.

        A succeeded entry whose rows cannot be read is run again.
        """
        entry = self._queries.get(query_id)
        if entry is None or entry.get("sql_digest") != digest:
            return None
        status = entry.get("status")
        if status not in ("succeeded", "skipped"):
            return None
        data: pl.DataFrame | None = None
        if status == "succeeded":
            try:
                raw = await asyncio.to_thread(self._sink.get_bytes, entry["data"])
                data = pl.read_ipc(io.BytesIO(raw))
            except Exception as exc:  # noqa: BLE001 - missing/corrupt rows run again
                logger.warning(
                    "capture_rows_unreadable", query_id=query_id, error=str(exc)
                )
                return None
        self.reused += 1
        self._finished.add(query_id)
        return QueryResult(
            query_id=query_id,
            domain=domain,
            data=data,
            error=entry.get("error"),
            execution_time_ms=float(entry.get("execution_time_ms", 0.0)),
            row_count=int(entry.get("row_count", 0)),
            skipped=status == "skipped",
            result_limit=entry.get("result_limit"),
            lookback_days=entry.get("lookback_days"),
            attempts=int(entry.get("attempts", 0)),
            attempt_elapsed_ms=tuple(entry.get("attempt_elapsed_ms", ())),
        )

    async def note_timeout(self, query_id: str, digest: str, elapsed_ms: float) -> None:
        """Record one timed-out attempt now (it counts even if the run is stopped)."""
        entry = self._entry(query_id, digest)
        entry.setdefault("timeout_attempt_ms", []).append(round(elapsed_ms, 1))
        await self.flush()

    async def record(self, qr: QueryResult, digest: str) -> None:
        """Record a finished query; a succeeded one only once its rows are stored."""
        if qr.succeeded:
            status = "succeeded"
        elif qr.skipped:
            status = "skipped"
        else:
            status = "failed"
        # Done only once a resume would reuse it: a failed query, or a succeeded one
        # whose rows could not be stored, runs again.
        self._finished.discard(qr.query_id)
        fields: dict[str, Any] = {
            "domain": qr.domain,
            "error": qr.error,
            "row_count": qr.row_count,
            "execution_time_ms": round(qr.execution_time_ms, 1),
            "result_limit": qr.result_limit,
            "lookback_days": qr.lookback_days,
            "attempts": qr.attempts,
            "attempt_elapsed_ms": list(qr.attempt_elapsed_ms),
        }
        if status == "succeeded":
            path = _data_path(qr.query_id)
            try:
                buf = io.BytesIO()
                assert qr.data is not None  # noqa: S101 - succeeded implies rows
                qr.data.write_ipc(buf, compression="zstd")
            except Exception as exc:  # noqa: BLE001 - unstorable rows just re-run
                logger.warning(
                    "capture_rows_not_stored", query_id=qr.query_id, error=str(exc)
                )
                return
            await asyncio.to_thread(
                self._sink.put_bytes, path, buf.getvalue(), _ARROW_MIME
            )
            fields["data"] = path
        entry = self._entry(qr.query_id, digest)
        entry.update(fields)
        entry["status"] = status
        if status != "failed":
            self._finished.add(qr.query_id)
        await self.flush()

    async def flush(self) -> None:
        """Write the record if it changed since the last write."""
        self._dirty = True
        async with self._lock:
            if not self._dirty:
                return
            self._dirty = False
            payload = {
                "schema": PROGRESS_SCHEMA,
                "updated_at": datetime.now(UTC).isoformat(),
                "key": self._key,
                "queries": self._queries,
            }
            data = json.dumps(payload, sort_keys=True, default=str).encode()
            await asyncio.to_thread(
                self._sink.put_bytes, PROGRESS_PATH, data, _JSON_MIME
            )

    def summary(self) -> dict[str, Any]:
        """``{queries_reused, fresh_reason?}`` for the run summary."""
        out: dict[str, Any] = {"queries_reused": self.reused}
        if self.fresh_reason:
            out["fresh_reason"] = self.fresh_reason
        return out

    def _entry(self, query_id: str, digest: str) -> dict[str, Any]:
        entry = self._queries.get(query_id)
        if entry is None or entry.get("sql_digest") != digest:
            entry = {"sql_digest": digest}
            self._queries[query_id] = entry
        if entry.get("status") in _TERMINAL:
            # A finished entry being written again (a failed query re-attempted):
            # its earlier outcome no longer applies.
            entry.pop("status")
        return entry
