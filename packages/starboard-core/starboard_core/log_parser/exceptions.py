# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Custom exceptions for the Spark log parser.

These exceptions are specific to log parsing operations and are independent
of any external error hierarchies. This allows the log_parser module to be
extracted into a standalone package without external dependencies.

Examples:
    >>> from starboard_core.log_parser.exceptions import SparkLogPathNotFoundError
    >>>
    >>> try:
    >>>     raise SparkLogPathNotFoundError("/missing/path", cluster_id="cluster-123")
    >>> except SparkLogPathNotFoundError as e:
    >>>     print(e.log_path)  # "/missing/path"
    >>>     print(e.cluster_id)  # "cluster-123"
"""

from __future__ import annotations

from typing import Any


class LogParserError(Exception):
    """
    Base exception for all log parser errors.

    All custom exceptions in the log_parser module inherit from this base class,
    making it easy to catch all log parser-related errors.

    Args:
        message: Human-readable error message
        details: Optional dictionary with additional error context

    Attributes:
        message: The error message
        details: Additional context dictionary

    Examples:
        >>> error = LogParserError("Parse failed", details={"line": 42})
        >>> print(error.message)  # "Parse failed"
        >>> print(error.details)  # {"line": 42}
    """

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
        """
        Return string representation of the error.

        If details are present, they are appended to the message in the format:
        "message (key1=value1, key2=value2)"

        Returns:
            Formatted error message with optional details
        """
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


class SparkLogPathNotFoundError(LogParserError):
    """
    Raised when Spark application log path does not exist.

    This can occur when:
    - Local file path doesn't exist on the filesystem
    - DBFS path doesn't exist in Databricks
    - HTTP URL returns 404
    - S3/ADLS/GCS path doesn't exist in cloud storage
    - Unity Catalog Volume path doesn't exist

    Args:
        log_path: The path that was not found
        cluster_id: Optional cluster identifier for context
        details: Optional additional context

    Attributes:
        log_path: The path that was not found
        cluster_id: Optional cluster identifier

    Examples:
        >>> error = SparkLogPathNotFoundError(
        ...     "/dbfs/cluster-logs/eventlog",
        ...     cluster_id="cluster-abc-123"
        ... )
        >>> print(error.log_path)  # "/dbfs/cluster-logs/eventlog"
        >>> print(error.cluster_id)  # "cluster-abc-123"
    """

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


class LogSubmissionException(LogParserError):
    """
    Raised when log submission or parsing fails.

    This is a general exception for log submission failures that don't
    fall into more specific categories.

    Examples:
        >>> raise LogSubmissionException("Invalid log format: expected JSON")
    """

    pass


class UrgentEventValidationException(LogParserError):
    """
    Raised when critical event validation fails during streaming parse.

    This exception indicates that required Spark listener event data is missing
    from the event log, which prevents accurate analysis.

    Examples:
        >>> raise UrgentEventValidationException(
        ...     "Missing 'Stage 0 Submit' event data"
        ... )
    """

    pass


class ArchiveTooLargeError(LogParserError):
    """
    Raised when archive expands beyond allowed size limit.

    This is a safety measure to prevent memory exhaustion when processing
    compressed archives that expand to very large sizes.

    Examples:
        >>> raise ArchiveTooLargeError("Archive exceeds 50GB limit")
    """

    pass


class ArchiveTooManyEntriesError(LogParserError):
    """
    Raised when archive has more entries than allowed.

    This is a safety measure to prevent resource exhaustion when processing
    archives with an excessive number of files.

    Examples:
        >>> raise ArchiveTooManyEntriesError("Archive contains >100 files")
    """

    pass


class DBFSOperationError(LogParserError):
    """
    Raised when DBFS operations fail.

    This exception wraps errors from DBFS file system operations such as
    reading, listing, or checking file existence.

    Args:
        operation: Operation that failed (e.g., "read", "list", "exists")
        dbfs_path: DBFS path involved in the operation
        reason: Why the operation failed
        details: Optional additional context

    Attributes:
        operation: Operation that failed
        dbfs_path: DBFS path involved
        reason: Failure reason

    Examples:
        >>> error = DBFSOperationError(
        ...     operation="read",
        ...     dbfs_path="/test/file.json",
        ...     reason="Permission denied",
        ...     details={"status_code": 403}
        ... )
        >>> print(error.operation)  # "read"
        >>> print(error.dbfs_path)  # "/test/file.json"
    """

    def __init__(
        self,
        operation: str,
        dbfs_path: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize DBFS operation error.

        Args:
            operation: Operation that failed (e.g., "read", "list", "exists")
            dbfs_path: DBFS path involved in the operation
            reason: Why the operation failed
            details: Optional additional context
        """
        message = f"DBFS {operation} failed for {dbfs_path}: {reason}"
        super().__init__(message, details)
        self.operation = operation
        self.dbfs_path = dbfs_path
        self.reason = reason


class CloudStorageError(LogParserError):
    """
    Raised when cloud storage operations fail.

    This exception wraps errors from cloud storage operations such as
    reading from S3, ADLS Gen2, or GCS, listing files, checking existence,
    or getting file metadata.

    Args:
        operation: Operation that failed (e.g., "read", "write", "list", "exists", "get_size")
        path: Cloud storage path involved in the operation
        reason: Why the operation failed
        details: Optional additional context

    Attributes:
        operation: Operation that failed
        path: Cloud storage path involved
        reason: Failure reason

    Examples:
        >>> error = CloudStorageError(
        ...     operation="read",
        ...     path="s3://my-bucket/file.json",
        ...     reason="Permission denied",
        ...     details={"status_code": 403}
        ... )
        >>> print(error.operation)  # "read"
        >>> print(error.path)  # "s3://my-bucket/file.json"
        >>> print(error.reason)  # "Permission denied"
    """

    def __init__(
        self,
        operation: str,
        path: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize cloud storage operation error.

        Args:
            operation: Operation that failed (e.g., "read", "write", "list", "exists")
            path: Cloud storage path involved in the operation
            reason: Why the operation failed
            details: Optional additional context
        """
        message = f"Cloud storage {operation} failed for {path}: {reason}"
        super().__init__(message, details)
        self.operation = operation
        self.path = path
        self.reason = reason
