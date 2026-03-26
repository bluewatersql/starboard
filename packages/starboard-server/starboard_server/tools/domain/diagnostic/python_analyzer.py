# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
PythonAnalyzer - Detects Python/PySpark anti-patterns.

Analyzes Python code for common anti-patterns that can cause performance
problems in PySpark / Databricks environments:

- collect() on potentially large DataFrames
- toPandas() on large DataFrames
- Non-vectorized Python UDFs (use pandas_udf instead)
- Inefficient loops over DataFrame rows
- Broadcast usage patterns
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class PythonAntiPatternType(StrEnum):
    """Types of Python/PySpark anti-patterns."""

    COLLECT_LARGE_DF = "collect_large_df"
    TO_PANDAS_LARGE_DF = "to_pandas_large_df"
    SCALAR_UDF = "scalar_udf"
    LOOP_OVER_ROWS = "loop_over_rows"
    BROADCAST_USAGE = "broadcast_usage"


@dataclass(frozen=True)
class PythonAntiPattern:
    """A detected Python anti-pattern.

    Attributes:
        pattern_type: The type of anti-pattern detected.
        description: Human-readable description of the issue.
        severity: How severe the issue is (low, medium, high, critical).
        recommendation: Suggested fix for the issue.
        line_hint: Optional line number or position hint.
    """

    pattern_type: PythonAntiPatternType
    description: str
    severity: Literal["low", "medium", "high", "critical"]
    recommendation: str
    line_hint: int | None = None


@dataclass
class PythonAnalysisResult:
    """Result of Python code analysis.

    Attributes:
        patterns: List of detected anti-patterns.
        original_code: The original code that was analyzed.
    """

    patterns: list[PythonAntiPattern] = field(default_factory=list)
    original_code: str = ""

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
            return "No Python anti-patterns detected."

        issues = [p.description for p in self.patterns]
        return f"Detected {len(issues)} issue(s): " + "; ".join(issues)


class PythonAnalyzer:
    """Analyzes Python/PySpark code for anti-patterns.

    This analyzer uses regex-based pattern matching to detect common
    PySpark anti-patterns. It's designed for quick, heuristic-based analysis
    rather than full AST parsing.
    """

    # Patterns for detection
    _COLLECT_PATTERN = re.compile(
        r"\.collect\(\s*\)",
    )

    _LIMIT_BEFORE_COLLECT = re.compile(
        r"\.limit\s*\(\s*\d+\s*\)",
    )

    _TAKE_PATTERN = re.compile(
        r"\.take\s*\(\s*\d+\s*\)",
    )

    _TOPANDAS_PATTERN = re.compile(
        r"\.toPandas\(\s*\)",
    )

    # Note: We just check for limit() presence; _LIMIT_BEFORE_COLLECT handles this

    _SCALAR_UDF_DECORATOR = re.compile(
        r"@udf\s*\(",
    )

    _UDF_FUNCTION = re.compile(
        r"\budf\s*\([^)]*\)",
    )

    _PANDAS_UDF = re.compile(
        r"@?pandas_udf\s*\(",
    )

    _ARROW_UDF = re.compile(
        r"useArrow\s*=\s*True",
    )

    _ITERROWS_PATTERN = re.compile(
        r"\.iterrows\(\s*\)",
    )

    _ITERTUPLES_PATTERN = re.compile(
        r"\.itertuples\(\s*\)",
    )

    _FOR_LOOP_COLLECT = re.compile(
        r"for\s+\w+\s+in\s+\w*\.?collect\(\)",
    )

    _BROADCAST_PATTERN = re.compile(
        r"\bbroadcast\s*\(",
    )

    def analyze(self, code: str) -> PythonAnalysisResult:
        """Analyze Python code for anti-patterns.

        Args:
            code: The Python code to analyze.

        Returns:
            PythonAnalysisResult with detected patterns.
        """
        result = PythonAnalysisResult(original_code=code)

        # Handle empty/whitespace code
        if not code or not code.strip():
            return result

        # Normalize code for analysis (preserve newlines for context)
        code_normalized = code

        # Check each anti-pattern
        self._check_collect(code_normalized, result)
        self._check_topandas(code_normalized, result)
        self._check_scalar_udf(code_normalized, result)
        self._check_loop_over_rows(code_normalized, result)

        return result

    def _check_collect(self, code: str, result: PythonAnalysisResult) -> None:
        """Check for collect() usage on potentially large DataFrames."""
        # Skip if there's no collect()
        if not self._COLLECT_PATTERN.search(code):
            return

        # Check if limit() appears anywhere in the code (heuristic: if limit is used,
        # the collect is likely bounded, especially in simple scripts)
        if self._LIMIT_BEFORE_COLLECT.search(code):
            # Bounded collect is ok or low severity
            return

        # Also check if take() is used (alternative to collect)
        # take() is already bounded, so no issue

        result.patterns.append(
            PythonAntiPattern(
                pattern_type=PythonAntiPatternType.COLLECT_LARGE_DF,
                description="collect() brings all data to driver memory, can cause OOM",
                severity="high",
                recommendation="Use .limit(n).collect() or write to storage instead: df.write.parquet('/path')",
            )
        )

    def _check_topandas(self, code: str, result: PythonAnalysisResult) -> None:
        """Check for toPandas() usage on potentially large DataFrames."""
        # Skip if there's no toPandas()
        if not self._TOPANDAS_PATTERN.search(code):
            return

        # Check if limit() appears anywhere (heuristic for bounded data)
        if self._LIMIT_BEFORE_COLLECT.search(code):
            # Bounded toPandas is ok
            return

        result.patterns.append(
            PythonAntiPattern(
                pattern_type=PythonAntiPatternType.TO_PANDAS_LARGE_DF,
                description="toPandas() brings all data to driver memory as Pandas DataFrame",
                severity="high",
                recommendation="Use .limit(n).toPandas() or use pandas_udf for distributed processing",
            )
        )

    def _check_scalar_udf(self, code: str, result: PythonAnalysisResult) -> None:
        """Check for non-vectorized Python UDFs."""
        # Skip if pandas_udf or Arrow UDF is used
        if self._PANDAS_UDF.search(code) or self._ARROW_UDF.search(code):
            return

        # Check for @udf decorator or udf() function
        has_udf = self._SCALAR_UDF_DECORATOR.search(code) or self._UDF_FUNCTION.search(
            code
        )

        if has_udf:
            result.patterns.append(
                PythonAntiPattern(
                    pattern_type=PythonAntiPatternType.SCALAR_UDF,
                    description="Scalar Python UDF processes one row at a time, causing serialization overhead",
                    severity="medium",
                    recommendation="Use @pandas_udf for vectorized processing: @pandas_udf(StringType())",
                )
            )

    def _check_loop_over_rows(self, code: str, result: PythonAnalysisResult) -> None:
        """Check for inefficient loops over DataFrame rows."""
        # Check for iterrows() usage
        if self._ITERROWS_PATTERN.search(code):
            result.patterns.append(
                PythonAntiPattern(
                    pattern_type=PythonAntiPatternType.LOOP_OVER_ROWS,
                    description="iterrows() is slow; iterates one row at a time with Python overhead",
                    severity="medium",
                    recommendation="Use vectorized Pandas operations or itertuples() for better performance",
                )
            )

        # Check for "for row in df.collect()"
        if self._FOR_LOOP_COLLECT.search(code):
            result.patterns.append(
                PythonAntiPattern(
                    pattern_type=PythonAntiPatternType.LOOP_OVER_ROWS,
                    description="Looping over collect() results processes data in Python, losing parallelism",
                    severity="high",
                    recommendation="Use DataFrame operations like .foreach() or .foreachPartition() for distributed processing",
                )
            )
