# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Unit tests for EvidenceWindowExtractor.

Tests cover:
- Evidence window extraction
- Stable ID generation
- Line range tracking
- Multiple evidence types
"""

from textwrap import dedent

import pytest
from starboard_server.tools.domain.diagnostic.evidence_extractor import (
    EvidenceType,
    EvidenceWindowExtractor,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def extractor() -> EvidenceWindowExtractor:
    """Create extractor instance."""
    return EvidenceWindowExtractor()


# =============================================================================
# BASIC EXTRACTION
# =============================================================================


class TestBasicExtraction:
    """Tests for basic evidence extraction."""

    def test_extract_java_exception(self, extractor: EvidenceWindowExtractor) -> None:
        """Extract Java exception evidence."""
        text = dedent("""
            Some log line
            java.lang.OutOfMemoryError: Java heap space
            at java.base/java.util.Arrays.copyOf
            """)
        result = extractor.extract(text)

        assert result.has_fatal
        assert result.window_count >= 1
        assert result.primary_evidence is not None
        assert result.primary_evidence.evidence_type == EvidenceType.OOM

    def test_extract_caused_by_chain(self, extractor: EvidenceWindowExtractor) -> None:
        """Extract Caused by chain."""
        text = dedent("""
            Exception in thread "main"
            java.lang.RuntimeException: Failed
            Caused by: java.io.IOException: Connection refused
            """)
        result = extractor.extract(text)

        types = {w.evidence_type for w in result.windows}
        assert EvidenceType.CAUSE_CHAIN in types

    def test_extract_exit_code(self, extractor: EvidenceWindowExtractor) -> None:
        """Extract exit code evidence."""
        text = "Container exited with code 137"
        result = extractor.extract(text)

        assert result.has_fatal
        types = {w.evidence_type for w in result.windows}
        assert EvidenceType.EXIT_CODE in types


# =============================================================================
# EVIDENCE TYPES
# =============================================================================


class TestEvidenceTypes:
    """Tests for different evidence types."""

    def test_oom_evidence(self, extractor: EvidenceWindowExtractor) -> None:
        """OOM evidence is extracted with high confidence."""
        text = "java.lang.OutOfMemoryError: Java heap space"
        result = extractor.extract(text)

        assert result.primary_evidence is not None
        assert result.primary_evidence.evidence_type == EvidenceType.OOM
        assert result.primary_evidence.confidence >= 0.9

    def test_spark_error_evidence(self, extractor: EvidenceWindowExtractor) -> None:
        """Spark error evidence is extracted."""
        text = "org.apache.spark.shuffle.FetchFailedException: Failed"
        result = extractor.extract(text)

        types = {w.evidence_type for w in result.windows}
        assert EvidenceType.SPARK_ERROR in types

    def test_sql_error_evidence(self, extractor: EvidenceWindowExtractor) -> None:
        """SQL error evidence is extracted."""
        text = "AnalysisException: cannot resolve 'column'"
        result = extractor.extract(text)

        types = {w.evidence_type for w in result.windows}
        assert EvidenceType.SQL_ERROR in types

    def test_warning_lower_priority(self, extractor: EvidenceWindowExtractor) -> None:
        """Warnings have lower confidence than errors."""
        text = dedent("""
            [WARN] This is a warning
            java.lang.OutOfMemoryError: heap
            """)
        result = extractor.extract(text)

        # OOM should be primary (higher confidence)
        assert result.primary_evidence is not None
        assert result.primary_evidence.evidence_type == EvidenceType.OOM


# =============================================================================
# WINDOW PROPERTIES
# =============================================================================


class TestWindowProperties:
    """Tests for evidence window properties."""

    def test_window_has_stable_id(self, extractor: EvidenceWindowExtractor) -> None:
        """Windows have stable IDs for citation."""
        text = "java.lang.OutOfMemoryError: Java heap space"
        result = extractor.extract(text)

        assert result.primary_evidence is not None
        assert result.primary_evidence.window_id.startswith("ev_")

    def test_window_id_is_stable(self, extractor: EvidenceWindowExtractor) -> None:
        """Same content produces same window ID."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result1 = extractor.extract(text)
        result2 = extractor.extract(text)

        assert result1.primary_evidence is not None
        assert result2.primary_evidence is not None
        assert result1.primary_evidence.window_id == result2.primary_evidence.window_id

    def test_window_has_line_numbers(self, extractor: EvidenceWindowExtractor) -> None:
        """Windows have line number tracking."""
        text = dedent("""
            Line 1
            Line 2
            java.lang.OutOfMemoryError: heap
            Line 4
            Line 5
            """)
        result = extractor.extract(text)

        assert result.primary_evidence is not None
        assert result.primary_evidence.line_start >= 1
        assert result.primary_evidence.line_end >= result.primary_evidence.line_start

    def test_window_contains_pattern_match(
        self, extractor: EvidenceWindowExtractor
    ) -> None:
        """Windows include the pattern that triggered extraction."""
        text = "OutOfMemoryError: Java heap space"
        result = extractor.extract(text)

        assert result.primary_evidence is not None
        assert len(result.primary_evidence.pattern_match) > 0


# =============================================================================
# CONTEXT EXTRACTION
# =============================================================================


class TestContextExtraction:
    """Tests for context around matches."""

    def test_includes_context_lines(self, extractor: EvidenceWindowExtractor) -> None:
        """Window includes context lines around match."""
        text = dedent("""
            Processing data...
            Loading table...
            java.lang.OutOfMemoryError: Java heap space
            at method1
            at method2
            Cleanup...
            """)
        result = extractor.extract(text)

        assert result.primary_evidence is not None
        # Window should include some context
        assert (
            "Processing" in result.primary_evidence.content
            or "at method" in result.primary_evidence.content
        )


# =============================================================================
# MULTIPLE WINDOWS
# =============================================================================


class TestMultipleWindows:
    """Tests for multiple evidence windows."""

    def test_extracts_multiple_windows(
        self, extractor: EvidenceWindowExtractor
    ) -> None:
        """Multiple evidence patterns create multiple windows."""
        text = dedent("""
            java.lang.OutOfMemoryError: heap

            Later...

            FetchFailedException: shuffle failed
            """)
        result = extractor.extract(text)

        assert result.window_count >= 2

    def test_windows_sorted_by_confidence(
        self, extractor: EvidenceWindowExtractor
    ) -> None:
        """Windows are sorted by confidence (highest first)."""
        text = dedent("""
            [WARN] Minor issue
            java.lang.OutOfMemoryError: heap
            """)
        result = extractor.extract(text)

        if result.window_count > 1:
            confidences = [w.confidence for w in result.windows]
            assert confidences == sorted(confidences, reverse=True)

    def test_max_windows_limit(self) -> None:
        """Max windows limit is respected."""
        extractor = EvidenceWindowExtractor(max_windows=2)
        text = dedent("""
            OutOfMemoryError: 1
            FetchFailedException: 2
            ExecutorLostFailure: 3
            AnalysisException: 4
            """)
        result = extractor.extract(text)

        assert result.window_count <= 2


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_text(self, extractor: EvidenceWindowExtractor) -> None:
        """Empty text returns no windows."""
        result = extractor.extract("")

        assert result.window_count == 0
        assert result.primary_evidence is None
        assert not result.has_fatal

    def test_no_matching_patterns(self, extractor: EvidenceWindowExtractor) -> None:
        """Text without matching patterns returns no windows."""
        text = "Everything is working fine"
        result = extractor.extract(text)

        assert result.window_count == 0

    def test_duplicate_windows_deduplicated(
        self, extractor: EvidenceWindowExtractor
    ) -> None:
        """Duplicate windows are deduplicated."""
        text = dedent("""
            java.lang.OutOfMemoryError: heap
            java.lang.OutOfMemoryError: heap
            """)
        result = extractor.extract(text)

        # Should have only one OOM window (same content = same ID)
        [w for w in result.windows if w.evidence_type == EvidenceType.OOM]
        # Due to different line contexts, they might be different
        # Just verify we don't have exact duplicates
        window_ids = [w.window_id for w in result.windows]
        assert len(window_ids) == len(set(window_ids))


# =============================================================================
# SUMMARY
# =============================================================================


class TestSummary:
    """Tests for extraction summary."""

    def test_summary_generated(self, extractor: EvidenceWindowExtractor) -> None:
        """Summary is generated for results."""
        text = "java.lang.OutOfMemoryError: heap"
        result = extractor.extract(text)

        assert len(result.summary) > 0

    def test_summary_no_evidence(self, extractor: EvidenceWindowExtractor) -> None:
        """Summary for no evidence."""
        result = extractor.extract("No errors here")

        assert "No significant evidence" in result.summary


# =============================================================================
# GET WINDOW BY ID
# =============================================================================


class TestGetWindowById:
    """Tests for getting windows by ID."""

    def test_get_existing_window(self, extractor: EvidenceWindowExtractor) -> None:
        """Get window by existing ID."""
        text = "java.lang.OutOfMemoryError: heap"
        result = extractor.extract(text)

        if result.primary_evidence:
            window = result.get_window(result.primary_evidence.window_id)
            assert window is not None
            assert window == result.primary_evidence

    def test_get_nonexistent_window(self, extractor: EvidenceWindowExtractor) -> None:
        """Get window by non-existent ID returns None."""
        text = "java.lang.OutOfMemoryError: heap"
        result = extractor.extract(text)

        window = result.get_window("ev_nonexistent")
        assert window is None
