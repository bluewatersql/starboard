# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Unit tests for ArtifactNormalizer.

Tests cover all normalization rules:
- Line ending normalization
- Whitespace handling
- Blank line collapsing
- Spark retry deduplication
- Size guardrails
"""

import pytest
from starboard_server.tools.domain.diagnostic import ArtifactType
from starboard_server.tools.domain.diagnostic.artifact_normalizer import (
    ArtifactNormalizer,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def normalizer() -> ArtifactNormalizer:
    """Create a fresh normalizer instance."""
    return ArtifactNormalizer()


# =============================================================================
# LINE ENDING NORMALIZATION
# =============================================================================


class TestLineEndingNormalization:
    """Tests for line ending normalization."""

    def test_crlf_to_lf(self, normalizer: ArtifactNormalizer) -> None:
        """Windows-style CRLF is converted to LF."""
        text = "line1\r\nline2\r\nline3"
        result = normalizer.normalize(text, ArtifactType.LOGS)
        assert result.content == "line1\nline2\nline3"

    def test_cr_to_lf(self, normalizer: ArtifactNormalizer) -> None:
        """Old Mac-style CR is converted to LF."""
        text = "line1\rline2\rline3"
        result = normalizer.normalize(text, ArtifactType.LOGS)
        assert result.content == "line1\nline2\nline3"

    def test_mixed_line_endings(self, normalizer: ArtifactNormalizer) -> None:
        """Mixed line endings are all normalized to LF."""
        text = "line1\r\nline2\rline3\nline4"
        result = normalizer.normalize(text, ArtifactType.LOGS)
        assert result.content == "line1\nline2\nline3\nline4"

    def test_lf_unchanged(self, normalizer: ArtifactNormalizer) -> None:
        """Unix-style LF is preserved."""
        text = "line1\nline2\nline3"
        result = normalizer.normalize(text, ArtifactType.LOGS)
        assert result.content == "line1\nline2\nline3"


# =============================================================================
# WHITESPACE HANDLING
# =============================================================================


class TestWhitespaceHandling:
    """Tests for whitespace normalization."""

    def test_trailing_whitespace_removed(self, normalizer: ArtifactNormalizer) -> None:
        """Trailing whitespace is removed from each line."""
        text = "line1   \nline2\t\nline3  \t  "
        result = normalizer.normalize(text, ArtifactType.LOGS)
        assert result.content == "line1\nline2\nline3"

    def test_leading_whitespace_preserved(self, normalizer: ArtifactNormalizer) -> None:
        """Leading whitespace (indentation) is preserved."""
        text = "def foo():\n    return True"
        result = normalizer.normalize(text, ArtifactType.CODE)
        assert result.content == "def foo():\n    return True"

    def test_internal_whitespace_preserved(
        self, normalizer: ArtifactNormalizer
    ) -> None:
        """Internal whitespace is preserved."""
        text = "key:    value"
        result = normalizer.normalize(text, ArtifactType.LOGS)
        assert result.content == "key:    value"


# =============================================================================
# BLANK LINE COLLAPSING
# =============================================================================


class TestBlankLineCollapsing:
    """Tests for blank line collapsing."""

    def test_multiple_blank_lines_collapsed(
        self, normalizer: ArtifactNormalizer
    ) -> None:
        """More than 2 consecutive blank lines are collapsed to 2."""
        text = "section1\n\n\n\n\nsection2"
        result = normalizer.normalize(text, ArtifactType.LOGS)
        assert result.content == "section1\n\n\nsection2"

    def test_two_blank_lines_preserved(self, normalizer: ArtifactNormalizer) -> None:
        """Exactly 2 blank lines are preserved."""
        text = "section1\n\n\nsection2"
        result = normalizer.normalize(text, ArtifactType.LOGS)
        assert result.content == "section1\n\n\nsection2"

    def test_single_blank_line_preserved(self, normalizer: ArtifactNormalizer) -> None:
        """Single blank lines are preserved."""
        text = "line1\n\nline2"
        result = normalizer.normalize(text, ArtifactType.LOGS)
        assert result.content == "line1\n\nline2"

    def test_trailing_newlines_normalized(self, normalizer: ArtifactNormalizer) -> None:
        """Trailing newlines are normalized to single newline."""
        text = "content\n\n\n\n"
        result = normalizer.normalize(text, ArtifactType.LOGS)
        # Should end with at most one newline
        assert result.content.rstrip("\n") == "content"


# =============================================================================
# SPARK RETRY DEDUPLICATION
# =============================================================================


class TestSparkRetryDeduplication:
    """Tests for Spark retry log deduplication."""

    def test_repeated_spark_lines_deduplicated(
        self, normalizer: ArtifactNormalizer
    ) -> None:
        """Repeated Spark retry messages are deduplicated."""
        repeated_line = "2025-12-17 10:15:23 WARN TaskSchedulerImpl: Initial job has not accepted any resources"
        text = "\n".join([repeated_line] * 50)

        result = normalizer.normalize(text, ArtifactType.LOGS)

        # Should have the line once plus a count indicator
        assert repeated_line in result.content
        assert "repeated" in result.content.lower() or "x " in result.content

    def test_different_lines_not_deduplicated(
        self, normalizer: ArtifactNormalizer
    ) -> None:
        """Different lines are not deduplicated."""
        text = """2025-12-17 10:15:23 INFO Line 1
2025-12-17 10:15:24 INFO Line 2
2025-12-17 10:15:25 INFO Line 3"""

        result = normalizer.normalize(text, ArtifactType.LOGS)

        # All lines should be present
        assert "Line 1" in result.content
        assert "Line 2" in result.content
        assert "Line 3" in result.content

    def test_dedup_preserves_first_occurrence(
        self, normalizer: ArtifactNormalizer
    ) -> None:
        """First occurrence of repeated line is preserved with full context."""
        text = """2025-12-17 10:15:23 WARN Resource busy
2025-12-17 10:15:24 WARN Resource busy
2025-12-17 10:15:25 WARN Resource busy
2025-12-17 10:15:26 ERROR Failed after retries"""

        result = normalizer.normalize(text, ArtifactType.LOGS)

        # Should contain the warning once and the final error
        assert "WARN Resource busy" in result.content
        assert "ERROR Failed after retries" in result.content


# =============================================================================
# ERROR WINDOW PRESERVATION
# =============================================================================


class TestErrorWindowPreservation:
    """Tests for error window preservation during normalization."""

    def test_exception_context_preserved(self, normalizer: ArtifactNormalizer) -> None:
        """Exception and surrounding context are preserved verbatim."""
        text = """2025-12-17 10:15:23 INFO Starting task
2025-12-17 10:15:24 ERROR Task failed
java.lang.OutOfMemoryError: Java heap space
    at java.util.Arrays.copyOf(Arrays.java:3236)
    at java.util.ArrayList.grow(ArrayList.java:265)
2025-12-17 10:15:25 INFO Cleanup started"""

        result = normalizer.normalize(text, ArtifactType.LOGS)

        # Exception should be fully preserved
        assert "java.lang.OutOfMemoryError: Java heap space" in result.content
        assert "at java.util.Arrays.copyOf" in result.content

    def test_exit_code_preserved(self, normalizer: ArtifactNormalizer) -> None:
        """Exit code messages are preserved."""
        text = "Command exited with code 137"
        result = normalizer.normalize(text, ArtifactType.ERROR_MESSAGE)
        assert "exit" in result.content.lower()
        assert "137" in result.content


# =============================================================================
# SIZE GUARDRAILS
# =============================================================================


class TestSizeGuardrails:
    """Tests for size limit enforcement."""

    def test_small_input_unchanged(self, normalizer: ArtifactNormalizer) -> None:
        """Small inputs pass through without truncation."""
        text = "Short error message"
        result = normalizer.normalize(text, ArtifactType.ERROR_MESSAGE)

        assert result.content == text
        assert result.truncation_applied is False

    def test_large_log_truncated(self, normalizer: ArtifactNormalizer) -> None:
        """Very large logs are truncated with notice."""
        # Generate a very large log
        lines = [f"2025-12-17 10:15:{i:02d} INFO Log line {i}" for i in range(10000)]
        text = "\n".join(lines)

        result = normalizer.normalize(text, ArtifactType.LOGS)

        # Should be truncated
        assert len(result.content) < len(text)
        assert result.truncation_applied is True
        assert result.truncation_notice is not None

    def test_truncation_preserves_head_and_tail(
        self, normalizer: ArtifactNormalizer
    ) -> None:
        """Truncation keeps beginning and end of logs."""
        lines = [
            f"2025-12-17 10:15:{i % 60:02d} INFO Log line {i}" for i in range(10000)
        ]
        text = "\n".join(lines)

        result = normalizer.normalize(text, ArtifactType.LOGS)

        # First and last lines should be present
        assert "Log line 0" in result.content
        assert "Log line 9999" in result.content

    def test_truncation_preserves_error_windows(
        self, normalizer: ArtifactNormalizer
    ) -> None:
        """Truncation preserves error windows even in middle."""
        lines = [
            f"2025-12-17 10:15:{i % 60:02d} INFO Normal line {i}" for i in range(5000)
        ]
        # Insert an error in the middle
        lines[2500] = (
            "2025-12-17 10:15:00 ERROR java.lang.OutOfMemoryError: Java heap space"
        )
        lines = lines + [
            f"2025-12-17 10:15:{i % 60:02d} INFO Normal line {i + 5000}"
            for i in range(5000)
        ]
        text = "\n".join(lines)

        result = normalizer.normalize(text, ArtifactType.LOGS)

        # Error should be preserved even if in the middle
        assert "OutOfMemoryError" in result.content


# =============================================================================
# ARTIFACT TYPE SPECIFIC HANDLING
# =============================================================================


class TestArtifactTypeHandling:
    """Tests for type-specific normalization."""

    def test_code_preserves_formatting(self, normalizer: ArtifactNormalizer) -> None:
        """Code artifacts preserve indentation and structure."""
        text = """def foo():
    if True:
        return 1
    else:
        return 0"""

        result = normalizer.normalize(text, ArtifactType.CODE)

        # Indentation should be preserved exactly
        assert "    if True:" in result.content
        assert "        return 1" in result.content

    def test_stack_trace_preserved_verbatim(
        self, normalizer: ArtifactNormalizer
    ) -> None:
        """Stack traces are preserved verbatim."""
        text = """Traceback (most recent call last):
  File "main.py", line 10, in <module>
    raise ValueError("test")
ValueError: test"""

        result = normalizer.normalize(text, ArtifactType.STACK_TRACE)

        # Should be essentially unchanged (only line endings normalized)
        assert "Traceback (most recent call last):" in result.content
        assert 'File "main.py", line 10, in <module>' in result.content


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_string(self, normalizer: ArtifactNormalizer) -> None:
        """Empty string returns empty result."""
        result = normalizer.normalize("", ArtifactType.LOGS)
        assert result.content == ""
        assert result.truncation_applied is False

    def test_whitespace_only(self, normalizer: ArtifactNormalizer) -> None:
        """Whitespace-only input is normalized to empty or minimal."""
        result = normalizer.normalize("   \n\t\n   ", ArtifactType.LOGS)
        assert result.content.strip() == ""

    def test_unicode_preserved(self, normalizer: ArtifactNormalizer) -> None:
        """Unicode content is preserved."""
        text = "Error: 日本語メッセージ"
        result = normalizer.normalize(text, ArtifactType.ERROR_MESSAGE)
        assert "日本語メッセージ" in result.content

    def test_binary_like_content_handled(self, normalizer: ArtifactNormalizer) -> None:
        """Content with escape sequences is handled."""
        text = "\\x00\\x01 binary \\xff"
        result = normalizer.normalize(text, ArtifactType.ERROR_MESSAGE)
        assert result is not None


# =============================================================================
# NORMALIZATION RESULT
# =============================================================================


class TestNormalizationResult:
    """Tests for NormalizationResult structure."""

    def test_result_has_content(self, normalizer: ArtifactNormalizer) -> None:
        """Result contains normalized content."""
        result = normalizer.normalize("test content", ArtifactType.LOGS)
        assert hasattr(result, "content")
        assert isinstance(result.content, str)

    def test_result_has_truncation_flag(self, normalizer: ArtifactNormalizer) -> None:
        """Result indicates whether truncation was applied."""
        result = normalizer.normalize("test content", ArtifactType.LOGS)
        assert hasattr(result, "truncation_applied")
        assert isinstance(result.truncation_applied, bool)

    def test_result_tracks_transformations(
        self, normalizer: ArtifactNormalizer
    ) -> None:
        """Result tracks what transformations were applied."""
        text = "line1   \r\nline2"
        result = normalizer.normalize(text, ArtifactType.LOGS)

        assert hasattr(result, "transformations_applied")
        assert len(result.transformations_applied) > 0
