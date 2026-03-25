"""Tool-specific exceptions for the Starboard Agent.

This module provides domain-specific exceptions for tool operations,
designed to be caught at the adapter layer and converted to dicts
for LLM responses.  It also contains adapter-level exceptions that
wrap Databricks SDK errors.

Exception Hierarchy:
    ToolError (base)
    ├── ResourceNotFoundError
    │   ├── ClusterNotFoundError
    │   ├── WarehouseNotFoundError
    │   ├── JobNotFoundError
    │   └── TableNotFoundError
    ├── DataUnavailableError
    │   └── SparkLogsUnavailableError
    └── AccessDeniedError

    AdapterError (base for adapter-level errors)
    ├── DatabricksAPIError
    ├── AdapterResourceNotFoundError
    ├── PermissionDeniedError
    ├── QueryExecutionError
    └── ValidationError

Usage:
    Service layer raises exceptions:
        if config is None:
            raise ClusterNotFoundError(cluster_id)

    Adapter layer catches and converts:
        try:
            return await self.service.fetch_cluster_config(cluster_id)
        except ClusterNotFoundError as e:
            return e.to_dict()
"""

from __future__ import annotations

from typing import Any, TypedDict

# ---------------------------------------------------------------------------
# ToolErrorResponse — standard return shape for all error dicts
# ---------------------------------------------------------------------------


class ToolErrorResponse(TypedDict, total=False):
    """Standard error response shape for tool adapter returns.

    All tool adapters that return an error dict must use this shape.
    Required keys: ``error``, ``error_code``.
    Optional key: ``details``.
    """

    error: str
    error_code: str
    details: dict[str, Any] | None


# ---------------------------------------------------------------------------
# ToolError hierarchy
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base exception for all tool errors.

    Provides a standardized interface for converting errors to dict
    format suitable for LLM responses.

    Attributes:
        message: Human-readable error message.
        details: Additional error context.

    Example:
        >>> error = ToolError("Something failed", details={"key": "value"})
        >>> error.to_dict()
        {'found': False, 'error': 'Something failed', 'error_code': 'tool_error', ...}
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize tool error.

        Args:
            message: Human-readable error message.
            details: Optional dictionary with additional error context.
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        """Return string representation of the error."""
        return self.message

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dict for LLM response.

        Returns:
            Dict with standardized error format.
        """
        return {
            "found": False,
            "error": self.message,
            "error_code": "tool_error",
            "error_type": "tool_error",
            "details": self.details,
        }


class ResourceNotFoundError(ToolError):
    """Base exception for resource not found errors.

    Attributes:
        resource_type: Type of resource (e.g., 'Cluster', 'Warehouse').
        resource_id: Identifier of the missing resource.
    """

    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize resource not found error.

        Args:
            resource_type: Type of resource.
            resource_id: Resource identifier.
            details: Optional additional context.
        """
        message = f"{resource_type} '{resource_id}' not found"
        super().__init__(message, details)
        self.resource_type = resource_type
        self.resource_id = resource_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with resource info."""
        return {
            "found": False,
            "error": self.message,
            "error_code": f"{self.resource_type.lower()}_not_found",
            "error_type": f"{self.resource_type.lower()}_not_found",
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
        }


class ClusterNotFoundError(ResourceNotFoundError):
    """Raised when a cluster cannot be found.

    Example:
        >>> raise ClusterNotFoundError("cluster-123")
        ClusterNotFoundError: Cluster 'cluster-123' not found
    """

    def __init__(self, cluster_id: str) -> None:
        """Initialize cluster not found error.

        Args:
            cluster_id: The cluster ID that was not found.
        """
        super().__init__("Cluster", cluster_id)
        self.cluster_id = cluster_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with cluster_id."""
        return {
            "found": False,
            "error": self.message,
            "error_code": "cluster_not_found",
            "error_type": "cluster_not_found",
            "cluster_id": self.cluster_id,
        }


class WarehouseNotFoundError(ResourceNotFoundError):
    """Raised when a SQL warehouse cannot be found.

    Example:
        >>> raise WarehouseNotFoundError("warehouse-abc")
        WarehouseNotFoundError: Warehouse 'warehouse-abc' not found
    """

    def __init__(self, warehouse_id: str) -> None:
        """Initialize warehouse not found error.

        Args:
            warehouse_id: The warehouse ID that was not found.
        """
        super().__init__("Warehouse", warehouse_id)
        self.warehouse_id = warehouse_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with warehouse_id."""
        return {
            "found": False,
            "error": self.message,
            "error_code": "warehouse_not_found",
            "error_type": "warehouse_not_found",
            "warehouse_id": self.warehouse_id,
        }


class JobNotFoundError(ResourceNotFoundError):
    """Raised when a job cannot be found.

    Example:
        >>> raise JobNotFoundError("12345")
        JobNotFoundError: Job '12345' not found
    """

    def __init__(self, job_id: str) -> None:
        """Initialize job not found error.

        Args:
            job_id: The job ID that was not found.
        """
        super().__init__("Job", job_id)
        self.job_id = job_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with job_id."""
        return {
            "found": False,
            "error": self.message,
            "error_code": "job_not_found",
            "error_type": "job_not_found",
            "job_id": self.job_id,
        }


class TableNotFoundError(ResourceNotFoundError):
    """Raised when a table cannot be found.

    Example:
        >>> raise TableNotFoundError("catalog.schema.table")
        TableNotFoundError: Table 'catalog.schema.table' not found
    """

    def __init__(self, table_name: str) -> None:
        """Initialize table not found error.

        Args:
            table_name: The fully-qualified table name that was not found.
        """
        super().__init__("Table", table_name)
        self.table_name = table_name

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with table_name."""
        return {
            "found": False,
            "error": self.message,
            "error_code": "table_not_found",
            "error_type": "table_not_found",
            "table_name": self.table_name,
        }


class DataUnavailableError(ToolError):
    """Raised when data exists but is unavailable.

    This covers scenarios like:
    - Logs not yet written
    - Metrics not collected
    - Data expired
    - Feature not configured

    Attributes:
        reason: Why the data is unavailable.
    """

    def __init__(
        self,
        message: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize data unavailable error.

        Args:
            message: Human-readable error message.
            reason: Specific reason data is unavailable.
            details: Optional additional context.
        """
        super().__init__(message, details)
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with reason."""
        return {
            "found": False,
            "error": self.message,
            "error_code": "data_unavailable",
            "error_type": "data_unavailable",
            "reason": self.reason,
        }


class SparkLogsUnavailableError(DataUnavailableError):
    """Raised when Spark logs are not available for a cluster.

    This can happen when:
    - Cluster logging is not configured
    - Logs have not been written yet
    - Log destination is inaccessible
    - Cluster terminated before logs were captured

    Attributes:
        cluster_id: The cluster ID.
        reason: Why logs are unavailable.

    Example:
        >>> raise SparkLogsUnavailableError("cl-1", "Logging not configured")
        SparkLogsUnavailableError: Spark logs unavailable for cluster 'cl-1': Logging not configured
    """

    def __init__(self, cluster_id: str, reason: str) -> None:
        """Initialize spark logs unavailable error.

        Args:
            cluster_id: The cluster ID.
            reason: Why logs are unavailable.
        """
        message = f"Spark logs unavailable for cluster '{cluster_id}': {reason}"
        super().__init__(message, reason)
        self.cluster_id = cluster_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with cluster_id and reason."""
        return {
            "found": False,
            "error": self.message,
            "error_code": "spark_logs_unavailable",
            "error_type": "spark_logs_unavailable",
            "cluster_id": self.cluster_id,
            "reason": self.reason,
        }


class AccessDeniedError(ToolError):
    """Raised when user lacks permission to access a resource.

    Attributes:
        resource_type: Type of resource.
        resource_id: Resource identifier.
        required_permission: Permission that is missing.

    Example:
        >>> raise AccessDeniedError("Cluster", "cluster-123", "CAN_MANAGE")
        AccessDeniedError: Access denied to Cluster 'cluster-123'
    """

    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        required_permission: str | None = None,
    ) -> None:
        """Initialize access denied error.

        Args:
            resource_type: Type of resource.
            resource_id: Resource identifier.
            required_permission: Optional permission that is required.
        """
        message = f"Access denied to {resource_type} '{resource_id}'"
        if required_permission:
            message += f" (requires {required_permission})"
        super().__init__(message)
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.required_permission = required_permission

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict with access info."""
        result: dict[str, Any] = {
            "found": False,
            "error": self.message,
            "error_code": "access_denied",
            "error_type": "access_denied",
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
        }
        if self.required_permission:
            result["required_permission"] = self.required_permission
        return result


# ---------------------------------------------------------------------------
# AdapterError hierarchy (formerly in tools/adapters/exceptions.py)
# ---------------------------------------------------------------------------


class AdapterError(Exception):
    """Base exception for adapter-level errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        """Initialize adapter error.

        Args:
            message: Error message.
            details: Additional error context.
        """
        super().__init__(message)
        self.details: dict[str, Any] = details or {}


class DatabricksAPIError(AdapterError):
    """Error communicating with Databricks API.

    Covers:
    - Network errors
    - Authentication failures
    - Rate limiting (429)
    - Server errors (5xx)
    """

    pass


class AdapterResourceNotFoundError(AdapterError):
    """Requested resource does not exist (adapter-level).

    Covers:
    - Table not found
    - Warehouse not found
    - Job not found
    - Cluster not found
    """

    pass


class PermissionDeniedError(AdapterError):
    """Insufficient permissions for requested operation.

    Covers:
    - Table access denied
    - Warehouse access denied
    - Admin-only operations
    """

    pass


class QueryExecutionError(AdapterError):
    """SQL query execution failed.

    Covers:
    - Syntax errors
    - Schema mismatches
    - Timeout errors
    """

    pass


class ValidationError(AdapterError):
    """Input validation failed.

    This should be raised for invalid inputs that should fail fast.
    Do NOT catch this - let it propagate.
    """

    pass


def wrap_databricks_error(e: Exception) -> AdapterError:
    """Wrap a Databricks SDK exception in an appropriate adapter error.

    This function inspects the exception and wraps it in the most
    specific error type available.

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
