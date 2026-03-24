"""Job domain logic - pure business rules with no I/O dependencies."""

from starboard_core.domain.models.job import (
    AnalysisMode,
    JobHistoryResult,
    JobResolutionInput,
    JobResolutionResult,
    TaskDependencyResult,
)
from starboard_core.domain.transformers.job_transformers import (
    transform_job_config,
    transform_job_runs,
    transform_system_tables_job_detail,
    transform_task_sources,
)

from starboard_server.tools.domain.job.analyzer import JobAnalyzer
from starboard_server.tools.domain.job.resolver import JobResolver
from starboard_server.tools.domain.job.spark_ui_analyzer import SparkUIAnalyzer
from starboard_server.tools.domain.job.spark_ui_models import (
    IOMetrics,
    JobInfo,
    SparkUIAnalysis,
    SQLExecutionSummary,
    StageInfo,
)

__all__ = [
    # Analyzers and resolvers
    "JobAnalyzer",
    "JobResolver",
    "SparkUIAnalyzer",
    # Models
    "AnalysisMode",
    "JobResolutionInput",
    "JobResolutionResult",
    "JobHistoryResult",
    "TaskDependencyResult",
    # Spark UI models
    "JobInfo",
    "StageInfo",
    "IOMetrics",
    "SQLExecutionSummary",
    "SparkUIAnalysis",
    # Transform functions
    "transform_job_config",
    "transform_job_runs",
    "transform_system_tables_job_detail",
    "transform_task_sources",
]
