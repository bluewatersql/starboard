# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Query pack executor — parallel SQL execution with bounded concurrency.

Executes query packs against Databricks via AsyncDatabricksClient,
respecting concurrency limits and tracking execution metrics.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import re
import time
import types
from collections.abc import AsyncIterator, Callable, Generator
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    PackResult,
    QueryPack,
    QueryResult,
)

from starboard.discovery.query_cache import (
    DEFAULT_FRESHNESS_FLOOR_S,
    DiscoveryQueryCache,
)
from starboard.discovery.sources import (
    PreparedQuery,
    QuerySource,
    SystemTablesSource,
    Unavailable,
)
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    import polars as pl
    from starboard_core.domain.models.discovery.query import SystemQuery

logger = get_logger(__name__)


# Trailing ``LIMIT n`` of the outermost statement (optionally followed by ``;``).
_TRAILING_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\s*;?\s*\Z", re.IGNORECASE)


#: Bounded retries for a statement that hit its poll deadline (internal fleet
#: path, ``FleetStatementTimeout``). Policy: a dedicated fleet warehouse now
#: serves these statements, so a deadline miss is usually transient load and a
#: re-submission can succeed (the adapter cancels the timed-out statement first,
#: so retries never stack load). SQL errors are never retried. Overridable per
#: run via ``starboard --discover --timeout-retries N``.
DEFAULT_TIMEOUT_RETRIES = 2

#: Back-off (seconds) before each timeout retry, in order; the last value
#: repeats if more retries are configured than steps listed.
TIMEOUT_BACKOFF_S: tuple[float, ...] = (30.0, 60.0)

#: Max in-flight query ids listed in a heartbeat line before truncating.
MAX_IN_FLIGHT_IDS_SHOWN = 8


def _trailing_limit(sql: str) -> int | None:
    """Return the row cap of the statement's final ``LIMIT n``, if any."""
    match = _TRAILING_LIMIT.search(sql.strip())
    return int(match.group(1)) if match else None


@types.coroutine
def _yield_once() -> Generator[None, None, None]:
    """Yield to the event loop exactly once (a bare ``sleep(0)`` without a timer)."""
    yield


@runtime_checkable
class SQLExecutor(Protocol):
    """Protocol for executing SQL and returning Polars DataFrames."""

    async def execute_sql(self, sql: str) -> pl.DataFrame: ...


class QueryPackExecutor:
    """Executes query packs with bounded parallelism.

    Renders SQL templates with ``{lookback_days}`` and ``{result_limit}``,
    executes via the provided ``SQLExecutor``, and collects results as
    ``PackResult`` objects. Supports filtering by ``DiscoveryMode``.

    Args:
        sql_executor: Async SQL execution backend (e.g., ``AsyncDatabricksClient``).
        max_parallelism: Maximum concurrent SQL queries.
        default_lookback_days: Default time window when no override is set.
        max_retries: Maximum retry attempts for transient errors.
        discovery_mode: Controls which queries run (GENERAL or DEEP_DIVE).
        default_result_limit: Default row limit for queries using ``{result_limit}``.
        enable_cache: Dedupe identical scans within/across runs. When False
            (``--no-cache``) every query hits the SQL client directly.
        cache: Optional pre-built :class:`DiscoveryQueryCache`. When omitted and
            ``enable_cache`` is True, one is created with the freshness floor.
        cache_freshness_floor_s: Max age (seconds) a cached scan may be served.
        workspace_id: Workspace scope mixed into the cache key.
        source: Resolves where/how each query's SQL executes. Defaults to
            :class:`SystemTablesSource` (identity — run on ``sql_executor``),
            preserving today's behavior.
        timeout_retries: Re-submissions allowed after a poll-deadline timeout
            (``FleetStatementTimeout``). 0 disables timeout retries.
        timeout_backoff_s: Back-off before each timeout retry (seconds).
    """

    def __init__(
        self,
        sql_executor: SQLExecutor,
        max_parallelism: int = 4,
        default_lookback_days: int = 30,
        max_retries: int = 3,
        discovery_mode: DiscoveryMode = DiscoveryMode.GENERAL,
        default_result_limit: int = 50,
        *,
        enable_cache: bool = True,
        cache: DiscoveryQueryCache | None = None,
        cache_freshness_floor_s: int = DEFAULT_FRESHNESS_FLOOR_S,
        workspace_id: str | None = None,
        source: QuerySource | None = None,
        timeout_retries: int = DEFAULT_TIMEOUT_RETRIES,
        timeout_backoff_s: tuple[float, ...] = TIMEOUT_BACKOFF_S,
    ) -> None:
        self._sql_executor = sql_executor
        self._semaphore = asyncio.Semaphore(max_parallelism)
        self._default_lookback_days = default_lookback_days
        self._max_retries = max_retries
        self._discovery_mode = discovery_mode
        self._default_result_limit = default_result_limit
        self._workspace_id = workspace_id
        self._source: QuerySource = source or SystemTablesSource(sql_executor)
        self._timeout_retries = max(0, timeout_retries)
        self._timeout_backoff_s = timeout_backoff_s
        # Queries currently holding the semaphore (i.e. executing), in start
        # order. Read by the engine's Phase-2 heartbeat so a long quiet stretch
        # still shows liveness — and which statements are still running.
        self._in_flight_ids: list[str] = []
        if enable_cache:
            self._cache: DiscoveryQueryCache | None = cache or DiscoveryQueryCache(
                freshness_floor_s=cache_freshness_floor_s
            )
        else:
            self._cache = None

    @property
    def in_flight(self) -> int:
        """Number of queries executing right now (inside the concurrency cap)."""
        return len(self._in_flight_ids)

    @property
    def in_flight_ids(self) -> tuple[str, ...]:
        """Ids of the queries executing right now, oldest first."""
        return tuple(self._in_flight_ids)

    @contextlib.asynccontextmanager
    async def _slot(self, query_id: str = "") -> AsyncIterator[None]:
        """Acquire a concurrency slot and record ``query_id`` as in flight while held.

        A source may flag long poles via ``schedule_first`` (query ids whose
        latency is a fixed scan cost on that source). Every other query yields
        once before queueing for a slot, so all of a run's query tasks — created
        together — let the long poles take slots first: they overlap the run
        instead of extending its tail. Only those ids jump the queue; pack and
        result order are unchanged.
        """
        if query_id not in getattr(self._source, "schedule_first", ()):
            await _yield_once()
        async with self._semaphore:
            self._in_flight_ids.append(query_id)
            try:
                yield
            finally:
                self._in_flight_ids.remove(query_id)

    def eligible_queries(self, pack: QueryPack) -> list[SystemQuery]:
        """Queries of ``pack`` that will actually run under this discovery mode.

        GENERAL mode runs only GENERAL queries; DEEP_DIVE runs both. Exposed so
        callers (the engine's progress banner) report the same count that runs.
        """
        return [
            q for q in pack.queries
            if q.discovery_mode == DiscoveryMode.GENERAL
            or q.discovery_mode == self._discovery_mode
        ]

    async def execute_pack(
        self,
        pack: QueryPack,
        on_query_done: Callable[[str, str], None] | None = None,
        on_pack_done: Callable[[PackResult], None] | None = None,
    ) -> PackResult:
        """Execute eligible queries in a pack with bounded parallelism.

        Filters queries by ``discovery_mode``: when mode is GENERAL, only
        GENERAL queries run. When DEEP_DIVE, both GENERAL and DEEP_DIVE run.

        Args:
            pack: The query pack to execute.
            on_query_done: Optional ``(query_id, domain)`` callback fired once
                per query immediately after it completes (success, skip, or
                failure).  Used for per-query liveness progress in the CLI.
            on_pack_done: Optional callback fired once with the finished
                :class:`PackResult` when every query in the pack has completed
                (per-pack "done" progress lines).

        Returns:
            PackResult with individual query results.
        """
        eligible = self.eligible_queries(pack)
        if not eligible:
            empty = PackResult(pack_id=pack.pack_id, domain=pack.domain, results=())
            if on_pack_done is not None:
                on_pack_done(empty)
            return empty

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._execute_query(query, pack.domain, on_done=on_query_done))
                for query in eligible
            ]
        results = [t.result() for t in tasks]
        pack_result = PackResult(
            pack_id=pack.pack_id,
            domain=pack.domain,
            results=tuple(results),
        )
        if on_pack_done is not None:
            on_pack_done(pack_result)
        return pack_result

    async def execute_packs(
        self,
        packs: list[QueryPack],
        on_query_done: Callable[[str, str], None] | None = None,
        on_pack_done: Callable[[PackResult], None] | None = None,
    ) -> list[PackResult]:
        """Execute multiple packs with bounded parallelism.

        All queries across all packs share the same concurrency semaphore.

        Args:
            packs: Packs to execute.
            on_query_done: Optional ``(query_id, domain)`` callback fired once
                per completed query (success, skip, or failure).  Threaded
                into every :meth:`execute_pack` call so the caller can drive
                live progress displays.
            on_pack_done: Optional per-pack completion callback, threaded into
                every :meth:`execute_pack` call.

        Returns:
            List of PackResults in input order.
        """
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(
                    self.execute_pack(
                        pack, on_query_done=on_query_done, on_pack_done=on_pack_done
                    )
                )
                for pack in packs
            ]
        return [t.result() for t in tasks]

    #: Error types worth retrying with a short exponential back-off. These are
    #: network-level transients (a dropped connection / socket timeout) where an
    #: immediate retry can succeed. A fleet poll-deadline timeout
    #: (``FleetStatementTimeout``) is NOT in this list: it has its own bounded
    #: retry with a longer back-off (``timeout_retries`` / ``TIMEOUT_BACKOFF_S``).
    _TRANSIENT_ERROR_TYPES = (
        "ConnectError",
        "ConnectionError",
        "TimeoutError",
        "ReadTimeout",
        "ConnectTimeout",
        "ServerDisconnectedError",
    )

    #: Timeouts retried with back-off (``timeout_retries``) and, if every attempt
    #: times out, reported as *unavailable* (a coverage gap / skip) rather than a
    #: hard failure. Scoped to the INTERNAL fleet path only: the fleet adapter
    #: raises ``FleetStatementTimeout`` when a statement exceeds its poll deadline
    #: on the fleet warehouse — a best-effort miss under load. A bare
    #: ``TimeoutError`` (the EXTERNAL customer path, e.g.
    #: ``AsyncSQLExecutor``) is deliberately EXCLUDED so a genuine customer-query
    #: timeout stays a real failure — never silently masked as a coverage gap.
    _TIMEOUT_ERROR_TYPES = ("FleetStatementTimeout",)

    def _make_render(self, lookback: int) -> Callable[[str], str]:
        """Build the placeholder renderer for this run's lookback.

        Substitutes ``{lookback_days}`` / ``{result_limit}`` via ``format_map``
        with a ``defaultdict`` so a template missing a placeholder doesn't raise
        ``KeyError``. Returned as a callable so a ``QuerySource`` can render an
        alternative template (e.g. an internal override) with the *same*
        parameters — never shipping raw ``{…}`` placeholders to the warehouse.
        """
        params = {
            "lookback_days": lookback,
            "result_limit": self._default_result_limit,
        }
        return lambda template: template.format_map(
            collections.defaultdict(str, params)
        )

    def _render_sql(self, query: SystemQuery, lookback: int) -> str:
        """Render a query's own SQL template with known placeholders."""
        return self._make_render(lookback)(query.sql_template)

    async def _execute_query(
        self,
        query: SystemQuery,
        domain: str,
        on_done: Callable[[str, str], None] | None = None,
    ) -> QueryResult:
        """Execute a single query with semaphore, retry, and error handling.

        Retries up to ``_max_retries`` times on transient connection errors
        with exponential backoff, and up to ``timeout_retries`` times on a
        poll-deadline timeout with the ``timeout_backoff_s`` schedule. Every
        submission is recorded (``attempts`` / ``attempt_elapsed_ms``). Other
        errors (e.g. SQL errors) fail immediately.

        Args:
            query: The system query to execute.
            domain: Domain for the result.
            on_done: Optional ``(query_id, domain)`` callback fired once the
                query completes (success, skip, or failure).  Used by the
                engine's per-query liveness tracker (D4).

        Returns:
            QueryResult with data or error.
        """
        from starboard_core.domain.models.discovery.query import SystemQuery

        assert isinstance(query, SystemQuery)

        lookback = query.lookback_override or self._default_lookback_days
        # G5: clamp to the source table's retention so a larger configured or
        # overridden lookback never silently returns empty results.
        if query.max_lookback_days is not None:
            lookback = min(lookback, query.max_lookback_days)
        render = self._make_render(lookback)
        rendered_sql = render(query.sql_template)

        # Pass the renderer so a source swapping in an alternative template
        # (e.g. an internal override) substitutes the same placeholders.
        prepared = self._source.prepare(query, rendered_sql, render)
        if isinstance(prepared, Unavailable):
            # An unavailable query is an expected coverage gap on the selected
            # source, not a failure — mark it skipped so it is reported honestly.
            _qr = QueryResult(
                query_id=query.query_id,
                domain=domain,
                data=None,
                error=f"unavailable on internal source: {prepared.reason}",
                skipped=True,
                lookback_days=lookback,
            )
            if on_done is not None:
                on_done(query.query_id, domain)
            return _qr

        assert isinstance(prepared, PreparedQuery)
        run_sql, executor = prepared.sql, prepared.executor
        # A source may serve a shorter window than requested (a cheaper mirror
        # shape) — report the window the rows actually cover.
        if prepared.lookback_days is not None:
            lookback = prepared.lookback_days
        # The SQL ``LIMIT`` this query actually ran with, so a result that fills
        # it can be flagged. Parsed off the final SQL (not keyed on the
        # ``{result_limit}`` placeholder) so literal caps like ``LIMIT 500`` and
        # internal overrides are covered too.
        result_limit = _trailing_limit(run_sql)

        attempts_ms: list[float] = []
        last_exc: Exception | None = None
        transient_failures = 0
        timeout_retries_used = 0

        while True:
            # One slot per submission: back-off sleeps happen OUTSIDE the slot
            # so a retrying query never blocks the rest of the run.
            async with self._slot(query.query_id):
                try:
                    df = await self._submit(run_sql, executor, attempts_ms)
                except Exception as exc:  # noqa: BLE001 - classified below for retry / report
                    last_exc = exc
                else:
                    elapsed_ms = sum(attempts_ms)
                    row_count = len(df) if df is not None else 0
                    logger.info(
                        "query_executed",
                        query_id=query.query_id,
                        domain=domain,
                        row_count=row_count,
                        execution_time_ms=round(elapsed_ms, 1),
                        attempts=len(attempts_ms),
                    )
                    _qr = QueryResult(
                        query_id=query.query_id,
                        domain=domain,
                        data=df,
                        row_count=row_count,
                        execution_time_ms=elapsed_ms,
                        result_limit=result_limit,
                        lookback_days=lookback,
                        attempts=len(attempts_ms),
                        attempt_elapsed_ms=tuple(round(ms, 1) for ms in attempts_ms),
                    )
                    if on_done is not None:
                        on_done(query.query_id, domain)
                    return _qr

            error_type = type(last_exc).__name__
            if (
                error_type in self._TIMEOUT_ERROR_TYPES
                and timeout_retries_used < self._timeout_retries
            ):
                backoff = self._timeout_backoff(timeout_retries_used)
                timeout_retries_used += 1
                logger.warning(
                    "query_timeout_retrying",
                    query_id=query.query_id,
                    domain=domain,
                    attempt=len(attempts_ms),
                    timeout_retries=self._timeout_retries,
                    backoff_s=backoff,
                    last_attempt_ms=round(attempts_ms[-1], 1),
                )
                await asyncio.sleep(backoff)
                continue
            if error_type in self._TRANSIENT_ERROR_TYPES:
                transient_failures += 1
                if transient_failures < self._max_retries:
                    backoff = 2 ** (transient_failures - 1)
                    logger.warning(
                        "query_transient_error_retrying",
                        query_id=query.query_id,
                        domain=domain,
                        error_type=error_type,
                        attempt=transient_failures,
                        max_retries=self._max_retries,
                        backoff_s=backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
            break

        elapsed_ms = sum(attempts_ms)
        attempts = len(attempts_ms)
        # A statement timeout that survived every bounded retry is an expected
        # coverage gap on the fleet endpoint — report it as unavailable
        # (skipped) with the reason, not as a failure.
        is_timeout = type(last_exc).__name__ in self._TIMEOUT_ERROR_TYPES
        if is_timeout:
            tries = f" after {attempts} attempts" if attempts > 1 else ""
            error_msg = f"unavailable: statement timed out{tries} ({last_exc})"
        else:
            error_msg = f"{type(last_exc).__name__}: {last_exc}"

        logger.warning(
            "query_unavailable" if is_timeout else "query_failed",
            query_id=query.query_id,
            domain=domain,
            error=error_msg,
            execution_time_ms=round(elapsed_ms, 1),
            attempts=attempts,
            required=query.required,
        )

        _qr = QueryResult(
            query_id=query.query_id,
            domain=domain,
            data=None,
            error=error_msg,
            execution_time_ms=elapsed_ms,
            skipped=is_timeout,
            lookback_days=lookback,
            attempts=attempts,
            attempt_elapsed_ms=tuple(round(ms, 1) for ms in attempts_ms),
        )
        if on_done is not None:
            on_done(query.query_id, domain)
        return _qr

    def _timeout_backoff(self, retry_index: int) -> float:
        """Back-off (seconds) before timeout retry ``retry_index`` (0-based).

        Walks :attr:`_timeout_backoff_s`; the last value repeats when more
        retries than back-off steps are configured.
        """
        if not self._timeout_backoff_s:
            return 0.0
        return self._timeout_backoff_s[min(retry_index, len(self._timeout_backoff_s) - 1)]

    async def _submit(
        self, run_sql: str, executor: SQLExecutor, attempts_ms: list[float]
    ) -> pl.DataFrame:
        """Submit the statement once, appending its wall-clock time to ``attempts_ms``."""
        start = time.monotonic()
        try:
            if self._cache is not None:
                key = self._cache.make_key(run_sql, self._workspace_id)
                return await self._cache.get_or_execute(
                    key, lambda: executor.execute_sql(run_sql)
                )
            return await executor.execute_sql(run_sql)
        finally:
            attempts_ms.append((time.monotonic() - start) * 1000)
