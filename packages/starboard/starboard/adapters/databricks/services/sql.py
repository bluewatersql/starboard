# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Async SQL service implementation.

This module provides async SQL query execution on Databricks SQL Warehouses,
returning Polars DataFrames for efficient data processing.

Supports two execution modes:
- Streaming: Yields DataFrame batches as they download (memory efficient)
- Collected: Returns full DataFrame with optional max_rows safety limit

Result disposition strategy:
- Defaults to INLINE (results embedded in API response — no cloud storage)
- Falls back to EXTERNAL_LINKS when inline results are truncated
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any

import httpx
import polars as pl
import pyarrow as pa

from starboard.adapters.databricks.services.base import BaseService
from starboard.infra.observability.logging import get_logger
from starboard.infra.reliability.exceptions import DatabricksAPIError

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import (
        ExternalLink,
        StatementResponse,
    )

logger = get_logger(__name__)

# Default safety limit for non-streaming queries
DEFAULT_MAX_ROWS: int = 100_000

# Canonical mapping: Databricks SQL type_name → Polars dtype.
# Shared between SQLService (inline JSON_ARRAY parsing) and
# AsyncSQLExecutor (result_columns metadata casting).
DBSQL_TYPE_TO_POLARS: dict[str, type[pl.DataType]] = {
    "BYTE": pl.Int64, "TINYINT": pl.Int64,
    "SHORT": pl.Int64, "SMALLINT": pl.Int64,
    "INT": pl.Int64, "INTEGER": pl.Int64,
    "LONG": pl.Int64, "BIGINT": pl.Int64,
    "FLOAT": pl.Float64, "REAL": pl.Float64,
    "DOUBLE": pl.Float64,
    "DECIMAL": pl.Float64, "DEC": pl.Float64, "NUMERIC": pl.Float64,
    "NUMBER": pl.Float64,
    "BOOLEAN": pl.Boolean,
    "DATE": pl.Date,
    "DATETIME": pl.Datetime, "TIMESTAMP": pl.Datetime,
    "STRING": pl.Utf8, "VARCHAR": pl.Utf8, "TEXT": pl.Utf8,
}


def resolve_polars_type(sql_type: str | object) -> type[pl.DataType] | None:
    """Map a Databricks SQL type name to the corresponding Polars DataType.

    Handles parameterised types like ``DECIMAL(10,2)`` by stripping the
    parenthesised suffix before lookup.  Accepts both plain strings and
    Databricks SDK ``ColumnInfoTypeName`` enum instances.

    Args:
        sql_type: Databricks SQL type name (string or SDK enum).

    Returns:
        Polars DataType class, or ``None`` if the type is not mapped.
    """
    raw = sql_type.value if hasattr(sql_type, "value") else sql_type
    base = (str(raw) if raw else "").upper().split("(")[0].strip()
    return DBSQL_TYPE_TO_POLARS.get(base)


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
        """Execute SQL query and yield DataFrame batches.

        Uses INLINE disposition by default (no S3 round-trip).  Falls back to
        EXTERNAL_LINKS automatically when inline results are truncated.

        Args:
            query: SQL query to execute
            warehouse_id: Override warehouse ID (uses default if None)
            wait_timeout: Maximum time to wait for query completion

        Yields:
            Polars DataFrame batches

        Raises:
            TimeoutError: If query exceeds wait timeout
            RuntimeError: If query execution fails
        """
        try:
            stmt = await self._execute_statement(query, warehouse_id, wait_timeout)
        except RuntimeError as exc:
            if "Inline byte limit exceeded" in str(exc):
                logger.info(
                    "sql_inline_byte_limit_retrying_external",
                    extra={"query_preview": query[:100]},
                )
                stmt = await self._execute_statement(
                    query, warehouse_id, wait_timeout, disposition="EXTERNAL_LINKS"
                )
                if stmt.result and stmt.result.external_links:
                    async for batch_df in self._stream_external_links(stmt):
                        yield batch_df
                return
            raise
        statement_id = stmt.statement_id

        # ── Try inline result first ──────────────────────────────────
        inline_df = self._parse_inline_result(stmt)
        if inline_df is not None:
            truncated = getattr(stmt.result, "truncated", False) if stmt.result else False
            if truncated:
                logger.info(
                    "sql_inline_truncated_falling_back",
                    extra={
                        "statement_id": statement_id,
                        "inline_rows": len(inline_df),
                        "query_preview": query[:100],
                    },
                )
            else:
                logger.debug(
                    "sql_inline_result",
                    extra={
                        "statement_id": statement_id,
                        "rows": len(inline_df),
                        "columns": inline_df.columns,
                    },
                )
                yield inline_df
                return

        # ── Check for external_links in the same response ───────────
        has_external = (
            stmt.result
            and stmt.result.external_links
            and len(stmt.result.external_links) > 0
        )
        if has_external:
            async for batch_df in self._stream_external_links(stmt):
                yield batch_df
            return

        # ── Fallback: re-execute with EXTERNAL_LINKS ─────────────────
        logger.info(
            "sql_no_inline_retrying_external",
            extra={
                "statement_id": statement_id,
                "query_preview": query[:100],
            },
        )
        stmt = await self._execute_statement(
            query, warehouse_id, wait_timeout, disposition="EXTERNAL_LINKS"
        )

        if not stmt.result or not stmt.result.external_links:
            logger.warning(
                "sql_no_results",
                extra={
                    "statement_id": stmt.statement_id,
                    "query_preview": query[:100],
                },
            )
            return

        async for batch_df in self._stream_external_links(stmt):
            yield batch_df

    # ── Inline result parsing ────────────────────────────────────────

    @staticmethod
    def _parse_inline_result(stmt: StatementResponse) -> pl.DataFrame | None:
        """Extract a DataFrame from an INLINE statement response.

        Handles both ARROW_STREAM chunks (base64-encoded IPC) and
        JSON_ARRAY ``data_array`` payloads.

        Returns:
            DataFrame if inline data was present, else ``None``.
        """
        if not stmt.result:
            return None

        # ARROW_STREAM inline: result.chunk.data_array holds base64 Arrow IPC
        chunk = getattr(stmt.result, "chunk", None)
        if chunk is not None:
            data_array = getattr(chunk, "data_array", None)
            if data_array:
                try:
                    raw = base64.b64decode(data_array)
                    table = pa.ipc.open_stream(BytesIO(raw)).read_all()
                    result = pl.from_arrow(table)
                    return result if isinstance(result, pl.DataFrame) else pl.DataFrame(result)
                except Exception:  # noqa: BLE001
                    logger.debug("sql_inline_arrow_parse_failed", exc_info=True)

        # JSON_ARRAY inline: result.data_array holds list[list[str]]
        data_array_json = getattr(stmt.result, "data_array", None)
        if data_array_json:
            manifest = getattr(stmt, "manifest", None)
            columns: list[str] = []
            col_types: list[str] = []
            if manifest and hasattr(manifest, "schema") and manifest.schema:
                schema_obj = manifest.schema
                col_list = getattr(schema_obj, "columns", None)
                if col_list:
                    columns = [c.name for c in col_list if hasattr(c, "name")]
                    col_types = [
                        getattr(c, "type_name", "STRING") or "STRING"
                        for c in col_list
                        if hasattr(c, "name")
                    ]
            if not columns:
                columns = [f"col_{i}" for i in range(len(data_array_json[0]))]

            data: dict[str, list[Any]] = {col: [] for col in columns}
            for row in data_array_json:
                for i, col in enumerate(columns):
                    data[col].append(row[i] if i < len(row) else None)
            df = pl.DataFrame(data)

            if col_types and len(col_types) == len(columns):
                df = SQLService._apply_manifest_types(df, columns, col_types)

            return df

        return None

    @staticmethod
    def _apply_manifest_types(
        df: pl.DataFrame,
        columns: list[str],
        col_types: list[str],
    ) -> pl.DataFrame:
        """Cast all-string columns to proper Polars types using manifest metadata.

        JSON_ARRAY results arrive as strings. Uses the shared
        :func:`resolve_polars_type` mapping to determine target types.
        Boolean columns need special handling because Polars cannot
        directly cast ``"true"``/``"false"`` strings via ``.cast(pl.Boolean)``.

        Args:
            df: DataFrame with all-string columns from JSON_ARRAY parsing.
            columns: Ordered list of column names.
            col_types: Corresponding Databricks SQL type names.

        Returns:
            DataFrame with properly typed columns.
        """
        cast_exprs: list[pl.Expr] = []
        for col_name, type_name in zip(columns, col_types):
            if col_name not in df.columns:
                continue
            target = resolve_polars_type(type_name)
            if target is None or target == pl.Utf8:
                continue
            if target == pl.Boolean:
                cast_exprs.append(
                    pl.when(pl.col(col_name) == "true")
                    .then(True)
                    .when(pl.col(col_name) == "false")
                    .then(False)
                    .otherwise(None)
                    .alias(col_name)
                )
            else:
                cast_exprs.append(pl.col(col_name).cast(target, strict=False))

        if cast_exprs:
            df = df.with_columns(cast_exprs)
        return df

    # ── External-links streaming ─────────────────────────────────────

    async def _stream_external_links(
        self,
        stmt: StatementResponse,
    ) -> AsyncIterator[pl.DataFrame]:
        """Download and yield batches from external links."""
        statement_id = stmt.statement_id
        if not stmt.result or not stmt.result.external_links:
            return

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
        disposition: str | None = None,
    ) -> StatementResponse:
        """Execute statement and wait for completion.

        Defaults to INLINE disposition (results in API response body,
        no cloud storage round-trip).  Falls back to EXTERNAL_LINKS
        when the caller explicitly requests it (e.g. for streaming
        large result sets).

        Args:
            query: SQL query to execute.
            warehouse_id: Override warehouse ID.
            wait_timeout: Maximum time to wait.
            disposition: ``"INLINE"`` (default) or ``"EXTERNAL_LINKS"``.

        Returns:
            Completed StatementResponse.

        Raises:
            TimeoutError: If query exceeds timeout.
            RuntimeError: If query fails.
        """
        from databricks.sdk.service import sql

        effective_warehouse_id = warehouse_id or self._warehouse_id
        if not effective_warehouse_id:
            raise ValueError(
                "warehouse_id must be provided either in constructor or as parameter"
            )
        stmt_api = self._client.statement_execution

        use_inline = disposition != "EXTERNAL_LINKS"
        if use_inline:
            fmt = sql.Format.JSON_ARRAY
            disp = sql.Disposition.INLINE
        else:
            fmt = sql.Format.ARROW_STREAM
            disp = sql.Disposition.EXTERNAL_LINKS

        stmt = await self._run_sync(
            lambda: stmt_api.execute_statement(
                statement=query,
                warehouse_id=effective_warehouse_id,
                wait_timeout=wait_timeout,
                format=fmt,
                disposition=disp,
            )
        )

        statement_id = stmt.statement_id

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
        """Download and parse a single Arrow chunk from an external link.

        Args:
            http_client: Async HTTP client
            link_info: External link info with presigned URL

        Returns:
            Parsed Polars DataFrame, or None if no data

        Raises:
            DatabricksAPIError: On 403 (cloud storage permission denied).
        """
        external_url = link_info.external_link
        if external_url is None:
            return None

        response = await http_client.get(external_url)
        if response.status_code == 403:
            raise DatabricksAPIError(
                message=(
                    "403 Forbidden downloading query results from cloud storage. "
                    "Check service principal / token storage permissions."
                ),
                details={"url_host": httpx.URL(external_url).host},
            )
        response.raise_for_status()

        if not response.content:
            return None

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

        from starboard.infra.constraints.utils import DateTimeUtils

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
                    max_results=1000,  # cap pages to avoid exhausting all history
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
