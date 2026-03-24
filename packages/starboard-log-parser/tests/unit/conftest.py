"""
Pytest fixtures for log parser unit tests.

This module provides shared fixtures for testing the Spark UI log parser.
"""

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def temp_log_dir(tmp_path: Path) -> Path:
    """
    Provide a temporary directory for log files.

    Args:
        tmp_path: pytest's temporary directory fixture

    Returns:
        Path to temporary log directory
    """
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir


@pytest.fixture
def minimal_spark_log(temp_log_dir: Path) -> Path:
    """
    Create a minimal valid Spark event log.

    This log contains the bare minimum events to create a valid application:
    - SparkListenerLogStart
    - SparkListenerApplicationStart
    - SparkListenerApplicationEnd

    Returns:
        Path to created log file
    """
    log_file = temp_log_dir / "minimal_app.log"

    events = [
        '{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}',
        '{"Event":"SparkListenerApplicationStart","App Name":"MinimalApp","App ID":"app-001","Timestamp":1000000,"User":"test"}',
        '{"Event":"SparkListenerApplicationEnd","Timestamp":2000000}',
    ]

    with open(log_file, "w") as f:
        f.write("\n".join(events))

    return log_file


@pytest.fixture
def spark_log_with_tasks(temp_log_dir: Path) -> Path:
    """
    Create a Spark log with job, stage, and task events.

    This log contains a single job with a single stage with 3 tasks.

    Returns:
        Path to created log file
    """
    log_file = temp_log_dir / "app_with_tasks.log"

    events = [
        '{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}',
        '{"Event":"SparkListenerApplicationStart","App Name":"TaskApp","App ID":"app-002","Timestamp":1000000,"User":"test"}',
        # Job start
        '{"Event":"SparkListenerJobStart","Job ID":0,"Submission Time":1001000,"Stage Infos":[{"Stage ID":0,"Stage Attempt ID":0,"Stage Name":"test"}]}',
        # Stage start
        '{"Event":"SparkListenerStageSubmitted","Stage Info":{"Stage ID":0,"Stage Attempt ID":0,"Stage Name":"test","Number of Tasks":3,"Submission Time":1002000}}',
        # Task events
        '{"Event":"SparkListenerTaskStart","Stage ID":0,"Task Info":{"Task ID":0,"Attempt":0,"Launch Time":1003000}}',
        '{"Event":"SparkListenerTaskEnd","Stage ID":0,"Task Type":"ShuffleMapTask","Task Info":{"Task ID":0,"Attempt":0,"Launch Time":1003000,"Finish Time":1004000},"Task Metrics":{"Executor Run Time":1000}}',
        '{"Event":"SparkListenerTaskStart","Stage ID":0,"Task Info":{"Task ID":1,"Attempt":0,"Launch Time":1003000}}',
        '{"Event":"SparkListenerTaskEnd","Stage ID":0,"Task Type":"ShuffleMapTask","Task Info":{"Task ID":1,"Attempt":0,"Launch Time":1003000,"Finish Time":1004000},"Task Metrics":{"Executor Run Time":1000}}',
        '{"Event":"SparkListenerTaskStart","Stage ID":0,"Task Info":{"Task ID":2,"Attempt":0,"Launch Time":1003000}}',
        '{"Event":"SparkListenerTaskEnd","Stage ID":0,"Task Type":"ShuffleMapTask","Task Info":{"Task ID":2,"Attempt":0,"Launch Time":1003000,"Finish Time":1004000},"Task Metrics":{"Executor Run Time":1000}}',
        # Stage end
        '{"Event":"SparkListenerStageCompleted","Stage Info":{"Stage ID":0,"Stage Attempt ID":0,"Completion Time":1005000}}',
        # Job end
        '{"Event":"SparkListenerJobEnd","Job ID":0,"Completion Time":1006000,"Job Result":{"Result":"JobSucceeded"}}',
        '{"Event":"SparkListenerApplicationEnd","Timestamp":2000000}',
    ]

    with open(log_file, "w") as f:
        f.write("\n".join(events))

    return log_file


@pytest.fixture
def malformed_spark_log(temp_log_dir: Path) -> Path:
    """
    Create a malformed Spark log for testing error handling.

    This log contains invalid JSON and missing required fields.

    Returns:
        Path to created log file
    """
    log_file = temp_log_dir / "malformed_app.log"

    events = [
        '{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}',
        "this is not valid json",
        '{"Event":"SparkListenerApplicationStart"}',  # Missing required fields
        '{"Event":"SparkListenerApplicationEnd","Timestamp":2000000}',
    ]

    with open(log_file, "w") as f:
        f.write("\n".join(events))

    return log_file


@pytest.fixture
def deeply_nested_accum_data() -> dict[str, Any]:
    """
    Create deeply nested accumulated metrics data for recursion testing.

    Returns:
        Dictionary with nested structure
    """

    def create_nested(depth: int, include_metrics: bool = False) -> dict[str, Any]:
        """Recursively create nested dictionary."""
        if depth == 0:
            if include_metrics:
                return {
                    "metrics": [
                        {
                            "accumulatorId": 1,
                            "name": "test_metric",
                            "metricType": "counter",
                        }
                    ]
                }
            else:
                return {"leaf": "value"}

        return {"nested": create_nested(depth - 1, include_metrics)}

    # Create 10 levels deep (reasonable)
    return create_nested(10, include_metrics=True)


@pytest.fixture
def sample_task_metrics() -> dict[str, Any]:
    """
    Provide sample task metrics for testing.

    Returns:
        Dictionary of task metrics matching Spark format
    """
    return {
        "Executor Run Time": 1500,
        "Executor CPU Time": 1200,
        "Result Size": 1024,
        "JVM GC Time": 100,
        "Result Serialization Time": 50,
        "Memory Bytes Spilled": 0,
        "Disk Bytes Spilled": 0,
        "Shuffle Read Metrics": {
            "Remote Blocks Fetched": 10,
            "Local Blocks Fetched": 5,
            "Fetch Wait Time": 200,
            "Remote Bytes Read": 5242880,  # 5 MB
            "Local Bytes Read": 1048576,  # 1 MB
            "Total Records Read": 1000,
        },
        "Shuffle Write Metrics": {
            "Shuffle Bytes Written": 10485760,  # 10 MB
            "Shuffle Write Time": 500000000,  # 500ms in nanoseconds
            "Shuffle Records Written": 2000,
        },
        "Input Metrics": {"Bytes Read": 20971520, "Records Read": 5000},  # 20 MB
        "Output Metrics": {"Bytes Written": 15728640, "Records Written": 3000},  # 15 MB
    }


@pytest.fixture
def mock_application_model():
    """
    Provide a mock ApplicationModel for testing without file I/O.

    Returns:
        Mock ApplicationModel instance
    """
    from collections import defaultdict

    class MockApplicationModel:
        """Minimal mock of ApplicationModel for testing."""

        def __init__(self):
            self.accum_metrics = defaultdict(dict)
            self.start_time = 1000000
            self.finish_time = 2000000
            self.app_name = "TestApp"
            self.app_id = "app-test-001"

    return MockApplicationModel()


# Marks for organizing tests
def pytest_configure(config):
    """Register custom pytest marks."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line(
        "markers", "requires_log_parser: mark test as requiring log parser module"
    )
