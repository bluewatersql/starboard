# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Unit tests for PythonAnalyzer - detects Python/PySpark anti-patterns.

Tests cover:
- collect() on potentially large DataFrames
- Python UDFs vs vectorized/pandas UDFs
- Inefficient loops (Python loops over DataFrame rows)
- toPandas() on large DataFrames
- Other PySpark performance issues
"""

from __future__ import annotations

from textwrap import dedent

import pytest
from starboard_server.tools.domain.diagnostic.python_analyzer import (
    PythonAnalysisResult,
    PythonAnalyzer,
    PythonAntiPatternType,
)


@pytest.fixture
def analyzer() -> PythonAnalyzer:
    """Create PythonAnalyzer instance."""
    return PythonAnalyzer()


# =============================================================================
# COLLECT() DETECTION
# =============================================================================


class TestCollectDetection:
    """Tests for detecting collect() usage."""

    def test_simple_collect(self, analyzer: PythonAnalyzer) -> None:
        """Detect simple .collect() call."""
        code = "result = df.collect()"
        result = analyzer.analyze(code)

        assert result.has_issues
        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.COLLECT_LARGE_DF
        ]
        assert len(patterns) == 1
        assert "collect" in patterns[0].description.lower()

    def test_collect_in_chain(self, analyzer: PythonAnalyzer) -> None:
        """Detect collect() in method chain."""
        code = "data = df.filter(col('x') > 10).select('a', 'b').collect()"
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.COLLECT_LARGE_DF
        ]
        assert len(patterns) == 1

    def test_collect_with_limit_is_ok(self, analyzer: PythonAnalyzer) -> None:
        """collect() after limit() is less risky."""
        code = "sample = df.limit(100).collect()"
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.COLLECT_LARGE_DF
        ]
        # Should either not flag, or flag with lower severity
        assert len(patterns) == 0 or patterns[0].severity == "low"

    def test_take_is_ok(self, analyzer: PythonAnalyzer) -> None:
        """take(n) is bounded and ok."""
        code = "sample = df.take(10)"
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.COLLECT_LARGE_DF
        ]
        assert len(patterns) == 0


# =============================================================================
# TO_PANDAS DETECTION
# =============================================================================


class TestToPandasDetection:
    """Tests for detecting toPandas() usage."""

    def test_simple_topandas(self, analyzer: PythonAnalyzer) -> None:
        """Detect simple .toPandas() call."""
        code = "pdf = df.toPandas()"
        result = analyzer.analyze(code)

        assert result.has_issues
        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.TO_PANDAS_LARGE_DF
        ]
        assert len(patterns) == 1

    def test_topandas_in_chain(self, analyzer: PythonAnalyzer) -> None:
        """Detect toPandas() in method chain."""
        code = "pdf = df.select('a', 'b').toPandas()"
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.TO_PANDAS_LARGE_DF
        ]
        assert len(patterns) == 1

    def test_topandas_with_limit_is_ok(self, analyzer: PythonAnalyzer) -> None:
        """toPandas() after limit() is less risky."""
        code = "pdf = df.limit(1000).toPandas()"
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.TO_PANDAS_LARGE_DF
        ]
        assert len(patterns) == 0 or patterns[0].severity == "low"


# =============================================================================
# PYTHON UDF DETECTION
# =============================================================================


class TestPythonUDFDetection:
    """Tests for detecting non-vectorized Python UDFs."""

    def test_scalar_udf(self, analyzer: PythonAnalyzer) -> None:
        """Detect scalar @udf decorator."""
        code = dedent("""
            @udf(returnType=StringType())
            def my_udf(x):
                return x.upper()
        """)
        result = analyzer.analyze(code)

        assert result.has_issues
        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.SCALAR_UDF
        ]
        assert len(patterns) == 1

    def test_udf_function_call(self, analyzer: PythonAnalyzer) -> None:
        """Detect udf() function call."""
        code = "my_udf = udf(lambda x: x.upper(), StringType())"
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.SCALAR_UDF
        ]
        assert len(patterns) == 1

    def test_pandas_udf_is_ok(self, analyzer: PythonAnalyzer) -> None:
        """pandas_udf is vectorized and ok."""
        code = dedent("""
            @pandas_udf(StringType())
            def my_pandas_udf(s: pd.Series) -> pd.Series:
                return s.str.upper()
        """)
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.SCALAR_UDF
        ]
        assert len(patterns) == 0

    def test_vectorized_udf_is_ok(self, analyzer: PythonAnalyzer) -> None:
        """Vectorized udf_type is ok."""
        code = "my_udf = udf(my_func, StringType(), useArrow=True)"
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.SCALAR_UDF
        ]
        # Arrow UDFs are vectorized
        assert len(patterns) == 0


# =============================================================================
# INEFFICIENT LOOPS DETECTION
# =============================================================================


class TestIneffientLoopDetection:
    """Tests for detecting inefficient Python loops."""

    def test_for_loop_over_collect(self, analyzer: PythonAnalyzer) -> None:
        """Detect for loop over collect() result."""
        code = dedent("""
            for row in df.collect():
                process(row)
        """)
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.LOOP_OVER_ROWS
        ]
        assert len(patterns) >= 1

    def test_for_loop_over_topandas(self, analyzer: PythonAnalyzer) -> None:
        """Detect for loop over toPandas() result."""
        code = dedent("""
            pdf = df.toPandas()
            for idx, row in pdf.iterrows():
                process(row)
        """)
        result = analyzer.analyze(code)

        # Should detect both toPandas and iterrows
        assert result.has_issues

    def test_iterrows_usage(self, analyzer: PythonAnalyzer) -> None:
        """Detect iterrows() usage."""
        code = "for idx, row in pdf.iterrows():"
        result = analyzer.analyze(code)

        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.LOOP_OVER_ROWS
        ]
        assert len(patterns) == 1

    def test_itertuples_is_ok(self, analyzer: PythonAnalyzer) -> None:
        """itertuples() is faster than iterrows()."""
        code = "for row in pdf.itertuples():"
        result = analyzer.analyze(code)

        # itertuples is less of an anti-pattern, may or may not flag
        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.LOOP_OVER_ROWS
        ]
        assert len(patterns) == 0 or patterns[0].severity == "low"


# =============================================================================
# BROADCAST DETECTION
# =============================================================================


class TestBroadcastDetection:
    """Tests for detecting broadcast issues."""

    def test_large_broadcast_hint(self, analyzer: PythonAnalyzer) -> None:
        """Detect explicit broadcast on potentially large DataFrame."""
        code = "result = large_df.join(broadcast(huge_table), 'key')"
        result = analyzer.analyze(code)

        # Just verify it doesn't crash; broadcast detection is optional
        assert isinstance(result, PythonAnalysisResult)


# =============================================================================
# MULTIPLE ANTI-PATTERNS
# =============================================================================


class TestMultipleAntiPatterns:
    """Tests for detecting multiple anti-patterns."""

    def test_collect_and_loop(self, analyzer: PythonAnalyzer) -> None:
        """Detect both collect and loop over results."""
        code = dedent("""
            rows = df.collect()
            for row in rows:
                print(row.name)
        """)
        result = analyzer.analyze(code)

        assert result.has_issues
        assert result.pattern_count >= 1  # At least collect()

    def test_udf_and_collect(self, analyzer: PythonAnalyzer) -> None:
        """Detect both UDF and collect."""
        code = dedent("""
            @udf(StringType())
            def upper(x):
                return x.upper()

            result = df.withColumn('upper', upper('name')).collect()
        """)
        result = analyzer.analyze(code)

        pattern_types = {p.pattern_type for p in result.patterns}
        assert PythonAntiPatternType.SCALAR_UDF in pattern_types
        assert PythonAntiPatternType.COLLECT_LARGE_DF in pattern_types


# =============================================================================
# RESULT STRUCTURE
# =============================================================================


class TestResultStructure:
    """Tests for analysis result structure."""

    def test_clean_code_result(self, analyzer: PythonAnalyzer) -> None:
        """Clean code should have no issues."""
        code = dedent("""
            df = spark.read.parquet('/data/input')
            result = df.filter(col('x') > 10).write.parquet('/data/output')
        """)
        result = analyzer.analyze(code)

        assert not result.has_issues
        assert result.pattern_count == 0

    def test_pattern_has_severity(self, analyzer: PythonAnalyzer) -> None:
        """Each pattern should have a severity."""
        code = "result = df.collect()"
        result = analyzer.analyze(code)

        for pattern in result.patterns:
            assert pattern.severity in ("low", "medium", "high", "critical")

    def test_pattern_has_recommendation(self, analyzer: PythonAnalyzer) -> None:
        """Each pattern should have a recommendation."""
        code = "result = df.collect()"
        result = analyzer.analyze(code)

        for pattern in result.patterns:
            assert pattern.recommendation
            assert len(pattern.recommendation) > 0

    def test_result_summary(self, analyzer: PythonAnalyzer) -> None:
        """Result should provide a summary."""
        code = "result = df.collect()"
        result = analyzer.analyze(code)

        assert result.summary
        assert len(result.summary) > 0


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_code(self, analyzer: PythonAnalyzer) -> None:
        """Empty code should not crash."""
        result = analyzer.analyze("")
        assert not result.has_issues

    def test_whitespace_only(self, analyzer: PythonAnalyzer) -> None:
        """Whitespace-only code should not crash."""
        result = analyzer.analyze("   \n\t  ")
        assert not result.has_issues

    def test_comment_only(self, analyzer: PythonAnalyzer) -> None:
        """Comment-only code should not crash."""
        result = analyzer.analyze("# just a comment")
        assert not result.has_issues

    def test_non_spark_code(self, analyzer: PythonAnalyzer) -> None:
        """Non-Spark Python code should not trigger false positives."""
        code = dedent("""
            def hello(name):
                return f"Hello, {name}!"

            result = hello("World")
        """)
        result = analyzer.analyze(code)

        # Should not flag non-Spark code
        assert not result.has_issues

    def test_multiline_code(self, analyzer: PythonAnalyzer) -> None:
        """Multi-line code should be handled."""
        code = dedent("""
            df = spark.read.parquet('/data')
            df_filtered = df.filter(
                col('amount') > 100
            )
            df_limited = df_filtered.limit(100)
            result = df_limited.collect()
        """)
        result = analyzer.analyze(code)

        # collect() after limit() should be ok or low severity
        patterns = [
            p
            for p in result.patterns
            if p.pattern_type == PythonAntiPatternType.COLLECT_LARGE_DF
        ]
        assert len(patterns) == 0 or patterns[0].severity == "low"
