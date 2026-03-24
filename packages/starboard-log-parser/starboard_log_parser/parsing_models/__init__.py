"""
Spark Log Parser - Parsing Models

This module contains models and utilities for parsing Apache Spark event logs.
"""

# Core event log parser - import directly to avoid circular import with loaders
# from starboard_log_parser.parsing_models.event_log_parser import ApplicationModel

# Individual component models
from starboard_log_parser.parsing_models.dag_model import DagModel

# Error handling
from starboard_log_parser.parsing_models.errors import (
    ParserErrorCodes,
    ParserErrorMessages,
    ParserErrorTypes,
)
from starboard_log_parser.parsing_models.exceptions import (
    ConfigurationException,
    LazyEventValidationException,
    LogSubmissionException,
    SyncParserException,
    UrgentEventValidationException,
)
from starboard_log_parser.parsing_models.executor_model import (
    ExecutorModel,
)
from starboard_log_parser.parsing_models.job_model import JobModel
from starboard_log_parser.parsing_models.stage_model import StageModel
from starboard_log_parser.parsing_models.task_model import TaskModel
from starboard_log_parser.parsing_models.utility import db_to_aws_configs

# Validation classes
from starboard_log_parser.parsing_models.validation_configs import (
    ConfigValidation,
    ConfigValidationDatabricks,
    ConfigValidationEMR,
)
from starboard_log_parser.parsing_models.validation_event_data import (
    EventDataValidation,
)

# Defer imports that cause circular dependencies
# These will be imported on first access via __getattr__
_LAZY_IMPORTS = {
    "SparkApplication": "starboard_log_parser.parsing_models.application",
    "create_spark_application": "starboard_log_parser.parsing_models.application",
    "ApplicationModel": "starboard_log_parser.parsing_models.event_log_parser",
}

__all__ = [
    # Main API (lazy loaded)
    "SparkApplication",
    "create_spark_application",
    "ApplicationModel",
    # Core models
    "DagModel",
    "ExecutorModel",
    "JobModel",
    "StageModel",
    "TaskModel",
    # Validation
    "ConfigValidation",
    "ConfigValidationDatabricks",
    "ConfigValidationEMR",
    "EventDataValidation",
    # Utility
    "db_to_aws_configs",
    # Error types
    "ParserErrorCodes",
    "ParserErrorMessages",
    "ParserErrorTypes",
    # Exceptions
    "ConfigurationException",
    "LazyEventValidationException",
    "LogSubmissionException",
    "SyncParserException",
    "UrgentEventValidationException",
]


def __getattr__(name):
    """Lazy import for attributes to avoid circular imports."""
    if name in _LAZY_IMPORTS:
        module_path = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
