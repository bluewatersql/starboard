# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tool-specific exceptions for the Starboard Agent.

.. deprecated::
    All exceptions have been consolidated into
    ``starboard_server.exceptions``.  Import from there instead.

This module re-exports everything from the canonical location for
backward compatibility.
"""

from __future__ import annotations

# Re-export everything from the canonical module for backward compatibility
from starboard_server.exceptions import (
    AccessDeniedError,
    AdapterError,
    AdapterResourceNotFoundError,
    ClusterNotFoundError,
    DatabricksAPIError,
    DataUnavailableError,
    JobNotFoundError,
    PermissionDeniedError,
    QueryExecutionError,
    ResourceNotFoundError,
    SparkLogsUnavailableError,
    TableNotFoundError,
    ToolError,
    ToolErrorResponse,
    ValidationError,
    WarehouseNotFoundError,
    wrap_databricks_error,
)

__all__ = [
    "AccessDeniedError",
    "AdapterError",
    "AdapterResourceNotFoundError",
    "ClusterNotFoundError",
    "DatabricksAPIError",
    "DataUnavailableError",
    "JobNotFoundError",
    "PermissionDeniedError",
    "QueryExecutionError",
    "ResourceNotFoundError",
    "SparkLogsUnavailableError",
    "TableNotFoundError",
    "ToolError",
    "ToolErrorResponse",
    "ValidationError",
    "WarehouseNotFoundError",
    "wrap_databricks_error",
]
