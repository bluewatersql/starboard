# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Loaders for Spark application data.

Provides loaders for various data sources and formats.
"""

from starboard_core.log_parser.parsing_models.application.loaders.ambiguous import (
    AmbiguousLogFormatSparkApplicationLoader,
    BaseAmbiguousLogFormatSparkApplicationLoader,
)
from starboard_core.log_parser.parsing_models.application.loaders.base import (
    AbstractSparkApplicationDataLoader,
    SparkApplicationClass,
    SparkApplicationLoaderKey,
    SparkApplicationRawDataType,
)
from starboard_core.log_parser.parsing_models.application.loaders.parsed import (
    ParsedLogSparkApplicationLoader,
)
from starboard_core.log_parser.parsing_models.application.loaders.unparsed import (
    UnparsedLogSparkApplicationLoader,
)

__all__ = [
    # Base types and abstract class
    "AbstractSparkApplicationDataLoader",
    "SparkApplicationClass",
    "SparkApplicationLoaderKey",
    "SparkApplicationRawDataType",
    # Concrete loaders
    "ParsedLogSparkApplicationLoader",
    "UnparsedLogSparkApplicationLoader",
    "BaseAmbiguousLogFormatSparkApplicationLoader",
    "AmbiguousLogFormatSparkApplicationLoader",
]
