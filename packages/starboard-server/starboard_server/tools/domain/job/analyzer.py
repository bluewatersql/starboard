# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure job analysis logic."""

from typing import Any

from starboard_core.domain.models.job import (
    JobHistoryResult,
    TaskDependencyResult,
)

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class JobAnalyzer:
    """Pure job analysis logic (no I/O)."""

    @staticmethod
    def analyze_job_history(
        runs: list[dict[str, Any]], runtime_meta: dict[str, Any]
    ) -> JobHistoryResult:
        """
        Analyze job run history and identify patterns.

        Args:
            runs: List of job runs
            runtime_meta: Runtime metadata

        Returns:
            JobHistoryResult with analysis

        Example:
            >>> runs = [{"status": "SUCCESS"}, {"status": "FAILED"}]
            >>> meta = {"success_rate": 0.5, "avg_duration_seconds": 120}
            >>> result = JobAnalyzer.analyze_job_history(runs, meta)
            >>> result.total_runs
            2
        """
        return JobHistoryResult(
            total_runs=len(runs),
            success_rate=runtime_meta.get("success_rate", 0.0),
            avg_duration_seconds=runtime_meta.get("avg_duration_seconds", 0.0),
            has_failures=runtime_meta.get("failed_runs", 0) > 0,
        )

    @staticmethod
    def analyze_task_dependencies(
        task_definitions: list[dict[str, Any]],
    ) -> TaskDependencyResult:
        """
        Analyze task dependencies and identify critical path.

        Args:
            task_definitions: List of task definitions

        Returns:
            TaskDependencyResult with dependency graph

        Example:
            >>> tasks = [
            ...     {"task_key": "task1", "depends_on": []},
            ...     {"task_key": "task2", "depends_on": ["task1"]}
            ... ]
            >>> result = JobAnalyzer.analyze_task_dependencies(tasks)
            >>> result.dependencies
            {'task1': [], 'task2': ['task1']}
        """
        # Build dependency graph
        dependencies: dict[str, list[str]] = {}
        for task in task_definitions:
            task_key = task.get("task_key")
            if task_key is None:
                continue
            depends_on = task.get("depends_on", [])
            dependencies[task_key] = depends_on

        # Simple critical path analysis (tasks with no dependencies are critical)
        critical_tasks = [
            task_key for task_key, deps in dependencies.items() if not deps
        ]

        logger.debug(
            f"Analyzed dependencies for {len(task_definitions)} tasks. "
            f"Critical path: {len(critical_tasks)} tasks"
        )

        return TaskDependencyResult(
            dependencies=dependencies,
            critical_path=critical_tasks,
        )
