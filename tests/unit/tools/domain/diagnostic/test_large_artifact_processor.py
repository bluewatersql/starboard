# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for LargeArtifactProcessor."""

from __future__ import annotations

import pytest
from starboard_server.tools.domain.diagnostic.large_artifact_processor import (
    LARGE_FILE_THRESHOLD,
    LargeArtifactProcessor,
    ProcessedArtifact,
    is_large_file,
)
from starboard_server.tools.domain.diagnostic.models import ArtifactType

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def processor() -> LargeArtifactProcessor:
    """Create a processor instance."""
    return LargeArtifactProcessor()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def create_spark_event_log() -> str:
    """Create a minimal Spark event log."""
    return (
        '{"Event": "SparkListenerLogStart", "Spark Version": "3.5.0"}\n'
        '{"Event": "SparkListenerApplicationStart", "App Name": "test", "Timestamp": 1000}\n'
        '{"Event": "SparkListenerApplicationEnd", "Timestamp": 2000}\n'
    )


def create_query_profile() -> str:
    """Create a minimal query profile."""
    return '{"operatorID": 0, "operatorName": "LocalLimit", "children": []}'


def create_explain_text() -> str:
    """Create a minimal EXPLAIN plan."""
    return (
        "== Parsed Logical Plan ==\n"
        "Project [col1, col2]\n"
        "\n"
        "== Physical Plan ==\n"
        "*(1) Project [col1, col2]\n"
        "+- *(1) Scan parquet\n"
    )


def create_stack_trace() -> str:
    """Create a realistic stack trace with enough context for detection."""
    return (
        'Exception in thread "main" java.lang.OutOfMemoryError: Java heap space\n'
        "\tat com.example.DataProcessor.process(DataProcessor.java:156)\n"
        "\tat com.example.DataProcessor.run(DataProcessor.java:42)\n"
        "\tat com.example.Pipeline.execute(Pipeline.java:89)\n"
        "\tat com.example.Main.main(Main.java:10)\n"
        "Caused by: java.lang.RuntimeException: Memory limit exceeded\n"
        "\tat com.example.Buffer.allocate(Buffer.java:23)\n"
        "\tat com.example.DataProcessor.loadData(DataProcessor.java:78)\n"
    )


# =============================================================================
# TYPE DETECTION TESTS
# =============================================================================


class TestTypeDetection:
    """Tests for artifact type detection."""

    def test_detect_spark_event_log(self, processor: LargeArtifactProcessor) -> None:
        """Should detect Spark event log format."""
        content = create_spark_event_log()
        result = processor._detect_artifact_type(content, "events.json")
        assert result.artifact_type == ArtifactType.SPARK_EVENT_LOG
        assert result.confidence >= 0.9

    def test_detect_query_profile(self, processor: LargeArtifactProcessor) -> None:
        """Should detect query profile format."""
        content = create_query_profile()
        result = processor._detect_artifact_type(content, "profile.json")
        assert result.artifact_type == ArtifactType.QUERY_PROFILE
        assert result.confidence >= 0.9

    def test_detect_explain_text(self, processor: LargeArtifactProcessor) -> None:
        """Should detect EXPLAIN plan text."""
        content = create_explain_text()
        result = processor._detect_artifact_type(content, "explain.txt")
        assert result.artifact_type == ArtifactType.EXPLAIN_PLAN
        assert result.confidence >= 0.9

    def test_detect_stack_trace(self, processor: LargeArtifactProcessor) -> None:
        """Should detect stack trace or error message (both are valid for exceptions)."""
        content = create_stack_trace()
        result = processor._detect_artifact_type(content, "error.txt")
        # Stack traces may be detected as STACK_TRACE or ERROR_MESSAGE depending on signals
        assert result.artifact_type in (
            ArtifactType.STACK_TRACE,
            ArtifactType.ERROR_MESSAGE,
        )

    def test_detect_empty_content(self, processor: LargeArtifactProcessor) -> None:
        """Should handle empty content gracefully."""
        result = processor._detect_artifact_type("", "empty.txt")
        # Should fall back to error message type
        assert result.artifact_type in (ArtifactType.ERROR_MESSAGE, ArtifactType.LOGS)


class TestSparkEventLogDetection:
    """Tests for Spark event log detection."""

    def test_is_spark_event_log_valid(self, processor: LargeArtifactProcessor) -> None:
        """Should detect valid Spark event log."""
        content = '{"Event": "SparkListenerJobStart", "Job ID": 0}'
        assert processor._is_spark_event_log(content) is True

    def test_is_spark_event_log_invalid_json(
        self, processor: LargeArtifactProcessor
    ) -> None:
        """Should reject invalid JSON."""
        content = "not json"
        assert processor._is_spark_event_log(content) is False

    def test_is_spark_event_log_wrong_format(
        self, processor: LargeArtifactProcessor
    ) -> None:
        """Should reject JSON without SparkListener event."""
        content = '{"type": "something_else"}'
        assert processor._is_spark_event_log(content) is False


class TestQueryProfileDetection:
    """Tests for query profile detection."""

    def test_is_query_profile_dict(self, processor: LargeArtifactProcessor) -> None:
        """Should detect query profile as dict."""
        content = '{"operatorID": 1, "operatorName": "Scan"}'
        assert processor._is_query_profile(content) is True

    def test_is_query_profile_array(self, processor: LargeArtifactProcessor) -> None:
        """Should detect query profile as array."""
        content = '[{"operatorID": 1}]'
        assert processor._is_query_profile(content) is True

    def test_is_query_profile_invalid(self, processor: LargeArtifactProcessor) -> None:
        """Should reject non-query-profile JSON."""
        content = '{"foo": "bar"}'
        assert processor._is_query_profile(content) is False


class TestExplainTextDetection:
    """Tests for EXPLAIN text detection."""

    def test_is_explain_text_physical_plan(
        self, processor: LargeArtifactProcessor
    ) -> None:
        """Should detect Physical Plan section."""
        content = "== Physical Plan ==\nScan parquet"
        assert processor._is_explain_text(content) is True

    def test_is_explain_text_parsed_plan(
        self, processor: LargeArtifactProcessor
    ) -> None:
        """Should detect Parsed Logical Plan section."""
        content = "== Parsed Logical Plan ==\nProject"
        assert processor._is_explain_text(content) is True

    def test_is_explain_text_not_explain(
        self, processor: LargeArtifactProcessor
    ) -> None:
        """Should reject non-EXPLAIN text."""
        content = "Just some random text"
        assert processor._is_explain_text(content) is False


# =============================================================================
# GOAL INFERENCE TESTS
# =============================================================================


class TestGoalInference:
    """Tests for goal inference from artifact type."""

    @pytest.mark.parametrize(
        ("artifact_type", "expected_substring"),
        [
            (ArtifactType.STACK_TRACE, "root cause"),
            (ArtifactType.LOGS, "errors"),
            (ArtifactType.GC_LOGS, "memory"),
            (ArtifactType.SPARK_EVENT_LOG, "Spark"),
            (ArtifactType.QUERY_PROFILE, "query"),
            (ArtifactType.EXPLAIN_PLAN, "execution plan"),
        ],
    )
    def test_infer_goal(
        self,
        processor: LargeArtifactProcessor,
        artifact_type: ArtifactType,
        expected_substring: str,
    ) -> None:
        """Should infer appropriate goal for each artifact type."""
        goal = processor._infer_goal(artifact_type)
        assert expected_substring.lower() in goal.lower()


# =============================================================================
# PROCESSING TESTS
# =============================================================================


class TestProcessGeneral:
    """Tests for general artifact processing."""

    @pytest.mark.asyncio
    async def test_process_returns_result(
        self,
        processor: LargeArtifactProcessor,
    ) -> None:
        """Should process content and return result."""
        content = create_stack_trace()

        result = await processor.process(
            content=content,
            filename="error.txt",
        )

        assert isinstance(result, ProcessedArtifact)
        assert result.artifact_type in (
            ArtifactType.STACK_TRACE,
            ArtifactType.ERROR_MESSAGE,
        )
        assert result.evidence_count > 0
        assert result.distilled_content

    @pytest.mark.asyncio
    async def test_process_with_user_goal(
        self,
        processor: LargeArtifactProcessor,
    ) -> None:
        """Should use provided user goal."""
        content = create_stack_trace()
        user_goal = "Find the memory leak"

        result = await processor.process(
            content=content,
            filename="error.txt",
            user_goal=user_goal,
        )

        assert result.inferred_goal == user_goal

    @pytest.mark.asyncio
    async def test_process_empty_content(
        self,
        processor: LargeArtifactProcessor,
    ) -> None:
        """Should handle empty content gracefully."""
        result = await processor.process(
            content="",
            filename="empty.txt",
        )

        assert isinstance(result, ProcessedArtifact)


# =============================================================================
# UTILITY TESTS
# =============================================================================


class TestUtilities:
    """Tests for utility functions."""

    def test_format_size_bytes(self, processor: LargeArtifactProcessor) -> None:
        """Should format bytes correctly."""
        assert processor._format_size(500) == "500B"

    def test_format_size_kilobytes(self, processor: LargeArtifactProcessor) -> None:
        """Should format kilobytes correctly."""
        assert processor._format_size(1024) == "1.0KB"
        assert processor._format_size(2048) == "2.0KB"

    def test_format_size_megabytes(self, processor: LargeArtifactProcessor) -> None:
        """Should format megabytes correctly."""
        assert processor._format_size(1024 * 1024) == "1.00MB"
        assert processor._format_size(7 * 1024 * 1024) == "7.00MB"


class TestIsLargeFile:
    """Tests for is_large_file helper."""

    def test_small_file(self) -> None:
        """Should return False for small files."""
        assert is_large_file(1000) is False
        assert is_large_file(LARGE_FILE_THRESHOLD - 1) is False

    def test_large_file(self) -> None:
        """Should return True for large files."""
        assert is_large_file(LARGE_FILE_THRESHOLD) is True
        assert is_large_file(LARGE_FILE_THRESHOLD + 1) is True
        assert is_large_file(1024 * 1024) is True  # 1MB


# =============================================================================
# PROCESSED ARTIFACT TESTS
# =============================================================================


class TestProcessedArtifact:
    """Tests for ProcessedArtifact dataclass."""

    def test_create_processed_artifact(self) -> None:
        """Should create ProcessedArtifact with all fields."""
        artifact = ProcessedArtifact(
            artifact_type=ArtifactType.LOGS,
            distilled_content="## Summary\nTest content",
            evidence_count=5,
            original_size=10000,
            compression_ratio=0.9,
            inferred_goal="Identify errors",
            metadata={"test": True},
        )

        assert artifact.artifact_type == ArtifactType.LOGS
        assert "Summary" in artifact.distilled_content
        assert artifact.evidence_count == 5
        assert artifact.compression_ratio == 0.9

    def test_processed_artifact_is_frozen(self) -> None:
        """ProcessedArtifact should be immutable."""
        artifact = ProcessedArtifact(
            artifact_type=ArtifactType.LOGS,
            distilled_content="test",
            evidence_count=1,
            original_size=100,
            compression_ratio=0.5,
            inferred_goal="test",
        )

        with pytest.raises(AttributeError):
            artifact.evidence_count = 10  # type: ignore[misc]

    def test_processed_artifact_to_dict(self) -> None:
        """Should convert to dictionary."""
        artifact = ProcessedArtifact(
            artifact_type=ArtifactType.LOGS,
            distilled_content="test content",
            evidence_count=3,
            original_size=1000,
            compression_ratio=0.8,
            inferred_goal="test goal",
            metadata={"key": "value"},
        )

        result = artifact.to_dict()

        assert result["artifact_type"] == "logs"
        assert result["distilled_content"] == "test content"
        assert result["evidence_count"] == 3
        assert result["metadata"]["key"] == "value"
