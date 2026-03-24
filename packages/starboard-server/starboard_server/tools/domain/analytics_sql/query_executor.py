"""Analytics SQL - Query Executor.

Wraps SQL execution with specific error handling, retries, and result transformation.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

import polars as pl

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class SQLExecutor(Protocol):
    """Protocol for SQL execution."""

    async def execute_sql(
        self,
        sql: str,
        workspace_id: str | None = None,
        **kwargs: Any,
    ) -> pl.DataFrame:
        """Execute SQL query.

        Args:
            sql: SQL query to execute
            workspace_id: Optional workspace ID
            **kwargs: Additional executor-specific arguments

        Returns:
            Polars DataFrame with results
        """
        ...


class AnalyticsQueryExecutor:
    """Executor for analytics queries with error handling and retries.

    This adapter wraps SQL execution with:
    - Automatic retries for transient errors
    - Result transformation (DataFrame → dict)
    - Execution metadata (timing, row counts)
    - Error handling with detailed messages
    - Result limiting and truncation

    Example:
        >>> executor = AnalyticsQueryExecutor(
        ...     sql_executor=sql_executor,
        ...     max_retries=3,
        ...     timeout_seconds=30
        ... )
        >>>
        >>> result = await executor.execute(
        ...     "SELECT warehouse_id, SUM(total_cost_usd) FROM ..."
        ... )
        >>> print(f"Rows: {result['row_count']}")
        >>> print(f"Time: {result['execution_time_ms']}ms")
    """

    def __init__(
        self,
        sql_executor: SQLExecutor,
        max_retries: int = 3,
        timeout_seconds: int = 30,
    ):
        """Initialize query executor.

        Args:
            sql_executor: SQL executor implementation
            max_retries: Maximum retry attempts for transient errors
            timeout_seconds: Query timeout in seconds

        Example:
            >>> executor = AnalyticsQueryExecutor(
            ...     sql_executor=databricks_executor,
            ...     max_retries=3,
            ...     timeout_seconds=30
            ... )
        """
        self.sql_executor = sql_executor
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    async def execute(
        self,
        sql: str,
        workspace_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Execute SQL query with error handling and retries.

        Args:
            sql: SQL query to execute
            workspace_id: Optional workspace ID for filtering
            limit: Optional result limit (truncate if needed)

        Returns:
            Dict with:
                - success: bool - Whether execution succeeded
                - results: list[dict] - Query results (empty if error)
                - row_count: int - Number of rows returned
                - column_names: list[str] - Column names
                - execution_time_ms: float - Execution time
                - error: str - Error message (if failed)
                - truncated: bool - Whether results were truncated
                - total_row_count: int - Total rows before limit

        Example:
            >>> result = await executor.execute(
            ...     "SELECT * FROM system.billing.usage LIMIT 10"
            ... )
            >>> if result["success"]:
            ...     print(f"Got {result['row_count']} rows")
        """
        # Validate input
        if not sql or not sql.strip():
            return {
                "success": False,
                "error": "SQL query cannot be empty",
                "results": [],
                "row_count": 0,
            }

        start_time = time.perf_counter()

        # Execute with retries
        for attempt in range(self.max_retries + 1):
            try:
                # Execute SQL
                df = await self.sql_executor.execute_sql(
                    sql=sql,
                    workspace_id=workspace_id,
                )

                # Calculate timing
                execution_time_ms = (time.perf_counter() - start_time) * 1000

                # Transform results
                return self._transform_result(
                    df=df,
                    execution_time_ms=execution_time_ms,
                    limit=limit,
                )

            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    "query_execution_failed",
                    extra={
                        "attempt": attempt + 1,
                        "max_retries": self.max_retries,
                        "error": error_msg,
                        "sql_preview": sql[:100],
                    },
                )

                # If this was the last attempt, return error
                if attempt >= self.max_retries:
                    execution_time_ms = (time.perf_counter() - start_time) * 1000
                    return {
                        "success": False,
                        "error": f"Query execution failed after {self.max_retries + 1} attempts: {error_msg}",
                        "results": [],
                        "row_count": 0,
                        "execution_time_ms": execution_time_ms,
                    }

                # Wait before retry (exponential backoff)
                wait_time = 0.5 * (2**attempt)
                await asyncio.sleep(wait_time)

        # Should never reach here, but just in case
        return {
            "success": False,
            "error": "Query execution failed unexpectedly",
            "results": [],
            "row_count": 0,
        }

    def _transform_result(
        self,
        df: pl.DataFrame,
        execution_time_ms: float,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Transform DataFrame to result dict.

        Args:
            df: Polars DataFrame
            execution_time_ms: Execution time in milliseconds
            limit: Optional row limit

        Returns:
            Result dict with transformed data
        """
        total_row_count = len(df)
        truncated = False

        # Apply limit if specified
        if limit is not None and total_row_count > limit:
            df = df.head(limit)
            truncated = True

        # Convert to list of dicts
        results = df.to_dicts()

        # Build result
        result = {
            "success": True,
            "results": results,
            "row_count": len(results),
            "column_names": df.columns,
            "execution_time_ms": round(execution_time_ms, 2),
        }

        # Add truncation info if applicable
        if truncated:
            result["truncated"] = True
            result["total_row_count"] = total_row_count

        return result
