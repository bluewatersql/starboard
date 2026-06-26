# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Adapter-level exception hierarchy.

.. deprecated::
    All exceptions have been consolidated into
    ``starboard_server.exceptions``.  Import from there instead.

This module re-exports everything from the canonical location for
backward compatibility.
"""

from __future__ import annotations

# Re-export everything from the canonical module for backward compatibility
from starboard_server.exceptions import (
    AdapterError,
    AdapterResourceNotFoundError,
    DatabricksAPIError,
    PermissionDeniedError,
    QueryExecutionError,
    ValidationError,
    wrap_databricks_error,
)

# Backward-compat alias: the old module had ResourceNotFoundError as adapter-level
ResourceNotFoundError = AdapterResourceNotFoundError

__all__ = [
    "AdapterError",
    "AdapterResourceNotFoundError",
    "DatabricksAPIError",
    "PermissionDeniedError",
    "QueryExecutionError",
    "ResourceNotFoundError",
    "ValidationError",
    "wrap_databricks_error",
]
