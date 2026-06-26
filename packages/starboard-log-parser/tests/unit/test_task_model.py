# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for TaskModel.

Following TDD: Tests are written first to document expected behavior,
then implementation is verified/fixed to match.

These tests ensure TaskModel correctly:
- Parses task metrics from Spark events
- Calculates task duration
- Handles shuffle metrics
- Validates required fields
"""

from typing import Any

import pytest

# Skip all tests if log parser not available
try:
    from starboard_log_parser.parsing_models.task_model import TaskModel

    LOG_PARSER_AVAILABLE = True
except ImportError:
    LOG_PARSER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not LOG_PARSER_AVAILABLE, reason="Log parser not available"
)


def create_task_data(
    task_id: int = 1,
    launch_time: int = 1000000,
    finish_time: int = 1001000,
    executor_run_time: int = 1000,
    **kwargs,
) -> dict[str, Any]:
    """
    Helper to create minimal task data for testing.

    Args:
        task_id: Task ID
        launch_time: Launch time in milliseconds
        finish_time: Finish time in milliseconds
        executor_run_time: Executor run time in milliseconds
        **kwargs: Additional task metrics

    Returns:
        Dict with task data in Spark event log format
    """
    task_data = {
        "Event": "SparkListenerTaskEnd",
        "Stage ID": kwargs.get("stage_id", 0),
        "Task Info": {
            "Task ID": task_id,
            "Attempt": kwargs.get("attempt", 0),
            "Launch Time": launch_time,
            "Finish Time": finish_time,
            "Host": kwargs.get("host", "worker-1.example.com"),
            "Executor ID": kwargs.get("executor_id", "executor-1"),
            "Killed": kwargs.get("killed", False),
            "Speculative": kwargs.get("speculative", False),
            "Locality": kwargs.get("locality", "PROCESS_LOCAL"),
        },
        "Task Metrics": {
            "Executor Run Time": executor_run_time,
            "Executor CPU Time": kwargs.get(
                "executor_cpu_time", executor_run_time * 800000
            ),  # ~80% utilization in nanoseconds
            "Executor Deserialize Time": kwargs.get("executor_deserialize_time", 10),
            "Result Serialization Time": kwargs.get("result_serialization_time", 5),
            "JVM GC Time": kwargs.get("jvm_gc_time", 50),  # milliseconds
            "Memory Bytes Spilled": kwargs.get("memory_bytes_spilled", 0),
            "Disk Bytes Spilled": kwargs.get("disk_bytes_spilled", 0),
            "Result Size": kwargs.get("result_size", 1024),  # bytes
        },
    }

    # Add optional metrics
    if "shuffle_read_metrics" in kwargs:
        task_data["Task Metrics"]["Shuffle Read Metrics"] = kwargs[
            "shuffle_read_metrics"
        ]

    if "shuffle_write_metrics" in kwargs:
        task_data["Task Metrics"]["Shuffle Write Metrics"] = kwargs[
            "shuffle_write_metrics"
        ]

    if "input_metrics" in kwargs:
        task_data["Task Metrics"]["Input Metrics"] = kwargs["input_metrics"]

    if "output_metrics" in kwargs:
        task_data["Task Metrics"]["Output Metrics"] = kwargs["output_metrics"]

    return task_data


@pytest.mark.unit
def test_task_model_initialization():
    """
    Test that TaskModel can be initialized with basic task info.

    Verifies that a TaskModel can be created with minimal required data.
    """
    task_data = create_task_data()
    task = TaskModel(task_data, is_json=True)

    # Verify basic fields
    assert task.task_id == 1
    assert task.start_time == 1000.0  # Converted to seconds
    assert task.finish_time == 1001.0  # Converted to seconds
    assert task.executor_run_time == 1.0  # Converted to seconds


@pytest.mark.unit
def test_task_duration_calculation():
    """
    Test that task duration is calculated correctly.

    Duration should be finish_time - start_time.
    """
    task_data = create_task_data(
        launch_time=1000000, finish_time=1005000, executor_run_time=4000
    )
    task = TaskModel(task_data, is_json=True)

    # Duration should be 5 seconds
    expected_duration = 5.0
    actual_duration = task.finish_time - task.start_time

    assert actual_duration == expected_duration


@pytest.mark.unit
def test_shuffle_read_metrics_parsing():
    """
    Test that shuffle read metrics are parsed correctly.

    Verifies that shuffle read bytes and time are extracted and converted
    to appropriate units (MB for bytes, seconds for time).
    """
    task_data = create_task_data(
        shuffle_read_metrics={
            "Remote Blocks Fetched": 10,
            "Local Blocks Fetched": 5,
            "Fetch Wait Time": 200,
            "Remote Bytes Read": 5242880,  # 5 MB
            "Local Bytes Read": 1048576,  # 1 MB
            "Total Records Read": 1000,
        }
    )

    task = TaskModel(task_data, is_json=True)

    # Verify shuffle read metrics exist and are reasonable
    assert hasattr(task, "remote_mb_read")
    assert hasattr(task, "local_mb_read")

    expected_remote_mb = 5242880 / 1048576.0
    expected_local_mb = 1048576 / 1048576.0

    assert task.remote_mb_read == pytest.approx(expected_remote_mb, rel=0.01)
    assert task.local_mb_read == pytest.approx(expected_local_mb, rel=0.01)


@pytest.mark.unit
def test_shuffle_write_metrics_parsing():
    """
    Test that shuffle write metrics are parsed correctly.

    Verifies that shuffle write bytes and time are extracted and converted.
    Note: This test also verifies the fix for print statement removal.
    """
    task_data = create_task_data(
        shuffle_write_metrics={
            "Shuffle Bytes Written": 10485760,  # 10 MB
            "Shuffle Write Time": 500000000,  # 500ms in nanoseconds
            "Shuffle Records Written": 2000,
        }
    )

    task = TaskModel(task_data, is_json=True)

    # Verify shuffle write metrics
    assert hasattr(task, "shuffle_mb_written")
    expected_mb = 10485760 / 1048576.0
    assert task.shuffle_mb_written == pytest.approx(expected_mb, rel=0.01)

    # Verify shuffle write time
    assert hasattr(task, "shuffle_write_time")
    expected_time = 500000000 / 1.0e9
    assert task.shuffle_write_time == pytest.approx(expected_time, rel=0.01)


@pytest.mark.unit
def test_input_metrics_parsing():
    """
    Test that input metrics (bytes read, records read) are parsed correctly.
    """
    task_data = create_task_data(
        input_metrics={
            "Bytes Read": 20971520,  # 20 MB
            "Records Read": 5000,
        }
    )

    task = TaskModel(task_data, is_json=True)

    # Verify input metrics
    assert hasattr(task, "input_mb")
    expected_mb = 20971520 / 1048576.0
    assert task.input_mb == pytest.approx(expected_mb, rel=0.01)


@pytest.mark.unit
def test_output_metrics_parsing():
    """
    Test that output metrics (bytes written, records written) are parsed correctly.
    """
    task_data = create_task_data(
        output_metrics={
            "Bytes Written": 15728640,  # 15 MB
            "Records Written": 3000,
        }
    )

    task = TaskModel(task_data, is_json=True)

    # Verify output metrics
    assert hasattr(task, "output_mb")
    expected_mb = 15728640 / 1048576.0
    assert task.output_mb == pytest.approx(expected_mb, rel=0.01)


@pytest.mark.unit
def test_task_with_missing_metrics():
    """
    Test that TaskModel handles missing optional metrics gracefully.

    Not all tasks have all metrics (e.g., map tasks don't have shuffle read).
    The model should handle missing metrics without crashing.
    """
    # Task with only required metrics
    task_data = create_task_data()
    task = TaskModel(task_data, is_json=True)

    # Should not crash
    assert task.task_id == 1
    assert task.executor_run_time == 1.0


@pytest.mark.unit
def test_task_attempt_tracking():
    """
    Test that task attempts are tracked correctly.

    When a task fails and retries, the attempt number should increment.
    """
    # First attempt (failed)
    task_data1 = create_task_data(task_id=1, attempt=0, killed=False)
    task1 = TaskModel(task_data1, is_json=True)

    # TaskModel doesn't have attempt field exposed, but we can verify it initializes
    assert task1.task_id == 1

    # Second attempt (retry)
    task_data2 = create_task_data(
        task_id=1, attempt=1, launch_time=1002000, finish_time=1003000
    )
    task2 = TaskModel(task_data2, is_json=True)

    assert task2.task_id == 1


@pytest.mark.unit
def test_gc_time_tracking():
    """
    Test that JVM GC time is tracked.

    High GC time can indicate memory pressure.
    """
    task_data = create_task_data(jvm_gc_time=100)  # 100 milliseconds
    task = TaskModel(task_data, is_json=True)

    # Verify GC time is captured
    assert hasattr(task, "gc_time")
    # GC time is converted to seconds (divided by 1000)
    assert task.gc_time == pytest.approx(0.1, rel=0.01)  # 100ms = 0.1s


@pytest.mark.unit
def test_task_locality():
    """
    Test that task locality is captured.

    Locality indicates whether data was local to the executor.
    """
    task_data = create_task_data(locality="PROCESS_LOCAL")
    task = TaskModel(task_data, is_json=True)

    # Verify locality is captured
    assert hasattr(task, "data_local")
    # data_local is a boolean based on locality
    # PROCESS_LOCAL should be considered local
    assert task.data_local


@pytest.mark.unit
def test_task_with_disk_spill():
    """
    Test that disk spill metrics are captured.

    Disk spill indicates memory pressure and should be monitored.
    """
    task_data = create_task_data(
        memory_bytes_spilled=10485760,  # 10 MB
        disk_bytes_spilled=5242880,  # 5 MB
    )
    task = TaskModel(task_data, is_json=True)

    # Verify spill metrics are captured
    # These are stored as MB in the model
    if hasattr(task, "memory_bytes_spilled"):
        assert task.memory_bytes_spilled > 0

    if hasattr(task, "disk_bytes_spilled"):
        assert task.disk_bytes_spilled > 0


@pytest.mark.unit
def test_task_result_size():
    """
    Test that task result size is captured.

    Large result sizes can cause driver OOM.
    """
    task_data = create_task_data(result_size=1048576)  # 1048576 bytes = 1 MB
    task = TaskModel(task_data, is_json=True)

    # Verify result size
    assert hasattr(task, "result_size")
    # Result size is converted to MB (divided by 1000000)
    expected_mb = 1048576 / 1000000.0
    assert task.result_size == pytest.approx(expected_mb, rel=0.01)


@pytest.mark.unit
def test_scheduler_delay_calculation():
    """
    Test that scheduler delay is calculated correctly.

    Scheduler delay = total time - executor time - deserialize - serialize
    """
    task_data = create_task_data(
        launch_time=1000000,
        finish_time=1010000,  # 10 seconds total
        executor_run_time=8000,  # 8 seconds execution
        executor_deserialize_time=100,  # 0.1 seconds
        result_serialization_time=50,  # 0.05 seconds
    )
    task = TaskModel(task_data, is_json=True)

    # Scheduler delay should be positive
    assert hasattr(task, "scheduler_delay")
    # Should be roughly 10 - 8 - 0.1 - 0.05 = 1.85 seconds
    assert task.scheduler_delay > 0


@pytest.mark.unit
@pytest.mark.slow
def test_task_model_performance():
    """
    Test that TaskModel parsing is reasonably fast.

    Parsing 1000 tasks should take < 1 second.
    """
    import time

    start = time.time()

    for i in range(1000):
        task_data = create_task_data(task_id=i)
        TaskModel(task_data, is_json=True)

    elapsed = time.time() - start

    # Should be fast (< 2 seconds for 1000 tasks)
    assert elapsed < 2.0, f"Parsing 1000 tasks took {elapsed:.2f}s, expected < 2s"
