# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Unit tests for SQLAnalyzer - detects SQL anti-patterns and issues.

Tests cover:
- Missing LIMIT detection
- SELECT * detection
- Cartesian join detection
- Date comparison issues
- Multiple anti-patterns in same query
"""

from __future__ import annotations

from textwrap import dedent

import pytest
from starboard_server.tools.domain.diagnostic.sql_analyzer import (
    SQLAnalysisResult,
    SQLAnalyzer,
    SQLAntiPatternType,
)


@pytest.fixture
def analyzer() -> SQLAnalyzer:
    """Create SQLAnalyzer instance."""
    return SQLAnalyzer()


# =============================================================================
# MISSING LIMIT DETECTION
# =============================================================================


class TestMissingLimitDetection:
    """Tests for detecting missing LIMIT clauses."""

    def test_select_without_limit(self, analyzer: SQLAnalyzer) -> None:
        """Detect SELECT without LIMIT."""
        sql = "SELECT id, name FROM users"
        result = analyzer.analyze(sql)

        assert result.has_issues
        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.MISSING_LIMIT
        ]
        assert len(patterns) == 1
        assert "LIMIT" in patterns[0].description

    def test_select_with_limit_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """SELECT with LIMIT should not flag missing limit."""
        sql = "SELECT id, name FROM users LIMIT 100"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.MISSING_LIMIT
        ]
        assert len(patterns) == 0

    def test_select_with_top_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """SELECT TOP should not flag missing limit."""
        sql = "SELECT TOP 100 id, name FROM users"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.MISSING_LIMIT
        ]
        assert len(patterns) == 0

    def test_count_query_no_limit_needed(self, analyzer: SQLAnalyzer) -> None:
        """COUNT queries don't need LIMIT."""
        sql = "SELECT COUNT(*) FROM users"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.MISSING_LIMIT
        ]
        assert len(patterns) == 0

    def test_aggregate_query_no_limit_needed(self, analyzer: SQLAnalyzer) -> None:
        """Aggregate queries (SUM, AVG, etc.) don't need LIMIT."""
        sql = "SELECT department, SUM(salary) FROM employees GROUP BY department"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.MISSING_LIMIT
        ]
        assert len(patterns) == 0

    def test_insert_select_no_limit_warning(self, analyzer: SQLAnalyzer) -> None:
        """INSERT...SELECT typically doesn't need LIMIT warning."""
        sql = "INSERT INTO archive SELECT * FROM orders WHERE year < 2020"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.MISSING_LIMIT
        ]
        assert len(patterns) == 0

    def test_ctas_no_limit_warning(self, analyzer: SQLAnalyzer) -> None:
        """CREATE TABLE AS SELECT doesn't need LIMIT warning."""
        sql = "CREATE TABLE summary AS SELECT * FROM large_table"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.MISSING_LIMIT
        ]
        assert len(patterns) == 0


# =============================================================================
# SELECT STAR DETECTION
# =============================================================================


class TestSelectStarDetection:
    """Tests for detecting SELECT * usage."""

    def test_select_star(self, analyzer: SQLAnalyzer) -> None:
        """Detect SELECT *."""
        sql = "SELECT * FROM users"
        result = analyzer.analyze(sql)

        assert result.has_issues
        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.SELECT_STAR
        ]
        assert len(patterns) == 1
        assert "SELECT *" in patterns[0].description

    def test_select_star_with_alias(self, analyzer: SQLAnalyzer) -> None:
        """Detect SELECT t.* with alias."""
        sql = "SELECT t.* FROM users t"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.SELECT_STAR
        ]
        assert len(patterns) == 1

    def test_select_columns_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """Explicit column selection should not flag."""
        sql = "SELECT id, name, email FROM users"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.SELECT_STAR
        ]
        assert len(patterns) == 0

    def test_count_star_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """COUNT(*) is not SELECT * anti-pattern."""
        sql = "SELECT COUNT(*) FROM users"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.SELECT_STAR
        ]
        assert len(patterns) == 0

    def test_select_star_in_subquery(self, analyzer: SQLAnalyzer) -> None:
        """Detect SELECT * in subquery."""
        sql = "SELECT id FROM (SELECT * FROM users) sub"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.SELECT_STAR
        ]
        assert len(patterns) == 1


# =============================================================================
# CARTESIAN JOIN DETECTION
# =============================================================================


class TestCartesianJoinDetection:
    """Tests for detecting Cartesian joins."""

    def test_cross_join(self, analyzer: SQLAnalyzer) -> None:
        """Detect CROSS JOIN."""
        sql = "SELECT * FROM users CROSS JOIN orders"
        result = analyzer.analyze(sql)

        assert result.has_issues
        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.CARTESIAN_JOIN
        ]
        assert len(patterns) == 1

    def test_comma_join_no_where(self, analyzer: SQLAnalyzer) -> None:
        """Detect comma join without WHERE clause (implicit cross join)."""
        sql = "SELECT * FROM users, orders"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.CARTESIAN_JOIN
        ]
        assert len(patterns) == 1

    def test_comma_join_with_where_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """Comma join with WHERE is not flagged as cartesian."""
        sql = "SELECT * FROM users u, orders o WHERE u.id = o.user_id"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.CARTESIAN_JOIN
        ]
        assert len(patterns) == 0

    def test_inner_join_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """Proper INNER JOIN is not flagged."""
        sql = "SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.CARTESIAN_JOIN
        ]
        assert len(patterns) == 0

    def test_left_join_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """LEFT JOIN is not flagged."""
        sql = "SELECT * FROM users u LEFT JOIN orders o ON u.id = o.user_id"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.CARTESIAN_JOIN
        ]
        assert len(patterns) == 0


# =============================================================================
# DATE COMPARISON ISSUES
# =============================================================================


class TestDateComparisonIssues:
    """Tests for detecting date comparison issues."""

    def test_string_date_comparison(self, analyzer: SQLAnalyzer) -> None:
        """Detect string-to-date comparison."""
        sql = "SELECT * FROM orders WHERE order_date > '2024-01-01'"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.DATE_STRING_COMPARISON
        ]
        assert len(patterns) == 1
        assert "date" in patterns[0].description.lower()

    def test_date_function_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """Using DATE() function is acceptable."""
        sql = "SELECT * FROM orders WHERE order_date > DATE('2024-01-01')"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.DATE_STRING_COMPARISON
        ]
        assert len(patterns) == 0

    def test_timestamp_function_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """Using TIMESTAMP() function is acceptable."""
        sql = "SELECT * FROM logs WHERE created_at > TIMESTAMP('2024-01-01 00:00:00')"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.DATE_STRING_COMPARISON
        ]
        assert len(patterns) == 0

    def test_to_date_function_is_ok(self, analyzer: SQLAnalyzer) -> None:
        """Using TO_DATE() function is acceptable."""
        sql = "SELECT * FROM orders WHERE order_date > TO_DATE('2024-01-01', 'yyyy-MM-dd')"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.DATE_STRING_COMPARISON
        ]
        assert len(patterns) == 0


# =============================================================================
# MULTIPLE ANTI-PATTERNS
# =============================================================================


class TestMultipleAntiPatterns:
    """Tests for detecting multiple anti-patterns."""

    def test_select_star_and_no_limit(self, analyzer: SQLAnalyzer) -> None:
        """Detect both SELECT * and missing LIMIT."""
        sql = "SELECT * FROM users"
        result = analyzer.analyze(sql)

        assert result.has_issues
        pattern_types = {p.pattern_type for p in result.patterns}
        assert SQLAntiPatternType.SELECT_STAR in pattern_types
        assert SQLAntiPatternType.MISSING_LIMIT in pattern_types

    def test_complex_query_multiple_issues(self, analyzer: SQLAnalyzer) -> None:
        """Detect multiple issues in complex query."""
        sql = dedent("""
            SELECT *
            FROM users, orders
            WHERE created_date > '2024-01-01'
        """)
        result = analyzer.analyze(sql)

        assert result.has_issues
        # Should detect SELECT *, cartesian join risk, and date string comparison
        assert result.pattern_count >= 2


# =============================================================================
# RESULT STRUCTURE
# =============================================================================


class TestResultStructure:
    """Tests for analysis result structure."""

    def test_clean_query_result(self, analyzer: SQLAnalyzer) -> None:
        """Clean query should have no issues."""
        sql = "SELECT id, name FROM users WHERE active = true LIMIT 100"
        result = analyzer.analyze(sql)

        assert not result.has_issues
        assert result.pattern_count == 0
        assert len(result.patterns) == 0

    def test_pattern_has_severity(self, analyzer: SQLAnalyzer) -> None:
        """Each pattern should have a severity."""
        sql = "SELECT * FROM users"
        result = analyzer.analyze(sql)

        for pattern in result.patterns:
            assert pattern.severity in ("low", "medium", "high", "critical")

    def test_pattern_has_recommendation(self, analyzer: SQLAnalyzer) -> None:
        """Each pattern should have a recommendation."""
        sql = "SELECT * FROM users"
        result = analyzer.analyze(sql)

        for pattern in result.patterns:
            assert pattern.recommendation
            assert len(pattern.recommendation) > 0

    def test_result_summary(self, analyzer: SQLAnalyzer) -> None:
        """Result should provide a summary."""
        sql = "SELECT * FROM users CROSS JOIN orders"
        result = analyzer.analyze(sql)

        assert result.summary
        assert len(result.summary) > 0


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_sql(self, analyzer: SQLAnalyzer) -> None:
        """Empty SQL should not crash."""
        result = analyzer.analyze("")
        assert not result.has_issues

    def test_whitespace_only(self, analyzer: SQLAnalyzer) -> None:
        """Whitespace-only SQL should not crash."""
        result = analyzer.analyze("   \n\t  ")
        assert not result.has_issues

    def test_comment_only(self, analyzer: SQLAnalyzer) -> None:
        """Comment-only SQL should not crash."""
        result = analyzer.analyze("-- just a comment")
        assert not result.has_issues

    def test_malformed_sql(self, analyzer: SQLAnalyzer) -> None:
        """Malformed SQL should not crash."""
        result = analyzer.analyze("SELECT FROM WHERE")
        # Should not crash, may or may not detect issues
        assert isinstance(result, SQLAnalysisResult)

    def test_multiline_sql(self, analyzer: SQLAnalyzer) -> None:
        """Multi-line SQL should be handled."""
        sql = dedent("""
            SELECT
                id,
                name
            FROM
                users
            WHERE
                active = true
            LIMIT 100
        """)
        result = analyzer.analyze(sql)

        # This is a clean query with explicit columns and LIMIT
        assert not result.has_issues

    def test_case_insensitivity(self, analyzer: SQLAnalyzer) -> None:
        """Detection should be case-insensitive."""
        sql = "select * from USERS"
        result = analyzer.analyze(sql)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == SQLAntiPatternType.SELECT_STAR
        ]
        assert len(patterns) == 1
