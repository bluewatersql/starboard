# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
# ruff: noqa: ARG002 - Extraction methods have consistent signatures for API uniformity

"""
Intent-aware Spark event log explorer.

Uses starboard-core log parser to parse Spark event logs into the immutable
SparkApplication domain model, then extracts focused content based on
user intent.

Supported focus areas:
- Jobs: Job status, timing, failed jobs
- Stages: Stage metrics, slow stages, dependencies
- Tasks: Task metrics, failures, skew detection
- Executors: Executor lifecycle, resource usage
- Performance: Runtime analysis, bottlenecks
- Data Skew: Partition variance, task duration outliers

Design reference: changes/large-file-agent-discovery/ARCHITECTURE.md
"""

from __future__ import annotations

from typing import Any, Literal

from starboard.infra.observability.logging import get_logger
from starboard.tools.domain.diagnostic.models import (
    ExplorationResult,
)

logger = get_logger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Maximum content size by detail level
DETAIL_LIMITS = {
    "summary": 2000,
    "detailed": 10000,
    "exhaustive": 50000,
}

# Focus keyword to handler mapping
FOCUS_HANDLERS: dict[str, str] = {
    # Job-related
    "job": "_extract_jobs",
    "jobs": "_extract_jobs",
    "failed_job": "_extract_jobs",
    "failed": "_extract_jobs",
    # Stage-related
    "stage": "_extract_stages",
    "stages": "_extract_stages",
    "slow_stage": "_extract_stages",
    "slow": "_extract_stages",
    # Task-related
    "task": "_extract_tasks",
    "tasks": "_extract_tasks",
    "task_failure": "_extract_tasks",
    # Executor-related
    "executor": "_extract_executors",
    "executors": "_extract_executors",
    "oom": "_extract_executors",
    "memory": "_extract_executors",
    # Performance-related
    "performance": "_extract_performance",
    "runtime": "_extract_performance",
    "duration": "_extract_performance",
    "timing": "_extract_performance",
    "bottleneck": "_extract_performance",
    # Data skew
    "skew": "_extract_skew",
    "data_skew": "_extract_skew",
    "partition": "_extract_skew",
    # SQL-related
    "sql": "_extract_sql",
    "query": "_extract_sql",
}


# =============================================================================
# SPARK EVENT LOG EXPLORER
# =============================================================================


class SparkEventLogExplorer:
    """Intent-aware explorer for Spark event logs.

    Uses starboard-core log parser to parse event logs into the immutable
    SparkApplication domain model, then extracts relevant information
    based on user's focus query.

    Example:
        >>> explorer = SparkEventLogExplorer()
        >>> result = explorer.explore(
        ...     content="<spark event log json lines>",
        ...     focus="failed jobs",
        ...     detail_level="detailed"
        ... )
        >>> print(result.content)

    Attributes:
        None - this is a stateless explorer.
    """

    def explore(
        self,
        content: str,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"] = "detailed",
    ) -> ExplorationResult:
        """Explore Spark event log with intent-aware extraction.

        Args:
            content: Spark event log content (JSON lines format).
            focus: User's focus query (e.g., "failed jobs", "slow stages").
            detail_level: Level of detail to extract.

        Returns:
            ExplorationResult with extracted content based on focus.
        """
        # Parse the event log using the factory
        app = self._parse_content(content)
        if app is None:
            return ExplorationResult(
                focus_query=focus,
                content="## Parse Error\n\nFailed to parse Spark event log.",
                evidence_count=0,
                sections_found=(),
                has_more=False,
                suggested_followups=(),
            )

        # Determine handler based on focus keywords
        handler_name = self._get_handler(focus)

        # Call the appropriate extraction method
        handler = getattr(self, handler_name, self._extract_overview)
        extracted = handler(app, focus, detail_level)

        # Format and limit output
        limit = DETAIL_LIMITS.get(detail_level, DETAIL_LIMITS["detailed"])
        content_str = extracted.get("content", "")
        if len(content_str) > limit:
            content_str = content_str[:limit] + "\n\n... [truncated]"

        return ExplorationResult(
            focus_query=focus,
            content=content_str,
            evidence_count=extracted.get("evidence_count", 0),
            sections_found=tuple(extracted.get("sections_found", [])),
            has_more=len(extracted.get("content", "")) > limit,
            suggested_followups=tuple(extracted.get("suggested_followups", [])),
        )

    def _parse_content(self, content: str) -> Any:
        """Parse Spark event log content into SparkApplication domain model.

        Args:
            content: Spark event log content (JSON lines format).

        Returns:
            SparkApplication domain model or None if parsing fails.
        """
        try:
            from starboard_core.log_parser import create_spark_application_from_content

            return create_spark_application_from_content(content, debug=True)
        except (ValueError, KeyError, OSError) as e:
            logger.warning("failed_to_parse_spark_event_log", error=str(e))
            return None

    def _get_handler(self, focus: str) -> str:
        """Determine extraction handler based on focus keywords.

        Args:
            focus: User's focus query.

        Returns:
            Handler method name.
        """
        focus_lower = focus.lower()
        for keyword, handler in FOCUS_HANDLERS.items():
            if keyword in focus_lower:
                return handler
        return "_extract_overview"

    # =========================================================================
    # EXTRACTION METHODS
    # =========================================================================

    def _extract_overview(
        self,
        app: Any,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"],
    ) -> dict[str, Any]:
        """Extract application overview.

        Args:
            app: SparkApplication domain model.
            focus: User's focus query.
            detail_level: Level of detail.

        Returns:
            Dictionary with content, evidence_count, sections_found, suggested_followups.
        """
        sections = ["## Spark Application Overview"]

        # Application metadata
        info = app.metadata.application_info
        sections.append(f"\n**Application:** {info.name or 'Unknown'}")
        sections.append(f"**ID:** {info.id or 'Unknown'}")
        sections.append(f"**Spark Version:** {info.spark_version or 'Unknown'}")
        sections.append(f"**Cloud Platform:** {info.cloud_platform or 'Unknown'}")

        # Runtime
        runtime = info.runtime_sec or 0
        sections.append(f"**Runtime:** {self._format_duration(runtime)}")

        # Counts
        job_count = len(app.job_data) if app.job_data is not None else 0
        stage_count = len(app.stage_data) if app.stage_data is not None else 0
        task_count = len(app.task_data) if app.task_data is not None else 0

        sections.append("\n**Summary:**")
        sections.append(f"- Jobs: {job_count}")
        sections.append(f"- Stages: {stage_count}")
        sections.append(f"- Tasks: {task_count}")
        sections.append(f"- Has SQL Data: {app.has_sql_data()}")
        sections.append(f"- Has Executor Data: {app.has_executor_data()}")

        return {
            "content": "\n".join(sections),
            "evidence_count": 1,
            "sections_found": ["overview"],
            "suggested_followups": [
                "Show me failed jobs",
                "What are the slow stages?",
                "Are there executor issues?",
            ],
        }

    def _extract_jobs(
        self,
        app: Any,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"],
    ) -> dict[str, Any]:
        """Extract job information.

        Args:
            app: SparkApplication domain model.
            focus: User's focus query.
            detail_level: Level of detail.

        Returns:
            Dictionary with content, evidence_count, sections_found, suggested_followups.
        """
        sections = ["## Job Analysis"]

        if app.job_data is None or len(app.job_data) == 0:
            sections.append("\nNo job data available in the event log.")
            return {
                "content": "\n".join(sections),
                "evidence_count": 0,
                "sections_found": ["jobs"],
                "suggested_followups": ["Show stages instead"],
            }

        # Convert to list of dicts for easier processing
        jobs = app.job_data.to_dicts()
        total_jobs = len(jobs)

        # Categorize jobs
        failed_jobs = [
            j for j in jobs if j.get("status") not in ("SUCCESS", "JobSucceeded", None)
        ]
        successful_jobs = [
            j for j in jobs if j.get("status") in ("SUCCESS", "JobSucceeded")
        ]

        sections.append(f"\n**Total Jobs:** {total_jobs}")
        sections.append(f"- Successful: {len(successful_jobs)}")
        sections.append(f"- Failed: {len(failed_jobs)}")

        # Show failed jobs
        if failed_jobs:
            sections.append("\n### Failed Jobs")
            limit = 10 if detail_level == "exhaustive" else 5
            for job in failed_jobs[:limit]:
                job_id = job.get("job_id", "?")
                status = job.get("status", "UNKNOWN")
                sections.append(f"- **Job {job_id}:** {status}")

            if len(failed_jobs) > limit:
                sections.append(
                    f"\n... and {len(failed_jobs) - limit} more failed jobs"
                )

        # Show job duration distribution if detailed
        if detail_level in ("detailed", "exhaustive"):
            durations = []
            for job in jobs:
                duration = job.get("duration_sec") or job.get("duration")
                if duration is not None:
                    durations.append(float(duration))

            if durations:
                sections.append("\n### Job Duration Distribution")
                sections.append(f"- Min: {self._format_duration(min(durations))}")
                sections.append(f"- Max: {self._format_duration(max(durations))}")
                sections.append(
                    f"- Avg: {self._format_duration(sum(durations) / len(durations))}"
                )

        return {
            "content": "\n".join(sections),
            "evidence_count": len(failed_jobs) + 1,
            "sections_found": ["jobs", "failed_jobs"] if failed_jobs else ["jobs"],
            "suggested_followups": [
                "Show stages for failed jobs",
                "What caused the failures?",
                "Show executor issues",
            ],
        }

    def _extract_stages(
        self,
        app: Any,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"],
    ) -> dict[str, Any]:
        """Extract stage information.

        Args:
            app: SparkApplication domain model.
            focus: User's focus query.
            detail_level: Level of detail.

        Returns:
            Dictionary with content, evidence_count, sections_found, suggested_followups.
        """
        sections = ["## Stage Analysis"]

        if app.stage_data is None or len(app.stage_data) == 0:
            sections.append("\nNo stage data available in the event log.")
            return {
                "content": "\n".join(sections),
                "evidence_count": 0,
                "sections_found": ["stages"],
                "suggested_followups": ["Show job overview instead"],
            }

        stages = app.stage_data.to_dicts()
        total_stages = len(stages)

        # Calculate durations
        stage_durations = []
        for stage in stages:
            duration = stage.get("duration_sec") or stage.get("duration")
            if duration is not None:
                stage_durations.append((stage, float(duration)))

        # Sort by duration (slowest first)
        stage_durations.sort(key=lambda x: -x[1])

        sections.append(f"\n**Total Stages:** {total_stages}")

        # Find slow stages (> 2x median or > 60s)
        if stage_durations:
            durations_only = [d[1] for d in stage_durations]
            median = sorted(durations_only)[len(durations_only) // 2]
            threshold = max(60.0, median * 2)

            slow_stages = [(s, d) for s, d in stage_durations if d > threshold]

            if slow_stages:
                sections.append(
                    f"\n### Slow Stages (>{self._format_duration(threshold)})"
                )
                limit = 10 if detail_level == "exhaustive" else 5
                for stage, duration in slow_stages[:limit]:
                    stage_id = stage.get("stage_id", "?")
                    name = stage.get("name", "Unknown")
                    num_tasks = stage.get("num_tasks", "?")
                    sections.append(
                        f"- **Stage {stage_id}** ({name}): "
                        f"{self._format_duration(duration)}, {num_tasks} tasks"
                    )

                if len(slow_stages) > limit:
                    sections.append(
                        f"\n... and {len(slow_stages) - limit} more slow stages"
                    )

            # Show top stages by duration
            sections.append("\n### Top Stages by Duration")
            limit = 10 if detail_level == "exhaustive" else 5
            for stage, duration in stage_durations[:limit]:
                stage_id = stage.get("stage_id", "?")
                name = stage.get("name", "Unknown")
                sections.append(
                    f"- Stage {stage_id} ({name}): {self._format_duration(duration)}"
                )

        return {
            "content": "\n".join(sections),
            "evidence_count": len(stage_durations),
            "sections_found": ["stages", "slow_stages"],
            "suggested_followups": [
                "Show task details for slow stages",
                "Check for data skew",
                "Show shuffle metrics",
            ],
        }

    def _extract_tasks(
        self,
        app: Any,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"],
    ) -> dict[str, Any]:
        """Extract task information.

        Args:
            app: SparkApplication domain model.
            focus: User's focus query.
            detail_level: Level of detail.

        Returns:
            Dictionary with content, evidence_count, sections_found, suggested_followups.
        """
        sections = ["## Task Analysis"]

        if app.task_data is None or len(app.task_data) == 0:
            sections.append("\nNo task data available in the event log.")
            return {
                "content": "\n".join(sections),
                "evidence_count": 0,
                "sections_found": ["tasks"],
                "suggested_followups": ["Show stage overview instead"],
            }

        tasks = app.task_data.to_dicts()
        total_tasks = len(tasks)

        # Count failures
        failed_tasks = [t for t in tasks if t.get("failed") is True]

        sections.append(f"\n**Total Tasks:** {total_tasks}")
        sections.append(f"**Failed Tasks:** {len(failed_tasks)}")

        if failed_tasks and detail_level in ("detailed", "exhaustive"):
            sections.append("\n### Failed Tasks")
            limit = 10 if detail_level == "exhaustive" else 5
            for task in failed_tasks[:limit]:
                task_id = task.get("task_id", "?")
                stage_id = task.get("stage_id", "?")
                sections.append(f"- Task {task_id} (Stage {stage_id})")

            if len(failed_tasks) > limit:
                sections.append(
                    f"\n... and {len(failed_tasks) - limit} more failed tasks"
                )

        # Task duration statistics
        if detail_level in ("detailed", "exhaustive"):
            durations = []
            for task in tasks:
                duration = task.get("duration_ms") or task.get("executor_run_time")
                if duration is not None:
                    durations.append(float(duration) / 1000.0)  # Convert to seconds

            if durations:
                durations.sort()
                p50 = durations[len(durations) // 2]
                p99 = durations[int(len(durations) * 0.99)]

                sections.append("\n### Task Duration Statistics")
                sections.append(f"- Min: {self._format_duration(min(durations))}")
                sections.append(f"- P50: {self._format_duration(p50)}")
                sections.append(f"- P99: {self._format_duration(p99)}")
                sections.append(f"- Max: {self._format_duration(max(durations))}")

        return {
            "content": "\n".join(sections),
            "evidence_count": len(failed_tasks) + 1,
            "sections_found": ["tasks", "failed_tasks"] if failed_tasks else ["tasks"],
            "suggested_followups": [
                "Check for data skew",
                "Show executor issues",
                "Analyze shuffle metrics",
            ],
        }

    def _extract_executors(
        self,
        app: Any,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"],
    ) -> dict[str, Any]:
        """Extract executor information.

        Args:
            app: SparkApplication domain model.
            focus: User's focus query.
            detail_level: Level of detail.

        Returns:
            Dictionary with content, evidence_count, sections_found, suggested_followups.
        """
        sections = ["## Executor Analysis"]

        if not app.has_executor_data() or app.executor_data is None:
            sections.append("\nNo executor data available in the event log.")
            return {
                "content": "\n".join(sections),
                "evidence_count": 0,
                "sections_found": ["executors"],
                "suggested_followups": ["Show job overview instead"],
            }

        executors = app.executor_data.to_dicts()
        total_executors = len(executors)

        # Check for removed executors
        removed = [e for e in executors if e.get("removed_reason")]

        sections.append(f"\n**Total Executors:** {total_executors}")
        sections.append(f"**Removed Executors:** {len(removed)}")

        if removed:
            sections.append("\n### Executor Issues")
            limit = 10 if detail_level == "exhaustive" else 5
            for ex in removed[:limit]:
                exec_id = ex.get("executor_id", "?")
                reason = ex.get("removed_reason", "Unknown")
                host = ex.get("host", "?")
                sections.append(f"- **Executor {exec_id}** ({host}): {reason}")

            if len(removed) > limit:
                sections.append(f"\n... and {len(removed) - limit} more issues")

            # Check for OOM patterns
            oom_count = sum(
                1 for e in removed if "OOM" in str(e.get("removed_reason", "")).upper()
            )
            if oom_count > 0:
                sections.append(f"\n⚠️ **{oom_count} executors removed due to OOM**")

        # Show executor resources
        if detail_level in ("detailed", "exhaustive"):
            cores = [e.get("cores") for e in executors if e.get("cores")]
            if cores:
                sections.append("\n### Executor Resources")
                sections.append(f"- Cores per executor: {cores[0]}")
                sections.append(f"- Total executor cores: {sum(cores)}")

        return {
            "content": "\n".join(sections),
            "evidence_count": len(removed) + 1,
            "sections_found": ["executors", "oom"] if removed else ["executors"],
            "suggested_followups": [
                "Show memory configuration",
                "Check for slow stages",
                "Analyze task distribution",
            ],
        }

    def _extract_performance(
        self,
        app: Any,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"],
    ) -> dict[str, Any]:
        """Extract performance overview.

        Args:
            app: SparkApplication domain model.
            focus: User's focus query.
            detail_level: Level of detail.

        Returns:
            Dictionary with content, evidence_count, sections_found, suggested_followups.
        """
        sections = ["## Performance Analysis"]

        info = app.metadata.application_info
        runtime = info.runtime_sec or 0

        sections.append(f"\n**Total Runtime:** {self._format_duration(runtime)}")

        # Job breakdown
        if app.job_data is not None and len(app.job_data) > 0:
            jobs = app.job_data.to_dicts()
            job_durations = []
            for job in jobs:
                d = job.get("duration_sec") or job.get("duration")
                if d is not None:
                    job_durations.append((job.get("job_id"), float(d)))

            if job_durations:
                job_durations.sort(key=lambda x: -x[1])
                sections.append("\n### Time by Job")
                limit = 5
                for job_id, duration in job_durations[:limit]:
                    pct = (duration / runtime * 100) if runtime > 0 else 0
                    sections.append(
                        f"- Job {job_id}: {self._format_duration(duration)} ({pct:.1f}%)"
                    )

        # Stage breakdown
        if app.stage_data is not None and len(app.stage_data) > 0:
            stages = app.stage_data.to_dicts()
            stage_durations = []
            for stage in stages:
                d = stage.get("duration_sec") or stage.get("duration")
                if d is not None:
                    stage_durations.append(
                        (stage.get("stage_id"), stage.get("name"), float(d))
                    )

            if stage_durations:
                stage_durations.sort(key=lambda x: -x[2])
                sections.append("\n### Time by Stage (Top 10)")
                for stage_id, name, duration in stage_durations[:10]:
                    pct = (duration / runtime * 100) if runtime > 0 else 0
                    sections.append(
                        f"- Stage {stage_id} ({name or 'N/A'}): {self._format_duration(duration)} ({pct:.1f}%)"
                    )

        return {
            "content": "\n".join(sections),
            "evidence_count": 1,
            "sections_found": ["performance"],
            "suggested_followups": [
                "Check for data skew",
                "Show executor issues",
                "Analyze shuffle data",
            ],
        }

    def _extract_skew(
        self,
        app: Any,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"],
    ) -> dict[str, Any]:
        """Extract data skew analysis.

        Args:
            app: SparkApplication domain model.
            focus: User's focus query.
            detail_level: Level of detail.

        Returns:
            Dictionary with content, evidence_count, sections_found, suggested_followups.
        """
        sections = ["## Data Skew Analysis"]

        if app.task_data is None or len(app.task_data) == 0:
            sections.append("\nNo task data available for skew analysis.")
            return {
                "content": "\n".join(sections),
                "evidence_count": 0,
                "sections_found": ["skew"],
                "suggested_followups": ["Show job overview instead"],
            }

        tasks = app.task_data.to_dicts()

        # Group tasks by stage and analyze duration variance
        stage_tasks: dict[Any, list[float]] = {}
        for task in tasks:
            stage_id = task.get("stage_id")
            duration = task.get("duration_ms") or task.get("executor_run_time")
            if stage_id is not None and duration is not None:
                if stage_id not in stage_tasks:
                    stage_tasks[stage_id] = []
                stage_tasks[stage_id].append(float(duration))

        # Find skewed stages (max > 5x median)
        skewed_stages = []
        for stage_id, durations in stage_tasks.items():
            if len(durations) >= 10:
                durations.sort()
                median = durations[len(durations) // 2]
                max_dur = max(durations)
                if median > 0 and max_dur / median > 5:
                    skewed_stages.append(
                        {
                            "stage_id": stage_id,
                            "task_count": len(durations),
                            "median_ms": median,
                            "max_ms": max_dur,
                            "skew_ratio": max_dur / median,
                        }
                    )

        # Sort by skew ratio
        skewed_stages.sort(key=lambda x: -x["skew_ratio"])

        sections.append(f"\n**Stages Analyzed:** {len(stage_tasks)}")
        sections.append(f"**Skewed Stages (max > 5x median):** {len(skewed_stages)}")

        if skewed_stages:
            sections.append("\n### Skewed Stages")
            sections.append("\n📊 **Data skew detected in the following stages:**\n")
            limit = 10 if detail_level == "exhaustive" else 5
            for stage in skewed_stages[:limit]:
                sections.append(
                    f"- **Stage {stage['stage_id']}**: "
                    f"Max {self._format_duration(stage['max_ms'] / 1000)} vs "
                    f"Median {self._format_duration(stage['median_ms'] / 1000)} "
                    f"(Skew: {stage['skew_ratio']:.1f}x, {stage['task_count']} tasks)"
                )

            if len(skewed_stages) > limit:
                sections.append(
                    f"\n... and {len(skewed_stages) - limit} more skewed stages"
                )

            sections.append("\n### Recommendations")
            sections.append("- Consider salting keys for skewed joins")
            sections.append("- Use broadcast join for small tables")
            sections.append("- Enable AQE (Adaptive Query Execution)")
            sections.append("- Check for null key concentration")
        else:
            sections.append("\n✅ **No significant data skew detected**")

        return {
            "content": "\n".join(sections),
            "evidence_count": len(skewed_stages),
            "sections_found": ["skew", "recommendations"]
            if skewed_stages
            else ["skew"],
            "suggested_followups": [
                "Show slow stages",
                "Analyze shuffle data",
                "Check memory usage",
            ],
        }

    def _extract_sql(
        self,
        app: Any,
        focus: str,
        detail_level: Literal["summary", "detailed", "exhaustive"],
    ) -> dict[str, Any]:
        """Extract SQL execution information.

        Args:
            app: SparkApplication domain model.
            focus: User's focus query.
            detail_level: Level of detail.

        Returns:
            Dictionary with content, evidence_count, sections_found, suggested_followups.
        """
        sections = ["## SQL Execution Analysis"]

        if not app.has_sql_data() or app.sql_data is None:
            sections.append("\nNo SQL execution data available in the event log.")
            return {
                "content": "\n".join(sections),
                "evidence_count": 0,
                "sections_found": ["sql"],
                "suggested_followups": ["Show job overview instead"],
            }

        sql_executions = app.sql_data.to_dicts()
        total_executions = len(sql_executions)

        sections.append(f"\n**SQL Executions:** {total_executions}")

        # Show execution summaries
        if detail_level in ("detailed", "exhaustive"):
            sections.append("\n### SQL Execution Summary")
            limit = 10 if detail_level == "exhaustive" else 5
            for idx, execution in enumerate(sql_executions[:limit]):
                exec_id = execution.get("execution_id", idx)
                description = execution.get("description", "N/A")
                # Truncate long descriptions
                if len(description) > 100:
                    description = description[:100] + "..."
                sections.append(f"- **Execution {exec_id}:** {description}")

            if len(sql_executions) > limit:
                sections.append(
                    f"\n... and {len(sql_executions) - limit} more executions"
                )

        return {
            "content": "\n".join(sections),
            "evidence_count": total_executions,
            "sections_found": ["sql"],
            "suggested_followups": [
                "Show slow stages",
                "Analyze query performance",
                "Check for data skew",
            ],
        }

    # =========================================================================
    # UTILITIES
    # =========================================================================

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable form.

        Args:
            seconds: Duration in seconds.

        Returns:
            Formatted duration string (e.g., "1h 23m 45s").
        """
        if seconds < 0:
            return "N/A"
        if seconds < 1:
            return f"{seconds * 1000:.0f}ms"
        if seconds < 60:
            return f"{seconds:.1f}s"
        if seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
