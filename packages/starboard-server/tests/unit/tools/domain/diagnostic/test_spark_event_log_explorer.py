# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Unit tests for SparkEventLogExplorer.

Tests intent-aware exploration of Spark event logs using the
SparkApplication domain model from starboard-log-parser.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


def make_preparsed_spark_app(
    jobs: list[dict[str, Any]] | None = None,
    stages: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    executors: list[dict[str, Any]] | None = None,
    sql_executions: list[dict[str, Any]] | None = None,
    app_name: str = "TestApp",
    runtime_sec: float = 100.0,
) -> str:
    """Create a pre-parsed Spark application JSON for testing.

    Returns JSON string that can be parsed by create_spark_application_from_content.
    """
    # Build DataFrame-like structures (column-oriented)
    job_data: dict[str, list] = {}
    if jobs:
        for key in jobs[0]:
            job_data[key] = [j.get(key) for j in jobs]

    stage_data: dict[str, list] = {}
    if stages:
        for key in stages[0]:
            stage_data[key] = [s.get(key) for s in stages]

    task_data: dict[str, list] = {}
    if tasks:
        for key in tasks[0]:
            task_data[key] = [t.get(key) for t in tasks]

    executor_data: dict[str, list] = {}
    has_executors = executors is not None and len(executors) > 0
    if has_executors:
        for key in executors[0]:
            executor_data[key] = [e.get(key) for e in executors]

    sql_data: dict[str, list] = {}
    has_sql = sql_executions is not None and len(sql_executions) > 0
    if has_sql:
        for key in sql_executions[0]:
            sql_data[key] = [s.get(key) for s in sql_executions]

    data = {
        "metadata": {
            "application_info": {
                "id": "app-test-001",
                "name": app_name,
                "timestamp_start_ms": 1000000,
                "timestamp_end_ms": 1000000 + int(runtime_sec * 1000),
                "runtime_sec": runtime_sec,
                "spark_version": "3.5.0",
                "cloud_platform": "databricks",
                "cloud_provider": "aws",
            },
            "existsSQL": has_sql,
            "existsExecutors": has_executors,
        },
        "jobData": job_data,
        "stageData": stage_data,
        "taskData": task_data,
        "accumData": {},
    }

    if has_sql:
        data["sqlData"] = sql_data
    if has_executors:
        data["executors"] = executor_data

    return json.dumps(data)


class TestSparkEventLogExplorerOverview:
    """Tests for overview/general exploration."""

    def test_explore_overview(self) -> None:
        """Should extract application overview."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            app_name="MySparkApp",
            runtime_sec=300.0,
            jobs=[
                {"job_id": 0, "status": "SUCCESS"},
                {"job_id": 1, "status": "SUCCESS"},
            ],
            stages=[{"stage_id": i} for i in range(5)],
            tasks=[{"task_id": i} for i in range(100)],
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "show overview", "summary")

        assert "Spark Application Overview" in result.content
        assert "MySparkApp" in result.content
        assert "Jobs: 2" in result.content
        assert "Stages: 5" in result.content
        assert "Tasks: 100" in result.content
        assert result.evidence_count >= 1

    def test_handles_empty_content(self) -> None:
        """Should handle empty or invalid content gracefully."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore("", "show overview", "summary")

        assert "Parse Error" in result.content or "Overview" in result.content
        assert result.evidence_count >= 0


class TestSparkEventLogExplorerJobs:
    """Tests for job-focused exploration."""

    def test_extract_jobs_with_failures(self) -> None:
        """Should extract job information including failures."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            jobs=[
                {"job_id": 0, "status": "SUCCESS", "duration_sec": 10.0},
                {"job_id": 1, "status": "FAILED", "duration_sec": 5.0},
                {"job_id": 2, "status": "SUCCESS", "duration_sec": 15.0},
                {"job_id": 3, "status": "JobFailed", "duration_sec": 2.0},
            ]
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "failed jobs", "detailed")

        assert "Job Analysis" in result.content
        assert "Failed: 2" in result.content
        assert "FAILED" in result.content or "JobFailed" in result.content
        assert "failed_jobs" in result.sections_found

    def test_extract_jobs_all_successful(self) -> None:
        """Should handle all successful jobs."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            jobs=[
                {"job_id": 0, "status": "SUCCESS"},
                {"job_id": 1, "status": "JobSucceeded"},
            ]
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "show jobs", "summary")

        assert "Job Analysis" in result.content
        assert "Failed: 0" in result.content


class TestSparkEventLogExplorerStages:
    """Tests for stage-focused exploration."""

    def test_extract_slow_stages(self) -> None:
        """Should identify slow stages."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            stages=[
                {"stage_id": 0, "name": "scan", "duration_sec": 10.0, "num_tasks": 100},
                {
                    "stage_id": 1,
                    "name": "filter",
                    "duration_sec": 5.0,
                    "num_tasks": 100,
                },
                {
                    "stage_id": 2,
                    "name": "aggregate",
                    "duration_sec": 200.0,
                    "num_tasks": 100,
                },  # Slow!
                {"stage_id": 3, "name": "write", "duration_sec": 8.0, "num_tasks": 50},
            ]
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "slow stages", "detailed")

        assert "Stage Analysis" in result.content
        assert "aggregate" in result.content
        assert "Slow Stages" in result.content or "Duration" in result.content


class TestSparkEventLogExplorerTasks:
    """Tests for task-focused exploration."""

    def test_extract_task_failures(self) -> None:
        """Should extract task failure information."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            tasks=[
                {"task_id": 0, "stage_id": 0, "failed": False, "duration_ms": 1000},
                {"task_id": 1, "stage_id": 0, "failed": True, "duration_ms": 500},
                {"task_id": 2, "stage_id": 0, "failed": False, "duration_ms": 1200},
                {"task_id": 3, "stage_id": 1, "failed": True, "duration_ms": 300},
            ]
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "task failures", "detailed")

        assert "Task Analysis" in result.content
        assert "Failed Tasks:** 2" in result.content


class TestSparkEventLogExplorerExecutors:
    """Tests for executor-focused exploration."""

    def test_extract_executor_issues(self) -> None:
        """Should extract executor removal reasons."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            executors=[
                {
                    "executor_id": "0",
                    "host": "host1",
                    "cores": 4,
                    "removed_reason": None,
                },
                {
                    "executor_id": "1",
                    "host": "host2",
                    "cores": 4,
                    "removed_reason": "OOM killed",
                },
                {
                    "executor_id": "2",
                    "host": "host3",
                    "cores": 4,
                    "removed_reason": "lost",
                },
            ]
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "executor issues oom", "detailed")

        assert "Executor Analysis" in result.content
        assert "Removed Executors:** 2" in result.content
        assert "OOM" in result.content

    def test_handles_no_executor_data(self) -> None:
        """Should handle missing executor data."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app()

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "executor issues", "summary")

        assert "No executor data" in result.content


class TestSparkEventLogExplorerSkew:
    """Tests for data skew detection."""

    def test_detect_data_skew(self) -> None:
        """Should detect data skew from task duration variance."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        # Create tasks with significant skew in stage 0
        # 9 fast tasks + 1 very slow task
        tasks = [{"task_id": i, "stage_id": 0, "duration_ms": 1000} for i in range(9)]
        tasks.append({"task_id": 9, "stage_id": 0, "duration_ms": 50000})  # 50x slower

        content = make_preparsed_spark_app(tasks=tasks)

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "data skew", "detailed")

        assert "Data Skew Analysis" in result.content
        # Should detect the skewed stage
        assert "Stage 0" in result.content or "Skewed Stages" in result.content

    def test_no_skew_uniform_tasks(self) -> None:
        """Should report no skew for uniform task durations."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        # All tasks have similar duration
        tasks = [
            {"task_id": i, "stage_id": 0, "duration_ms": 1000 + i} for i in range(20)
        ]

        content = make_preparsed_spark_app(tasks=tasks)

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "check for skew", "summary")

        assert "No significant data skew" in result.content


class TestSparkEventLogExplorerPerformance:
    """Tests for performance-focused exploration."""

    def test_extract_performance_summary(self) -> None:
        """Should extract performance breakdown by job/stage."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            runtime_sec=600.0,
            jobs=[
                {"job_id": 0, "duration_sec": 200.0},
                {"job_id": 1, "duration_sec": 150.0},
                {"job_id": 2, "duration_sec": 250.0},
            ],
            stages=[
                {"stage_id": 0, "name": "scan", "duration_sec": 100.0},
                {"stage_id": 1, "name": "filter", "duration_sec": 50.0},
                {"stage_id": 2, "name": "aggregate", "duration_sec": 300.0},
                {"stage_id": 3, "name": "write", "duration_sec": 150.0},
            ],
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "performance analysis", "detailed")

        assert "Performance Analysis" in result.content
        assert "Total Runtime" in result.content
        assert "aggregate" in result.content  # Should show stages by time


class TestSparkEventLogExplorerSQL:
    """Tests for SQL-focused exploration."""

    def test_extract_sql_executions(self) -> None:
        """Should extract SQL execution information."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            sql_executions=[
                {
                    "execution_id": 0,
                    "description": "SELECT * FROM customers WHERE id = 1",
                },
                {"execution_id": 1, "description": "INSERT INTO orders SELECT ..."},
            ]
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "sql executions", "detailed")

        assert "SQL Execution Analysis" in result.content
        assert "SQL Executions:** 2" in result.content


class TestSparkEventLogExplorerDetailLevels:
    """Tests for different detail levels."""

    def test_summary_level_is_concise(self) -> None:
        """Summary level should produce concise output."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            jobs=[{"job_id": i, "status": "SUCCESS"} for i in range(100)]
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, "show jobs", "summary")

        # Should be within summary limit
        assert len(result.content) <= 2500  # 2000 + some buffer

    def test_exhaustive_level_provides_more_detail(self) -> None:
        """Exhaustive level should provide more detail."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            jobs=[
                {"job_id": i, "status": "FAILED" if i % 3 == 0 else "SUCCESS"}
                for i in range(20)
            ]
        )

        explorer = SparkEventLogExplorer()
        result_summary = explorer.explore(content, "failed jobs", "summary")
        result_exhaustive = explorer.explore(content, "failed jobs", "exhaustive")

        # Exhaustive should have more content
        assert len(result_exhaustive.content) >= len(result_summary.content)


class TestSparkEventLogExplorerFocusDetection:
    """Tests for focus keyword detection."""

    @pytest.mark.parametrize(
        "focus,expected_section",
        [
            ("show me jobs", "Job"),
            ("failed jobs", "Job"),
            ("slow stages", "Stage"),
            ("stage analysis", "Stage"),
            ("task failures", "Task"),
            ("executor issues", "Executor"),
            ("oom problems", "Executor"),
            ("data skew", "Skew"),
            ("performance bottleneck", "Performance"),
            ("sql queries", "SQL"),
        ],
    )
    def test_focus_routing(self, focus: str, expected_section: str) -> None:
        """Should route to correct extraction handler based on focus."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        content = make_preparsed_spark_app(
            jobs=[{"job_id": 0, "status": "SUCCESS"}],
            stages=[{"stage_id": 0, "name": "test"}],
            tasks=[{"task_id": 0}],
            executors=[{"executor_id": "0", "host": "host1", "cores": 4}],
            sql_executions=[{"execution_id": 0, "description": "SELECT 1"}],
        )

        explorer = SparkEventLogExplorer()
        result = explorer.explore(content, focus, "summary")

        assert expected_section in result.content, (
            f"Expected '{expected_section}' in content for focus '{focus}'"
        )


class TestSparkEventLogExplorerDurationFormatting:
    """Tests for duration formatting helper."""

    def test_format_duration_milliseconds(self) -> None:
        """Should format sub-second durations as milliseconds."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        assert SparkEventLogExplorer._format_duration(0.5) == "500ms"
        assert SparkEventLogExplorer._format_duration(0.05) == "50ms"

    def test_format_duration_seconds(self) -> None:
        """Should format durations under a minute as seconds."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        assert SparkEventLogExplorer._format_duration(5.0) == "5.0s"
        assert SparkEventLogExplorer._format_duration(30.5) == "30.5s"

    def test_format_duration_minutes(self) -> None:
        """Should format durations under an hour as minutes."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        assert SparkEventLogExplorer._format_duration(125) == "2m 5s"

    def test_format_duration_hours(self) -> None:
        """Should format long durations as hours."""
        from starboard_server.tools.domain.diagnostic.spark_event_log_explorer import (
            SparkEventLogExplorer,
        )

        assert SparkEventLogExplorer._format_duration(3725) == "1h 2m"
