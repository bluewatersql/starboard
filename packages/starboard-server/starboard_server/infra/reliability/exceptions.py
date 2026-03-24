"""
Custom exceptions for the Starboard Agent.

This module defines domain-specific exceptions for better error handling
and more informative error messages throughout the application.
"""

from __future__ import annotations

from typing import Any


class StarboardAgentError(Exception):
    """Base exception for all Starboard Agent errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """
        Initialize base exception.

        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


# =============================================================================
# Databricks API Errors
# =============================================================================


class DatabricksAPIError(StarboardAgentError):
    """Base exception for Databricks API errors."""

    pass


class ResourceNotFoundError(DatabricksAPIError):
    """Raised when a Databricks resource cannot be found."""

    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize resource not found error.

        Args:
            resource_type: Type of resource (e.g., 'table', 'warehouse', 'cluster')
            resource_id: Identifier of the missing resource
            details: Optional additional context
        """
        message = f"{resource_type} not found: {resource_id}"
        super().__init__(message, details)
        self.resource_type = resource_type
        self.resource_id = resource_id


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
        """
        Initialize invalid state error.

        Args:
            resource_type: Type of resource
            resource_id: Resource identifier
            current_state: Current state of the resource
            expected_state: Expected state of the resource
            details: Optional additional context
        """
        message = (
            f"{resource_type} '{resource_id}' is in state '{current_state}', "
            f"expected '{expected_state}'"
        )
        super().__init__(message, details)
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.current_state = current_state
        self.expected_state = expected_state


class APIRateLimitError(DatabricksAPIError):
    """Raised when API rate limits are exceeded."""

    def __init__(
        self,
        retry_after: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize rate limit error.

        Args:
            retry_after: Number of seconds to wait before retrying
            details: Optional additional context
        """
        message = "API rate limit exceeded"
        if retry_after:
            message += f", retry after {retry_after} seconds"
        super().__init__(message, details)
        self.retry_after = retry_after


# =============================================================================
# Validation Errors
# =============================================================================


class ValidationError(StarboardAgentError):
    """Base exception for validation errors."""

    pass


class InvalidSQLError(ValidationError):
    """Raised when SQL query validation fails."""

    def __init__(
        self, sql: str, reason: str, details: dict[str, Any] | None = None
    ) -> None:
        """
        Initialize invalid SQL error.

        Args:
            sql: The invalid SQL query
            reason: Why the SQL is invalid
            details: Optional additional context
        """
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
        """
        Initialize unsafe SQL error.

        Args:
            sql: The unsafe SQL query
            forbidden_operations: List of forbidden operations detected
            details: Optional additional context
        """
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
        """
        Initialize missing parameter error.

        Args:
            parameter_name: Name of the missing parameter
            context: Context where the parameter is needed
            details: Optional additional context
        """
        message = f"Missing required parameter '{parameter_name}' in {context}"
        super().__init__(message, details)
        self.parameter_name = parameter_name
        self.context = context


# =============================================================================
# Data Processing Errors
# =============================================================================


class DataProcessingError(StarboardAgentError):
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
        """
        Initialize Spark log path not found error.

        Args:
            log_path: The path that was not found
            cluster_id: Optional cluster identifier
            details: Optional additional context
        """
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
        """
        Initialize missing data error.

        Args:
            data_key: Key or identifier of the missing data
            source: Where the data was expected to be found
            details: Optional additional context
        """
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
        """
        Initialize invalid data format error.

        Args:
            data_key: Key or identifier of the data
            expected_type: Expected data type/format
            actual_type: Actual data type/format
            details: Optional additional context
        """
        message = (
            f"Invalid data format for '{data_key}': "
            f"expected {expected_type}, got {actual_type}"
        )
        super().__init__(message, details)
        self.data_key = data_key
        self.expected_type = expected_type
        self.actual_type = actual_type


# =============================================================================
# Workflow Errors
# =============================================================================


class WorkflowError(StarboardAgentError):
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
        """
        Initialize task execution error.

        Args:
            task_name: Name of the failed task
            reason: Why the task failed
            original_error: Original exception that caused the failure
            details: Optional additional context
        """
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
        """
        Initialize approval required error.

        Args:
            operation: Name of the operation requiring approval
            reason: Why approval is required
            required_token: Name of the required approval token
            details: Optional additional context
        """
        message = f"Operation '{operation}' requires approval: {reason}"
        super().__init__(message, details)
        self.operation = operation
        self.reason = reason
        self.required_token = required_token


# =============================================================================
# Configuration Errors
# =============================================================================


class ConfigurationError(StarboardAgentError):
    """Raised when configuration is invalid or missing."""

    def __init__(
        self, config_key: str, reason: str, details: dict[str, Any] | None = None
    ) -> None:
        """
        Initialize configuration error.

        Args:
            config_key: Configuration key that is invalid
            reason: Why the configuration is invalid
            details: Optional additional context
        """
        message = f"Configuration error for '{config_key}': {reason}"
        super().__init__(message, details)
        self.config_key = config_key
        self.reason = reason
