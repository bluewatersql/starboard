# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
SQLAnalyzer - Detects SQL anti-patterns and performance issues.

Analyzes SQL queries for common anti-patterns that can cause performance
problems in Spark SQL / Databricks environments:

- Missing LIMIT clauses on SELECT queries
- SELECT * usage (column explosion)
- Cartesian joins (CROSS JOIN or comma joins without WHERE)
- Date/string comparison issues
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class SQLAntiPatternType(StrEnum):
    """Types of SQL anti-patterns."""

    MISSING_LIMIT = "missing_limit"
    SELECT_STAR = "select_star"
    CARTESIAN_JOIN = "cartesian_join"
    DATE_STRING_COMPARISON = "date_string_comparison"


@dataclass(frozen=True)
class SQLAntiPattern:
    """A detected SQL anti-pattern.

    Attributes:
        pattern_type: The type of anti-pattern detected.
        description: Human-readable description of the issue.
        severity: How severe the issue is (low, medium, high, critical).
        recommendation: Suggested fix for the issue.
        line_hint: Optional line number or position hint.
    """

    pattern_type: SQLAntiPatternType
    description: str
    severity: Literal["low", "medium", "high", "critical"]
    recommendation: str
    line_hint: int | None = None


@dataclass
class SQLAnalysisResult:
    """Result of SQL analysis.

    Attributes:
        patterns: List of detected anti-patterns.
        original_sql: The original SQL that was analyzed.
    """

    patterns: list[SQLAntiPattern] = field(default_factory=list)
    original_sql: str = ""

    @property
    def has_issues(self) -> bool:
        """Whether any issues were detected."""
        return len(self.patterns) > 0

    @property
    def pattern_count(self) -> int:
        """Number of patterns detected."""
        return len(self.patterns)

    @property
    def summary(self) -> str:
        """Generate a summary of detected issues."""
        if not self.patterns:
            return "No SQL anti-patterns detected."

        issues = [p.description for p in self.patterns]
        return f"Detected {len(issues)} issue(s): " + "; ".join(issues)


class SQLAnalyzer:
    """Analyzes SQL queries for anti-patterns.

    This analyzer uses regex-based pattern matching to detect common
    SQL anti-patterns. It's designed for quick, heuristic-based analysis
    rather than full SQL parsing.
    """

    # Patterns for detection
    _SELECT_STAR_PATTERN = re.compile(
        r"\bSELECT\s+(?:\w+\.)?\*(?!\s*\))",  # SELECT * but not COUNT(*)
        re.IGNORECASE,
    )

    _COUNT_STAR_PATTERN = re.compile(
        r"\bCOUNT\s*\(\s*\*\s*\)",
        re.IGNORECASE,
    )

    _LIMIT_PATTERN = re.compile(
        r"\bLIMIT\s+\d+",
        re.IGNORECASE,
    )

    _TOP_PATTERN = re.compile(
        r"\bSELECT\s+TOP\s+\d+",
        re.IGNORECASE,
    )

    _CROSS_JOIN_PATTERN = re.compile(
        r"\bCROSS\s+JOIN\b",
        re.IGNORECASE,
    )

    _COMMA_JOIN_PATTERN = re.compile(
        r"\bFROM\s+(\w+)(?:\s+\w+)?\s*,\s*(\w+)",
        re.IGNORECASE,
    )

    _WHERE_CLAUSE_PATTERN = re.compile(
        r"\bWHERE\b",
        re.IGNORECASE,
    )

    _AGGREGATE_PATTERN = re.compile(
        r"\b(?:COUNT|SUM|AVG|MIN|MAX|GROUP\s+BY)\b",
        re.IGNORECASE,
    )

    _INSERT_PATTERN = re.compile(
        r"\bINSERT\s+INTO\b",
        re.IGNORECASE,
    )

    _CREATE_TABLE_AS_PATTERN = re.compile(
        r"\bCREATE\s+TABLE\s+\w+\s+AS\b",
        re.IGNORECASE,
    )

    _DATE_STRING_PATTERN = re.compile(
        r"(?:_date|date_|created|updated|timestamp)\w*\s*[><=!]+\s*'(\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    )

    _DATE_FUNCTION_PATTERN = re.compile(
        r"\b(?:DATE|TIMESTAMP|TO_DATE|TO_TIMESTAMP)\s*\(",
        re.IGNORECASE,
    )

    _EXPLICIT_JOIN_PATTERN = re.compile(
        r"\b(?:INNER|LEFT|RIGHT|FULL|OUTER)\s+JOIN\b",
        re.IGNORECASE,
    )

    def analyze(self, sql: str) -> SQLAnalysisResult:
        """Analyze SQL for anti-patterns.

        Args:
            sql: The SQL query to analyze.

        Returns:
            SQLAnalysisResult with detected patterns.
        """
        result = SQLAnalysisResult(original_sql=sql)

        # Handle empty/whitespace SQL
        if not sql or not sql.strip():
            return result

        # Normalize SQL for analysis
        sql_normalized = " ".join(sql.split())

        # Check each anti-pattern
        self._check_select_star(sql_normalized, result)
        self._check_missing_limit(sql_normalized, result)
        self._check_cartesian_join(sql_normalized, result)
        self._check_date_string_comparison(sql_normalized, result)

        return result

    def _check_select_star(self, sql: str, result: SQLAnalysisResult) -> None:
        """Check for SELECT * usage."""
        # Skip if it's just COUNT(*)
        sql_without_count = self._COUNT_STAR_PATTERN.sub("COUNT(1)", sql)

        if self._SELECT_STAR_PATTERN.search(sql_without_count):
            result.patterns.append(
                SQLAntiPattern(
                    pattern_type=SQLAntiPatternType.SELECT_STAR,
                    description="SELECT * retrieves all columns, which can cause memory issues with wide tables",
                    severity="medium",
                    recommendation="Specify only the columns you need: SELECT col1, col2, ... FROM table",
                )
            )

    def _check_missing_limit(self, sql: str, result: SQLAnalysisResult) -> None:
        """Check for missing LIMIT clause."""
        # Skip non-SELECT queries
        if not re.search(r"\bSELECT\b", sql, re.IGNORECASE):
            return

        # Skip if it's INSERT...SELECT or CREATE TABLE AS
        if self._INSERT_PATTERN.search(sql) or self._CREATE_TABLE_AS_PATTERN.search(
            sql
        ):
            return

        # Skip aggregate queries (they return limited rows)
        if self._AGGREGATE_PATTERN.search(sql):
            return

        # Check if LIMIT or TOP is present
        if self._LIMIT_PATTERN.search(sql) or self._TOP_PATTERN.search(sql):
            return

        result.patterns.append(
            SQLAntiPattern(
                pattern_type=SQLAntiPatternType.MISSING_LIMIT,
                description="Query lacks LIMIT clause, which can return unbounded rows",
                severity="medium",
                recommendation="Add LIMIT clause to prevent returning too many rows: SELECT ... LIMIT 1000",
            )
        )

    def _check_cartesian_join(self, sql: str, result: SQLAnalysisResult) -> None:
        """Check for Cartesian join patterns."""
        # Explicit CROSS JOIN
        if self._CROSS_JOIN_PATTERN.search(sql):
            result.patterns.append(
                SQLAntiPattern(
                    pattern_type=SQLAntiPatternType.CARTESIAN_JOIN,
                    description="CROSS JOIN creates Cartesian product, can explode row count",
                    severity="high",
                    recommendation="Use INNER/LEFT JOIN with ON clause if you need to join tables",
                )
            )
            return

        # Check for comma join without WHERE (implicit Cartesian)
        if self._COMMA_JOIN_PATTERN.search(
            sql
        ) and not self._WHERE_CLAUSE_PATTERN.search(sql):
            result.patterns.append(
                SQLAntiPattern(
                    pattern_type=SQLAntiPatternType.CARTESIAN_JOIN,
                    description="Comma-separated tables without WHERE creates Cartesian product",
                    severity="high",
                    recommendation="Add WHERE clause with join condition, or use explicit JOIN...ON syntax",
                )
            )

    def _check_date_string_comparison(
        self, sql: str, result: SQLAnalysisResult
    ) -> None:
        """Check for date/string comparison issues."""
        # Look for date column compared to string literal without DATE function
        if self._DATE_STRING_PATTERN.search(
            sql
        ) and not self._DATE_FUNCTION_PATTERN.search(sql):
            result.patterns.append(
                SQLAntiPattern(
                    pattern_type=SQLAntiPatternType.DATE_STRING_COMPARISON,
                    description="Comparing date column to string literal may cause implicit conversion issues",
                    severity="low",
                    recommendation="Use DATE() or TO_DATE() function: WHERE date_col > DATE('2024-01-01')",
                )
            )
