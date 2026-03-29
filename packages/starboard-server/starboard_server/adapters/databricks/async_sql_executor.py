"""Async SQL executor adapter for analytics queries.

This module provides an async SQL executor that uses the AsyncDatabricksClient
for executing system table queries. Uses Polars DataFrames for performance.

This replaces the deprecated DatabricksSQLExecutor which used CachedDatabricksAPI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from starboard_server.exceptions import QueryExecutionError
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_server.adapters.databricks import AsyncDatabricksClient

logger = get_logger(__name__)


class AsyncSQLExecutor:
    """Async executor for SQL queries using AsyncDatabricksClient.

    This adapter uses the unified AsyncDatabricksClient for SQL execution,
    with built-in caching via CacheManager. Returns Polars DataFrames for
    efficient data processing.

    Example:
        >>> async with AsyncDatabricksClient() as client:
        ...     executor = AsyncSQLExecutor(client)
        ...     df = await executor.execute_sql(
        ...         sql="SELECT * FROM system.billing.usage LIMIT 10"
        ...     )
        ...     print(df.shape)
        (10, 15)
    """

    def __init__(
        self,
        client: AsyncDatabricksClient,
        *,
        default_cache_ttl: int = 300,
    ):
        """Initialize the async SQL executor.

        Args:
            client: AsyncDatabricksClient instance
            default_cache_ttl: Default cache TTL in seconds (default: 5 minutes)
        """
        self._client = client
        self._default_cache_ttl = default_cache_ttl

        logger.debug(
            "async_sql_executor_initialized",
            extra={
                "cache_ttl": default_cache_ttl,
            },
        )

    async def execute_sql(
        self,
        sql: str,
        result_columns: list[dict[str, Any]] | None = None,
        *,
        sql_cache_key: str | None = None,
        use_cache: bool = True,
        cache_ttl: int | None = None,
    ) -> pl.DataFrame:
        """Execute SQL query and return results as Polars DataFrame.

        Uses the AsyncDatabricksClient's streaming SQL execution with
        optional caching. Provides comprehensive logging at each step.

        Args:
            sql: SQL query to execute
            workspace_id: Optional workspace identifier (currently unused,
                         but included for interface compatibility)
            result_columns: Optional result column metadata from query_map
                         (includes data_type and semantic_type for type casting)
            use_cache: Whether to use caching (default: True)
            cache_ttl: Optional cache TTL override

        Returns:
            Polars DataFrame with query results

        Raises:
            Exception: If query execution fails
        """
        logger.debug(
            "async_sql_executor_starting",
            extra={
                "sql_length": len(sql),
                "sql_preview": sql[:300] + "..." if len(sql) > 300 else sql,
                "use_cache": use_cache,
            },
        )

        try:
            # Execute SQL using AsyncDatabricksClient
            # Use execute_sql for caching support, execute_polars directly for no caching
            ttl = cache_ttl if cache_ttl is not None else self._default_cache_ttl

            if use_cache:
                # Use client's execute_sql which wraps with caching
                df = await self._client.execute_sql(
                    sql,
                    cache_ttl=ttl,
                    sql_cache_key=sql_cache_key,
                )
            else:
                # Use SQL service directly without caching
                df = await self._client.sql.execute_polars(sql)

            # Apply type casting based on result_columns if provided
            if result_columns:
                df = self._apply_type_casting(df, result_columns)

            # Log detailed result information
            logger.debug(
                "async_sql_executor_completed",
                extra={
                    "shape": df.shape,
                    "row_count": len(df),
                    "column_count": len(df.columns),
                    "columns": df.columns,
                    "dtypes": {
                        col: str(dtype) for col, dtype in zip(df.columns, df.dtypes)
                    },
                    "memory_mb": df.estimated_size() / (1024 * 1024),
                    "is_empty": len(df) == 0,
                    # Log aggregations for cost columns
                    **self._log_cost_aggregations(df),
                },
            )

            return df

        except (QueryExecutionError, pl.exceptions.ComputeError) as e:
            logger.error(
                "async_sql_executor_failed",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "sql_preview": sql[:300] + "..." if len(sql) > 300 else sql,
                },
            )
            raise

    def _apply_type_casting(
        self,
        df: pl.DataFrame,
        result_columns: list[dict[str, Any]],
    ) -> pl.DataFrame:
        """Apply type casting based on result column metadata.

        Uses the shared :func:`resolve_polars_type` mapping from
        :mod:`~starboard_server.adapters.databricks.services.sql` to
        avoid duplicating the Databricks-SQL-type → Polars-type mapping.

        Args:
            df: Input DataFrame
            result_columns: Column metadata with data_type info

        Returns:
            DataFrame with properly typed columns
        """
        from starboard_server.adapters.databricks.services.sql import resolve_polars_type

        type_map: dict[str, type[pl.DataType]] = {}
        for col_info in result_columns:
            col_name = col_info.get("name")
            data_type = col_info.get("data_type", "")
            if col_name and col_name in df.columns:
                target = resolve_polars_type(data_type)
                if target is not None:
                    type_map[col_name] = target

        if type_map:
            try:
                df = df.cast(type_map)  # type: ignore[arg-type]
            except (QueryExecutionError, pl.exceptions.ComputeError) as e:
                logger.warning(
                    "type_casting_partial_failure",
                    extra={"error": str(e), "type_map": str(type_map)},
                )

        return df

    def _log_cost_aggregations(self, df: pl.DataFrame) -> dict[str, Any]:
        """Log aggregations for common cost/metric columns.

        Args:
            df: DataFrame to analyze

        Returns:
            Dictionary of aggregations for logging
        """
        aggregations = {}

        # Common cost/metric column patterns
        cost_patterns = ["cost", "price", "spend", "usage_quantity"]

        for col in df.columns:
            col_lower = col.lower()
            if (any(pattern in col_lower for pattern in cost_patterns)) and (
                df[col].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)
            ):
                try:
                    aggregations[f"{col}_total"] = float(df[col].sum())  # type: ignore[arg-type]
                    aggregations[f"{col}_avg"] = float(df[col].mean())  # type: ignore[arg-type]
                    aggregations[f"{col}_max"] = float(df[col].max())  # type: ignore[arg-type]
                    aggregations[f"{col}_min"] = float(df[col].min())  # type: ignore[arg-type]
                except (QueryExecutionError, pl.exceptions.ComputeError):
                    # Skip if aggregation fails (e.g., all nulls)
                    pass

        return aggregations


class MockAsyncSQLExecutor:
    """Mock async SQL executor for testing using Polars DataFrames.

    This executor returns mock Polars DataFrames for testing purposes without
    actually connecting to Databricks.

    Example:
        >>> executor = MockAsyncSQLExecutor()
        >>> df = await executor.execute_sql("SELECT * FROM table")
        >>> print(df.shape)
        (3, 3)
    """

    def __init__(self, mock_df: pl.DataFrame | None = None):
        """Initialize the mock executor.

        Args:
            mock_df: Optional mock DataFrame to return.
                    If None, returns default mock data.
        """
        self.mock_df = mock_df or pl.DataFrame(
            {
                "id": [1, 2, 3],
                "name": ["Test 1", "Test 2", "Test 3"],
                "value": [100.0, 200.0, 300.0],
            }
        )

    async def execute_sql(
        self,
        sql: str,
        workspace_id: str | None = None,  # noqa: ARG002
        result_columns: list[dict[str, Any]] | None = None,  # noqa: ARG002
        **kwargs,  # noqa: ARG002
    ) -> pl.DataFrame:
        """Execute mock SQL query.

        Args:
            sql: SQL query (ignored in mock)
            workspace_id: Workspace ID (ignored in mock)
            result_columns: Column metadata (ignored in mock)
            **kwargs: Additional arguments (ignored in mock)

        Returns:
            Mock Polars DataFrame
        """
        logger.debug(
            "mock_async_sql_execution",
            extra={
                "sql_preview": sql[:100],
                "result_shape": self.mock_df.shape,
                "result_columns": self.mock_df.columns,
            },
        )
        return self.mock_df
