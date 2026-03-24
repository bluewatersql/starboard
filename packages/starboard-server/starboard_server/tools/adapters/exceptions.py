"""Adapter-level exception hierarchy.

Provides specific exception types for better error handling and logging.
These exceptions wrap underlying SDK errors with additional context.

Usage:
    Instead of:
        except Exception as e:
            logger.error(f"Failed: {e}")
            return {"error": str(e)}

    Use:
        except DatabricksAPIError as e:
            logger.error(
                "databricks_api_error",
                extra={"error_type": type(e).__name__, "details": str(e)},
            )
            return {"error": str(e), "error_type": "api_error"}
        except ValidationError as e:
            raise  # Fail fast on validation
        except Exception as e:
            logger.error(
                "unexpected_error",
                extra={"error_type": type(e).__name__, "details": str(e)},
            )
            return {"error": str(e), "error_type": "unexpected"}
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base exception for adapter-level errors."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        """Initialize adapter error.

        Args:
            message: Error message.
            details: Additional error context.
        """
        super().__init__(message)
        self.details = details or {}


class DatabricksAPIError(AdapterError):
    """Error communicating with Databricks API.

    Covers:
    - Network errors
    - Authentication failures
    - Rate limiting (429)
    - Server errors (5xx)
    """

    pass


class ResourceNotFoundError(AdapterError):
    """Requested resource does not exist.

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

    # Check for common error patterns
    if "not found" in error_str or "does not exist" in error_str:
        return ResourceNotFoundError(
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

    # Default to generic API error
    return DatabricksAPIError(str(e), details={"original_type": type(e).__name__})
