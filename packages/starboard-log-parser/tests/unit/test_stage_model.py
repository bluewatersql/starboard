# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for StageModel.

Following TDD: Tests are written first to document expected behavior,
then implementation is verified/fixed to match.

These tests ensure StageModel correctly:
- Aggregates task statistics
- Tracks stage lifecycle (start, tasks, finalize, completion)
- Calculates averages, totals, maximums
- Handles empty stages gracefully
"""

from typing import Any

import pytest

# Skip all tests if log parser not available
try:
    from starboard_log_parser.parsing_models.stage_model import StageModel
    from starboard_log_parser.parsing_models.task_model import TaskModel

    LOG_PARSER_AVAILABLE = True
except ImportError:
    LOG_PARSER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not LOG_PARSER_AVAILABLE, reason="Log parser not available"
)


def create_task_data(
    task_id: int = 1,
    stage_id: int = 0,
    launch_time: int = 1000000,
    finish_time: int = 1001000,
    executor_run_time: int = 1000,
    **kwargs,
) -> dict[str, Any]:
    """
    Helper to create minimal task data for testing.

    Reuses the pattern from test_task_model.py for consistency.

    Args:
        task_id: Task ID
        stage_id: Stage ID this task belongs to
        launch_time: Launch time in milliseconds
        finish_time: Finish time in milliseconds
        executor_run_time: Executor run time in milliseconds
        **kwargs: Additional task metrics

    Returns:
        Dict with task data in Spark event log format
    """
    task_data = {
        "Event": "SparkListenerTaskEnd",
        "Stage ID": stage_id,
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
            ),
            "Executor Deserialize Time": kwargs.get("executor_deserialize_time", 10),
            "Result Serialization Time": kwargs.get("result_serialization_time", 5),
            "JVM GC Time": kwargs.get("jvm_gc_time", 50),
            "Memory Bytes Spilled": kwargs.get("memory_bytes_spilled", 0),
            "Disk Bytes Spilled": kwargs.get("disk_bytes_spilled", 0),
            "Result Size": kwargs.get("result_size", 1024),
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
def test_stage_model_initialization():
    """
    Test that StageModel can be initialized.

    Verifies that a StageModel starts with proper default values.
    """
    stage = StageModel()

    # Verify default values
    assert stage.id is None
    assert stage.stage_name is None
    assert stage.attempt_id is None
    assert stage.start_time == -1
    assert stage.tasks == []
    assert not stage.tasks_finalized
    assert stage.num_tasks == 0


@pytest.mark.unit
def test_stage_add_single_task():
    """
    Test that a single task can be added to a stage.

    Verifies that task is added to the list and start_time is set.
    """
    stage = StageModel()
    task_data = create_task_data(task_id=1, launch_time=1000000, finish_time=1001000)
    task = TaskModel(task_data, is_json=True)

    stage.add_task(task)

    # Verify task was added
    assert len(stage.tasks) == 1
    assert stage.tasks[0] == task
    assert stage.start_time == 1000.0  # Converted to seconds


@pytest.mark.unit
def test_stage_add_multiple_tasks():
    """
    Test that multiple tasks can be added to a stage.

    Verifies that:
    - All tasks are added
    - start_time is the minimum of all task start times
    """
    stage = StageModel()

    # Add 3 tasks with different start times
    for i in range(3):
        task_data = create_task_data(
            task_id=i,
            launch_time=1000000 + i * 1000,  # Stagger start times
            finish_time=1001000 + i * 1000,
        )
        task = TaskModel(task_data, is_json=True)
        stage.add_task(task)

    # Verify all tasks added
    assert len(stage.tasks) == 3
    # Verify start_time is minimum
    assert stage.start_time == 1000.0  # First task's start time


@pytest.mark.unit
def test_stage_add_event():
    """
    Test that add_event creates and adds a task.

    Verifies that add_event is a convenience method that creates
    a TaskModel and adds it.
    """
    stage = StageModel()
    task_data = create_task_data(task_id=1)

    stage.add_event(task_data, is_json=True)

    # Verify task was created and added
    assert len(stage.tasks) == 1
    assert isinstance(stage.tasks[0], TaskModel)


@pytest.mark.unit
def test_stage_finalize_tasks():
    """
    Test that finalize_tasks sorts tasks by finish time.

    Verifies that:
    - tasks_finalized flag is set
    - tasks are sorted by finish_time
    """
    stage = StageModel()

    # Add tasks in random order
    finish_times = [1005000, 1001000, 1003000]  # Out of order
    for i, finish_time in enumerate(finish_times):
        task_data = create_task_data(
            task_id=i, launch_time=1000000, finish_time=finish_time
        )
        task = TaskModel(task_data, is_json=True)
        stage.add_task(task)

    # Finalize
    stage.finalize_tasks()

    # Verify finalized
    assert stage.tasks_finalized

    # Verify tasks are sorted by finish_time
    finish_times_sorted = [t.finish_time for t in stage.tasks]
    assert finish_times_sorted == sorted(finish_times_sorted)
    assert finish_times_sorted == [1001.0, 1003.0, 1005.0]


@pytest.mark.unit
def test_stage_cannot_add_task_after_finalize():
    """
    Test that adding a task after finalize raises RuntimeError.

    Verifies that the stage is immutable after finalization.
    """
    stage = StageModel()
    task_data = create_task_data(task_id=1)
    task = TaskModel(task_data, is_json=True)

    stage.add_task(task)
    stage.finalize_tasks()

    # Attempt to add another task
    task_data2 = create_task_data(task_id=2)
    task2 = TaskModel(task_data2, is_json=True)

    with pytest.raises(RuntimeError) as exc_info:
        stage.add_task(task2)

    assert "finalized" in str(exc_info.value)


@pytest.mark.unit
def test_stage_average_task_runtime():
    """
    Test that average_task_runtime calculates median compute time.

    Uses numpy.percentile(50) to get median.
    """
    stage = StageModel()

    # Add 3 tasks with different runtimes
    runtimes_ms = [1000, 2000, 3000]  # 1s, 2s, 3s
    for i, runtime in enumerate(runtimes_ms):
        task_data = create_task_data(
            task_id=i,
            launch_time=1000000,
            finish_time=1000000 + runtime,
            executor_run_time=runtime,
        )
        task = TaskModel(task_data, is_json=True)
        stage.add_task(task)

    avg_runtime = stage.average_task_runtime()

    # Median should be 2.0 seconds
    assert avg_runtime == pytest.approx(2.0, rel=0.01)


@pytest.mark.unit
def test_stage_average_task_runtime_empty():
    """
    Test that average_task_runtime returns 0 for empty stage.

    Verifies graceful handling of edge case.
    """
    stage = StageModel()
    avg_runtime = stage.average_task_runtime()
    assert avg_runtime == 0


@pytest.mark.unit
def test_stage_total_gc_time():
    """
    Test that total_gc_time sums GC time across all tasks.
    """
    stage = StageModel()

    # Add 3 tasks with known GC times
    gc_times = [100, 200, 300]  # milliseconds
    for i, gc_time in enumerate(gc_times):
        task_data = create_task_data(task_id=i, jvm_gc_time=gc_time)
        task = TaskModel(task_data, is_json=True)
        stage.add_task(task)

    total_gc = stage.total_gc_time()

    # Total: (100 + 200 + 300) / 1000 = 0.6 seconds
    expected = sum([gc / 1000.0 for gc in gc_times])
    assert total_gc == pytest.approx(expected, rel=0.01)


@pytest.mark.unit
def test_stage_has_shuffle_read():
    """
    Test that has_shuffle_read detects shuffle reads.

    Returns True if any task has shuffle read data.
    """
    stage = StageModel()

    # Add task with shuffle read
    task_data = create_task_data(
        task_id=1,
        shuffle_read_metrics={
            "Remote Blocks Fetched": 10,
            "Local Blocks Fetched": 5,
            "Fetch Wait Time": 200,
            "Remote Bytes Read": 5242880,  # 5 MB
            "Local Bytes Read": 1048576,  # 1 MB
        },
    )
    task = TaskModel(task_data, is_json=True)
    stage.add_task(task)

    assert stage.has_shuffle_read()


@pytest.mark.unit
def test_stage_has_shuffle_read_false():
    """
    Test that has_shuffle_read returns False when no shuffle reads.
    """
    stage = StageModel()

    # Add task without shuffle read
    task_data = create_task_data(task_id=1)
    task = TaskModel(task_data, is_json=True)
    stage.add_task(task)

    # has_fetch will be False, so has_shuffle_read should be False
    assert not stage.has_shuffle_read()


@pytest.mark.unit
def test_stage_finish_time():
    """
    Test that finish_time returns maximum task finish time.
    """
    stage = StageModel()

    # Add tasks with different finish times
    finish_times = [1001000, 1003000, 1005000]
    for i, finish_time in enumerate(finish_times):
        task_data = create_task_data(
            task_id=i, launch_time=1000000, finish_time=finish_time
        )
        task = TaskModel(task_data, is_json=True)
        stage.add_task(task)

    assert stage.finish_time() == 1005.0  # Maximum, in seconds


@pytest.mark.unit
def test_stage_finish_time_empty():
    """
    Test that finish_time returns 0 for empty stage.
    """
    stage = StageModel()
    assert stage.finish_time() == 0


@pytest.mark.unit
def test_stage_input_output_mb():
    """
    Test that input_mb and output_mb aggregate data across tasks.
    """
    stage = StageModel()

    # Add task with input and shuffle write
    task_data = create_task_data(
        task_id=1,
        input_metrics={"Bytes Read": 10485760},  # 10 MB
        shuffle_write_metrics={
            "Shuffle Bytes Written": 5242880,  # 5 MB
            "Shuffle Write Time": 500000000,
        },
    )
    task = TaskModel(task_data, is_json=True)
    stage.add_task(task)

    # Input: 10 MB
    assert stage.input_mb() == pytest.approx(10.0, rel=0.01)

    # Output: 5 MB (shuffle write)
    assert stage.output_mb() == pytest.approx(5.0, rel=0.01)


@pytest.mark.unit
def test_stage_total_runtime():
    """
    Test that total_runtime sums all task durations.
    """
    stage = StageModel()

    # Add 3 tasks with 1s duration each
    for i in range(3):
        task_data = create_task_data(
            task_id=i,
            launch_time=1000000 + i * 2000,
            finish_time=1001000 + i * 2000,  # 1s duration
        )
        task = TaskModel(task_data, is_json=True)
        stage.add_task(task)

    total = stage.total_runtime()

    # 3 tasks * 1s = 3s
    assert total == pytest.approx(3.0, rel=0.01)


@pytest.mark.unit
def test_stage_max_task_runtime():
    """
    Test that max_task_runtime returns 100th percentile (maximum).
    """
    stage = StageModel()

    # Add tasks with different compute times
    runtimes_ms = [1000, 2000, 5000]  # 1s, 2s, 5s
    for i, runtime in enumerate(runtimes_ms):
        task_data = create_task_data(
            task_id=i,
            launch_time=1000000,
            finish_time=1000000 + runtime,
            executor_run_time=runtime,
        )
        task = TaskModel(task_data, is_json=True)
        stage.add_task(task)

    max_runtime = stage.max_task_runtime()

    # Maximum should be 5.0 seconds
    assert max_runtime == pytest.approx(5.0, rel=0.01)


@pytest.mark.unit
def test_stage_total_memory_disk_spilled():
    """
    Test that spill metrics are aggregated across tasks.
    """
    stage = StageModel()

    # Add tasks with spill
    for i in range(3):
        task_data = create_task_data(
            task_id=i,
            memory_bytes_spilled=10000000,  # 10000000 bytes each
            disk_bytes_spilled=5000000,  # 5000000 bytes each
        )
        task = TaskModel(task_data, is_json=True)
        stage.add_task(task)

    # TaskModel converts bytes to MB: 10000000 / 1000000 = 10 MB per task
    # Total memory spill: 3 * 10 MB = 30 MB
    total_memory = stage.total_memory_bytes_spilled()
    assert total_memory == pytest.approx(30.0, rel=0.01)

    # Total disk spill: 3 * 5 MB = 15 MB
    total_disk = stage.total_disk_bytes_spilled()
    assert total_disk == pytest.approx(15.0, rel=0.01)


@pytest.mark.unit
@pytest.mark.slow
def test_stage_model_performance():
    """
    Test that StageModel aggregation is reasonably fast.

    Aggregating 1000 tasks should take < 1 second.
    """
    import time

    stage = StageModel()

    # Add 1000 tasks
    for i in range(1000):
        task_data = create_task_data(
            task_id=i,
            launch_time=1000000 + i,
            finish_time=1001000 + i,
        )
        task = TaskModel(task_data, is_json=True)
        stage.add_task(task)

    # Time aggregations
    start = time.time()

    _ = stage.average_task_runtime()
    _ = stage.total_gc_time()
    _ = stage.finish_time()
    _ = stage.total_runtime()
    _ = stage.input_mb()
    _ = stage.output_mb()

    elapsed = time.time() - start

    # Should be very fast (< 0.1s for all aggregations)
    assert elapsed < 0.1, f"Aggregations took {elapsed:.2f}s, expected < 0.1s"
