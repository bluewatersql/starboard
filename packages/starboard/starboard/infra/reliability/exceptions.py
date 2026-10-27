# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Custom exceptions for the Starboard Agent.

.. deprecated::
    All exceptions have been consolidated into
    ``starboard.exceptions``.  Import from there instead.

This module re-exports everything from the canonical location for
backward compatibility.
"""

from __future__ import annotations

# Re-export everything from the canonical module for backward compatibility
from starboard.exceptions import (
    AdapterError,
    APIRateLimitError,
    ApprovalRequiredError,
    ConfigurationError,
    DatabricksAPIError,
    DataProcessingError,
    InvalidDataFormatError,
    InvalidResourceStateError,
    InvalidSQLError,
    MissingDataError,
    MissingParameterError,
    ResourceNotFoundError,
    SparkLogPathNotFoundError,
    StarboardError,
    TaskExecutionError,
    UnsafeSQLError,
    ValidationError,
    WorkflowError,
)

# Backward-compat alias: old module used StarboardAgentError as the base
StarboardAgentError = StarboardError

__all__ = [
    "APIRateLimitError",
    "AdapterError",
    "ApprovalRequiredError",
    "ConfigurationError",
    "DatabricksAPIError",
    "DataProcessingError",
    "InvalidDataFormatError",
    "InvalidResourceStateError",
    "InvalidSQLError",
    "MissingDataError",
    "MissingParameterError",
    "ResourceNotFoundError",
    "SparkLogPathNotFoundError",
    "StarboardAgentError",
    "StarboardError",
    "TaskExecutionError",
    "UnsafeSQLError",
    "ValidationError",
    "WorkflowError",
]
