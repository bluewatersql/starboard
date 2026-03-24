"""Domain models for source code operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceInfo:
    """Information about extracted source code."""

    source_type: str  # notebook, python_file, sql
    path: str | None
    source_code: str


@dataclass(frozen=True)
class CodeQualityIssue:
    """A code quality issue identified by analysis."""

    context: str
    severity: str
    issue: str
    description: str
    recommendation: str
    code_snippet: str | None = None
    fix_snippet: str | None = None
    line_range: str | None = None
    signals: list[str] | None = None
