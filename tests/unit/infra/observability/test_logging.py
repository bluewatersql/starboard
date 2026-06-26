# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for structured logging with correlation IDs.

Coverage targets:
- Request ID management
- Structured logging setup
- Context variable handling
"""

import logging
import uuid

from starboard_server.infra.observability.logging import (
    clear_request_id,
    get_logger,
    get_request_id,
    set_request_id,
    setup_structured_logging,
)


class TestRequestIDManagement:
    """Tests for request ID context management."""

    def test_get_request_id_generates_new_id(self) -> None:
        """Test that get_request_id generates a new UUID when none exists."""
        # Arrange
        clear_request_id()

        # Act
        rid = get_request_id()

        # Assert
        assert rid
        assert isinstance(rid, str)
        # Verify it's a valid UUID
        uuid.UUID(rid)

    def test_get_request_id_returns_existing_id(self) -> None:
        """Test that get_request_id returns the existing ID if set."""
        # Arrange
        clear_request_id()
        expected_id = "test-request-123"
        set_request_id(expected_id)

        # Act
        rid = get_request_id()

        # Assert
        assert rid == expected_id

    def test_set_request_id(self) -> None:
        """Test setting a custom request ID."""
        # Arrange
        test_id = "custom-id-456"

        # Act
        set_request_id(test_id)
        rid = get_request_id()

        # Assert
        assert rid == test_id

    def test_clear_request_id(self) -> None:
        """Test clearing the request ID."""
        # Arrange
        set_request_id("test-id")

        # Act
        clear_request_id()
        rid = get_request_id()

        # Assert
        # Should generate a new ID after clearing
        assert rid != "test-id"
        assert rid  # Should not be empty

    def test_request_id_isolation_between_contexts(self) -> None:
        """Test that request IDs are isolated in different contexts."""
        # Arrange
        clear_request_id()

        # Act
        id1 = get_request_id()
        clear_request_id()
        id2 = get_request_id()

        # Assert
        assert id1 != id2


class TestStructuredLoggingSetup:
    """Tests for structured logging configuration."""

    def test_setup_structured_logging_default(self) -> None:
        """Test setup with default configuration (pii redaction off)."""
        # Act
        setup_structured_logging()

        # Assert
        # Get a logger and verify it works
        logger = get_logger(__name__)
        assert logger is not None

        # Verify we can log without errors
        logger.info("test_message", key="value")

    def test_setup_with_pii_redaction_enabled(self) -> None:
        """Test setup with PII redaction enabled."""
        setup_structured_logging(enable_pii_redaction=True)
        logger = get_logger(__name__)
        assert logger is not None
        logger.info("test_pii_redaction", token="Bearer secret123")

    def test_setup_with_pii_redaction_disabled(self) -> None:
        """Test setup with PII redaction disabled (default)."""
        setup_structured_logging(enable_pii_redaction=False)
        logger = get_logger(__name__)
        assert logger is not None
        logger.info("test_no_redaction", token="Bearer secret123")

    def test_setup_structured_logging_with_info_level(self) -> None:
        """Test setup with INFO level."""
        # Act
        setup_structured_logging(level=logging.INFO)

        # Assert
        logger = get_logger(__name__)
        assert logger is not None

    def test_setup_structured_logging_with_debug_level(self) -> None:
        """Test setup with DEBUG level."""
        # Act
        setup_structured_logging(level=logging.DEBUG)

        # Assert
        logger = get_logger(__name__)
        assert logger is not None

    def test_setup_structured_logging_with_json_output(self) -> None:
        """Test setup with JSON output format."""
        # Act
        setup_structured_logging(json_output=True)

        # Assert
        logger = get_logger(__name__)
        assert logger is not None
        # Verify we can log in JSON format
        logger.info("test_json", data={"key": "value"})

    def test_setup_structured_logging_with_console_output(self) -> None:
        """Test setup with console output format."""
        # Act
        setup_structured_logging(json_output=False)

        # Assert
        logger = get_logger(__name__)
        assert logger is not None
        # Verify we can log with console colors
        logger.info("test_console", data={"key": "value"})

    def test_setup_structured_logging_is_idempotent(self) -> None:
        """Test that setup can be called multiple times safely."""
        # Act
        setup_structured_logging(level=logging.INFO)
        setup_structured_logging(level=logging.DEBUG)
        setup_structured_logging(json_output=True)

        # Assert
        logger = get_logger(__name__)
        assert logger is not None
        logger.debug("test_reconfiguration")


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_bound_logger(self) -> None:
        """Test that get_logger returns a structlog BoundLogger."""
        # Act
        logger = get_logger(__name__)

        # Assert
        assert logger is not None
        # Should have structlog methods
        assert hasattr(logger, "bind")
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")

    def test_get_logger_with_different_names(self) -> None:
        """Test getting loggers with different names."""
        # Act
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")

        # Assert
        assert logger1 is not None
        assert logger2 is not None
        # They should be different instances
        assert logger1 != logger2

    def test_logger_can_log_with_context(self) -> None:
        """Test that logger can log with additional context."""
        # Arrange
        logger = get_logger(__name__)

        # Act & Assert - should not raise
        logger.info("test_message", user_id="123", action="test")
        logger.debug("debug_message", trace_id="abc")
        logger.warning("warning_message", status="warning")
        logger.error("error_message", error_code=500)

    def test_logger_bind_creates_new_context(self) -> None:
        """Test that logger.bind creates a new logger with context."""
        # Arrange
        logger = get_logger(__name__)

        # Act
        bound_logger = logger.bind(request_id="req-123", user="test_user")

        # Assert
        assert bound_logger is not None
        # Should be able to log with bound context
        bound_logger.info("test_with_context")


class TestLoggingIntegration:
    """Integration tests for logging functionality."""

    def test_request_id_in_log_context(self) -> None:
        """Test that request ID is included in log context."""
        # Arrange
        setup_structured_logging()
        logger = get_logger(__name__)
        test_id = "integration-test-id"
        set_request_id(test_id)

        # Act & Assert - should not raise
        logger.info("test_with_request_id", action="test")

        # Cleanup
        clear_request_id()

    def test_multiple_log_levels(self) -> None:
        """Test logging at different levels."""
        # Arrange
        setup_structured_logging(level=logging.DEBUG)
        logger = get_logger(__name__)

        # Act & Assert - should not raise
        logger.debug("debug_message")
        logger.info("info_message")
        logger.warning("warning_message")
        logger.error("error_message")

    def test_logging_with_exception_info(self) -> None:
        """Test logging with exception information."""
        # Arrange
        logger = get_logger(__name__)

        # Act & Assert - should not raise
        try:
            raise ValueError("Test exception")
        except ValueError:
            logger.error("exception_occurred", exc_info=True)
