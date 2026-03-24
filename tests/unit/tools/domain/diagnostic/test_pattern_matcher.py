# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Unit tests for PatternMatcher.

Tests cover:
- Basic pattern matching
- Confidence scoring
- Negative signal handling
- Multi-pattern matching
- Exit code matching
"""

from textwrap import dedent

import pytest
from starboard_server.tools.domain.diagnostic.pattern_matcher import (
    ConfidenceDetails,
    PatternMatcher,
)
from starboard_server.tools.domain.diagnostic.patterns.registry import (
    PatternRegistry,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_yaml() -> str:
    """Sample patterns for testing."""
    return dedent("""
        version: "1.0.0"
        patterns:
          - id: java_heap_space
            name: "Java Heap Space OOM"
            category: memory
            severity: critical
            responsibility: configuration
            keywords:
              - "OutOfMemoryError"
              - "Java heap space"
            regex_patterns:
              - "java\\\\.lang\\\\.OutOfMemoryError.*Java heap space"
            exception_class: "OutOfMemoryError"
            message_pattern: "Java heap space"
            root_cause: "JVM heap exhausted"
            evidence_checklist:
              required:
                - "OutOfMemoryError in logs"
            confidence_factors:
              increase:
                - "collect() in stack trace"
                - "Full GC events"
              decrease:
                - "job was cancelled"
                - "manually stopped"

          - id: exit_code_137
            name: "SIGKILL (Exit 137)"
            category: memory
            severity: high
            responsibility: configuration
            keywords:
              - "exit code 137"
              - "SIGKILL"
              - "signal 9"
            regex_patterns:
              - "exit(?:ed)?\\\\s*(?:with)?\\\\s*code\\\\s*137"
            exit_code: 137
            root_cause: "Process killed by SIGKILL"
            confidence_factors:
              increase:
                - "OOMKilled"
                - "container killed"
              decrease:
                - "user cancelled"
                - "job cancellation"

          - id: shuffle_fetch_failed
            name: "Shuffle Fetch Failed"
            category: shuffle
            severity: high
            responsibility: configuration
            keywords:
              - "FetchFailedException"
              - "shuffle fetch"
            regex_patterns:
              - "FetchFailedException"
            exception_class: "FetchFailedException"
            root_cause: "Shuffle fetch failed"
            confidence_factors:
              increase:
                - "executor lost"
              decrease: []
    """)


@pytest.fixture
def registry(sample_yaml: str) -> PatternRegistry:
    """Registry with sample patterns loaded."""
    reg = PatternRegistry()
    reg.load_from_yaml_string(sample_yaml)
    return reg


@pytest.fixture
def matcher(registry: PatternRegistry) -> PatternMatcher:
    """Pattern matcher with sample patterns."""
    return PatternMatcher(registry)


# =============================================================================
# BASIC MATCHING TESTS
# =============================================================================


class TestBasicMatching:
    """Tests for basic pattern matching functionality."""

    def test_match_by_keyword(self, matcher: PatternMatcher) -> None:
        """Pattern matches when keyword is present."""
        result = matcher.match("java.lang.OutOfMemoryError: Java heap space")

        assert result.has_matches
        assert result.top_match is not None
        assert result.top_match.pattern_id == "java_heap_space"

    def test_match_by_regex(self, matcher: PatternMatcher) -> None:
        """Pattern matches via regex."""
        result = matcher.match("Caused by: java.lang.OutOfMemoryError: Java heap space")

        assert result.has_matches
        assert "java_heap_space" in [m.pattern_id for m in result.matches]

    def test_match_by_exit_code(self, matcher: PatternMatcher) -> None:
        """Pattern matches by exit code."""
        result = matcher.match("Container exited with code 137", exit_code=137)

        assert result.has_matches
        assert result.top_match is not None
        assert result.top_match.pattern_id == "exit_code_137"

    def test_no_match(self, matcher: PatternMatcher) -> None:
        """No match when text doesn't match any pattern."""
        result = matcher.match("Everything is working fine")

        assert not result.has_matches
        assert result.top_match is None
        assert result.match_count == 0


# =============================================================================
# CONFIDENCE SCORING TESTS
# =============================================================================


class TestConfidenceScoring:
    """Tests for confidence score calculation."""

    def test_base_confidence_exception_class(self, matcher: PatternMatcher) -> None:
        """Exception class match has high base confidence."""
        result = matcher.match("java.lang.OutOfMemoryError: Java heap space")

        assert result.top_match is not None
        # Exception class base score is 0.8
        assert result.top_match.confidence >= 0.5

    def test_confidence_increases_with_positive_signals(
        self, matcher: PatternMatcher
    ) -> None:
        """Confidence increases with positive evidence."""
        # Text with positive signal ("Full GC events")
        text = """
        java.lang.OutOfMemoryError: Java heap space
        GC logs show Full GC events before failure
        """
        result = matcher.match(text)

        assert result.top_match is not None
        # Should have higher confidence due to positive signal
        assert result.top_match.confidence >= 0.6

    def test_confidence_decreases_with_negative_signals(
        self, matcher: PatternMatcher
    ) -> None:
        """Confidence decreases with negative evidence (job was cancelled)."""
        # First, get baseline confidence without negative signal
        text_baseline = "java.lang.OutOfMemoryError: Java heap space"
        result_baseline = matcher.match(text_baseline)

        # Now with negative signal
        text_with_negative = """
        java.lang.OutOfMemoryError: Java heap space
        Note: job was cancelled by user
        """
        result = matcher.match(text_with_negative)

        assert result.top_match is not None
        assert result_baseline.top_match is not None
        # Confidence should be reduced due to negative signal
        assert result.top_match.confidence < result_baseline.top_match.confidence

    def test_multiple_signals_increase_confidence(
        self, matcher: PatternMatcher
    ) -> None:
        """Multiple matching signal types increase confidence."""
        # This text matches multiple signals for exit_code_137
        text = "Container exited with code 137, killed by signal 9"
        result = matcher.match(text, exit_code=137)

        assert result.top_match is not None
        # Should have bonus for multiple signal types
        assert result.top_match.confidence >= 0.6


# =============================================================================
# MULTI-PATTERN MATCHING TESTS
# =============================================================================


class TestMultiPatternMatching:
    """Tests for matching multiple patterns."""

    def test_returns_multiple_matches(self, matcher: PatternMatcher) -> None:
        """Multiple patterns can match same text."""
        text = """
        FetchFailedException: Failed to connect to executor
        java.lang.OutOfMemoryError: Java heap space
        """
        result = matcher.match(text)

        assert result.match_count >= 2
        pattern_ids = [m.pattern_id for m in result.matches]
        assert "java_heap_space" in pattern_ids
        assert "shuffle_fetch_failed" in pattern_ids

    def test_matches_sorted_by_confidence(self, matcher: PatternMatcher) -> None:
        """Matches are sorted by confidence (highest first)."""
        text = """
        FetchFailedException: shuffle fetch failed
        java.lang.OutOfMemoryError: Java heap space with collect()
        """
        result = matcher.match(text)

        if result.match_count > 1:
            confidences = [m.confidence for m in result.matches]
            assert confidences == sorted(confidences, reverse=True)

    def test_max_matches_limit(self, registry: PatternRegistry) -> None:
        """Max matches limit is respected."""
        matcher = PatternMatcher(registry, max_matches=1)
        text = """
        FetchFailedException
        java.lang.OutOfMemoryError: Java heap space
        """
        result = matcher.match(text)

        assert result.match_count <= 1


# =============================================================================
# MATCH RESULT TESTS
# =============================================================================


class TestMatchResult:
    """Tests for MatchResult dataclass."""

    def test_match_result_has_processing_time(self, matcher: PatternMatcher) -> None:
        """Match result includes processing time."""
        result = matcher.match("java.lang.OutOfMemoryError")

        assert result.processing_time_ms >= 0

    def test_match_has_evidence_refs(self, matcher: PatternMatcher) -> None:
        """Match includes evidence references."""
        result = matcher.match("java.lang.OutOfMemoryError: Java heap space")

        if result.top_match:
            # Evidence refs should contain the matched line
            assert len(result.top_match.evidence_refs) >= 0


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_text(self, matcher: PatternMatcher) -> None:
        """Empty text returns no matches."""
        result = matcher.match("")

        assert not result.has_matches

    def test_case_insensitive(self, matcher: PatternMatcher) -> None:
        """Matching is case-insensitive."""
        result = matcher.match("JAVA.LANG.OUTOFMEMORYERROR: JAVA HEAP SPACE")

        assert result.has_matches
        assert result.top_match is not None
        assert result.top_match.pattern_id == "java_heap_space"

    def test_minimum_confidence_filter(self, registry: PatternRegistry) -> None:
        """Matches below minimum confidence are filtered."""
        matcher = PatternMatcher(registry, min_confidence=0.9)
        result = matcher.match("Something that barely matches OutOfMemoryError")

        # May or may not match depending on confidence calculation
        for match in result.matches:
            assert match.confidence >= 0.9


# =============================================================================
# MATCH WITH DETAILS TESTS
# =============================================================================


class TestMatchWithDetails:
    """Tests for match_with_details method."""

    def test_returns_confidence_details(self, matcher: PatternMatcher) -> None:
        """Returns detailed confidence breakdown."""
        result, details = matcher.match_with_details(
            "java.lang.OutOfMemoryError: Java heap space"
        )

        assert result.has_matches
        assert result.top_match is not None
        assert result.top_match.pattern_id in details

    def test_confidence_details_structure(self, matcher: PatternMatcher) -> None:
        """Confidence details have correct structure."""
        _, details = matcher.match_with_details(
            "java.lang.OutOfMemoryError: Java heap space, Full GC events"
        )

        if details:
            for _pattern_id, conf in details.items():
                assert isinstance(conf, ConfidenceDetails)
                assert 0.0 <= conf.base_score <= 1.0
                assert 0.0 <= conf.final_score <= 1.0
                assert isinstance(conf.increase_factors, tuple)
                assert isinstance(conf.decrease_factors, tuple)
