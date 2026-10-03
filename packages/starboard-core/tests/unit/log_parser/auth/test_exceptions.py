# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for authentication exceptions.

Following TDD: tests written first, implementation follows.
"""

from __future__ import annotations

import pytest

# Import will fail initially - that's expected in TDD
from starboard_core.log_parser.auth.exceptions import (
    AuthenticationError,
    CredentialExpiredError,
)
from starboard_core.log_parser.exceptions import LogParserError


class TestAuthenticationError:
    """Tests for AuthenticationError exception."""

    def test_inherits_from_log_parser_error(self) -> None:
        """AuthenticationError should inherit from LogParserError base class."""
        error = AuthenticationError("Auth failed")
        assert isinstance(error, LogParserError)
        assert isinstance(error, AuthenticationError)

    def test_basic_message(self) -> None:
        """Should initialize with basic error message."""
        error = AuthenticationError("Invalid credentials")
        assert error.message == "Invalid credentials"
        assert str(error) == "Invalid credentials"

    def test_with_details(self) -> None:
        """Should support optional details dictionary."""
        error = AuthenticationError(
            "Auth failed", details={"provider": "aws", "reason": "expired"}
        )
        assert error.message == "Auth failed"
        assert error.details == {"provider": "aws", "reason": "expired"}
        assert "provider=aws" in str(error)
        assert "reason=expired" in str(error)

    def test_without_details(self) -> None:
        """Should work without details parameter."""
        error = AuthenticationError("Simple error")
        assert error.details == {}
        assert str(error) == "Simple error"

    def test_can_be_raised(self) -> None:
        """Should be raisable as an exception."""
        with pytest.raises(AuthenticationError) as exc_info:
            raise AuthenticationError("Test error")
        assert "Test error" in str(exc_info.value)

    def test_can_be_caught_as_log_parser_error(self) -> None:
        """Should be catchable as base LogParserError."""
        with pytest.raises(LogParserError):
            raise AuthenticationError("Test error")

    def test_repr(self) -> None:
        """Should have useful repr."""
        error = AuthenticationError("Auth failed")
        # Should contain class name and message
        assert "AuthenticationError" in repr(error)


class TestCredentialExpiredError:
    """Tests for CredentialExpiredError exception."""

    def test_inherits_from_authentication_error(self) -> None:
        """CredentialExpiredError should inherit from AuthenticationError."""
        error = CredentialExpiredError("Credentials expired")
        assert isinstance(error, AuthenticationError)
        assert isinstance(error, LogParserError)
        assert isinstance(error, CredentialExpiredError)

    def test_basic_message(self) -> None:
        """Should initialize with basic error message."""
        error = CredentialExpiredError("Token expired")
        assert error.message == "Token expired"
        assert str(error) == "Token expired"

    def test_with_details(self) -> None:
        """Should support optional details dictionary."""
        error = CredentialExpiredError(
            "Credentials expired",
            details={"expires_at": "2024-01-01T00:00:00Z", "provider": "aws"},
        )
        assert error.message == "Credentials expired"
        assert "expires_at" in error.details
        assert "provider" in error.details

    def test_without_details(self) -> None:
        """Should work without details parameter."""
        error = CredentialExpiredError("Expired")
        assert error.details == {}

    def test_can_be_raised(self) -> None:
        """Should be raisable as an exception."""
        with pytest.raises(CredentialExpiredError) as exc_info:
            raise CredentialExpiredError("Expired credentials")
        assert "Expired credentials" in str(exc_info.value)

    def test_can_be_caught_as_authentication_error(self) -> None:
        """Should be catchable as AuthenticationError."""
        with pytest.raises(AuthenticationError):
            raise CredentialExpiredError("Expired")

    def test_can_be_caught_as_log_parser_error(self) -> None:
        """Should be catchable as base LogParserError."""
        with pytest.raises(LogParserError):
            raise CredentialExpiredError("Expired")


class TestExceptionHierarchy:
    """Tests for exception hierarchy and relationships."""

    def test_exception_hierarchy(self) -> None:
        """Verify complete exception hierarchy."""
        # CredentialExpiredError -> AuthenticationError -> LogParserError -> Exception
        error = CredentialExpiredError("Test")

        assert isinstance(error, CredentialExpiredError)
        assert isinstance(error, AuthenticationError)
        assert isinstance(error, LogParserError)
        assert isinstance(error, Exception)

    def test_authentication_error_hierarchy(self) -> None:
        """Verify AuthenticationError hierarchy."""
        # AuthenticationError -> LogParserError -> Exception
        error = AuthenticationError("Test")

        assert isinstance(error, AuthenticationError)
        assert isinstance(error, LogParserError)
        assert isinstance(error, Exception)
        assert not isinstance(error, CredentialExpiredError)

    def test_catch_specific_before_general(self) -> None:
        """Should catch most specific exception first."""
        caught_exceptions = []

        try:
            raise CredentialExpiredError("Expired")
        except CredentialExpiredError:
            caught_exceptions.append("CredentialExpiredError")
        except AuthenticationError:
            caught_exceptions.append("AuthenticationError")
        except LogParserError:
            caught_exceptions.append("LogParserError")

        assert caught_exceptions == ["CredentialExpiredError"]

    def test_catch_authentication_error(self) -> None:
        """Should catch CredentialExpiredError as AuthenticationError."""
        caught_exceptions = []

        try:
            raise CredentialExpiredError("Expired")
        except AuthenticationError:
            caught_exceptions.append("AuthenticationError")
        except LogParserError:
            caught_exceptions.append("LogParserError")

        assert caught_exceptions == ["AuthenticationError"]
