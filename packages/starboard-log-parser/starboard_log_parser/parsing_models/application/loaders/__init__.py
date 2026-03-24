"""
Loaders for Spark application data.

Provides loaders for various data sources and formats.
"""

from starboard_log_parser.parsing_models.application.loaders.ambiguous import (
    AmbiguousLogFormatSparkApplicationLoader,
    BaseAmbiguousLogFormatSparkApplicationLoader,
)
from starboard_log_parser.parsing_models.application.loaders.base import (
    AbstractSparkApplicationDataLoader,
    SparkApplicationClass,
    SparkApplicationLoaderKey,
    SparkApplicationRawDataType,
)
from starboard_log_parser.parsing_models.application.loaders.parsed import (
    ParsedLogSparkApplicationLoader,
)
from starboard_log_parser.parsing_models.application.loaders.unparsed import (
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
