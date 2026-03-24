# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
ArtifactSummarizer - Token-efficient summarization for large artifacts.

Provides two summarization modes:
- Extractive: Verbatim extraction of key sections (errors, stack traces)
- Abstractive: Grounded summary preserving key details

Also supports timeline construction from timestamped log entries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class TimelineEntry:
    """A single entry in a timeline.

    Attributes:
        timestamp: Parsed timestamp.
        raw_timestamp: Original timestamp string.
        level: Log level (INFO, WARN, ERROR, etc.).
        message: Log message content.
        line_number: Original line number in artifact.
    """

    timestamp: datetime
    raw_timestamp: str
    level: str
    message: str
    line_number: int = 0


@dataclass(frozen=True)
class SummarySection:
    """A section extracted from the artifact.

    Attributes:
        content: The verbatim or summarized content.
        section_type: Type of section (error, warning, stack_trace, etc.).
        line_range: Original line range (start, end).
        importance: Importance score (0-1).
    """

    content: str
    section_type: str
    line_range: tuple[int, int] = (0, 0)
    importance: float = 1.0


@dataclass
class SummarizationResult:
    """Result of artifact summarization.

    Attributes:
        summary: The final summarized text.
        sections: Individual sections extracted.
        compression_ratio: How much the text was compressed (0-1).
        original_length: Original text length in characters.
        summary_length: Summary length in characters.
        lines_omitted: Number of lines omitted from original.
    """

    summary: str = ""
    sections: list[SummarySection] = field(default_factory=list)
    compression_ratio: float = 0.0
    original_length: int = 0
    summary_length: int = 0
    lines_omitted: int = 0

    @property
    def has_content(self) -> bool:
        """Whether the summary has meaningful content."""
        return bool(self.summary.strip())

    @property
    def section_count(self) -> int:
        """Number of sections extracted."""
        return len(self.sections)


class ArtifactSummarizer:
    """Summarizes large artifacts for token efficiency.

    Supports two modes:
    - extractive: Pulls out key sections verbatim
    - abstractive: Creates a grounded summary

    Uses regex-based heuristics for fast, non-LLM summarization.
    """

    # Patterns for important log lines
    _ERROR_PATTERN = re.compile(
        r"^.*\b(ERROR|FATAL|EXCEPTION|FAILURE|FAILED)\b.*$",
        re.IGNORECASE | re.MULTILINE,
    )

    _WARN_PATTERN = re.compile(
        r"^.*\bWARN(?:ING)?\b.*$",
        re.IGNORECASE | re.MULTILINE,
    )

    _STACK_TRACE_START = re.compile(
        r"^\s*(?:at\s+[\w.$]+|Caused by:|java\.\w+\.\w+Exception|"
        r"Traceback|File\s+\".*\",\s+line|^\s+\d+\s+\|)",
        re.MULTILINE,
    )

    _EXIT_CODE_PATTERN = re.compile(
        r"exit(?:ed)?.*code\s*(\d+)",
        re.IGNORECASE,
    )

    _TIMESTAMP_PATTERN = re.compile(
        r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
        r"(DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL)\s*:?\s*(.*)$",
        re.MULTILINE,
    )

    _IMPORTANT_KEYWORDS = [
        "OutOfMemoryError",
        "SIGKILL",
        "SIGTERM",
        "OOMKilled",
        "exit code",
        "failed",
        "timeout",
        "exception",
        "stack overflow",
        "connection refused",
        "permission denied",
    ]

    def summarize(
        self,
        text: str,
        mode: Literal["extractive", "abstractive"] = "extractive",
        max_length: int = 2000,
    ) -> SummarizationResult:
        """Summarize an artifact.

        Args:
            text: The artifact text to summarize.
            mode: Summarization mode (extractive or abstractive).
            max_length: Maximum length of summary in characters.

        Returns:
            SummarizationResult with summary and metadata.
        """
        if not text or not text.strip():
            return SummarizationResult(original_length=len(text) if text else 0)

        original_length = len(text)
        lines = text.split("\n")

        # Validate mode
        if mode not in ("extractive", "abstractive"):
            mode = "extractive"

        if mode == "extractive":
            result = self._extractive_summarize(text, lines, max_length)
        else:
            result = self._abstractive_summarize(text, lines, max_length)

        result.original_length = original_length
        result.summary_length = len(result.summary)
        if original_length > 0:
            result.compression_ratio = 1 - (result.summary_length / original_length)
        result.lines_omitted = max(0, len(lines) - result.summary.count("\n") - 1)

        return result

    def _extractive_summarize(
        self, text: str, lines: list[str], max_length: int
    ) -> SummarizationResult:
        """Extract key sections verbatim."""
        sections: list[SummarySection] = []
        important_lines: set[int] = set()

        # Find error lines
        for match in self._ERROR_PATTERN.finditer(text):
            line_num = text[: match.start()].count("\n")
            important_lines.add(line_num)
            # Include context (2 lines before and after)
            for offset in range(-2, 3):
                if 0 <= line_num + offset < len(lines):
                    important_lines.add(line_num + offset)

        # Find warning lines (less priority)
        for match in self._WARN_PATTERN.finditer(text):
            line_num = text[: match.start()].count("\n")
            important_lines.add(line_num)

        # Find stack traces
        in_stack_trace = False
        stack_start = 0
        for i, line in enumerate(lines):
            if self._STACK_TRACE_START.match(line):
                if not in_stack_trace:
                    stack_start = i
                    in_stack_trace = True
                important_lines.add(i)
            elif in_stack_trace:
                # Check if still in stack trace
                if line.strip() and not line.strip().startswith(("at ", "...")):
                    in_stack_trace = False
                    if i - stack_start > 2:
                        sections.append(
                            SummarySection(
                                content="\n".join(lines[stack_start:i]),
                                section_type="stack_trace",
                                line_range=(stack_start, i),
                            )
                        )
                else:
                    important_lines.add(i)

        # Find lines with important keywords
        for i, line in enumerate(lines):
            line_lower = line.lower()
            for keyword in self._IMPORTANT_KEYWORDS:
                if keyword.lower() in line_lower:
                    important_lines.add(i)
                    # Include context
                    for offset in range(-1, 2):
                        if 0 <= i + offset < len(lines):
                            important_lines.add(i + offset)
                    break

        # If no important lines found, take first and last few
        if not important_lines:
            for i in range(min(5, len(lines))):
                important_lines.add(i)
            for i in range(max(0, len(lines) - 3), len(lines)):
                important_lines.add(i)

        # Build summary from important lines
        sorted_lines = sorted(important_lines)
        summary_parts: list[str] = []
        prev_line = -2

        for line_num in sorted_lines:
            if line_num > prev_line + 1 and summary_parts:
                # Gap detected - add separator
                summary_parts.append("...")
            if line_num < len(lines):
                summary_parts.append(lines[line_num])
            prev_line = line_num

        summary = "\n".join(summary_parts)

        # Truncate if too long
        if len(summary) > max_length:
            summary = summary[: max_length - 50] + "\n... [truncated]"

        # Create section for the summary
        if summary.strip():
            sections.append(
                SummarySection(
                    content=summary,
                    section_type="extracted",
                    line_range=(
                        min(sorted_lines) if sorted_lines else 0,
                        max(sorted_lines) if sorted_lines else 0,
                    ),
                )
            )

        return SummarizationResult(summary=summary, sections=sections)

    def _abstractive_summarize(
        self, text: str, lines: list[str], max_length: int
    ) -> SummarizationResult:
        """Create a grounded abstract summary."""
        # First do extractive to find key info
        extractive = self._extractive_summarize(text, lines, max_length * 2)

        # Now create a structured summary
        summary_parts: list[str] = []
        sections: list[SummarySection] = []

        # Check for exit codes
        exit_matches = self._EXIT_CODE_PATTERN.findall(text)
        if exit_matches:
            code = exit_matches[0]
            signal_info = ""
            code_int = int(code)
            if code_int > 128:
                signal = code_int - 128
                signal_names = {
                    9: "SIGKILL",
                    15: "SIGTERM",
                    11: "SIGSEGV",
                    6: "SIGABRT",
                }
                signal_info = f" (signal {signal}"
                if signal in signal_names:
                    signal_info += f"/{signal_names[signal]}"
                signal_info += ")"
            summary_parts.append(f"Exit code {code}{signal_info}")

        # Check for OOM
        if "OutOfMemoryError" in text or "OOMKilled" in text.lower():
            if "Java heap space" in text:
                summary_parts.append("Java heap space exhaustion detected")
            elif "GC overhead" in text:
                summary_parts.append("GC overhead limit exceeded")
            elif "SIGKILL" in text.upper() or "137" in text:
                summary_parts.append(
                    "Process killed by OOM killer (likely memory exhaustion)"
                )
            else:
                summary_parts.append("Out of memory condition detected")

        # Check for connection issues
        if "connection" in text.lower() and any(
            x in text.lower() for x in ["refused", "timeout", "failed"]
        ):
            summary_parts.append("Connection issue detected")

        # Check for permission issues
        if "permission" in text.lower() and "denied" in text.lower():
            summary_parts.append("Permission denied error")

        # If we found specific issues, combine them
        if summary_parts:
            summary = "Summary: " + "; ".join(summary_parts)
            summary += (
                "\n\nKey evidence:\n"
                + extractive.summary[: max_length - len(summary) - 50]
            )
        else:
            # Fall back to extractive
            summary = extractive.summary

        # Truncate if needed
        if len(summary) > max_length:
            summary = summary[: max_length - 50] + "\n... [truncated]"

        if summary.strip():
            sections.append(
                SummarySection(
                    content=summary,
                    section_type="abstract",
                )
            )

        return SummarizationResult(summary=summary, sections=sections)

    def build_timeline(self, text: str) -> list[TimelineEntry]:
        """Extract timeline from timestamped log entries.

        Args:
            text: Log text with timestamps.

        Returns:
            List of TimelineEntry objects in chronological order.
        """
        entries: list[TimelineEntry] = []

        for match in self._TIMESTAMP_PATTERN.finditer(text):
            raw_ts, level, message = match.groups()
            try:
                # Parse timestamp
                ts = datetime.fromisoformat(raw_ts.replace(" ", "T"))
                line_num = text[: match.start()].count("\n")

                entries.append(
                    TimelineEntry(
                        timestamp=ts,
                        raw_timestamp=raw_ts,
                        level=level.upper(),
                        message=message.strip(),
                        line_number=line_num,
                    )
                )
            except ValueError:
                # Skip malformed timestamps
                continue

        # Filter out DEBUG noise if we have enough entries
        if len(entries) > 10:
            # Keep non-DEBUG entries and a sample of DEBUG
            filtered = [e for e in entries if e.level != "DEBUG"]
            if len(filtered) < len(entries):
                # Add back a few DEBUG if they provide context
                debug_entries = [e for e in entries if e.level == "DEBUG"]
                # Keep only first and last DEBUG
                if debug_entries:
                    filtered = [debug_entries[0]] + filtered
                    if len(debug_entries) > 1:
                        filtered.append(debug_entries[-1])
                entries = filtered

        # Sort by timestamp
        entries.sort(key=lambda e: e.timestamp)

        return entries
