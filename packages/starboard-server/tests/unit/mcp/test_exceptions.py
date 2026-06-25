# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCP exception hierarchy."""

from starboard_server.mcp.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ExecutionError,
    MCPBaseError,
    RateLimitError,
)


class TestConfigurationError:
    """Tests for ConfigurationError."""

    def test_has_code_and_message(self) -> None:
        err = ConfigurationError("Missing workspace")
        assert err.code == "CONFIG_INVALID"
        assert err.message == "Missing workspace"
        assert str(err) == "Missing workspace"

    def test_is_mcp_base_error(self) -> None:
        err = ConfigurationError("bad")
        assert isinstance(err, MCPBaseError)
        assert isinstance(err, Exception)


class TestAuthenticationError:
    """Tests for AuthenticationError."""

    def test_has_code_and_message(self) -> None:
        err = AuthenticationError("Token expired")
        assert err.code == "AUTH_FAILED"
        assert err.message == "Token expired"

    def test_is_mcp_base_error(self) -> None:
        assert isinstance(AuthenticationError("x"), MCPBaseError)


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_has_code_and_message(self) -> None:
        err = RateLimitError("Too many requests")
        assert err.code == "RATE_LIMITED"
        assert err.message == "Too many requests"

    def test_retry_after_default_none(self) -> None:
        err = RateLimitError("limit hit")
        assert err.retry_after is None

    def test_retry_after_set(self) -> None:
        err = RateLimitError("limit hit", retry_after=30)
        assert err.retry_after == 30


class TestExecutionError:
    """Tests for ExecutionError."""

    def test_default_code(self) -> None:
        err = ExecutionError("Tool failed")
        assert err.code == "EXEC_FAILED"
        assert err.message == "Tool failed"

    def test_custom_code(self) -> None:
        err = ExecutionError("Not implemented", code="EXEC_NOT_IMPLEMENTED")
        assert err.code == "EXEC_NOT_IMPLEMENTED"

    def test_is_mcp_base_error(self) -> None:
        assert isinstance(ExecutionError("x"), MCPBaseError)
