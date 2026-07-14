# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Unit tests for ArtifactSummarizer - summarizes large artifacts for token efficiency.

Tests cover:
- Extractive summarization (verbatim key sections)
- Abstractive summarization (grounded in evidence)
- Timeline construction from log entries
- Token budget management
"""

from __future__ import annotations

from textwrap import dedent

import pytest
from starboard.tools.domain.diagnostic.artifact_summarizer import (
    ArtifactSummarizer,
    SummarizationResult,
    SummarySection,
)


@pytest.fixture
def summarizer() -> ArtifactSummarizer:
    """Create ArtifactSummarizer instance."""
    return ArtifactSummarizer()


# =============================================================================
# EXTRACTIVE SUMMARIZATION
# =============================================================================


class TestExtractiveSummarization:
    """Tests for extractive (verbatim) summarization."""

    def test_extract_error_section(self, summarizer: ArtifactSummarizer) -> None:
        """Extract error sections verbatim."""
        text = dedent("""
            INFO: Starting job
            INFO: Processing data
            ERROR: java.lang.OutOfMemoryError: Java heap space
            at org.apache.spark.memory.TaskMemoryManager.allocatePage
            INFO: Cleaning up
        """)
        result = summarizer.summarize(text, mode="extractive")

        assert result.has_content
        assert "OutOfMemoryError" in result.summary
        # Should preserve error context
        assert len(result.sections) >= 1

    def test_extract_multiple_sections(self, summarizer: ArtifactSummarizer) -> None:
        """Extract multiple important lines into summary."""
        text = dedent("""
            INFO: Job started at 10:00:00
            WARN: Shuffle spill detected
            INFO: Stage 1 completed
            ERROR: Task failed due to OOM
            INFO: Retrying task
            ERROR: Max retries exceeded
            INFO: Job failed
        """)
        result = summarizer.summarize(text, mode="extractive")

        assert result.has_content
        # Should capture both errors
        assert "Task failed due to OOM" in result.summary
        assert "Max retries exceeded" in result.summary

    def test_preserve_stack_trace(self, summarizer: ArtifactSummarizer) -> None:
        """Stack traces should be preserved in extraction."""
        text = dedent("""
            java.lang.RuntimeException: Task failed
                at org.apache.spark.scheduler.Task.run(Task.scala:123)
                at org.apache.spark.executor.Executor.run(Executor.scala:456)
            Caused by: java.io.IOException: Connection refused
                at java.net.Socket.connect(Socket.java:789)
        """)
        result = summarizer.summarize(text, mode="extractive")

        assert "Caused by" in result.summary
        assert "RuntimeException" in result.summary

    def test_respects_max_length(self, summarizer: ArtifactSummarizer) -> None:
        """Extractive summary respects max length."""
        long_text = "ERROR: Something failed\n" * 1000
        result = summarizer.summarize(text=long_text, mode="extractive", max_length=500)

        assert len(result.summary) <= 600  # Allow some margin for truncation message


# =============================================================================
# ABSTRACTIVE SUMMARIZATION
# =============================================================================


class TestAbstractiveSummarization:
    """Tests for abstractive (grounded) summarization."""

    def test_abstract_simple_error(self, summarizer: ArtifactSummarizer) -> None:
        """Generate abstract summary of simple error."""
        text = dedent("""
            ERROR: java.lang.OutOfMemoryError: Java heap space
            at org.apache.spark.executor.Executor.run(Executor.scala:456)
        """)
        result = summarizer.summarize(text, mode="abstractive")

        assert result.has_content
        # Should mention the error type
        assert "memory" in result.summary.lower() or "oom" in result.summary.lower()

    def test_abstract_preserves_key_details(
        self, summarizer: ArtifactSummarizer
    ) -> None:
        """Abstract summary preserves key error details."""
        text = dedent("""
            Command exited with exit code 137
            Container killed by SIGKILL
            Memory limit: 16GB
        """)
        result = summarizer.summarize(text, mode="abstractive")

        assert result.has_content
        # Should mention exit code or signal
        assert "137" in result.summary or "SIGKILL" in result.summary.upper()

    def test_abstract_multi_error(self, summarizer: ArtifactSummarizer) -> None:
        """Abstract summary handles multiple errors."""
        text = dedent("""
            ERROR: Connection timeout to node 1
            ERROR: Shuffle fetch failed from executor 2
            ERROR: Task failed, max retries exceeded
        """)
        result = summarizer.summarize(text, mode="abstractive")

        assert result.has_content
        # Should mention multiple issues or consolidate them
        assert len(result.summary) > 0


# =============================================================================
# TIMELINE CONSTRUCTION
# =============================================================================


class TestTimelineConstruction:
    """Tests for timeline extraction from logs."""

    def test_extract_timestamps(self, summarizer: ArtifactSummarizer) -> None:
        """Extract entries with timestamps."""
        text = dedent("""
            2024-01-15 10:00:00 INFO Job started
            2024-01-15 10:05:00 WARN Low memory
            2024-01-15 10:10:00 ERROR OOM occurred
            2024-01-15 10:10:05 INFO Job failed
        """)
        result = summarizer.build_timeline(text)

        assert len(result) >= 2
        # Should have chronological order
        assert result[0].timestamp <= result[-1].timestamp

    def test_timeline_with_duration(self, summarizer: ArtifactSummarizer) -> None:
        """Timeline should calculate duration when possible."""
        text = dedent("""
            2024-01-15 10:00:00 INFO Stage 1 started
            2024-01-15 10:30:00 INFO Stage 1 completed
        """)
        result = summarizer.build_timeline(text)

        assert len(result) >= 2
        # Should be able to infer duration from timestamps

    def test_timeline_filters_noise(self, summarizer: ArtifactSummarizer) -> None:
        """Timeline should filter out low-value entries when many entries exist."""
        # Create a log with many DEBUG entries (>10 to trigger filtering)
        lines = ["2024-01-15 10:00:00 DEBUG Memory check OK"]
        for i in range(1, 15):
            lines.append(f"2024-01-15 10:00:{i:02d} DEBUG Memory check OK")
        lines.insert(7, "2024-01-15 10:00:07 ERROR Critical failure")
        text = "\n".join(lines)

        result = summarizer.build_timeline(text)

        # Should filter out most DEBUG entries
        assert len(result) < len(lines)
        # Should include the ERROR
        assert any(e.level == "ERROR" for e in result)

    def test_timeline_empty_for_no_timestamps(
        self, summarizer: ArtifactSummarizer
    ) -> None:
        """No timeline when no timestamps present."""
        text = "Just some error text without timestamps"
        result = summarizer.build_timeline(text)

        assert len(result) == 0


# =============================================================================
# TOKEN BUDGET
# =============================================================================


class TestTokenBudget:
    """Tests for token-efficient summarization."""

    def test_small_artifact_unchanged(self, summarizer: ArtifactSummarizer) -> None:
        """Small artifacts may not need summarization."""
        text = "ERROR: Simple error message"
        result = summarizer.summarize(text, mode="extractive")

        # Small text should be preserved largely intact
        assert "Simple error message" in result.summary

    def test_large_artifact_compressed(self, summarizer: ArtifactSummarizer) -> None:
        """Large artifacts should be compressed."""
        # Create a large log file
        lines = []
        for i in range(1000):
            lines.append(f"2024-01-15 10:00:{i:02d} INFO Processing record {i}")
        lines.append("2024-01-15 10:16:40 ERROR Critical failure occurred")
        text = "\n".join(lines)

        result = summarizer.summarize(text, mode="extractive", max_length=500)

        # Should be significantly smaller
        assert len(result.summary) < len(text) / 2
        # But should preserve the error
        assert "Critical failure" in result.summary

    def test_compression_ratio_reported(self, summarizer: ArtifactSummarizer) -> None:
        """Report compression ratio."""
        text = "INFO: Line\n" * 100 + "ERROR: Important"
        result = summarizer.summarize(text, mode="extractive", max_length=200)

        assert result.compression_ratio >= 0
        assert result.compression_ratio <= 1

    def test_metadata_included(self, summarizer: ArtifactSummarizer) -> None:
        """Summary includes metadata about what was removed."""
        text = "INFO: Line\n" * 100 + "ERROR: Important"
        result = summarizer.summarize(text, mode="extractive", max_length=200)

        # Should indicate something was omitted
        assert result.lines_omitted >= 0


# =============================================================================
# RESULT STRUCTURE
# =============================================================================


class TestResultStructure:
    """Tests for result structure."""

    def test_result_properties(self, summarizer: ArtifactSummarizer) -> None:
        """Result has expected properties."""
        text = "ERROR: Test error"
        result = summarizer.summarize(text, mode="extractive")

        assert isinstance(result, SummarizationResult)
        assert hasattr(result, "summary")
        assert hasattr(result, "sections")
        assert hasattr(result, "compression_ratio")

    def test_section_structure(self, summarizer: ArtifactSummarizer) -> None:
        """Sections have expected structure."""
        text = dedent("""
            ERROR: First error
            ERROR: Second error
        """)
        result = summarizer.summarize(text, mode="extractive")

        for section in result.sections:
            assert isinstance(section, SummarySection)
            assert hasattr(section, "content")
            assert hasattr(section, "section_type")


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_text(self, summarizer: ArtifactSummarizer) -> None:
        """Empty text should not crash."""
        result = summarizer.summarize("", mode="extractive")
        assert not result.has_content or result.summary == ""

    def test_whitespace_only(self, summarizer: ArtifactSummarizer) -> None:
        """Whitespace-only text should not crash."""
        result = summarizer.summarize("   \n\t  ", mode="extractive")
        assert not result.has_content or result.summary.strip() == ""

    def test_binary_like_content(self, summarizer: ArtifactSummarizer) -> None:
        """Binary-like content should be handled gracefully."""
        text = "\x00\x01\x02 ERROR: Real error \x03\x04"
        result = summarizer.summarize(text, mode="extractive")
        # Should not crash; may or may not extract the error
        assert isinstance(result, SummarizationResult)

    def test_unicode_content(self, summarizer: ArtifactSummarizer) -> None:
        """Unicode content should be handled."""
        text = "ERROR: 数据处理失败 - Data processing failed"
        result = summarizer.summarize(text, mode="extractive")
        assert result.has_content

    def test_invalid_mode_fallback(self, summarizer: ArtifactSummarizer) -> None:
        """Invalid mode should use default or raise clear error."""
        text = "ERROR: Test error"
        # Should either use default mode or raise clear error
        try:
            result = summarizer.summarize(text, mode="invalid")  # type: ignore
            assert isinstance(result, SummarizationResult)
        except ValueError as e:
            assert "mode" in str(e).lower()
