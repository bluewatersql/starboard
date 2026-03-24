# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Evidence window extractor for diagnostic artifacts.

This module provides:
- Pattern-based evidence window extraction
- Stable ID generation for citation
- Line range tracking for source reference

Design reference:
- changes/diagnostic_agent/UNIFIED_DESIGN.md Section 3.4
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum


class EvidenceType(str, Enum):
    """Types of evidence windows that can be extracted."""

    FATAL_EXCEPTION = "fatal_exception"
    """Root exception in a stack trace."""

    CAUSE_CHAIN = "cause_chain"
    """Caused by chain in exceptions."""

    EXIT_CODE = "exit_code"
    """Exit code and surrounding context."""

    OOM = "oom"
    """Out of memory related messages."""

    ERROR_MESSAGE = "error_message"
    """General error message."""

    WARNING = "warning"
    """Warning message."""

    SPARK_ERROR = "spark_error"
    """Spark-specific error."""

    SQL_ERROR = "sql_error"
    """SQL-related error."""


@dataclass(frozen=True)
class EvidenceWindow:
    """A window of evidence extracted from an artifact.

    Evidence windows are verbatim extracts with stable IDs for citation.
    The LLM can reference these by ID in its response.
    """

    window_id: str
    """Stable unique identifier for citation (e.g., 'ev_abc123')."""

    evidence_type: EvidenceType
    """Type of evidence extracted."""

    line_start: int
    """Starting line number (1-indexed)."""

    line_end: int
    """Ending line number (1-indexed, inclusive)."""

    content: str
    """Verbatim content of the evidence window."""

    confidence: float
    """Confidence that this window is relevant (0.0-1.0)."""

    pattern_match: str = ""
    """The specific pattern that triggered extraction."""


@dataclass(frozen=True)
class ExtractionResult:
    """Result of evidence extraction from an artifact.

    Attributes:
        windows: All extracted evidence windows.
        summary: Brief summary of extraction.
        primary_evidence: Most important evidence (if any).
        has_fatal: True if fatal/exception evidence was found.
    """

    windows: tuple[EvidenceWindow, ...]
    summary: str = ""
    primary_evidence: EvidenceWindow | None = None
    has_fatal: bool = False

    @property
    def window_count(self) -> int:
        """Number of evidence windows extracted."""
        return len(self.windows)

    def get_window(self, window_id: str) -> EvidenceWindow | None:
        """Get a window by its ID."""
        for window in self.windows:
            if window.window_id == window_id:
                return window
        return None


# Evidence extraction patterns with context window sizes
_EVIDENCE_PATTERNS: list[tuple[re.Pattern[str], EvidenceType, int, int, float]] = [
    # (pattern, type, lines_before, lines_after, base_confidence)
    # Fatal exceptions
    (
        re.compile(r"^(?:Exception|Error|Failure).*:", re.MULTILINE),
        EvidenceType.FATAL_EXCEPTION,
        2,
        5,
        0.9,
    ),
    (
        re.compile(r"java\.lang\.\w*Exception", re.MULTILINE),
        EvidenceType.FATAL_EXCEPTION,
        1,
        4,
        0.85,
    ),
    (
        re.compile(r"java\.lang\.\w*Error", re.MULTILINE),
        EvidenceType.FATAL_EXCEPTION,
        1,
        4,
        0.9,
    ),
    # Caused by chains
    (
        re.compile(r"^Caused by:", re.MULTILINE),
        EvidenceType.CAUSE_CHAIN,
        0,
        3,
        0.85,
    ),
    # Exit codes
    (
        re.compile(r"exit(?:ed)?\s*(?:with\s*)?code\s*(\d+)", re.IGNORECASE),
        EvidenceType.EXIT_CODE,
        2,
        2,
        0.9,
    ),
    # OOM patterns
    (
        re.compile(r"OutOfMemoryError", re.IGNORECASE),
        EvidenceType.OOM,
        3,
        5,
        0.95,
    ),
    (
        re.compile(r"OOM[Kk]illed", re.IGNORECASE),
        EvidenceType.OOM,
        2,
        3,
        0.9,
    ),
    (
        re.compile(r"oom-killer", re.IGNORECASE),
        EvidenceType.OOM,
        2,
        3,
        0.85,
    ),
    # Spark errors
    (
        re.compile(r"SparkException", re.IGNORECASE),
        EvidenceType.SPARK_ERROR,
        2,
        4,
        0.85,
    ),
    (
        re.compile(r"FetchFailedException", re.IGNORECASE),
        EvidenceType.SPARK_ERROR,
        2,
        4,
        0.9,
    ),
    (
        re.compile(r"ExecutorLostFailure", re.IGNORECASE),
        EvidenceType.SPARK_ERROR,
        2,
        4,
        0.85,
    ),
    # SQL errors
    (
        re.compile(r"AnalysisException", re.IGNORECASE),
        EvidenceType.SQL_ERROR,
        1,
        3,
        0.9,
    ),
    (
        re.compile(r"TABLE_OR_VIEW_NOT_FOUND", re.IGNORECASE),
        EvidenceType.SQL_ERROR,
        1,
        2,
        0.9,
    ),
    (
        re.compile(r"PERMISSION_DENIED", re.IGNORECASE),
        EvidenceType.SQL_ERROR,
        1,
        2,
        0.9,
    ),
    # General errors
    (
        re.compile(r"^\[ERROR\]", re.MULTILINE),
        EvidenceType.ERROR_MESSAGE,
        1,
        2,
        0.7,
    ),
    (
        re.compile(r"^ERROR:", re.MULTILINE),
        EvidenceType.ERROR_MESSAGE,
        1,
        2,
        0.75,
    ),
    # Warnings (lower priority)
    (
        re.compile(r"^\[WARN\]", re.MULTILINE),
        EvidenceType.WARNING,
        0,
        1,
        0.5,
    ),
]


class EvidenceWindowExtractor:
    """Extracts evidence windows from diagnostic artifacts.

    Identifies key evidence (exceptions, errors, exit codes) and
    extracts windows of context around them for LLM analysis.

    Example:
        >>> extractor = EvidenceWindowExtractor()
        >>> result = extractor.extract("java.lang.OutOfMemoryError: Java heap space")
        >>> print(result.primary_evidence.evidence_type)
        EvidenceType.OOM
    """

    def __init__(
        self,
        *,
        max_windows: int = 10,
        max_window_lines: int = 15,
        min_confidence: float = 0.5,
    ) -> None:
        """Initialize extractor.

        Args:
            max_windows: Maximum evidence windows to extract.
            max_window_lines: Maximum lines per window.
            min_confidence: Minimum confidence to include a window.
        """
        self._max_windows = max_windows
        self._max_window_lines = max_window_lines
        self._min_confidence = min_confidence

    def extract(self, text: str) -> ExtractionResult:
        """Extract evidence windows from text.

        Args:
            text: Log or error text to extract evidence from.

        Returns:
            ExtractionResult with extracted windows.
        """
        lines = text.split("\n")
        windows: list[EvidenceWindow] = []

        for pattern, evidence_type, before, after, confidence in _EVIDENCE_PATTERNS:
            for match in pattern.finditer(text):
                # Find line number of match
                line_num = text[: match.start()].count("\n") + 1

                # Calculate window boundaries
                start_line = max(1, line_num - before)
                end_line = min(len(lines), line_num + after)

                # Limit window size
                if end_line - start_line + 1 > self._max_window_lines:
                    end_line = start_line + self._max_window_lines - 1

                # Extract content
                content_lines = lines[start_line - 1 : end_line]
                content = "\n".join(content_lines)

                # Generate stable ID
                window_id = self._generate_window_id(content, evidence_type)

                # Skip if we already have this window
                if any(w.window_id == window_id for w in windows):
                    continue

                if confidence >= self._min_confidence:
                    windows.append(
                        EvidenceWindow(
                            window_id=window_id,
                            evidence_type=evidence_type,
                            line_start=start_line,
                            line_end=end_line,
                            content=content,
                            confidence=confidence,
                            pattern_match=match.group(0)[:100],
                        )
                    )

        # Sort by confidence and limit
        windows.sort(key=lambda w: -w.confidence)
        windows = windows[: self._max_windows]

        # Determine primary evidence
        primary = windows[0] if windows else None

        # Check for fatal evidence
        has_fatal = any(
            w.evidence_type
            in (EvidenceType.FATAL_EXCEPTION, EvidenceType.OOM, EvidenceType.EXIT_CODE)
            for w in windows
        )

        # Generate summary
        summary = self._generate_summary(windows)

        return ExtractionResult(
            windows=tuple(windows),
            summary=summary,
            primary_evidence=primary,
            has_fatal=has_fatal,
        )

    def _generate_window_id(self, content: str, evidence_type: EvidenceType) -> str:
        """Generate a stable ID for an evidence window."""
        hash_input = f"{evidence_type.value}:{content[:200]}"
        hash_value = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
        return f"ev_{hash_value}"

    def _generate_summary(self, windows: list[EvidenceWindow]) -> str:
        """Generate a brief summary of extracted evidence."""
        if not windows:
            return "No significant evidence extracted"

        types = {w.evidence_type for w in windows}
        type_names = [t.value.replace("_", " ") for t in types]

        return f"Extracted {len(windows)} evidence window(s): {', '.join(type_names)}"

    def extract_for_pattern(
        self,
        text: str,
        pattern: re.Pattern[str],
        evidence_type: EvidenceType,
        *,
        lines_before: int = 2,
        lines_after: int = 3,
    ) -> list[EvidenceWindow]:
        """Extract windows for a custom pattern.

        Useful for pattern-specific evidence extraction.

        Args:
            text: Text to extract from.
            pattern: Regex pattern to match.
            evidence_type: Type to assign to matches.
            lines_before: Lines of context before match.
            lines_after: Lines of context after match.

        Returns:
            List of extracted evidence windows.
        """
        lines = text.split("\n")
        windows: list[EvidenceWindow] = []

        for match in pattern.finditer(text):
            line_num = text[: match.start()].count("\n") + 1
            start_line = max(1, line_num - lines_before)
            end_line = min(len(lines), line_num + lines_after)

            content = "\n".join(lines[start_line - 1 : end_line])
            window_id = self._generate_window_id(content, evidence_type)

            if not any(w.window_id == window_id for w in windows):
                windows.append(
                    EvidenceWindow(
                        window_id=window_id,
                        evidence_type=evidence_type,
                        line_start=start_line,
                        line_end=end_line,
                        content=content,
                        confidence=0.8,
                        pattern_match=match.group(0)[:100],
                    )
                )

        return windows
