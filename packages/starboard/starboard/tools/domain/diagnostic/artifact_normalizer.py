# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Artifact normalization for consistent processing.

This module provides the ArtifactNormalizer class for cleaning and formatting
user-provided artifacts before analysis. Normalization ensures:
- Consistent line endings (LF)
- Removed trailing whitespace
- Collapsed blank lines
- Deduplicated Spark retry messages
- Size guardrails with intelligent truncation

Design reference: changes/diagnostic_agent/UNIFIED_DESIGN.md Section 5.1.3
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from starboard.tools.domain.diagnostic.models import ArtifactType


@dataclass
class NormalizationResult:
    """Result of artifact normalization.

    Contains the normalized content and metadata about transformations applied.
    """

    content: str
    """Normalized content."""

    truncation_applied: bool
    """Whether the content was truncated due to size limits."""

    truncation_notice: str | None = None
    """Human-readable notice about truncation."""

    transformations_applied: list[str] = field(default_factory=list)
    """List of transformations that were applied."""

    original_line_count: int = 0
    """Original number of lines before normalization."""

    final_line_count: int = 0
    """Number of lines after normalization."""


class ArtifactNormalizer:
    """Normalize artifacts for consistent processing.

    The normalizer applies a series of transformations to clean up user input
    while preserving important diagnostic information like error windows,
    stack traces, and exception context.

    Example:
        >>> normalizer = ArtifactNormalizer()
        >>> result = normalizer.normalize("line1\\r\\nline2  \\n", ArtifactType.LOGS)
        >>> result.content
        'line1\\nline2'
    """

    # Size limits (configurable)
    MAX_CHARS_INBOUND: int = 120_000  # ~30K tokens
    MAX_LINES_INBOUND: int = 3_000
    MAX_CODE_CHARS: int = 60_000

    # Truncation parameters
    HEAD_LINES: int = 200  # Keep first N lines
    TAIL_LINES: int = 200  # Keep last N lines
    ERROR_WINDOW_CONTEXT: int = 20  # Lines before/after error patterns

    # Deduplication threshold
    MIN_REPEATS_TO_DEDUPE: int = 3

    # Error patterns to preserve during truncation
    _ERROR_PATTERNS = re.compile(
        r"(ERROR|Exception|Error:|FATAL|Caused by|OutOfMemory|exit.*code|SIGKILL|SIGTERM)",
        re.IGNORECASE,
    )

    def normalize(
        self,
        text: str,
        artifact_type: ArtifactType,
    ) -> NormalizationResult:
        """Normalize artifact content.

        Args:
            text: Raw artifact content.
            artifact_type: Type of artifact (affects normalization rules).

        Returns:
            NormalizationResult with normalized content and metadata.
        """
        transformations: list[str] = []
        original_lines = text.split("\n") if text else []
        original_line_count = len(original_lines)

        if not text:
            return NormalizationResult(
                content="",
                truncation_applied=False,
                transformations_applied=[],
                original_line_count=0,
                final_line_count=0,
            )

        # Step 1: Normalize line endings
        content = self._normalize_line_endings(text)
        if content != text:
            transformations.append("line_endings")

        # Step 2: Remove trailing whitespace
        content_before = content
        content = self._remove_trailing_whitespace(content)
        if content != content_before:
            transformations.append("trailing_whitespace")

        # Step 3: Collapse blank lines
        content_before = content
        content = self._collapse_blank_lines(content)
        if content != content_before:
            transformations.append("blank_lines")

        # Step 4: Deduplicate repeated lines (for logs)
        if artifact_type == ArtifactType.LOGS:
            content_before = content
            content = self._deduplicate_repeats(content)
            if content != content_before:
                transformations.append("deduplication")

        # Step 5: Apply size guardrails
        truncation_applied = False
        truncation_notice = None

        max_chars = (
            self.MAX_CODE_CHARS
            if artifact_type == ArtifactType.CODE
            else self.MAX_CHARS_INBOUND
        )

        if len(content) > max_chars or content.count("\n") > self.MAX_LINES_INBOUND:
            content, truncation_notice = self._apply_truncation(content, artifact_type)
            truncation_applied = True
            transformations.append("truncation")

        # Final cleanup: ensure no trailing whitespace at end
        content = content.rstrip()

        final_lines = content.split("\n") if content else []

        return NormalizationResult(
            content=content,
            truncation_applied=truncation_applied,
            truncation_notice=truncation_notice,
            transformations_applied=transformations,
            original_line_count=original_line_count,
            final_line_count=len(final_lines),
        )

    def _normalize_line_endings(self, text: str) -> str:
        """Normalize line endings to LF.

        Converts CRLF (Windows) and CR (old Mac) to LF (Unix).
        """
        # CRLF -> LF first, then CR -> LF
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def _remove_trailing_whitespace(self, text: str) -> str:
        """Remove trailing whitespace from each line."""
        lines = text.split("\n")
        return "\n".join(line.rstrip() for line in lines)

    def _collapse_blank_lines(self, text: str) -> str:
        """Collapse more than 2 consecutive blank lines to 2.

        This preserves intentional paragraph breaks while removing excessive whitespace.
        """
        # Replace 3+ consecutive newlines with 3 (2 blank lines)
        while "\n\n\n\n" in text:
            text = text.replace("\n\n\n\n", "\n\n\n")
        return text

    def _deduplicate_repeats(self, text: str) -> str:
        """Deduplicate repeated log lines.

        Spark jobs often generate many identical retry messages. This replaces
        N identical lines with the first occurrence plus a count.

        Empty lines are not deduplicated (they're handled by blank line collapse).
        """
        lines = text.split("\n")
        if len(lines) < self.MIN_REPEATS_TO_DEDUPE:
            return text

        result: list[str] = []
        i = 0

        while i < len(lines):
            current_line = lines[i]

            # Skip deduplication for empty/whitespace-only lines
            if not current_line.strip():
                result.append(current_line)
                i += 1
                continue

            # Count consecutive duplicates
            count = 1
            while i + count < len(lines) and lines[i + count] == current_line:
                count += 1

            if count >= self.MIN_REPEATS_TO_DEDUPE:
                # Deduplicate: keep first line with count
                result.append(current_line)
                result.append(f"  [... repeated {count - 1}x ...]")
                i += count
            else:
                # Keep all lines
                result.append(current_line)
                i += 1

        return "\n".join(result)

    def _apply_truncation(
        self,
        text: str,
        artifact_type: ArtifactType,
    ) -> tuple[str, str]:
        """Apply intelligent truncation while preserving important content.

        Strategy:
        1. Keep first HEAD_LINES lines (context)
        2. Keep last TAIL_LINES lines (crash tail)
        3. Keep windows around error patterns

        Returns:
            Tuple of (truncated_content, truncation_notice)
        """
        lines = text.split("\n")
        total_lines = len(lines)

        if total_lines <= self.MAX_LINES_INBOUND:
            # Truncate by characters
            return self._truncate_by_chars(text, artifact_type)

        # Find error windows to preserve
        error_windows: list[tuple[int, int]] = []
        for i, line in enumerate(lines):
            if self._ERROR_PATTERNS.search(line):
                start = max(0, i - self.ERROR_WINDOW_CONTEXT)
                end = min(total_lines, i + self.ERROR_WINDOW_CONTEXT + 1)
                error_windows.append((start, end))

        # Merge overlapping windows
        error_windows = self._merge_windows(error_windows)

        # Determine which lines to keep
        keep_lines: set[int] = set()

        # Keep head
        for i in range(min(self.HEAD_LINES, total_lines)):
            keep_lines.add(i)

        # Keep tail
        for i in range(max(0, total_lines - self.TAIL_LINES), total_lines):
            keep_lines.add(i)

        # Keep error windows
        for start, end in error_windows:
            for i in range(start, end):
                keep_lines.add(i)

        # Build result
        sorted_lines = sorted(keep_lines)
        result_lines: list[str] = []
        prev_line = -1

        for line_num in sorted_lines:
            if prev_line >= 0 and line_num > prev_line + 1:
                # Gap in line numbers - add ellipsis
                skipped = line_num - prev_line - 1
                result_lines.append(f"\n[... {skipped} lines omitted ...]\n")
            result_lines.append(lines[line_num])
            prev_line = line_num

        truncated = "\n".join(result_lines)
        kept_lines = len(sorted_lines)
        notice = (
            f"Truncated from {total_lines} to {kept_lines} lines "
            f"(kept head, tail, and {len(error_windows)} error windows)"
        )

        return truncated, notice

    def _truncate_by_chars(
        self,
        text: str,
        artifact_type: ArtifactType,
    ) -> tuple[str, str]:
        """Truncate by character count while preserving line boundaries."""
        max_chars = (
            self.MAX_CODE_CHARS
            if artifact_type == ArtifactType.CODE
            else self.MAX_CHARS_INBOUND
        )

        if len(text) <= max_chars:
            return text, ""

        # Keep roughly half from head, half from tail
        half = max_chars // 2

        # Find line boundaries
        lines = text.split("\n")
        head_lines: list[str] = []
        head_chars = 0

        for line in lines:
            if head_chars + len(line) + 1 > half:
                break
            head_lines.append(line)
            head_chars += len(line) + 1

        tail_lines: list[str] = []
        tail_chars = 0

        for line in reversed(lines):
            if tail_chars + len(line) + 1 > half:
                break
            tail_lines.insert(0, line)
            tail_chars += len(line) + 1

        omitted = len(lines) - len(head_lines) - len(tail_lines)
        result = (
            "\n".join(head_lines)
            + f"\n\n[... {omitted} lines omitted ...]\n\n"
            + "\n".join(tail_lines)
        )

        notice = f"Truncated from {len(text)} to ~{len(result)} characters"
        return result, notice

    def _merge_windows(self, windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Merge overlapping windows."""
        if not windows:
            return []

        # Sort by start position
        sorted_windows = sorted(windows)
        merged: list[tuple[int, int]] = [sorted_windows[0]]

        for start, end in sorted_windows[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                # Overlapping - merge
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

        return merged
