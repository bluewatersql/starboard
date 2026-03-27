"""Async SQL service implementation.

This module provides async SQL query execution on Databricks SQL Warehouses,
returning Polars DataFrames for efficient data processing.

Supports two execution modes:
- Streaming: Yields DataFrame batches as they download (memory efficient)
- Collected: Returns full DataFrame with optional max_rows safety limit
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import polars as pl
import pyarrow as pa

from starboard_server.adapters.databricks.services.base import BaseService
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.reliability.exceptions import DatabricksAPIError

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import (
        ExternalLink,
        StatementResponse,
    )

logger = get_logger(__name__)

# Default safety limit for non-streaming queries
DEFAULT_MAX_ROWS: int = 100_000


class RowLimitExceededError(Exception):
    """Raised when query results exceed the specified max_rows limit."""

    def __init__(self, row_count: int, max_rows: int) -> None:
        self.row_count = row_count
        self.max_rows = max_rows
        super().__init__(
            f"Query returned {row_count:,} rows, exceeding limit of {max_rows:,}. "
            f"Use execute_polars_streaming() for large results or increase max_rows."
        )


@dataclass
class StreamingResult:
    """Metadata about a streaming SQL execution."""

    statement_id: str | None
    total_batches: int
    total_rows: int
    columns: list[str]


class SQLService(BaseService):
    """Async service for Databricks SQL Warehouse operations.

    Provides async SQL execution with:
    - Streaming results via async generator (memory efficient for large datasets)
    - Collected results with configurable max_rows safety limit
    - Polars DataFrame results for efficient processing
    - Arrow format for optimal data transfer
    - External links disposition for chunked results

    Example (streaming - memory efficient):
        >>> service = SQLService(workspace_client, "warehouse-123")
        >>> async for batch in service.execute_polars_streaming("SELECT * FROM huge_table"):
        ...     process_batch(batch)  # Each batch is a Polars DataFrame

    Example (collected with safety limit):
        >>> df = await service.execute_polars("SELECT * FROM table", max_rows=50_000)
        >>> print(df.shape)
        (50000, 5)
    """

    def __init__(
        self,
        client: WorkspaceClient,
        http_client: httpx.AsyncClient | None = None,
        warehouse_id: str | None = None,
    ) -> None:
        """Initialize SQL service.

        Args:
            client: Authenticated Databricks WorkspaceClient
            warehouse_id: Default warehouse ID for query execution
        """
        super().__init__(client)
        self._warehouse_id = warehouse_id
        self._http_client = http_client

    @property
    def warehouse_id(self) -> str | None:
        """Get the configured warehouse ID."""
        return self._warehouse_id

    async def execute_polars_streaming(
        self,
        query: str,
        warehouse_id: str | None = None,
        wait_timeout: str = "50s",
    ) -> AsyncIterator[pl.DataFrame]:
        """Execute SQL query and yield DataFrame batches as they download.

        This is the memory-efficient streaming method. Each batch is yielded
        as soon as it's downloaded and parsed, avoiding loading the entire
        result set into memory.

        Args:
            query: SQL query to execute
            warehouse_id: Override warehouse ID (uses default if None)
            wait_timeout: Maximum time to wait for query completion

        Yields:
            Polars DataFrame batches (one per external link chunk)

        Raises:
            TimeoutError: If query exceeds wait timeout
            RuntimeError: If query execution fails

        Example:
            >>> total_rows = 0
            >>> async for batch in service.execute_polars_streaming(
            ...     "SELECT * FROM billion_row_table"
            ... ):
            ...     total_rows += len(batch)
            ...     # Process batch without holding all data in memory
            ...     save_to_parquet(batch, f"chunk_{total_rows}.parquet")
        """
        # Execute and wait for statement completion
        stmt = await self._execute_statement(query, warehouse_id, wait_timeout)
        statement_id = stmt.statement_id

        # Handle empty results
        if not stmt.result or not stmt.result.external_links:
            logger.warning(
                "sql_no_results",
                extra={
                    "statement_id": statement_id,
                    "query_preview": query[:100],
                },
            )
            return

        # Stream batches as they download
        batch_count = 0
        total_rows = 0
        columns: list[str] = []

        async with httpx.AsyncClient(timeout=60.0) as http_client:
            for link_info in stmt.result.external_links:
                batch_df = await self._download_and_parse_chunk(http_client, link_info)

                if batch_df is not None and len(batch_df) > 0:
                    batch_count += 1
                    total_rows += len(batch_df)
                    if not columns:
                        columns = batch_df.columns

                    logger.debug(
                        "sql_batch_yielded",
                        extra={
                            "statement_id": statement_id,
                            "batch_number": batch_count,
                            "batch_rows": len(batch_df),
                            "total_rows_so_far": total_rows,
                        },
                    )

                    yield batch_df

        logger.debug(
            "sql_streaming_completed",
            extra={
                "statement_id": statement_id,
                "total_batches": batch_count,
                "total_rows": total_rows,
                "columns": columns,
            },
        )

    async def execute_polars(
        self,
        query: str,
        warehouse_id: str | None = None,
        wait_timeout: str = "50s",
        max_rows: int | None = DEFAULT_MAX_ROWS,
    ) -> pl.DataFrame:
        """Execute SQL query and return collected Polars DataFrame.

        This method collects all streaming batches into a single DataFrame.
        Use `max_rows` as a safety limit to prevent accidental memory exhaustion.

        For large result sets, consider using `execute_polars_streaming()` instead.

        Args:
            query: SQL query to execute
            warehouse_id: Override warehouse ID (uses default if None)
            wait_timeout: Maximum time to wait for query completion
            max_rows: Maximum rows to collect (default: 100,000).
                      Set to None to disable the limit (use with caution).
                      Raises RowLimitExceededError if exceeded.

        Returns:
            Polars DataFrame with query results

        Raises:
            TimeoutError: If query exceeds wait timeout
            RuntimeError: If query execution fails
            RowLimitExceededError: If results exceed max_rows limit
        """
        effective_warehouse_id = warehouse_id or self.warehouse_id

        logger.debug(
            "sql_service_execute_sql",
            extra={
                "query_length": len(query),
                "query_preview": query[:100],
                "warehouse_id": effective_warehouse_id,
                "max_rows": max_rows,
            },
        )

        # Collect batches from streaming execution
        batches: list[pl.DataFrame] = []
        total_rows = 0

        async for batch in self.execute_polars_streaming(
            query=query,
            warehouse_id=warehouse_id,
            wait_timeout=wait_timeout,
        ):
            # Check row limit before adding batch
            if max_rows is not None and total_rows + len(batch) > max_rows:
                # We've exceeded the limit
                raise RowLimitExceededError(
                    row_count=total_rows + len(batch),
                    max_rows=max_rows,
                )

            batches.append(batch)
            total_rows += len(batch)

        # Combine all batches
        if not batches:
            return pl.DataFrame()

        df = batches[0] if len(batches) == 1 else pl.concat(batches)

        logger.debug(
            "sql_collected",
            extra={
                "row_count": len(df),
                "column_count": len(df.columns),
                "columns": df.columns,
                "batch_count": len(batches),
            },
        )

        return df

    async def _execute_statement(
        self,
        query: str,
        warehouse_id: str | None,
        wait_timeout: str,
    ) -> StatementResponse:
        """Execute statement and wait for completion.

        Internal method that handles statement execution and polling.

        Args:
            query: SQL query to execute
            warehouse_id: Override warehouse ID
            wait_timeout: Maximum time to wait

        Returns:
            Completed StatementResponse

        Raises:
            TimeoutError: If query exceeds timeout
            RuntimeError: If query fails
        """
        from databricks.sdk.service import sql

        effective_warehouse_id = warehouse_id or self._warehouse_id
        if not effective_warehouse_id:
            raise ValueError(
                "warehouse_id must be provided either in constructor or as parameter"
            )
        stmt_api = self._client.statement_execution

        # Execute statement
        stmt = await self._run_sync(
            lambda: stmt_api.execute_statement(
                statement=query,
                warehouse_id=effective_warehouse_id,
                wait_timeout=wait_timeout,
                format=sql.Format.ARROW_STREAM,
                disposition=sql.Disposition.EXTERNAL_LINKS,
            )
        )

        statement_id = stmt.statement_id

        # Poll until statement completes
        max_wait_seconds = 60
        poll_interval = 2
        elapsed = 0

        while stmt.status and stmt.status.state in [
            sql.StatementState.PENDING,
            sql.StatementState.RUNNING,
        ]:
            if elapsed >= max_wait_seconds:
                raise TimeoutError(f"Query exceeded {max_wait_seconds}s timeout")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            if statement_id:

                def get_stmt() -> sql.StatementResponse:
                    return stmt_api.get_statement(statement_id)

                stmt = await self._run_sync(get_stmt)

        # Check for failure
        if not stmt.status or stmt.status.state != sql.StatementState.SUCCEEDED:
            error_msg = (
                stmt.status.error.message
                if stmt.status and stmt.status.error
                else "Unknown error"
            )
            raise RuntimeError(f"Query failed: {error_msg}")

        return stmt

    async def _download_and_parse_chunk(
        self,
        http_client: httpx.AsyncClient,
        link_info: ExternalLink,
    ) -> pl.DataFrame | None:
        """Download and parse a single Arrow chunk.

        Args:
            http_client: Async HTTP client
            link_info: External link info with URL

        Returns:
            Parsed Polars DataFrame, or None if no data
        """
        external_url = link_info.external_link
        if external_url is None:
            return None

        response = await http_client.get(external_url)
        response.raise_for_status()

        if not response.content:
            return None

        # Parse Arrow data
        arrow_table = pa.ipc.open_stream(response.content).read_all()
        result = pl.from_arrow(arrow_table)

        return result if isinstance(result, pl.DataFrame) else pl.DataFrame(result)

    async def get_query(
        self,
        statement_id: str,
        include_metrics: bool = False,
        include_plan: bool = False,
    ) -> dict[str, Any] | None:
        """Get query by statement ID.

        Args:
            statement_id: Statement ID to get query for
            include_metrics: Include metrics
            include_plan: Include plan

        Returns:
            Query details dict, or None if not found
        """

        logger.debug("get_query", extra={"statement_id": statement_id})

        endpoint = f"/api/2.0/sql/history/queries/{statement_id}"
        params: dict[str, str] = {
            "include_plans": str(include_plan).lower(),
            "include_metrics": str(include_metrics).lower(),
        }

        if not self._http_client:
            raise ValueError("HTTP client not configured for SQL service")

        try:
            async with httpx.AsyncClient(
                base_url=str(self._http_client.base_url),
                headers=dict(self._http_client.headers),
                timeout=httpx.Timeout(30.0, connect=5.0),
            ) as client:
                response = await client.get(endpoint, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "get_query_failed",
                extra={"statement_id": statement_id, "error": str(e)},
            )
            raise DatabricksAPIError(
                message=f"Get Query from History failed for {statement_id}",
                details={"statement_id": statement_id, "error": str(e)},
            ) from e

    async def get_query_history(
        self,
        statement_id: str | None = None,
        warehouse_id: str | None = None,
        days_history: int | None = None,
    ) -> list[dict[str, Any]] | None:
        """Get query history with optional filters.

        Args:
            statement_id: Filter by specific statement ID
            warehouse_id: Filter by warehouse ID
            days_history: Number of days to look back

        Returns:
            List of query history entries, or None if not found

        Example:
            >>> history = await service.get_query_history(days_history=7)
            >>> for entry in history:
            ...     print(f"{entry['query_id']}: {entry['status']}")
        """
        from databricks.sdk.errors import NotFound
        from databricks.sdk.service import sql as dbsql

        from starboard_server.infra.constraints.utils import DateTimeUtils

        # Build filter
        filter_kwargs: dict[str, Any] = {}
        if statement_id:
            filter_kwargs["statement_ids"] = [statement_id]
        if warehouse_id:
            filter_kwargs["warehouse_ids"] = [warehouse_id]

        if days_history:
            start_ms, end_ms = DateTimeUtils.last_n_days_epoch_ms(days_history)
            filter_kwargs["query_start_time_range"] = dbsql.TimeRange(
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            )

        def _get_history() -> list[dict[str, Any]] | None:
            try:
                query_filter = dbsql.QueryFilter(**filter_kwargs)
                history = self._client.query_history.list(
                    include_metrics=True,
                    filter_by=query_filter,
                )
                result = history.as_dict().get("res", [])
                return list(result) if result else []
            except NotFound:
                logger.warning(
                    "query_history_not_found",
                    extra={"statement_id": statement_id},
                )
                return None

        return await self._run_sync(_get_history)
