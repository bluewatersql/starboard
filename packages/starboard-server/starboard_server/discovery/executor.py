"""Query pack executor — parallel SQL execution with bounded concurrency.

Executes query packs against Databricks via AsyncDatabricksClient,
respecting concurrency limits and tracking execution metrics.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from starboard_core.domain.models.discovery.query import (
    PackResult,
    QueryPack,
    QueryResult,
)

from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    import polars as pl
    from starboard_core.domain.models.discovery.query import SystemQuery

logger = get_logger(__name__)


@runtime_checkable
class SQLExecutor(Protocol):
    """Protocol for executing SQL and returning Polars DataFrames."""

    async def execute_sql(self, sql: str) -> pl.DataFrame: ...


class QueryPackExecutor:
    """Executes query packs with bounded parallelism.

    Renders SQL templates with ``{lookback_days}``, executes via the
    provided ``SQLExecutor``, and collects results as ``PackResult`` objects.

    Args:
        sql_executor: Async SQL execution backend (e.g., ``AsyncDatabricksClient``).
        max_parallelism: Maximum concurrent SQL queries.
        default_lookback_days: Default time window when no override is set.
    """

    def __init__(
        self,
        sql_executor: SQLExecutor,
        max_parallelism: int = 4,
        default_lookback_days: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._sql_executor = sql_executor
        self._semaphore = asyncio.Semaphore(max_parallelism)
        self._default_lookback_days = default_lookback_days
        self._max_retries = max_retries

    async def execute_pack(self, pack: QueryPack) -> PackResult:
        """Execute all queries in a pack with bounded parallelism.

        Args:
            pack: The query pack to execute.

        Returns:
            PackResult with individual query results.
        """
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._execute_query(query, pack.domain))
                for query in pack.queries
            ]
        results = [t.result() for t in tasks]
        return PackResult(
            pack_id=pack.pack_id,
            domain=pack.domain,
            results=tuple(results),
        )

    async def execute_packs(
        self,
        packs: list[QueryPack],
    ) -> list[PackResult]:
        """Execute multiple packs with bounded parallelism.

        All queries across all packs share the same concurrency semaphore.

        Args:
            packs: Packs to execute.

        Returns:
            List of PackResults in input order.
        """
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(self.execute_pack(pack)) for pack in packs]
        return [t.result() for t in tasks]

    _TRANSIENT_ERROR_TYPES = (
        "ConnectError",
        "ConnectionError",
        "TimeoutError",
        "ReadTimeout",
        "ConnectTimeout",
        "ServerDisconnectedError",
    )

    async def _execute_query(
        self,
        query: SystemQuery,
        domain: str,
    ) -> QueryResult:
        """Execute a single query with semaphore, retry, and error handling.

        Retries up to ``_max_retries`` times on transient connection errors
        with exponential backoff. Non-transient errors fail immediately.

        Args:
            query: The system query to execute.
            domain: Domain for the result.

        Returns:
            QueryResult with data or error.
        """
        from starboard_core.domain.models.discovery.query import SystemQuery

        assert isinstance(query, SystemQuery)

        lookback = query.lookback_override or self._default_lookback_days
        rendered_sql = query.sql_template.format(lookback_days=lookback)

        async with self._semaphore:
            start = time.monotonic()
            last_exc: Exception | None = None

            for attempt in range(1, self._max_retries + 1):
                try:
                    df = await self._sql_executor.execute_sql(rendered_sql)
                    elapsed_ms = (time.monotonic() - start) * 1000
                    row_count = len(df) if df is not None else 0

                    logger.info(
                        "query_executed",
                        query_id=query.query_id,
                        domain=domain,
                        row_count=row_count,
                        execution_time_ms=round(elapsed_ms, 1),
                    )

                    return QueryResult(
                        query_id=query.query_id,
                        domain=domain,
                        data=df,
                        row_count=row_count,
                        execution_time_ms=elapsed_ms,
                    )

                except Exception as exc:  # noqa: BLE001 - retry loop with last_exc tracking
                    last_exc = exc
                    error_type = type(exc).__name__
                    is_transient = error_type in self._TRANSIENT_ERROR_TYPES

                    if is_transient and attempt < self._max_retries:
                        backoff = 2 ** (attempt - 1)
                        logger.warning(
                            "query_transient_error_retrying",
                            query_id=query.query_id,
                            domain=domain,
                            error_type=error_type,
                            attempt=attempt,
                            max_retries=self._max_retries,
                            backoff_s=backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue

                    break

            elapsed_ms = (time.monotonic() - start) * 1000
            error_msg = f"{type(last_exc).__name__}: {last_exc}"

            logger.warning(
                "query_failed",
                query_id=query.query_id,
                domain=domain,
                error=error_msg,
                execution_time_ms=round(elapsed_ms, 1),
                required=query.required,
            )

            return QueryResult(
                query_id=query.query_id,
                domain=domain,
                data=None,
                error=error_msg,
                execution_time_ms=elapsed_ms,
            )
