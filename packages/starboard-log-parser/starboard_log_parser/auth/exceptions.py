# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Authentication-specific exceptions.

These exceptions extend the base LogParserError hierarchy with auth-specific
error types for credential management and authentication failures.

Examples:
    >>> from starboard_log_parser.auth.exceptions import AuthenticationError
    >>>
    >>> try:
    ...     raise AuthenticationError("Invalid credentials", details={"provider": "aws"})
    ... except AuthenticationError as e:
    ...     print(e.message)  # "Invalid credentials"
    ...     print(e.details)  # {"provider": "aws"}
"""

from __future__ import annotations

from typing import Any

from starboard_log_parser.exceptions import LogParserError


class AuthenticationError(LogParserError):
    """
    Raised when authentication fails.

    This is the base exception for all authentication-related errors,
    including credential acquisition failures, invalid credentials,
    and permission denied errors.

    Args:
        message: Human-readable error message
        details: Optional dictionary with additional error context

    Attributes:
        message: The error message
        details: Additional context dictionary

    Examples:
        >>> error = AuthenticationError(
        ...     "Failed to get credentials",
        ...     details={"provider": "aws", "reason": "no access key"}
        ... )
        >>> print(error.message)  # "Failed to get credentials"
        >>> print(error.details["provider"])  # "aws"
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """
        Initialize authentication error.

        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
        """
        super().__init__(message, details)


class CredentialExpiredError(AuthenticationError):
    """
    Raised when credentials have expired.

    This exception indicates that temporary credentials (e.g., STS tokens,
    vended credentials) have reached their expiration time and need to be
    refreshed.

    Args:
        message: Human-readable error message
        details: Optional dictionary with additional error context
            (e.g., expires_at, provider)

    Attributes:
        message: The error message
        details: Additional context dictionary

    Examples:
        >>> from datetime import datetime
        >>> error = CredentialExpiredError(
        ...     "Credentials expired",
        ...     details={
        ...         "expires_at": "2024-01-01T00:00:00Z",
        ...         "provider": "databricks_vending"
        ...     }
        ... )
        >>> print(error.message)  # "Credentials expired"
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """
        Initialize credential expired error.

        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
        """
        super().__init__(message, details)
