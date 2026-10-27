# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Starboard Log Parser - High-performance Spark event log parser.

This package provides a flexible, protocol-based architecture for parsing
Spark event logs from multiple sources (local files, DBFS, Unity Catalog Volumes,
S3, and HTTP/HTTPS).

Main Entry Points:
    - create_spark_application: Unified path-based factory (local, DBFS, S3, HTTP)
    - SparkApplication: Main application model containing all parsed data
    - DBFSClient: Protocol for implementing custom DBFS clients
    - DatabricksSDKAdapter: Ready-to-use DBFS adapter for Databricks SDK

Examples:
    >>> from starboard_core.log_parser import create_spark_application
    >>> app = create_spark_application(path="/path/to/eventlog.gz")
    >>> print(f"Jobs: {len(app.job_data)}, Stages: {len(app.stage_data)}")

    >>> app = create_spark_application(path="dbfs:/logs/eventlog")

    >>> app = create_spark_application(path="s3://bucket/logs/app.json")
"""

from __future__ import annotations

__version__ = "0.1.0"

# In-memory factory helpers (content, dict, JSON file)
from starboard_core.log_parser.application.factory import (
    create_spark_application_from_content,
    create_spark_application_from_dict,
    create_spark_application_from_json,
)
from starboard_core.log_parser.domain.models.application import SparkApplication
from starboard_core.log_parser.domain.models.info import SparkApplicationInfo
from starboard_core.log_parser.domain.models.metadata import SparkApplicationMetadata

# Import exceptions
from starboard_core.log_parser.exceptions import (
    ArchiveTooLargeError,
    ArchiveTooManyEntriesError,
    DBFSOperationError,
    LogParserError,
    LogSubmissionException,
    SparkLogPathNotFoundError,
    UrgentEventValidationException,
)

# Import protocols
from starboard_core.log_parser.loaders.protocols import DBFSClient

# Unified path-based factory (local, DBFS, Volumes, S3, HTTP)
from starboard_core.log_parser.parsing_models.application.factory import (
    create_spark_application,
)

__all__ = [
    # Factory functions
    "create_spark_application",
    "create_spark_application_from_content",
    "create_spark_application_from_dict",
    "create_spark_application_from_json",
    # Models
    "SparkApplication",
    "SparkApplicationInfo",
    "SparkApplicationMetadata",
    # Protocols
    "DBFSClient",
    # Exceptions
    "LogParserError",
    "SparkLogPathNotFoundError",
    "LogSubmissionException",
    "UrgentEventValidationException",
    "ArchiveTooLargeError",
    "ArchiveTooManyEntriesError",
    "DBFSOperationError",
    # Version
    "__version__",
]
