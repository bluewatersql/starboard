# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for authentication exceptions.

Tests follow Python AI Agent Engineering Standards:
- Comprehensive coverage of all exception types
- Edge case testing
- Clear test names describing behavior
"""

import pytest
from starboard_server.domain.auth.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    SessionExpiredError,
    UserNotFoundError,
)


class TestAuthenticationError:
    """Test suite for AuthenticationError base exception."""

    def test_authentication_error_basic(self) -> None:
        """Test basic authentication error creation."""
        error = AuthenticationError("Authentication failed")

        assert error.message == "Authentication failed"
        assert error.provider is None
        assert error.details == {}
        assert str(error) == "Authentication failed"

    def test_authentication_error_with_provider(self) -> None:
        """Test authentication error with provider context."""
        error = AuthenticationError(
            "Failed to authenticate",
            provider="databricks",
        )

        assert error.message == "Failed to authenticate"
        assert error.provider == "databricks"
        assert str(error) == "[databricks] Failed to authenticate"

    def test_authentication_error_with_details(self) -> None:
        """Test authentication error with additional details."""
        details = {"reason": "invalid_token", "status_code": 401}
        error = AuthenticationError(
            "Auth failed",
            provider="oauth",
            details=details,
        )

        assert error.details == details
        assert error.details["reason"] == "invalid_token"
        assert error.details["status_code"] == 401

    def test_authentication_error_inheritance(self) -> None:
        """Test that AuthenticationError inherits from Exception."""
        error = AuthenticationError("Test error")
        assert isinstance(error, Exception)


class TestUserNotFoundError:
    """Test suite for UserNotFoundError exception."""

    def test_user_not_found_basic(self) -> None:
        """Test basic user not found error."""
        error = UserNotFoundError("user@example.com")

        assert error.user_identifier == "user@example.com"
        assert "user@example.com" in error.message
        assert error.provider is None

    def test_user_not_found_with_provider(self) -> None:
        """Test user not found error with provider."""
        error = UserNotFoundError(
            "user_123",
            provider="databricks",
        )

        assert error.user_identifier == "user_123"
        assert error.provider == "databricks"
        assert "[databricks]" in str(error)

    def test_user_not_found_with_details(self) -> None:
        """Test user not found error with additional context."""
        details = {"attempted_lookup": "email", "retry_count": 3}
        error = UserNotFoundError(
            "nonexistent@example.com",
            details=details,
        )

        assert error.details["attempted_lookup"] == "email"
        assert error.details["retry_count"] == 3

    def test_user_not_found_inheritance(self) -> None:
        """Test that UserNotFoundError inherits from AuthenticationError."""
        error = UserNotFoundError("user@example.com")
        assert isinstance(error, AuthenticationError)
        assert isinstance(error, Exception)


class TestInvalidCredentialsError:
    """Test suite for InvalidCredentialsError exception."""

    def test_invalid_credentials_basic(self) -> None:
        """Test basic invalid credentials error."""
        error = InvalidCredentialsError("Invalid username or password")

        assert error.message == "Invalid username or password"

    def test_invalid_credentials_with_provider(self) -> None:
        """Test invalid credentials with provider."""
        error = InvalidCredentialsError(
            "Bad credentials",
            provider="oauth",
        )

        assert error.provider == "oauth"
        assert "[oauth]" in str(error)

    def test_invalid_credentials_inheritance(self) -> None:
        """Test that InvalidCredentialsError inherits from AuthenticationError."""
        error = InvalidCredentialsError("Bad password")
        assert isinstance(error, AuthenticationError)


class TestSessionExpiredError:
    """Test suite for SessionExpiredError exception."""

    def test_session_expired_basic(self) -> None:
        """Test basic session expired error."""
        error = SessionExpiredError("sess_123")

        assert error.session_id == "sess_123"
        assert "sess_123" in error.message

    def test_session_expired_with_provider(self) -> None:
        """Test session expired with provider."""
        error = SessionExpiredError(
            "sess_456",
            provider="databricks",
        )

        assert error.session_id == "sess_456"
        assert error.provider == "databricks"

    def test_session_expired_with_details(self) -> None:
        """Test session expired with expiry details."""
        details = {"expired_at": "2023-01-01T00:00:00Z", "ttl_hours": 24}
        error = SessionExpiredError(
            "sess_789",
            details=details,
        )

        assert error.details["expired_at"] == "2023-01-01T00:00:00Z"
        assert error.details["ttl_hours"] == 24

    def test_session_expired_inheritance(self) -> None:
        """Test that SessionExpiredError inherits from AuthenticationError."""
        error = SessionExpiredError("sess_123")
        assert isinstance(error, AuthenticationError)


class TestExceptionHierarchy:
    """Test exception hierarchy and inheritance."""

    def test_all_exceptions_inherit_from_base(self) -> None:
        """Test that all auth exceptions inherit from AuthenticationError."""
        exceptions = [
            UserNotFoundError("user"),
            InvalidCredentialsError("creds"),
            SessionExpiredError("session"),
        ]

        for exc in exceptions:
            assert isinstance(exc, AuthenticationError)
            assert isinstance(exc, Exception)

    def test_exceptions_can_be_caught_generically(self) -> None:
        """Test that auth exceptions can be caught by base class."""
        with pytest.raises(AuthenticationError):
            raise UserNotFoundError("user")

        with pytest.raises(AuthenticationError):
            raise InvalidCredentialsError("bad creds")

        with pytest.raises(AuthenticationError):
            raise SessionExpiredError("expired")

    def test_exceptions_can_be_caught_specifically(self) -> None:
        """Test that auth exceptions can be caught specifically."""
        with pytest.raises(UserNotFoundError):
            raise UserNotFoundError("user")

        with pytest.raises(InvalidCredentialsError):
            raise InvalidCredentialsError("creds")

        with pytest.raises(SessionExpiredError):
            raise SessionExpiredError("session")
