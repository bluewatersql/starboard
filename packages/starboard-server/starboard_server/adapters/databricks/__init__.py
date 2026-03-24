"""Databricks client package.

Provides unified async access to Databricks APIs.

Main Entry Point:
    AsyncDatabricksClient - Unified async client with integrated caching
    AsyncSQLExecutor - Async SQL executor adapter for analytics

Usage:
    >>> from starboard_server.adapters.databricks import AsyncDatabricksClient
    >>>
    >>> async with AsyncDatabricksClient(cfg=config) as client:
    ...     job = await client.get_job(12345)
    ...     df = await client.execute_sql("SELECT 1")
"""

from starboard_server.adapters.databricks.async_sql_executor import (
    AsyncSQLExecutor,
    MockAsyncSQLExecutor,
)
from starboard_server.adapters.databricks.client import AsyncDatabricksClient

__all__ = [
    "AsyncDatabricksClient",
    "AsyncSQLExecutor",
    "MockAsyncSQLExecutor",
]
