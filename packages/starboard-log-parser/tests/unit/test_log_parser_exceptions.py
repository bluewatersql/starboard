# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for log_parser exceptions.

Tests custom exception classes for the Spark log parser.
Following TDD: Writing tests first, before implementation.
"""

from __future__ import annotations

import pytest


def test_log_parser_error_base_exception():
    """Test LogParserError base exception."""
    from starboard_log_parser.exceptions import LogParserError

    # Test basic construction
    error = LogParserError("Test error message")
    assert str(error) == "Test error message"
    assert error.message == "Test error message"
    assert error.details == {}


def test_log_parser_error_with_details():
    """Test LogParserError with details dictionary."""
    from starboard_log_parser.exceptions import LogParserError

    details = {"file_path": "/test/path", "line_number": 42}
    error = LogParserError("Parse failed", details=details)

    assert error.message == "Parse failed"
    assert error.details == details
    assert "file_path=/test/path" in str(error)
    assert "line_number=42" in str(error)


def test_spark_log_path_not_found_error():
    """Test SparkLogPathNotFoundError exception."""
    from starboard_log_parser.exceptions import SparkLogPathNotFoundError

    # Test without cluster_id
    error1 = SparkLogPathNotFoundError("/path/to/logs")
    assert "does not exist: /path/to/logs" in str(error1)
    assert error1.log_path == "/path/to/logs"
    assert error1.cluster_id is None

    # Test with cluster_id
    error2 = SparkLogPathNotFoundError("/path/to/logs", cluster_id="cluster-123")
    assert "/path/to/logs" in str(error2)
    assert "cluster-123" in str(error2)
    assert error2.cluster_id == "cluster-123"


def test_spark_log_path_not_found_error_with_details():
    """Test SparkLogPathNotFoundError with additional details."""
    from starboard_log_parser.exceptions import SparkLogPathNotFoundError

    details = {"scheme": "dbfs", "normalized_path": "/dbfs/logs"}
    error = SparkLogPathNotFoundError(
        "dbfs:/logs", cluster_id="cluster-456", details=details
    )

    assert error.log_path == "dbfs:/logs"
    assert error.cluster_id == "cluster-456"
    assert error.details == details


def test_log_submission_exception():
    """Test LogSubmissionException."""
    from starboard_log_parser.exceptions import LogSubmissionException

    error = LogSubmissionException("Invalid log format")
    assert str(error) == "Invalid log format"
    assert isinstance(error, Exception)


def test_urgent_event_validation_exception():
    """Test UrgentEventValidationException."""
    from starboard_log_parser.exceptions import (
        UrgentEventValidationException,
    )

    error = UrgentEventValidationException("Missing critical event data")
    assert "Missing critical event data" in str(error)


def test_archive_too_large_error():
    """Test ArchiveTooLargeError."""
    from starboard_log_parser.exceptions import ArchiveTooLargeError

    error = ArchiveTooLargeError("Archive exceeds 50GB limit")
    assert "50GB" in str(error)


def test_archive_too_many_entries_error():
    """Test ArchiveTooManyEntriesError."""
    from starboard_log_parser.exceptions import ArchiveTooManyEntriesError

    error = ArchiveTooManyEntriesError("Archive contains too many files")
    assert "too many" in str(error)


def test_dbfs_operation_error():
    """Test DBFSOperationError exception."""
    from starboard_log_parser.exceptions import DBFSOperationError

    error = DBFSOperationError(
        operation="read", dbfs_path="/test/file.json", reason="Permission denied"
    )

    assert "read" in str(error)
    assert "/test/file.json" in str(error)
    assert "Permission denied" in str(error)
    assert error.operation == "read"
    assert error.dbfs_path == "/test/file.json"
    assert error.reason == "Permission denied"


def test_dbfs_operation_error_with_details():
    """Test DBFSOperationError with additional details."""
    from starboard_log_parser.exceptions import DBFSOperationError

    details = {"offset": 0, "length": 1024, "status_code": 403}
    error = DBFSOperationError(
        operation="read",
        dbfs_path="/test/file",
        reason="Access denied",
        details=details,
    )

    assert error.details == details
    assert error.operation == "read"


@pytest.mark.parametrize(
    "operation,path,reason",
    [
        ("read", "/test/file.json", "File not found"),
        ("list", "/test/directory", "Permission denied"),
        ("exists", "/test/path", "Network error"),
    ],
)
def test_dbfs_operation_error_scenarios(operation: str, path: str, reason: str):
    """Test DBFSOperationError with various scenarios."""
    from starboard_log_parser.exceptions import DBFSOperationError

    error = DBFSOperationError(operation=operation, dbfs_path=path, reason=reason)

    assert operation in str(error)
    assert path in str(error)
    assert reason in str(error)
    assert error.operation == operation
    assert error.dbfs_path == path
    assert error.reason == reason


def test_exception_inheritance_hierarchy():
    """Test that exception inheritance hierarchy is correct."""
    from starboard_log_parser.exceptions import (
        ArchiveTooLargeError,
        ArchiveTooManyEntriesError,
        DBFSOperationError,
        LogParserError,
        LogSubmissionException,
        SparkLogPathNotFoundError,
        UrgentEventValidationException,
    )

    # All custom exceptions should inherit from LogParserError
    assert issubclass(SparkLogPathNotFoundError, LogParserError)
    assert issubclass(LogSubmissionException, LogParserError)
    assert issubclass(DBFSOperationError, LogParserError)
    assert issubclass(ArchiveTooLargeError, LogParserError)
    assert issubclass(ArchiveTooManyEntriesError, LogParserError)
    assert issubclass(UrgentEventValidationException, LogParserError)

    # LogParserError should inherit from Exception
    assert issubclass(LogParserError, Exception)


def test_exceptions_can_be_caught():
    """Test that exceptions can be caught and handled."""
    from starboard_log_parser.exceptions import (
        DBFSOperationError,
        LogParserError,
        SparkLogPathNotFoundError,
    )

    # Test catching specific exception
    with pytest.raises(SparkLogPathNotFoundError) as exc_info:
        raise SparkLogPathNotFoundError("/missing/path")

    assert "/missing/path" in str(exc_info.value)

    # Test catching base exception
    with pytest.raises(LogParserError):
        raise DBFSOperationError("read", "/test", "failed")

    # Test catching as generic Exception
    with pytest.raises(Exception):
        raise SparkLogPathNotFoundError("/test")


def test_exception_message_formatting():
    """Test that exception messages are properly formatted."""
    from starboard_log_parser.exceptions import LogParserError

    # Test with no details
    error1 = LogParserError("Simple message")
    assert str(error1) == "Simple message"

    # Test with empty details
    error2 = LogParserError("Message", details={})
    assert str(error2) == "Message"

    # Test with details
    error3 = LogParserError("Error occurred", details={"code": 404, "path": "/test"})
    error_str = str(error3)
    assert "Error occurred" in error_str
    assert "code=404" in error_str
    assert "path=/test" in error_str


def test_exception_attributes_are_accessible():
    """Test that exception attributes can be accessed."""
    from starboard_log_parser.exceptions import SparkLogPathNotFoundError

    error = SparkLogPathNotFoundError(
        "/test/logs", cluster_id="cluster-789", details={"scheme": "dbfs"}
    )

    # Access attributes
    assert error.log_path == "/test/logs"
    assert error.cluster_id == "cluster-789"
    assert error.details["scheme"] == "dbfs"
    assert error.message  # Should have a message

    # Test string representation
    error_str = str(error)
    assert isinstance(error_str, str)
    assert len(error_str) > 0


def test_exceptions_preserve_traceback():
    """Test that exceptions preserve traceback information."""
    from starboard_log_parser.exceptions import LogSubmissionException

    try:
        try:
            raise ValueError("Original error")
        except ValueError as e:
            raise LogSubmissionException("Wrapped error") from e
    except LogSubmissionException as exc:
        assert exc.__cause__ is not None
        assert isinstance(exc.__cause__, ValueError)
        assert str(exc.__cause__) == "Original error"


def test_exception_repr():
    """Test exception __repr__ method."""
    from starboard_log_parser.exceptions import LogParserError

    error = LogParserError("Test", details={"key": "value"})
    repr_str = repr(error)

    # Should be a valid representation
    assert isinstance(repr_str, str)
    assert len(repr_str) > 0
