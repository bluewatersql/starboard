"""Unified exception hierarchy for the Starboard Agent.

All application exceptions inherit from :class:`StarboardError`.
Domain sub-trees (MCP, Auth) live in their own modules but share
this common root so that any ``except StarboardError`` clause
catches everything application-related.

Exception Hierarchy::

    StarboardError (base for ALL application errors)
    |
    +-- ConfigurationError
    |
    +-- ValidationError
    |     +-- InvalidSQLError
    |     +-- UnsafeSQLError
    |     +-- MissingParameterError
    |
    +-- ToolError (base for tool-layer errors, provides to_dict())
    |     +-- ResourceNotFoundError (parameterized by resource_type)
    |     |     +-- ClusterNotFoundError
    |     |     +-- WarehouseNotFoundError
    |     |     +-- JobNotFoundError
    |     |     +-- TableNotFoundError
    |     +-- DataUnavailableError
    |     |     +-- SparkLogsUnavailableError
    |     +-- AccessDeniedError
    |
    +-- AdapterError (base for adapter/SDK boundary errors)
    |     +-- DatabricksAPIError
    |     |     +-- APIRateLimitError
    |     |     +-- InvalidResourceStateError
    |     +-- AdapterResourceNotFoundError
    |     +-- PermissionDeniedError
    |     +-- QueryExecutionError
    |
    +-- DataProcessingError
    |     +-- SparkLogPathNotFoundError
    |     +-- MissingDataError
    |     +-- InvalidDataFormatError
    |
    +-- WorkflowError
          +-- TaskExecutionError
          +-- ApprovalRequiredError
"""

from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class StarboardError(Exception):
    """Base exception for ALL Starboard Agent errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConfigurationError(StarboardError):
    """Raised when configuration is invalid or missing."""

    def __init__(
        self, config_key: str, reason: str, details: dict[str, Any] | None = None
    ) -> None:
        message = f"Configuration error for '{config_key}': {reason}"
        super().__init__(message, details)
        self.config_key = config_key
        self.reason = reason


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationError(StarboardError):
    """Base exception for validation errors."""

    pass


class InvalidSQLError(ValidationError):
    """Raised when SQL query validation fails."""

    def __init__(
        self, sql: str, reason: str, details: dict[str, Any] | None = None
    ) -> None:
        message = f"Invalid SQL: {reason}"
        super().__init__(message, details)
        self.sql = sql
        self.reason = reason


class UnsafeSQLError(ValidationError):
    """Raised when SQL contains potentially dangerous operations."""

    def __init__(
        self,
        sql: str,
        forbidden_operations: list[str],
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Unsafe SQL detected: {', '.join(forbidden_operations)}"
        super().__init__(message, details)
        self.sql = sql
        self.forbidden_operations = forbidden_operations


class MissingParameterError(ValidationError):
    """Raised when required parameters are missing."""

    def __init__(
        self,
        parameter_name: str,
        context: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Missing required parameter '{parameter_name}' in {context}"
        super().__init__(message, details)
        self.parameter_name = parameter_name
        self.context = context


# ---------------------------------------------------------------------------
# ToolError hierarchy -- standard ``to_dict()`` via template method
# ---------------------------------------------------------------------------


class ToolErrorResponse(TypedDict, total=False):
    """Standard error response shape for tool adapter returns.

    Required keys: ``error``, ``error_code``.
    Optional key: ``details``.
    """

    error: str
    error_code: str
    details: dict[str, Any] | None


class ToolError(StarboardError):
    """Base exception for all tool errors.

    Provides ``to_dict()`` returning a :class:`ToolErrorResponse`-shaped
    dict.  Subclasses add domain-specific fields via
    :meth:`_extra_dict_fields` -- they should **not** override
    ``to_dict()`` directly.
    """

    error_code: str = "tool_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)

    def to_dict(self) -> dict[str, Any]:
        """Standard error dict.  Subclasses override ``_extra_dict_fields()``."""
        base: dict[str, Any] = {
            "error": self.message,
            "error_code": self.error_code,
        }
        if self.details:
            base["details"] = self.details
        base.update(self._extra_dict_fields())
        return base

    def _extra_dict_fields(self) -> dict[str, Any]:
        """Override in subclasses to add domain-specific fields."""
        return {}


class ResourceNotFoundError(ToolError):
    """Base exception for resource not found errors."""

    error_code = "resource_not_found"

    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"{resource_type} '{resource_id}' not found"
        super().__init__(message, details)
        self.resource_type = resource_type
        self.resource_id = resource_id

    def _extra_dict_fields(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
        }


class ClusterNotFoundError(ResourceNotFoundError):
    """Raised when a cluster cannot be found."""

    error_code = "cluster_not_found"

    def __init__(self, cluster_id: str) -> None:
        super().__init__("Cluster", cluster_id)
        self.cluster_id = cluster_id


class WarehouseNotFoundError(ResourceNotFoundError):
    """Raised when a SQL warehouse cannot be found."""

    error_code = "warehouse_not_found"

    def __init__(self, warehouse_id: str) -> None:
        super().__init__("Warehouse", warehouse_id)
        self.warehouse_id = warehouse_id


class JobNotFoundError(ResourceNotFoundError):
    """Raised when a job cannot be found."""

    error_code = "job_not_found"

    def __init__(self, job_id: str) -> None:
        super().__init__("Job", job_id)
        self.job_id = job_id


class TableNotFoundError(ResourceNotFoundError):
    """Raised when a table cannot be found."""

    error_code = "table_not_found"

    def __init__(self, table_name: str) -> None:
        super().__init__("Table", table_name)
        self.table_name = table_name


class DataUnavailableError(ToolError):
    """Raised when data exists but is unavailable."""

    error_code = "data_unavailable"

    def __init__(
        self,
        message: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.reason = reason

    def _extra_dict_fields(self) -> dict[str, Any]:
        return {"reason": self.reason}


class SparkLogsUnavailableError(DataUnavailableError):
    """Raised when Spark logs are not available for a cluster."""

    error_code = "spark_logs_unavailable"

    def __init__(self, cluster_id: str, reason: str) -> None:
        message = f"Spark logs unavailable for cluster '{cluster_id}': {reason}"
        super().__init__(message, reason)
        self.cluster_id = cluster_id

    def _extra_dict_fields(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "reason": self.reason,
        }


class AccessDeniedError(ToolError):
    """Raised when user lacks permission to access a resource."""

    error_code = "access_denied"

    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        required_permission: str | None = None,
    ) -> None:
        message = f"Access denied to {resource_type} '{resource_id}'"
        if required_permission:
            message += f" (requires {required_permission})"
        super().__init__(message)
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.required_permission = required_permission

    def _extra_dict_fields(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
        }
        if self.required_permission:
            result["required_permission"] = self.required_permission
        return result


# ---------------------------------------------------------------------------
# AdapterError hierarchy
# ---------------------------------------------------------------------------


class AdapterError(StarboardError):
    """Base exception for adapter-level errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)


class DatabricksAPIError(AdapterError):
    """Error communicating with Databricks API."""

    pass


class APIRateLimitError(DatabricksAPIError):
    """Raised when API rate limits are exceeded."""

    def __init__(
        self,
        retry_after: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = "API rate limit exceeded"
        if retry_after:
            message += f", retry after {retry_after} seconds"
        super().__init__(message, details=details)
        self.retry_after = retry_after


class InvalidResourceStateError(DatabricksAPIError):
    """Raised when a resource is in an unexpected state."""

    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        current_state: str,
        expected_state: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = (
            f"{resource_type} '{resource_id}' is in state '{current_state}', "
            f"expected '{expected_state}'"
        )
        super().__init__(message, details=details)
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.current_state = current_state
        self.expected_state = expected_state


class AdapterResourceNotFoundError(AdapterError):
    """Requested resource does not exist (adapter-level)."""

    pass


class PermissionDeniedError(AdapterError):
    """Insufficient permissions for requested operation."""

    pass


class QueryExecutionError(AdapterError):
    """SQL query execution failed."""

    pass


# ---------------------------------------------------------------------------
# DataProcessingError hierarchy
# ---------------------------------------------------------------------------


class DataProcessingError(StarboardError):
    """Base exception for data processing errors."""

    pass


class SparkLogPathNotFoundError(DataProcessingError):
    """Raised when Spark application log path does not exist."""

    def __init__(
        self,
        log_path: str,
        cluster_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Spark application log path does not exist: {log_path}"
        if cluster_id:
            message += f" (cluster_id: {cluster_id})"
        super().__init__(message, details)
        self.log_path = log_path
        self.cluster_id = cluster_id


class MissingDataError(DataProcessingError):
    """Raised when expected data is not found."""

    def __init__(
        self, data_key: str, source: str, details: dict[str, Any] | None = None
    ) -> None:
        message = f"Expected data not found: '{data_key}' in {source}"
        super().__init__(message, details)
        self.data_key = data_key
        self.source = source


class InvalidDataFormatError(DataProcessingError):
    """Raised when data is in an unexpected format."""

    def __init__(
        self,
        data_key: str,
        expected_type: str,
        actual_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = (
            f"Invalid data format for '{data_key}': "
            f"expected {expected_type}, got {actual_type}"
        )
        super().__init__(message, details)
        self.data_key = data_key
        self.expected_type = expected_type
        self.actual_type = actual_type


# ---------------------------------------------------------------------------
# WorkflowError hierarchy
# ---------------------------------------------------------------------------


class WorkflowError(StarboardError):
    """Base exception for workflow execution errors."""

    pass


class TaskExecutionError(WorkflowError):
    """Raised when a workflow task fails to execute."""

    def __init__(
        self,
        task_name: str,
        reason: str,
        original_error: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Task '{task_name}' failed: {reason}"
        super().__init__(message, details)
        self.task_name = task_name
        self.reason = reason
        self.original_error = original_error


class ApprovalRequiredError(WorkflowError):
    """Raised when an operation requires user approval."""

    def __init__(
        self,
        operation: str,
        reason: str,
        required_token: str = "approval_token",
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Operation '{operation}' requires approval: {reason}"
        super().__init__(message, details)
        self.operation = operation
        self.reason = reason
        self.required_token = required_token


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def wrap_databricks_error(e: Exception) -> AdapterError:
    """Wrap a Databricks SDK exception in an appropriate adapter error.

    Args:
        e: Original exception from Databricks SDK.

    Returns:
        Wrapped AdapterError subclass.
    """
    error_str = str(e).lower()

    if "not found" in error_str or "does not exist" in error_str:
        return AdapterResourceNotFoundError(
            str(e), details={"original_type": type(e).__name__}
        )

    if "permission" in error_str or "access denied" in error_str or "403" in error_str:
        return PermissionDeniedError(
            str(e), details={"original_type": type(e).__name__}
        )

    if "rate limit" in error_str or "429" in error_str:
        return DatabricksAPIError(
            str(e), details={"original_type": type(e).__name__, "retryable": True}
        )

    if "timeout" in error_str or "504" in error_str:
        return DatabricksAPIError(
            str(e), details={"original_type": type(e).__name__, "retryable": True}
        )

    if "syntax error" in error_str or "parse error" in error_str:
        return QueryExecutionError(str(e), details={"original_type": type(e).__name__})

    return DatabricksAPIError(str(e), details={"original_type": type(e).__name__})
