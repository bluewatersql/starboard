"""
Tests for create_spark_application_from_content factory function.

Tests creating SparkApplication instances from string/bytes content,
handling both pre-parsed JSON and raw event log formats.
"""

from __future__ import annotations

import json

import pytest


class TestCreateSparkApplicationFromContent:
    """Tests for create_spark_application_from_content factory."""

    # =========================================================================
    # PRE-PARSED JSON TESTS
    # =========================================================================

    def test_parses_preparsed_json_string(self) -> None:
        """Should parse pre-parsed JSON content (string)."""
        from starboard_log_parser import create_spark_application_from_content

        content = json.dumps(
            {
                "metadata": {
                    "application_info": {
                        "id": "app-preparsed",
                        "name": "PreparsedApp",
                        "timestamp_start_ms": 1000000,
                        "timestamp_end_ms": 2000000,
                        "runtime_sec": 1000,
                        "spark_version": "3.2.1",
                    },
                    "existsSQL": False,
                    "existsExecutors": False,
                },
                "jobData": [],
                "stageData": [],
                "taskData": [],
                "accumData": [],
            }
        )

        app = create_spark_application_from_content(content)

        assert app.metadata.application_info.id == "app-preparsed"
        assert app.metadata.application_info.name == "PreparsedApp"
        assert len(app.job_data) == 0

    def test_parses_preparsed_json_bytes(self) -> None:
        """Should parse pre-parsed JSON content (bytes)."""
        from starboard_log_parser import create_spark_application_from_content

        content = json.dumps(
            {
                "metadata": {
                    "application_info": {
                        "id": "app-bytes",
                        "name": "BytesApp",
                        "timestamp_start_ms": 1000000,
                        "timestamp_end_ms": 2000000,
                        "runtime_sec": 1000,
                        "spark_version": "3.2.1",
                    },
                    "existsSQL": False,
                    "existsExecutors": False,
                },
                "jobData": [],
                "stageData": [],
                "taskData": [],
                "accumData": [],
            }
        ).encode("utf-8")

        app = create_spark_application_from_content(content)

        assert app.metadata.application_info.id == "app-bytes"
        assert app.metadata.application_info.name == "BytesApp"

    def test_parses_preparsed_json_with_data(self) -> None:
        """Should parse pre-parsed JSON with job/stage/task data."""
        from starboard_log_parser import create_spark_application_from_content

        content = json.dumps(
            {
                "metadata": {
                    "application_info": {
                        "id": "app-with-data",
                        "name": "DataApp",
                        "timestamp_start_ms": 1000000,
                        "timestamp_end_ms": 2000000,
                        "runtime_sec": 1000,
                        "spark_version": "3.2.1",
                    },
                    "existsSQL": False,
                    "existsExecutors": False,
                },
                "jobData": {"job_id": [0, 1], "status": ["SUCCESS", "SUCCESS"]},
                "stageData": {"stage_id": [0, 1, 2]},
                "taskData": {"task_id": [0, 1, 2, 3, 4]},
                "accumData": {},
            }
        )

        app = create_spark_application_from_content(content)

        assert len(app.job_data) == 2
        assert len(app.stage_data) == 3
        assert len(app.task_data) == 5

    def test_parses_preparsed_json_with_sql_data(self) -> None:
        """Should parse pre-parsed JSON with SQL data."""
        from starboard_log_parser import create_spark_application_from_content

        content = json.dumps(
            {
                "metadata": {
                    "application_info": {
                        "id": "app-sql",
                        "name": "SQLApp",
                        "timestamp_start_ms": 1000000,
                        "timestamp_end_ms": 2000000,
                        "runtime_sec": 1000,
                        "spark_version": "3.2.1",
                    },
                    "existsSQL": True,
                    "existsExecutors": False,
                },
                "jobData": [],
                "stageData": [],
                "taskData": [],
                "accumData": [],
                "sqlData": {"execution_id": [0, 1]},
            }
        )

        app = create_spark_application_from_content(content)

        assert app.has_sql_data()
        assert len(app.sql_data) == 2

    def test_parses_preparsed_json_with_executor_data(self) -> None:
        """Should parse pre-parsed JSON with executor data."""
        from starboard_log_parser import create_spark_application_from_content

        content = json.dumps(
            {
                "metadata": {
                    "application_info": {
                        "id": "app-executors",
                        "name": "ExecutorApp",
                        "timestamp_start_ms": 1000000,
                        "timestamp_end_ms": 2000000,
                        "runtime_sec": 1000,
                        "spark_version": "3.2.1",
                    },
                    "existsSQL": False,
                    "existsExecutors": True,
                },
                "jobData": [],
                "stageData": [],
                "taskData": [],
                "accumData": [],
                "executors": {"executor_id": ["0", "1", "2"]},
            }
        )

        app = create_spark_application_from_content(content)

        assert app.has_executor_data()
        assert len(app.executor_data) == 3

    def test_handles_pretty_printed_json(self) -> None:
        """Should parse pretty-printed JSON (multi-line)."""
        from starboard_log_parser import create_spark_application_from_content

        content = """{
            "metadata": {
                "application_info": {
                    "id": "app-pretty",
                    "name": "PrettyApp",
                    "timestamp_start_ms": 1000000,
                    "timestamp_end_ms": 2000000,
                    "runtime_sec": 1000,
                    "spark_version": "3.2.1"
                },
                "existsSQL": false,
                "existsExecutors": false
            },
            "jobData": [],
            "stageData": [],
            "taskData": [],
            "accumData": []
        }"""

        app = create_spark_application_from_content(content)

        assert app.metadata.application_info.id == "app-pretty"

    # =========================================================================
    # RAW EVENT LOG TESTS
    # =========================================================================

    def test_parses_minimal_event_log(self) -> None:
        """Should parse a minimal event log with just start/end events."""
        from starboard_log_parser import create_spark_application_from_content

        content = "\n".join(
            [
                '{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}',
                '{"Event":"SparkListenerApplicationStart","App Name":"MinimalApp","App ID":"app-minimal","Timestamp":1000000,"User":"test"}',
                '{"Event":"SparkListenerApplicationEnd","Timestamp":2000000}',
            ]
        )

        app = create_spark_application_from_content(content, debug=True)

        assert app.metadata.application_info.name == "MinimalApp"
        assert app.metadata.application_info.spark_version == "3.2.1"

    def test_correctly_routes_event_log_to_parser(self) -> None:
        """Should detect event log format and route to ApplicationModel parser.

        Note: Full event log parsing is tested in the ApplicationModel tests.
        This test verifies the routing logic works correctly for minimal event logs.
        Complex event logs (with jobs/tasks) require many fields - testing those
        is the responsibility of the event_log_parser tests.
        """
        from starboard_log_parser import create_spark_application_from_content
        from starboard_log_parser.application.factory import _is_event_log_content

        # Minimal event log (just start/end - no job/stage complexity)
        content = "\n".join(
            [
                '{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}',
                '{"Event":"SparkListenerApplicationStart","App Name":"RouteTestApp","App ID":"app-route","Timestamp":1000000,"User":"test"}',
                '{"Event":"SparkListenerApplicationEnd","Timestamp":2000000}',
            ]
        )

        # Verify format detection
        assert _is_event_log_content(content) is True

        # Verify parsing works
        app = create_spark_application_from_content(content, debug=True)

        assert app.metadata.application_info.name == "RouteTestApp"
        assert app.metadata.application_info.spark_version == "3.2.1"

    def test_parses_event_log_with_executors(self) -> None:
        """Should parse event log with executor events."""
        from starboard_log_parser import create_spark_application_from_content

        content = "\n".join(
            [
                '{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}',
                '{"Event":"SparkListenerApplicationStart","App Name":"ExecApp","App ID":"app-exec","Timestamp":1000000,"User":"test"}',
                '{"Event":"SparkListenerExecutorAdded","Executor ID":"0","Timestamp":1001000,"Executor Info":{"Host":"host1","Total Cores":4}}',
                '{"Event":"SparkListenerExecutorAdded","Executor ID":"1","Timestamp":1002000,"Executor Info":{"Host":"host2","Total Cores":4}}',
                '{"Event":"SparkListenerApplicationEnd","Timestamp":2000000}',
            ]
        )

        app = create_spark_application_from_content(content, debug=True)

        assert app.has_executor_data()
        assert len(app.executor_data) == 2

    # =========================================================================
    # EDGE CASES
    # =========================================================================

    def test_handles_empty_lines(self) -> None:
        """Should skip empty lines in event log."""
        from starboard_log_parser import create_spark_application_from_content

        content = """
{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}

{"Event":"SparkListenerApplicationStart","App Name":"EmptyLineApp","App ID":"app-empty","Timestamp":1000000,"User":"test"}

{"Event":"SparkListenerApplicationEnd","Timestamp":2000000}

"""

        app = create_spark_application_from_content(content, debug=True)

        assert app.metadata.application_info.name == "EmptyLineApp"

    def test_handles_infinity_values_in_preparsed(self) -> None:
        """Should handle Infinity values in pre-parsed JSON."""
        from starboard_log_parser import create_spark_application_from_content

        # Note: This uses literal Infinity which orjson would reject
        # The factory should clean it up by replacing Infinity with null
        # Using a field that can handle null (like spark_params or empty fields)
        content = """{
            "metadata": {
                "application_info": {
                    "id": "app-inf",
                    "name": "InfinityApp",
                    "timestamp_start_ms": 1000000,
                    "timestamp_end_ms": 2000000,
                    "runtime_sec": 1000,
                    "spark_version": "3.2.1"
                },
                "existsSQL": false,
                "existsExecutors": false,
                "spark_params": {"some_value": Infinity}
            },
            "jobData": [],
            "stageData": [],
            "taskData": [],
            "accumData": []
        }"""

        app = create_spark_application_from_content(content)

        assert app.metadata.application_info.id == "app-inf"
        assert app.metadata.application_info.name == "InfinityApp"
        # Infinity is converted to null in spark_params
        assert app.metadata.spark_params.get("some_value") is None

    def test_handles_bytes_input(self) -> None:
        """Should handle bytes input (like file uploads)."""
        from starboard_log_parser import create_spark_application_from_content

        content = b'{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}\n{"Event":"SparkListenerApplicationStart","App Name":"BytesApp","App ID":"app-bytes","Timestamp":1000000,"User":"test"}\n{"Event":"SparkListenerApplicationEnd","Timestamp":2000000}'

        app = create_spark_application_from_content(content, debug=True)

        assert app.metadata.application_info.name == "BytesApp"

    def test_handles_unicode_content(self) -> None:
        """Should handle unicode characters in content."""
        from starboard_log_parser import create_spark_application_from_content

        content = json.dumps(
            {
                "metadata": {
                    "application_info": {
                        "id": "app-unicode",
                        "name": "测试应用 🚀",  # Chinese + emoji
                        "timestamp_start_ms": 1000000,
                        "timestamp_end_ms": 2000000,
                        "runtime_sec": 1000,
                        "spark_version": "3.2.1",
                    },
                    "existsSQL": False,
                    "existsExecutors": False,
                },
                "jobData": [],
                "stageData": [],
                "taskData": [],
                "accumData": [],
            }
        )

        app = create_spark_application_from_content(content)

        assert app.metadata.application_info.name == "测试应用 🚀"

    # =========================================================================
    # ERROR CASES
    # =========================================================================

    def test_handles_invalid_json_gracefully(self) -> None:
        """Should handle completely invalid content (treated as empty event log)."""
        from starboard_log_parser import create_spark_application_from_content

        # Invalid content with no valid JSON - treated as empty event log
        # This produces an "empty" SparkApplication since no events are parsed
        content = "this is not json at all"

        # This will be treated as an event log with no valid events
        # The ApplicationModel should still be created but with no data
        app = create_spark_application_from_content(content, debug=True)

        # The app should have empty data
        assert len(app.job_data) == 0
        assert len(app.stage_data) == 0
        assert len(app.task_data) == 0

    def test_raises_on_missing_required_fields_preparsed(self) -> None:
        """Should raise error when required fields are missing (pre-parsed)."""
        from starboard_log_parser import create_spark_application_from_content

        content = json.dumps(
            {
                "metadata": {},  # Missing required fields
                "jobData": [],
            }
        )

        with pytest.raises((KeyError, ValueError)):
            create_spark_application_from_content(content)


class TestCreateSparkApplicationFromContentPerformance:
    """Performance-related tests for content parsing."""

    def test_parses_large_preparsed_content(self) -> None:
        """Should handle large pre-parsed JSON content."""
        from starboard_log_parser import create_spark_application_from_content

        # Create content with many jobs
        job_ids = list(range(1000))
        content = json.dumps(
            {
                "metadata": {
                    "application_info": {
                        "id": "app-large",
                        "name": "LargeApp",
                        "timestamp_start_ms": 1000000,
                        "timestamp_end_ms": 2000000,
                        "runtime_sec": 1000,
                        "spark_version": "3.2.1",
                    },
                    "existsSQL": False,
                    "existsExecutors": False,
                },
                "jobData": {"job_id": job_ids},
                "stageData": {"stage_id": list(range(5000))},
                "taskData": {"task_id": list(range(10000))},
                "accumData": {},
            }
        )

        app = create_spark_application_from_content(content)

        assert len(app.job_data) == 1000
        assert len(app.stage_data) == 5000
        assert len(app.task_data) == 10000


class TestFormatDetection:
    """Tests for format detection logic."""

    def test_detects_preparsed_format(self) -> None:
        """Should detect pre-parsed format from jobData key."""
        from starboard_log_parser.application.factory import _is_event_log_content

        content = json.dumps({"metadata": {}, "jobData": []})

        assert _is_event_log_content(content) is False

    def test_detects_event_log_format(self) -> None:
        """Should detect event log format from Event key."""
        from starboard_log_parser.application.factory import _is_event_log_content

        content = '{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}'

        assert _is_event_log_content(content) is True

    def test_detects_event_log_with_newlines(self) -> None:
        """Should detect event log format even with leading newlines."""
        from starboard_log_parser.application.factory import _is_event_log_content

        content = "\n\n\n" + '{"Event":"SparkListenerLogStart","Spark Version":"3.2.1"}'

        assert _is_event_log_content(content) is True
