"""Domain models for job operations.

Pure domain models for job resolution and analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AnalysisMode(Enum):
    """Mode of job analysis."""

    JOB = "job"
    ADHOC = "adhoc"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class JobResolutionInput:
    """
    Input for job resolution.

    Attributes:
        target: Raw input string (job ID, job name, or source code)
        classification: Optional LLM classification hints
    """

    target: str
    classification: dict[str, Any] | None = None


@dataclass(frozen=True)
class JobResolutionResult:
    """
    Result of job resolution.

    Attributes:
        job_id: Resolved job ID
        job_name: Job name if available
        source_code: Source code for adhoc analysis
        analysis_mode: How the job should be analyzed
    """

    job_id: str | None
    job_name: str | None
    source_code: str | None
    analysis_mode: AnalysisMode


@dataclass(frozen=True)
class JobHistoryResult:
    """
    Result of job history analysis.

    Attributes:
        total_runs: Total number of runs analyzed
        success_rate: Success rate (0.0 to 1.0)
        avg_duration_seconds: Average duration in seconds
        has_failures: Whether there are any failures
        spark_logs: Spark UI logs from most recent cluster (if available and logging enabled)
        cluster_id: Cluster ID that generated the logs (if available)
    """

    total_runs: int
    success_rate: float
    avg_duration_seconds: float
    has_failures: bool
    spark_logs: dict[str, Any] | None = None
    cluster_id: str | None = None


@dataclass(frozen=True)
class TaskDependencyResult:
    """
    Result of task dependency analysis.

    Attributes:
        dependencies: Dict mapping task keys to their dependencies
        critical_path: List of tasks on the critical path
    """

    dependencies: dict[str, list[str]]
    critical_path: list[str]
