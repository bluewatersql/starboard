"""
Simple test for parallel tool execution.

Focuses on testing the core parallel execution behavior without complex mocking.
"""

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_parallel_execution_with_gather():
    """Test that asyncio.gather executes tasks in parallel."""
    execution_log = []

    async def slow_task(task_id: str, duration: float):
        """Simulates a tool call with delay."""
        start = time.time()
        await asyncio.sleep(duration)
        end = time.time()
        execution_log.append(
            {"task_id": task_id, "start": start, "end": end, "duration": end - start}
        )
        return f"Result from {task_id}"

    # Execute 3 tasks that each take 0.1 seconds
    start_time = time.time()
    results = await asyncio.gather(
        slow_task("task1", 0.1),
        slow_task("task2", 0.1),
        slow_task("task3", 0.1),
    )
    total_duration = time.time() - start_time

    # Verify all tasks completed
    assert len(results) == 3
    assert len(execution_log) == 3

    # Verify parallel execution (should take ~0.1s, not ~0.3s sequentially)
    assert total_duration < 0.2, (
        f"Parallel execution took {total_duration:.2f}s, "
        "expected <0.2s (sequential would be ~0.3s)"
    )

    # Verify tasks overlapped in execution
    overlaps = 0
    for i in range(len(execution_log)):
        for j in range(i + 1, len(execution_log)):
            # If task i starts before task j ends AND task j starts before task i ends
            if (
                execution_log[i]["start"] < execution_log[j]["end"]
                and execution_log[j]["start"] < execution_log[i]["end"]
            ):
                overlaps += 1

    assert overlaps > 0, "Tasks should have overlapping execution times"


@pytest.mark.asyncio
async def test_parallel_execution_with_error():
    """Test that errors in one task don't block others."""
    results_log = []

    async def task_with_error(task_id: str):
        """Task that raises an error."""
        await asyncio.sleep(0.05)
        if task_id == "fail":
            raise ValueError("Test error")
        results_log.append(task_id)
        return f"Result from {task_id}"

    # Execute tasks with one that fails
    results = await asyncio.gather(
        task_with_error("task1"),
        task_with_error("fail"),
        task_with_error("task3"),
        return_exceptions=True,  # Don't propagate exceptions
    )

    # Verify we got results for all tasks
    assert len(results) == 3

    # First and third should succeed
    assert results[0] == "Result from task1"
    assert isinstance(results[1], ValueError)  # The error
    assert results[2] == "Result from task3"

    # Verify successful tasks completed
    assert "task1" in results_log
    assert "task3" in results_log
    assert "fail" not in results_log


@pytest.mark.asyncio
async def test_parallel_execution_performance_benefit():
    """Test that parallel execution provides performance benefit."""

    # Create 5 tasks that each take 0.1 seconds
    async def slow_task(n: int):
        await asyncio.sleep(0.1)
        return n

    # Execute in parallel
    start_time = time.time()
    results = await asyncio.gather(*[slow_task(i) for i in range(5)])
    parallel_duration = time.time() - start_time

    # Verify all completed
    assert len(results) == 5
    assert results == [0, 1, 2, 3, 4]

    # Parallel should be much faster than sequential
    # Sequential would be ~0.5s, parallel should be ~0.1s
    assert parallel_duration < 0.3, (
        f"Parallel execution took {parallel_duration:.2f}s, "
        "should be significantly less than sequential (~0.5s)"
    )
