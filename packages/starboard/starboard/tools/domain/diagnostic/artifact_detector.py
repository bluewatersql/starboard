# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Artifact type and language detection.

This module provides the ArtifactDetector class for classifying user-provided
artifacts (error messages, logs, stack traces, code) into canonical types.

Detection Rules (priority order):
1. Stack traces: Python Traceback, Java "at org.", "Caused by:"
2. GC logs: [GC, [Full GC, GC-specific patterns
3. Application logs: Timestamp density, log levels (INFO/WARN/ERROR/DEBUG)
4. Exit codes: "exit code NNN" patterns
5. SQL code: SELECT, INSERT, UPDATE, CREATE, WITH keywords
6. Python code: def, import, class, Traceback context
7. Scala code: val, var, case class, SparkSession, object
8. Error messages: Exception class names, SQLSTATE, SIGKILL

Design reference: changes/diagnostic_agent/UNIFIED_DESIGN.md Section 5.1.2
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from starboard.tools.domain.diagnostic.models import (
    ArtifactType,
    CodeLanguage,
    DetectionResult,
)


@dataclass
class _DetectionScore:
    """Internal scoring for artifact type detection."""

    artifact_type: ArtifactType
    language: CodeLanguage | None
    score: float
    signals: list[str]


class ArtifactDetector:
    """Detect artifact type and language from user input.

    The detector uses pattern matching and heuristics to classify input text
    into one of the canonical artifact types. It also detects the programming
    language for code artifacts.

    Example:
        >>> detector = ArtifactDetector()
        >>> result = detector.detect("Traceback (most recent call last):\\n...")
        >>> result.artifact_type
        <ArtifactType.STACK_TRACE: 'stack_trace'>
        >>> result.confidence
        0.95
    """

    # =========================================================================
    # PATTERN DEFINITIONS
    # =========================================================================

    # Stack trace patterns
    _PYTHON_TRACEBACK = re.compile(
        r"Traceback \(most recent call last\)", re.IGNORECASE
    )
    _JAVA_AT_LINE = re.compile(r"^\s+at\s+[\w.$]+\([\w.]+:\d+\)", re.MULTILINE)
    _CAUSED_BY = re.compile(r"^Caused by:", re.MULTILINE)
    _EXCEPTION_CLASS = re.compile(
        r"\b(Exception|Error|Throwable)\b.*?:",
        re.IGNORECASE,
    )

    # GC log patterns
    _GC_STANDARD = re.compile(r"\[(Full )?GC\s*\(")
    _GC_G1 = re.compile(r"\[gc(,\w+)*\]", re.IGNORECASE)
    _GC_METRICS = re.compile(r"\d+K->\d+K\(\d+K\)")

    # Log patterns
    _TIMESTAMP_ISO = re.compile(
        r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}",
    )
    _TIMESTAMP_BRACKETED = re.compile(
        r"\[\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}",
    )
    _LOG_LEVELS = re.compile(r"\b(INFO|WARN|WARNING|ERROR|DEBUG|TRACE|FATAL)\b")

    # Exit code patterns
    _EXIT_CODE = re.compile(
        r"exit(?:ed)?\s*(?:with\s*)?code\s*(\d+)",
        re.IGNORECASE,
    )

    # SQL patterns
    _SQL_KEYWORDS = re.compile(
        r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|WITH|MERGE)\b",
        re.IGNORECASE | re.MULTILINE,
    )
    _SQL_FROM = re.compile(r"\bFROM\s+[\w.`\"]+", re.IGNORECASE)
    _SQL_WHERE = re.compile(r"\bWHERE\b", re.IGNORECASE)

    # Python patterns
    _PYTHON_DEF = re.compile(r"^\s*def\s+\w+\s*\(", re.MULTILINE)
    _PYTHON_CLASS = re.compile(r"^\s*class\s+\w+", re.MULTILINE)
    _PYTHON_IMPORT = re.compile(r"^\s*(import|from)\s+\w+", re.MULTILINE)
    _PYTHON_INDENT = re.compile(r"^    \w", re.MULTILINE)  # 4-space indent

    # Scala patterns
    _SCALA_VAL_VAR = re.compile(r"^\s*(val|var)\s+\w+\s*[=:]", re.MULTILINE)
    _SCALA_CASE_CLASS = re.compile(r"^\s*case\s+class\s+\w+", re.MULTILINE)
    _SCALA_OBJECT = re.compile(r"^\s*object\s+\w+", re.MULTILINE)
    _SCALA_DEF = re.compile(r"^\s*def\s+\w+\s*[\[(]", re.MULTILINE)
    _SPARK_SESSION = re.compile(r"SparkSession\.builder", re.IGNORECASE)

    # Error message patterns
    _SQLSTATE = re.compile(r"SQLSTATE", re.IGNORECASE)
    _PERMISSION_DENIED = re.compile(r"PERMISSION_DENIED", re.IGNORECASE)
    _ANALYSIS_EXCEPTION = re.compile(r"AnalysisException", re.IGNORECASE)

    # Thresholds
    _TIMESTAMP_DENSITY_THRESHOLD = 0.1  # 10% of lines have timestamps
    _MIN_LINES_FOR_DENSITY = 3

    def detect(self, text: str) -> DetectionResult:
        """Detect artifact type and language from user input.

        The detection algorithm evaluates multiple signals and returns the
        most likely artifact type with a confidence score.

        Args:
            text: The user-provided artifact text.

        Returns:
            DetectionResult with artifact_type, language, confidence, and signals.
        """
        if not text or not text.strip():
            return DetectionResult(
                artifact_type=ArtifactType.ERROR_MESSAGE,
                language=None,
                confidence=0.3,
                signals=("empty_input",),
            )

        # Score each artifact type
        scores: list[_DetectionScore] = []

        # Check stack traces first (highest priority)
        stack_score = self._score_stack_trace(text)
        if stack_score.score > 0:
            scores.append(stack_score)

        # Check GC logs (high priority, very specific)
        gc_score = self._score_gc_logs(text)
        if gc_score.score > 0:
            scores.append(gc_score)

        # Check application logs
        log_score = self._score_logs(text)
        if log_score.score > 0:
            scores.append(log_score)

        # Check for code (SQL, Python, Scala)
        code_score = self._score_code(text)
        if code_score.score > 0:
            scores.append(code_score)

        # Check for exit codes
        exit_score = self._score_exit_code(text)
        if exit_score.score > 0:
            scores.append(exit_score)

        # Check for general error messages
        error_score = self._score_error_message(text)
        if error_score.score > 0:
            scores.append(error_score)

        # Select the best match
        if not scores:
            return DetectionResult(
                artifact_type=ArtifactType.ERROR_MESSAGE,
                language=None,
                confidence=0.4,
                signals=("no_patterns_matched",),
            )

        # Sort by score (highest first)
        scores.sort(key=lambda s: s.score, reverse=True)
        best = scores[0]

        # Check for mixed content (multiple high-scoring types)
        if len(scores) >= 2:
            second = scores[1]
            # If two types are close in score and fundamentally different, classify as mixed
            is_close_score = second.score >= 0.6 and best.score - second.score < 0.2
            is_different = self._are_different_categories(
                best.artifact_type, second.artifact_type
            )
            if is_close_score and is_different:
                return DetectionResult(
                    artifact_type=ArtifactType.MIXED,
                    language=best.language or second.language,
                    confidence=min(best.score, 0.85),
                    signals=tuple(best.signals + second.signals + ["mixed_content"]),
                )

        return DetectionResult(
            artifact_type=best.artifact_type,
            language=best.language,
            confidence=min(best.score, 1.0),
            signals=tuple(best.signals),
        )

    def _are_different_categories(
        self, type1: ArtifactType, type2: ArtifactType
    ) -> bool:
        """Check if two artifact types are fundamentally different.

        Used to determine if content should be classified as MIXED.
        """
        # Group related types
        log_types = {ArtifactType.LOGS, ArtifactType.GC_LOGS}
        code_types = {ArtifactType.CODE}
        error_types = {ArtifactType.ERROR_MESSAGE, ArtifactType.STACK_TRACE}

        for group in [log_types, code_types, error_types]:
            if type1 in group and type2 in group:
                return False

        return True

    # =========================================================================
    # SCORING METHODS
    # =========================================================================

    def _score_stack_trace(self, text: str) -> _DetectionScore:
        """Score text for stack trace characteristics."""
        signals: list[str] = []
        score = 0.0

        # Python traceback (very strong signal - definitive)
        if self._PYTHON_TRACEBACK.search(text):
            score += 0.9
            signals.append("python_traceback")

        # Java "at" lines (strong signal)
        at_matches = len(self._JAVA_AT_LINE.findall(text))
        if at_matches >= 3:
            score += 0.7
            signals.append("java_exception")
        elif at_matches >= 1:
            score += 0.4
            signals.append("java_at_line")

        # "Caused by:" chain (strong signal)
        caused_by_count = len(self._CAUSED_BY.findall(text))
        if caused_by_count >= 2:
            score += 0.4
            signals.append("caused_by_chain")
        elif caused_by_count >= 1:
            score += 0.3
            signals.append("caused_by_chain")

        # Exception class names
        if self._EXCEPTION_CLASS.search(text):
            score += 0.3
            signals.append("exception_class")

        return _DetectionScore(
            artifact_type=ArtifactType.STACK_TRACE,
            language=None,
            score=min(score, 1.0),
            signals=signals,
        )

    def _score_gc_logs(self, text: str) -> _DetectionScore:
        """Score text for GC log characteristics."""
        signals: list[str] = []
        score = 0.0

        # Standard GC format [GC or [Full GC
        gc_standard_count = len(self._GC_STANDARD.findall(text))
        if gc_standard_count >= 2:
            score += 0.7
            signals.append("gc_pattern")
        elif gc_standard_count >= 1:
            score += 0.4
            signals.append("gc_pattern")

        # G1 GC format [gc,...] - this is a strong signal
        g1_matches = len(self._GC_G1.findall(text))
        if g1_matches >= 2:
            score += 0.7
            signals.append("g1_gc")
        elif g1_matches >= 1:
            score += 0.4
            signals.append("g1_gc")

        # Memory metrics like 262144K->32768K(305664K)
        gc_metrics_count = len(self._GC_METRICS.findall(text))
        if gc_metrics_count >= 2:
            score += 0.4
            signals.append("gc_metrics")
        elif gc_metrics_count >= 1:
            score += 0.2
            signals.append("gc_metrics")

        return _DetectionScore(
            artifact_type=ArtifactType.GC_LOGS,
            language=None,
            score=min(score, 1.0),
            signals=signals,
        )

    def _score_logs(self, text: str) -> _DetectionScore:
        """Score text for application log characteristics."""
        signals: list[str] = []
        score = 0.0

        lines = text.split("\n")
        line_count = len([line for line in lines if line.strip()])

        if line_count < self._MIN_LINES_FOR_DENSITY:
            # Too short to reliably detect as logs
            return _DetectionScore(
                artifact_type=ArtifactType.LOGS,
                language=None,
                score=0.0,
                signals=[],
            )

        # Count timestamp lines
        timestamp_count = len(self._TIMESTAMP_ISO.findall(text))
        timestamp_count += len(self._TIMESTAMP_BRACKETED.findall(text))

        timestamp_density = timestamp_count / line_count
        if timestamp_density >= self._TIMESTAMP_DENSITY_THRESHOLD:
            score += 0.5
            signals.append("timestamp_density")

        # Log levels (INFO, WARN, ERROR, etc.)
        log_level_count = len(self._LOG_LEVELS.findall(text))
        if log_level_count >= 3:
            score += 0.4
            signals.append("log_levels")
        elif log_level_count >= 1:
            score += 0.2
            signals.append("log_levels")

        return _DetectionScore(
            artifact_type=ArtifactType.LOGS,
            language=None,
            score=min(score, 1.0),
            signals=signals,
        )

    def _score_code(self, text: str) -> _DetectionScore:
        """Score text for source code characteristics and detect language."""
        # Try each language
        sql_score = self._score_sql(text)
        python_score = self._score_python(text)
        scala_score = self._score_scala(text)

        # Return the highest scoring language
        best = max(
            [sql_score, python_score, scala_score],
            key=lambda s: s.score,
        )

        return best

    def _score_sql(self, text: str) -> _DetectionScore:
        """Score text for SQL characteristics."""
        signals: list[str] = []
        score = 0.0

        # SQL keywords at start of line (strong signal)
        sql_keyword_count = len(self._SQL_KEYWORDS.findall(text))
        if sql_keyword_count >= 2:
            score += 0.7
            signals.append("sql_keyword")
        elif sql_keyword_count >= 1:
            score += 0.5
            signals.append("sql_keyword")

        # FROM clause
        if self._SQL_FROM.search(text):
            score += 0.25
            signals.append("sql_from")

        # WHERE clause
        if self._SQL_WHERE.search(text):
            score += 0.15
            signals.append("sql_where")

        return _DetectionScore(
            artifact_type=ArtifactType.CODE,
            language=CodeLanguage.SQL if score > 0 else None,
            score=min(score, 1.0),
            signals=signals,
        )

    def _score_python(self, text: str) -> _DetectionScore:
        """Score text for Python characteristics."""
        signals: list[str] = []
        score = 0.0

        # def keyword (strong signal for Python)
        def_count = len(self._PYTHON_DEF.findall(text))
        if def_count >= 2:
            score += 0.6
            signals.append("python_def")
        elif def_count >= 1:
            score += 0.5
            signals.append("python_def")

        # class keyword
        if self._PYTHON_CLASS.search(text):
            score += 0.4
            signals.append("python_class")

        # import statements
        import_count = len(self._PYTHON_IMPORT.findall(text))
        if import_count >= 2:
            score += 0.5
            signals.append("python_import")
        elif import_count >= 1:
            score += 0.3
            signals.append("python_import")

        # 4-space indentation (Python style) - supporting signal
        indent_count = len(self._PYTHON_INDENT.findall(text))
        if indent_count >= 3:
            score += 0.3
            signals.append("python_indent")
        elif indent_count >= 1:
            score += 0.15
            signals.append("python_indent")

        return _DetectionScore(
            artifact_type=ArtifactType.CODE,
            language=CodeLanguage.PYTHON if score > 0 else None,
            score=min(score, 1.0),
            signals=signals,
        )

    def _score_scala(self, text: str) -> _DetectionScore:
        """Score text for Scala characteristics."""
        signals: list[str] = []
        score = 0.0

        # val/var declarations (strong Scala signal)
        val_var_count = len(self._SCALA_VAL_VAR.findall(text))
        if val_var_count >= 2:
            score += 0.6
            signals.append("scala_val_var")
        elif val_var_count >= 1:
            score += 0.4
            signals.append("scala_val_var")

        # case class (very Scala-specific)
        if self._SCALA_CASE_CLASS.search(text):
            score += 0.5
            signals.append("scala_case_class")

        # object definition (Scala-specific)
        if self._SCALA_OBJECT.search(text):
            score += 0.5
            signals.append("scala_object")

        # SparkSession.builder
        if self._SPARK_SESSION.search(text):
            score += 0.4
            signals.append("spark_session")

        # Scala-style def (with type params or parens)
        if self._SCALA_DEF.search(text) and not self._PYTHON_DEF.search(text):
            score += 0.3
            signals.append("scala_def")

        return _DetectionScore(
            artifact_type=ArtifactType.CODE,
            language=CodeLanguage.SCALA if score > 0 else None,
            score=min(score, 1.0),
            signals=signals,
        )

    def _score_exit_code(self, text: str) -> _DetectionScore:
        """Score text for exit code patterns."""
        signals: list[str] = []
        score = 0.0

        match = self._EXIT_CODE.search(text)
        if match:
            score += 0.6
            signals.append("exit_code")

            # Common fatal exit codes get a boost
            exit_code = int(match.group(1))
            if exit_code in (137, 143, 139, 1):
                score += 0.2
                signals.append(f"exit_code_{exit_code}")

        return _DetectionScore(
            artifact_type=ArtifactType.ERROR_MESSAGE,
            language=None,
            score=min(score, 1.0),
            signals=signals,
        )

    def _score_error_message(self, text: str) -> _DetectionScore:
        """Score text for general error message characteristics."""
        signals: list[str] = []
        score = 0.0

        # SQLSTATE error code (strong signal)
        if self._SQLSTATE.search(text):
            score += 0.6
            signals.append("sqlstate")

        # Permission denied
        if self._PERMISSION_DENIED.search(text):
            score += 0.5
            signals.append("permission_denied")

        # AnalysisException
        if self._ANALYSIS_EXCEPTION.search(text):
            score += 0.5
            signals.append("analysis_exception")

        # General Exception/Error pattern - check for standalone error messages
        # Look for patterns like "java.lang.OutOfMemoryError: message"
        standalone_exception = re.search(
            r"^[\w.]+(?:Exception|Error):\s*\S",
            text,
            re.MULTILINE,
        )
        if standalone_exception:
            score += 0.6
            signals.append("standalone_exception")
        elif self._EXCEPTION_CLASS.search(text) and score == 0:
            score += 0.4
            signals.append("exception_class")

        # Short text with error keywords
        lines = text.split("\n")
        if len(lines) <= 5:
            error_keywords = re.search(
                r"\b(error|exception|failed|failure)\b",
                text,
                re.IGNORECASE,
            )
            if error_keywords:
                score += 0.3
                signals.append("error_keyword")

        return _DetectionScore(
            artifact_type=ArtifactType.ERROR_MESSAGE,
            language=None,
            score=min(score, 1.0),
            signals=signals,
        )
