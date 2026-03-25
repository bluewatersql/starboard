"""Adapter-level exception hierarchy.

.. deprecated::
    All exceptions have been consolidated into
    ``starboard_server.tools.exceptions``.  Import from there instead.

This module re-exports everything from the canonical location for
backward compatibility.

Usage:
    Instead of:
        from starboard_server.tools.adapters.exceptions import DatabricksAPIError

    Prefer:
        from starboard_server.tools.exceptions import DatabricksAPIError
"""

from __future__ import annotations

# Re-export everything from the canonical module for backward compatibility
from starboard_server.tools.exceptions import (
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
