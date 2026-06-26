# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for ApplicationModel (event_log_parser.py).

Following TDD: Tests are written first to document expected behavior,
then implementation is verified/fixed to match.

ApplicationModel is a God class with many responsibilities:
- Event log parsing (various event types)
- Job, Stage, Task, Executor management
- Platform detection (Databricks, EMR)
- SQL query tracking
- Time tracking
- DAG processing

These tests focus on critical paths and key behaviors, targeting ~60% coverage
given the complexity.
"""

from collections.abc import Iterator
from typing import Any

import pytest

# Skip all tests if log parser not available
try:
    from starboard_log_parser.parsing_models.event_log_parser import (
        MAX_RECURSION_DEPTH,
        ApplicationModel,
    )
    from starboard_log_parser.parsing_models.task_model import TaskModel

    LOG_PARSER_AVAILABLE = True
except ImportError:
    LOG_PARSER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not LOG_PARSER_AVAILABLE, reason="Log parser not available"
)


def create_log_lines(events: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """
    Helper to create an iterator of event log lines.

    Args:
        events: List of event dictionaries

    Returns:
        Iterator of events
    """
    return iter(events)


def create_minimal_app_log() -> list[dict[str, Any]]:
    """
    Create a minimal valid Spark application log.

    Includes executor to avoid division by zero in finalization.

    Returns:
        List of events for a basic application
    """
    return [
        {"Event": "SparkListenerLogStart", "Spark Version": "3.2.1"},
        {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "testuser",
        },
        # Add executor to avoid division by zero
        {
            "Event": "SparkListenerExecutorAdded",
            "Executor ID": "1",
            "Timestamp": 1000500,
            "Executor Info": {
                "Host": "worker-1.example.com",
                "Total Cores": 4,
            },
        },
        {
            "Event": "SparkListenerApplicationEnd",
            "Timestamp": 2000000,
        },
    ]


def create_app_with_job() -> list[dict[str, Any]]:
    """
    Create log with a job.

    Returns:
        List of events including a job
    """
    events = create_minimal_app_log()

    # Insert job events before ApplicationEnd
    job_events = [
        {
            "Event": "SparkListenerJobStart",
            "Job ID": 0,
            "Submission Time": 1001000,
            "Stage IDs": [0],
        },
        {
            "Event": "SparkListenerJobEnd",
            "Job ID": 0,
            "Completion Time": 1010000,
            "Job Result": {"Result": "JobSucceeded"},
        },
    ]

    # Insert before ApplicationEnd
    events = events[:-1] + job_events + [events[-1]]
    return events


def create_app_with_task() -> list[dict[str, Any]]:
    """
    Create log with a task.

    Returns:
        List of events including a stage and task (tasks require stages)
    """
    events = create_app_with_job()

    # Stage submission is required before tasks - otherwise ApplicationModel raises
    stage_event = {
        "Event": "SparkListenerStageSubmitted",
        "Stage Info": {
            "Stage ID": 0,
            "Stage Attempt ID": 0,
            "Stage Name": "Test Stage",
            "Number of Tasks": 1,
            "Submission Time": 1001500,
            "Parent IDs": [],
        },
    }

    task_event = {
        "Event": "SparkListenerTaskEnd",
        "Stage ID": 0,
        "Task Info": {
            "Task ID": 1,
            "Attempt": 0,
            "Launch Time": 1002000,
            "Finish Time": 1003000,
            "Host": "worker-1",
            "Executor ID": "1",
            "Killed": False,
            "Speculative": False,
            "Locality": "PROCESS_LOCAL",
        },
        "Task Metrics": {
            "Executor Run Time": 1000,
            "Executor CPU Time": 800000000,
            "Executor Deserialize Time": 10,
            "Result Serialization Time": 5,
            "JVM GC Time": 50,
            "Memory Bytes Spilled": 0,
            "Disk Bytes Spilled": 0,
            "Result Size": 1024,
        },
    }

    # Insert stage then task before ApplicationEnd
    events = events[:-1] + [stage_event, task_event] + [events[-1]]
    return events


def create_app_with_stage() -> list[dict[str, Any]]:
    """
    Create log with a stage.

    Returns:
        List of events including a stage
    """
    events = create_app_with_task()

    stage_events = [
        {
            "Event": "SparkListenerStageSubmitted",
            "Stage Info": {
                "Stage ID": 0,
                "Stage Attempt ID": 0,
                "Stage Name": "Test Stage",
                "Number of Tasks": 1,
                "Submission Time": 1001500,
                "Parent IDs": [],  # Required for DAG processing
            },
        },
        {
            "Event": "SparkListenerStageCompleted",
            "Stage Info": {
                "Stage ID": 0,
                "Stage Attempt ID": 0,
                "Completion Time": 1009000,
            },
        },
    ]

    # Insert before ApplicationEnd
    events = events[:-1] + stage_events + [events[-1]]
    return events


@pytest.mark.unit
def test_application_model_initialization_minimal():
    """
    Test that ApplicationModel can be initialized with minimal log.

    Verifies basic initialization with minimal valid log.
    """
    log_lines = create_log_lines(create_minimal_app_log())
    app = ApplicationModel(log_lines)

    # Verify basic attributes exist
    assert hasattr(app, "jobs")
    assert hasattr(app, "stages")
    assert hasattr(app, "tasks")
    assert hasattr(app, "executors")
    assert hasattr(app, "spark_version")

    # Verify spark version was parsed
    assert app.spark_version == "3.2.1"


@pytest.mark.unit
def test_application_model_processes_job_events():
    """
    Test that ApplicationModel processes job events correctly.

    Verifies that JobStart and JobEnd events create and populate jobs.
    """
    log_lines = create_log_lines(create_app_with_job())
    app = ApplicationModel(log_lines)

    # Verify job was created
    assert 0 in app.jobs

    # Verify job attributes
    job = app.jobs[0]
    assert job.submission_time == 1001.0  # Converted to seconds
    assert job.completion_time == 1010.0
    assert job.result == "JobSucceeded"


@pytest.mark.unit
def test_application_model_processes_task_events():
    """
    Test that ApplicationModel processes task events correctly.

    Verifies that TaskEnd events create TaskModel instances.
    """
    log_lines = create_log_lines(create_app_with_task())
    app = ApplicationModel(log_lines)

    # Verify task was created
    assert len(app.tasks) >= 1

    # Verify task is TaskModel
    assert isinstance(app.tasks[0], TaskModel)

    # Verify task attributes
    task = app.tasks[0]
    assert task.task_id == 1
    assert task.start_time == 1002.0
    assert task.finish_time == 1003.0


@pytest.mark.unit
def test_application_model_processes_stage_events():
    """
    Test that ApplicationModel processes stage events correctly.

    Verifies that StageSubmitted and StageCompleted events populate stages.
    """
    log_lines = create_log_lines(create_app_with_stage())
    app = ApplicationModel(log_lines)

    # Verify stage was created
    assert 0 in app.stages

    # Verify stage attributes
    stage = app.stages[0]
    assert stage.id == 0
    assert stage.stage_name == "Test Stage"
    assert stage.num_tasks == 1
    assert stage.submission_time == 1001.5  # Converted to seconds
    assert stage.completion_time == 1009.0


@pytest.mark.unit
def test_application_model_tracks_start_time():
    """
    Test that ApplicationModel tracks application start time.

    Verifies that start_time is set from SparkListenerApplicationStart.
    """
    events = [
        {"Event": "SparkListenerLogStart", "Spark Version": "3.2.1"},
        {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "Timestamp": 1234567890,
        },
        {"Event": "SparkListenerApplicationEnd", "Timestamp": 2000000},
    ]

    log_lines = create_log_lines(events)
    app = ApplicationModel(log_lines)

    # Verify start time
    assert app.start_time == 1234567.890  # Converted to seconds


@pytest.mark.unit
def test_application_model_tracks_finish_time():
    """
    Test that ApplicationModel tracks application finish time.

    Verifies that finish_time is set from SparkListenerApplicationEnd
    or stage completion times.
    """
    log_lines = create_log_lines(create_app_with_stage())
    app = ApplicationModel(log_lines)

    # Verify finish time is set
    assert app.finish_time is not None
    assert app.finish_time > 0


@pytest.mark.unit
def test_application_model_maybe_set_new_finish_time():
    """
    Test that maybe_set_new_finish_time updates finish_time correctly.

    Verifies that finish_time is updated to the maximum time seen.
    """
    log_lines = create_log_lines(create_minimal_app_log())
    app = ApplicationModel(log_lines)

    # ApplicationEnd timestamp (2000000ms = 2000.0s) already set finish_time
    initial_finish = app.finish_time
    assert initial_finish == 2000.0  # From ApplicationEnd

    # Update to larger time should work
    app.maybe_set_new_finish_time(3000.0)
    assert app.finish_time == 3000.0

    # Should not update to smaller time
    app.maybe_set_new_finish_time(2500.0)
    assert app.finish_time == 3000.0  # Unchanged


@pytest.mark.unit
def test_application_model_executor_tracking():
    """
    Test that ApplicationModel tracks executor lifecycle.

    Verifies that ExecutorAdded and ExecutorRemoved events are processed.
    """
    # Use base events without the pre-existing executor from create_minimal_app_log
    events = [
        {"Event": "SparkListenerLogStart", "Spark Version": "3.2.1"},
        {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "testuser",
        },
        {
            "Event": "SparkListenerExecutorAdded",
            "Executor ID": "1",
            "Timestamp": 1001000,
            "Executor Info": {
                "Host": "worker-1.example.com",
                "Total Cores": 4,
            },
        },
        {
            "Event": "SparkListenerExecutorAdded",
            "Executor ID": "2",
            "Timestamp": 1002000,
            "Executor Info": {
                "Host": "worker-2.example.com",
                "Total Cores": 4,
            },
        },
        {
            "Event": "SparkListenerApplicationEnd",
            "Timestamp": 2000000,
        },
    ]

    log_lines = create_log_lines(events)
    app = ApplicationModel(log_lines)

    # Verify executors were tracked
    assert "1" in app.executors
    assert "2" in app.executors
    assert app.num_executors == 2
    assert app.max_executors == 2
    assert app.cores_per_executor == 4


@pytest.mark.unit
def test_application_model_executor_removal():
    """
    Test that ApplicationModel tracks executor removal.

    Verifies that ExecutorRemoved event decrements count and sets flag.
    """
    # Use base events without the pre-existing executor from create_minimal_app_log
    events = [
        {"Event": "SparkListenerLogStart", "Spark Version": "3.2.1"},
        {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "testuser",
        },
        {
            "Event": "SparkListenerExecutorAdded",
            "Executor ID": "1",
            "Timestamp": 1001000,
            "Executor Info": {
                "Host": "worker-1.example.com",
                "Total Cores": 4,
            },
        },
        {
            "Event": "SparkListenerExecutorRemoved",
            "Executor ID": "1",
            "Timestamp": 1500000,
            "Removed Reason": "Lost worker",
        },
        {
            "Event": "SparkListenerApplicationEnd",
            "Timestamp": 2000000,
        },
    ]

    log_lines = create_log_lines(events)
    app = ApplicationModel(log_lines)

    # Verify executor removal
    assert app.num_executors == 0  # Added 1, removed 1
    assert app.executorRemovedEarly
    assert app.executors["1"].removed_reason == "Lost worker"


@pytest.mark.unit
def test_application_model_platform_detection_databricks():
    """
    Test that ApplicationModel detects Databricks platform.

    Verifies that Databricks-specific properties are recognized.
    """
    events = [
        {"Event": "SparkListenerLogStart", "Spark Version": "3.2.1"},
        {
            "Event": "SparkListenerEnvironmentUpdate",
            "Spark Properties": {
                "spark.databricks.clusterUsageTags.sparkVersion": "11.3.x-scala2.12",
                "spark.databricks.clusterUsageTags.clusterId": "0123-456789-abc123",
                "spark.databricks.clusterUsageTags.cloudProvider": "AWS",
            },
            "System Properties": {},
        },
        {"Event": "SparkListenerApplicationEnd", "Timestamp": 2000000},
    ]

    log_lines = create_log_lines(events)
    app = ApplicationModel(log_lines)

    # Verify Databricks detection
    assert app.cloud_platform == "databricks"
    assert app.cloud_provider == "aws"
    assert app.cluster_id == "0123-456789-abc123"
    assert app.spark_version == "11.3.x-scala2.12"


@pytest.mark.unit
def test_application_model_platform_detection_emr():
    """
    Test that ApplicationModel detects EMR platform.

    Verifies that EMR-specific properties are recognized.
    """
    events = [
        {"Event": "SparkListenerLogStart", "Spark Version": "3.2.1"},
        {
            "Event": "SparkListenerEnvironmentUpdate",
            "Spark Properties": {},
            "System Properties": {
                "EMR_CLUSTER_ID": "j-ABCDEF123456",
                "EMR_RELEASE_LABEL": "emr-6.5.0",
            },
        },
        {"Event": "SparkListenerApplicationEnd", "Timestamp": 2000000},
    ]

    log_lines = create_log_lines(events)
    app = ApplicationModel(log_lines)

    # Verify EMR detection
    assert app.cloud_platform == "emr"
    assert app.cloud_provider == "aws"
    assert app.cluster_id == "j-ABCDEF123456"
    assert app.emr_version_tag == "emr-6.5.0"


@pytest.mark.unit
def test_application_model_parse_accum_metrics_with_depth_limit():
    """
    Test that parse_all_accum_metrics respects recursion depth limit.

    Verifies the recursion limit fix from Phase 1.
    """
    log_lines = create_log_lines(create_minimal_app_log())
    app = ApplicationModel(log_lines)

    # Create nested data within limit
    nested_data = {
        "level1": {
            "level2": {
                "metrics": [
                    {"accumulatorId": 1, "name": "test", "metricType": "counter"}
                ]
            }
        }
    }

    # Should not raise
    app.parse_all_accum_metrics(nested_data)

    # Verify metric was parsed
    assert 1 in app.accum_metrics
    assert app.accum_metrics[1]["name"] == "test"


@pytest.mark.unit
def test_application_model_parse_accum_metrics_exceeds_depth():
    """
    Test that parse_all_accum_metrics raises error on excessive depth.

    Verifies the recursion limit protection.
    """
    log_lines = create_log_lines(create_minimal_app_log())
    app = ApplicationModel(log_lines)

    # Create deeply nested data (exceed MAX_RECURSION_DEPTH)
    def create_deep_nest(depth: int) -> dict[str, Any]:
        if depth == 0:
            return {"metrics": []}
        return {"nested": create_deep_nest(depth - 1)}

    deep_data = create_deep_nest(MAX_RECURSION_DEPTH + 10)

    # Should raise ValueError
    with pytest.raises(ValueError) as exc_info:
        app.parse_all_accum_metrics(deep_data)

    assert "recursion depth" in str(exc_info.value).lower()


@pytest.mark.unit
def test_application_model_skips_invalid_events():
    """
    Test that ApplicationModel skips events without 'Event' field.

    Verifies robustness to malformed events.
    """
    events = [
        {"Event": "SparkListenerLogStart", "Spark Version": "3.2.1"},
        {"not_an_event": "invalid"},  # Missing 'Event' field
        {"Event": "SparkListenerApplicationEnd", "Timestamp": 2000000},
    ]

    log_lines = create_log_lines(events)
    app = ApplicationModel(log_lines)

    # Should not crash, just skip invalid event
    assert app.spark_version == "3.2.1"


@pytest.mark.unit
def test_application_model_jobs_for_stage_mapping():
    """
    Test that ApplicationModel maps stages to jobs correctly.

    Verifies jobs_for_stage tracking.
    """
    events = [
        {"Event": "SparkListenerLogStart", "Spark Version": "3.2.1"},
        {
            "Event": "SparkListenerJobStart",
            "Job ID": 0,
            "Submission Time": 1001000,
            "Stage IDs": [0, 1, 2],
        },
        {"Event": "SparkListenerApplicationEnd", "Timestamp": 2000000},
    ]

    log_lines = create_log_lines(events)
    app = ApplicationModel(log_lines)

    # Verify stage to job mapping
    assert 0 in app.jobs_for_stage
    assert 1 in app.jobs_for_stage
    assert 2 in app.jobs_for_stage
    assert 0 in app.jobs_for_stage[0]
    assert 0 in app.jobs_for_stage[1]
    assert 0 in app.jobs_for_stage[2]


@pytest.mark.unit
@pytest.mark.slow
def test_application_model_performance():
    """
    Test that ApplicationModel can process many events efficiently.

    Processing 1000 task events should be reasonably fast.
    """
    import time

    events = [
        {"Event": "SparkListenerLogStart", "Spark Version": "3.2.1"},
        # Job start is required before stages
        {
            "Event": "SparkListenerJobStart",
            "Job ID": 0,
            "Submission Time": 998000,
            "Stage IDs": [0],
        },
        # Stage submission is required before tasks
        {
            "Event": "SparkListenerStageSubmitted",
            "Stage Info": {
                "Stage ID": 0,
                "Stage Attempt ID": 0,
                "Stage Name": "Performance Test Stage",
                "Number of Tasks": 1000,
                "Submission Time": 999000,
                "Parent IDs": [],
            },
        },
    ]

    # Add 1000 task events
    for i in range(1000):
        events.append(
            {
                "Event": "SparkListenerTaskEnd",
                "Stage ID": 0,
                "Task Info": {
                    "Task ID": i,
                    "Attempt": 0,
                    "Launch Time": 1000000 + i * 100,
                    "Finish Time": 1001000 + i * 100,
                    "Host": "worker-1",
                    "Executor ID": "1",
                    "Killed": False,
                    "Speculative": False,
                    "Locality": "PROCESS_LOCAL",
                },
                "Task Metrics": {
                    "Executor Run Time": 1000,
                    "Executor CPU Time": 800000000,
                    "Executor Deserialize Time": 10,
                    "Result Serialization Time": 5,
                    "JVM GC Time": 50,
                    "Memory Bytes Spilled": 0,
                    "Disk Bytes Spilled": 0,
                    "Result Size": 1024,
                },
            }
        )

    events.append({"Event": "SparkListenerApplicationEnd", "Timestamp": 2000000})

    start = time.time()
    log_lines = create_log_lines(events)
    app = ApplicationModel(log_lines)
    elapsed = time.time() - start

    # Verify all tasks processed
    assert len(app.tasks) == 1000

    # Should be fast (< 5 seconds for 1000 events)
    assert elapsed < 5.0, f"Processing took {elapsed:.2f}s, expected < 5s"
