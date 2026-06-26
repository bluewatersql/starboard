# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Authentication-specific exceptions.

Following clean architecture principles, these exceptions are part of the domain layer
and can be raised by any authentication-related component.

All auth exceptions inherit from :class:`StarboardError` so they can be
caught by application-wide error boundaries.
"""

from typing import Any

from starboard_server.exceptions import StarboardError


class AuthenticationError(StarboardError):
    """Base exception for all authentication errors."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize authentication error.

        Args:
            message: Human-readable error message
            provider: Authentication provider that raised the error (e.g., 'databricks')
            details: Additional context about the error
        """
        self.provider = provider
        super().__init__(message, details)

    def __str__(self) -> str:
        """Return string representation with provider context."""
        if self.provider:
            return f"[{self.provider}] {self.message}"
        return self.message


class UserNotFoundError(AuthenticationError):
    """Raised when a user cannot be found in the system."""

    def __init__(
        self,
        user_identifier: str,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize user not found error.

        Args:
            user_identifier: The identifier used to look up the user
            provider: Authentication provider
            details: Additional context
        """
        message = f"User not found: {user_identifier}"
        super().__init__(message, provider, details)
        self.user_identifier = user_identifier


class InvalidCredentialsError(AuthenticationError):
    """Raised when authentication credentials are invalid."""

    pass


class SessionExpiredError(AuthenticationError):
    """Raised when a session has expired."""

    def __init__(
        self,
        session_id: str,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize session expired error.

        Args:
            session_id: The expired session identifier
            provider: Authentication provider
            details: Additional context
        """
        message = f"Session expired: {session_id}"
        super().__init__(message, provider, details)
        self.session_id = session_id
