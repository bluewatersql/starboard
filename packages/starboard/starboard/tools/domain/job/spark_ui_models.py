# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Domain models for Spark UI data structures.

These dataclasses provide type-safe representations of Spark jobs, stages,
and aggregated metrics for transformation and analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JobInfo:
    """Parsed Spark job information.

    Attributes:
        job_id: Unique job identifier
        sql_id: SQL execution ID (None for non-SQL jobs)
        duration_s: Job duration in seconds
        stage_ids: List of stage IDs associated with this job
    """

    job_id: int | None
    sql_id: str | None
    duration_s: float
    stage_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class StageInfo:
    """Parsed Spark stage information.

    Attributes:
        stage_id: Unique stage identifier
        query_id: Query ID (often matches sql_id)
        job_id: Parent job ID
        duration_s: Stage duration in seconds
        num_tasks: Number of tasks in this stage
        input_mb: Input data size in MB
        shuffle_written_mb: Shuffle write size in MB
        remote_read_mb: Remote shuffle read size in MB
        output_mb: Output data size in MB
        memory_spilled_mb: Memory spilled to disk in MB
        disk_spilled_mb: Disk spill size in MB
        stage_name: Human-readable stage name
    """

    stage_id: int | None
    query_id: str | None
    job_id: int | None
    duration_s: float
    num_tasks: int
    input_mb: float
    shuffle_written_mb: float
    remote_read_mb: float
    output_mb: float
    memory_spilled_mb: float
    disk_spilled_mb: float
    stage_name: str | None


@dataclass
class IOMetrics:
    """Aggregated I/O metrics for Spark execution.

    Attributes:
        input_mb: Total input data in MB
        shuffle_written_mb: Total shuffle write in MB
        remote_read_mb: Total remote shuffle read in MB
        output_mb: Total output data in MB
        memory_spilled_mb: Total memory spilled in MB
        disk_spilled_mb: Total disk spilled in MB
    """

    input_mb: float = 0.0
    shuffle_written_mb: float = 0.0
    remote_read_mb: float = 0.0
    output_mb: float = 0.0
    memory_spilled_mb: float = 0.0
    disk_spilled_mb: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary with rounded values."""
        return {
            "input_mb": round(self.input_mb, 3),
            "shuffle_written_mb": round(self.shuffle_written_mb, 3),
            "remote_read_mb": round(self.remote_read_mb, 3),
            "output_mb": round(self.output_mb, 3),
            "memory_spilled_mb": round(self.memory_spilled_mb, 3),
            "disk_spilled_mb": round(self.disk_spilled_mb, 3),
        }


@dataclass
class SQLExecutionSummary:
    """Summary of Spark execution grouped by SQL ID.

    Attributes:
        sql_id: SQL execution ID (or "unknown" for non-SQL jobs)
        job_ids: List of job IDs in this execution
        job_count: Number of jobs
        total_job_duration_s: Sum of job durations
        total_stages: Number of stages
        io: Aggregated I/O metrics
        long_stages: List of heavy/long-running stages
    """

    sql_id: str
    job_ids: list[int | None] = field(default_factory=list)
    job_count: int = 0
    total_job_duration_s: float = 0.0
    total_stages: int = 0
    io: IOMetrics = field(default_factory=IOMetrics)
    long_stages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "sql_id": self.sql_id,
            "job_count": self.job_count,
            "total_job_duration_s": round(self.total_job_duration_s, 3),
            "total_stages": self.total_stages,
            "io": self.io.to_dict(),
            "long_stages": self.long_stages[:5],
            "job_ids": self.job_ids,
        }


@dataclass(frozen=True)
class SparkUIAnalysis:
    """Complete analysis result from Spark UI log.

    Attributes:
        summary: Global summary metrics
        by_sql_id: Execution summaries grouped by SQL ID
        top_slowest_jobs: Top N slowest jobs
        top_heaviest_stages: Top N heaviest stages
    """

    summary: dict[str, Any]
    by_sql_id: dict[str, dict[str, Any]]
    top_slowest_jobs: list[dict[str, Any]]
    top_heaviest_stages: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "summary": self.summary,
            "by_sql_id": self.by_sql_id,
            "top_slowest_jobs": self.top_slowest_jobs,
            "top_heaviest_stages": self.top_heaviest_stages,
        }
