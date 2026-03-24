"""
Application layer for Spark log parser.

This package contains in-memory factory helpers that create SparkApplication
domain models from JSON files, dictionaries, and raw content.

For path-based loading (local, DBFS, S3, HTTP) use::

    from starboard_log_parser import create_spark_application
"""

from starboard_log_parser.application.factory import (
    create_spark_application_from_content,
    create_spark_application_from_dict,
    create_spark_application_from_json,
)

__all__ = [
    "create_spark_application_from_content",
    "create_spark_application_from_dict",
    "create_spark_application_from_json",
]
