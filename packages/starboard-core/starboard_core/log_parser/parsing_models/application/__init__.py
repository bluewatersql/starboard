# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Spark application data model and loaders.

This package provides:
- SparkApplication: Main data model for parsed Spark event logs
- Type definitions: SparkApplicationInfo, SparkApplicationMetadata
- Loaders: Various loaders for different data sources and formats
- Factory: Convenience function for creating SparkApplication instances

Public API:
    # Core model and types
    SparkApplication
    SparkApplicationInfo
    SparkApplicationMetadata

    # Factory function
    create_spark_application

    # Type variables
    SparkApplicationClass
    SparkApplicationLoaderKey
    SparkApplicationRawDataType

    # Loaders
    AbstractSparkApplicationDataLoader
    ParsedLogSparkApplicationLoader
    UnparsedLogSparkApplicationLoader
    AmbiguousLogFormatSparkApplicationLoader
    BaseAmbiguousLogFormatSparkApplicationLoader

Example:
    >>> from starboard_core.log_parser.parsing_models.application import (
    ...     create_spark_application,
    ...     SparkApplication,
    ... )
    >>> app = create_spark_application(path="/path/to/eventlog.gz")
    >>> print(app.jobData)
"""

# Core model and types
# Factory function
from starboard_core.log_parser.parsing_models.application.factory import (
    create_spark_application,
)

# Loaders (import full module to avoid circular imports)
from starboard_core.log_parser.parsing_models.application.loaders import (
    AbstractSparkApplicationDataLoader,
    AmbiguousLogFormatSparkApplicationLoader,
    BaseAmbiguousLogFormatSparkApplicationLoader,
    ParsedLogSparkApplicationLoader,
    SparkApplicationClass,
    SparkApplicationLoaderKey,
    SparkApplicationRawDataType,
    UnparsedLogSparkApplicationLoader,
)
from starboard_core.log_parser.parsing_models.application.model import (
    SparkApplication,
)
from starboard_core.log_parser.parsing_models.application.types import (
    SparkApplicationInfo,
    SparkApplicationMetadata,
)

__all__ = [
    # Core model and types
    "SparkApplication",
    "SparkApplicationInfo",
    "SparkApplicationMetadata",
    # Factory function
    "create_spark_application",
    # Type variables
    "SparkApplicationClass",
    "SparkApplicationLoaderKey",
    "SparkApplicationRawDataType",
    # Loaders
    "AbstractSparkApplicationDataLoader",
    "ParsedLogSparkApplicationLoader",
    "UnparsedLogSparkApplicationLoader",
    "BaseAmbiguousLogFormatSparkApplicationLoader",
    "AmbiguousLogFormatSparkApplicationLoader",
]
