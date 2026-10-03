# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for cloud storage exceptions.

Following TDD: tests written first, implementation follows.
"""

from __future__ import annotations

import pytest
from starboard_core.log_parser.exceptions import CloudStorageError, LogParserError


class TestCloudStorageError:
    """Tests for CloudStorageError exception."""

    def test_inherits_from_log_parser_error(self) -> None:
        """CloudStorageError should inherit from LogParserError."""
        error = CloudStorageError(
            operation="read", path="s3://bucket/key", reason="Permission denied"
        )
        assert isinstance(error, LogParserError)
        assert isinstance(error, CloudStorageError)

    def test_basic_initialization(self) -> None:
        """Should initialize with operation, path, and reason."""
        error = CloudStorageError(
            operation="read",
            path="s3://bucket/file.json",
            reason="File not found",
        )

        assert error.operation == "read"
        assert error.path == "s3://bucket/file.json"
        assert error.reason == "File not found"
        assert "read" in str(error)
        assert "s3://bucket/file.json" in str(error)
        assert "File not found" in str(error)

    def test_with_details(self) -> None:
        """Should support optional details dictionary."""
        error = CloudStorageError(
            operation="write",
            path="s3://bucket/file.json",
            reason="Permission denied",
            details={"status_code": 403, "region": "us-west-2"},
        )

        assert error.details == {"status_code": 403, "region": "us-west-2"}
        assert "status_code=403" in str(error) or "status_code: 403" in str(error)

    def test_without_details(self) -> None:
        """Should work without details parameter."""
        error = CloudStorageError(
            operation="list", path="s3://bucket/", reason="Timeout"
        )

        assert error.details == {}
        assert str(error) == "Cloud storage list failed for s3://bucket/: Timeout"

    def test_can_be_raised(self) -> None:
        """Should be raisable as an exception."""
        with pytest.raises(CloudStorageError) as exc_info:
            raise CloudStorageError(
                operation="delete", path="s3://bucket/key", reason="Access denied"
            )

        assert "delete" in str(exc_info.value)
        assert "s3://bucket/key" in str(exc_info.value)

    def test_can_be_caught_as_log_parser_error(self) -> None:
        """Should be catchable as base LogParserError."""
        with pytest.raises(LogParserError):
            raise CloudStorageError(
                operation="read", path="s3://bucket/key", reason="Error"
            )

    def test_message_formatting(self) -> None:
        """Should format message consistently."""
        error = CloudStorageError(
            operation="read",
            path="s3://my-bucket/logs/app.json",
            reason="Connection timeout",
        )

        expected = "Cloud storage read failed for s3://my-bucket/logs/app.json: Connection timeout"
        assert error.message == expected
        assert str(error) == expected
