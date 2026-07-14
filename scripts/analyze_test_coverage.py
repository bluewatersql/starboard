#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Analyze test coverage and generate prioritized action items.

Usage:
    python scripts/analyze_test_coverage.py
    python scripts/analyze_test_coverage.py --format markdown
    python scripts/analyze_test_coverage.py --min-lines 50
"""

import argparse
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Priority(Enum):
    """Test priority levels."""

    CRITICAL = "P1-CRITICAL"
    HIGH = "P2-HIGH"
    MEDIUM = "P3-MEDIUM"
    LOW = "P4-LOW"


@dataclass
class CoverageGap:
    """Represents a coverage gap."""

    file_path: str
    current_coverage: float
    lines: int
    priority: Priority
    category: str
    reason: str

    @property
    def relative_path(self) -> str:
        """Get relative path from starboard root."""
        return self.file_path.replace("packages/starboard-server/starboard/", "")

    def __str__(self) -> str:
        return (
            f"{self.priority.value} | {self.category:15s} | "
            f"{self.lines:4d} lines @ {self.current_coverage:5.1f}% | "
            f"{self.relative_path}"
        )


class CoverageAnalyzer:
    """Analyzes test coverage and identifies gaps."""

    def __init__(self, coverage_file: Path, min_lines: int = 20):
        """
        Initialize analyzer.

        Args:
            coverage_file: Path to coverage.json
            min_lines: Minimum lines to consider (skip small files)
        """
        self.coverage_file = coverage_file
        self.min_lines = min_lines
        self.data = self._load_coverage()

    def _load_coverage(self) -> dict:
        """Load coverage data from JSON file."""
        with self.coverage_file.open() as f:
            return json.load(f)

    def analyze(self) -> list[CoverageGap]:
        """
        Analyze coverage and return prioritized gaps.

        Returns:
            List of CoverageGap objects sorted by priority
        """
        gaps = []

        for file, info in self.data["files"].items():
            if not file.startswith("packages/starboard-server"):
                continue

            coverage = info["summary"]["percent_covered"]
            lines = info["summary"]["num_statements"]

            if lines < self.min_lines:
                continue

            gap = self._assess_gap(file, coverage, lines)
            if gap:
                gaps.append(gap)

        # Sort by priority, then by lines
        priority_order = {
            Priority.CRITICAL: 0,
            Priority.HIGH: 1,
            Priority.MEDIUM: 2,
            Priority.LOW: 3,
        }
        gaps.sort(key=lambda g: (priority_order[g.priority], -g.lines))

        return gaps

    def _assess_gap(self, file: str, coverage: float, lines: int) -> CoverageGap | None:
        """
        Assess a coverage gap and assign priority.

        Args:
            file: File path
            coverage: Current coverage percentage
            lines: Number of lines

        Returns:
            CoverageGap if this file needs testing, None otherwise
        """
        # Skip if coverage is already good
        if coverage >= 80:
            return None

        rel_path = file.replace("packages/starboard-server/starboard/", "")

        # Determine category and priority
        category, priority, reason = self._categorize_file(rel_path, coverage, lines)

        return CoverageGap(
            file_path=file,
            current_coverage=coverage,
            lines=lines,
            priority=priority,
            category=category,
            reason=reason,
        )

    def _categorize_file(
        self, rel_path: str, coverage: float, lines: int
    ) -> tuple[str, Priority, str]:
        """
        Categorize file and assign priority.

        Returns:
            Tuple of (category, priority, reason)
        """
        # Critical: 0% coverage in important areas
        if coverage == 0:
            if rel_path == "main.py":
                return ("Infrastructure", Priority.CRITICAL, "App entry point")
            elif rel_path.startswith("api/"):
                return ("API", Priority.CRITICAL, "User-facing endpoint")
            elif "agent" in rel_path and "domain" in rel_path:
                return ("Agent", Priority.CRITICAL, "Core agent logic")
            elif rel_path.startswith("services/message_processor"):
                return ("Services", Priority.CRITICAL, "Message handling")
            elif rel_path.startswith("services/intent_classifier"):
                return ("Services", Priority.CRITICAL, "Intent routing")
            elif "shared_context" in rel_path:
                return ("Agent", Priority.CRITICAL, "State management")
            elif lines > 100:
                return ("Services", Priority.HIGH, "Large untested file")
            else:
                return ("Services", Priority.MEDIUM, "No coverage")

        # High priority: Low coverage in critical areas
        if coverage < 20:
            if rel_path.startswith("api/"):
                return ("API", Priority.HIGH, "User-facing API")
            elif "domain_agent" in rel_path:
                return ("Agent", Priority.HIGH, "Core agent")
            elif rel_path.startswith("adapters/llm/"):
                return ("LLM", Priority.HIGH, "LLM integration")
            elif rel_path.startswith("services/"):
                return ("Services", Priority.HIGH, "Business logic")
            elif rel_path.startswith("tools/services/"):
                return ("Tools", Priority.HIGH, "Tool execution")
            else:
                return ("Other", Priority.MEDIUM, "Low coverage")

        # Medium priority: Coverage 20-50%
        if coverage < 50:
            if rel_path.startswith("services/context/transformers/"):
                return ("Transformers", Priority.MEDIUM, "Data transformation")
            elif rel_path.startswith("tools/"):
                return ("Tools", Priority.MEDIUM, "Tool logic")
            else:
                return ("Other", Priority.MEDIUM, "Partial coverage")

        # Low priority: Coverage 50-80%
        return ("Other", Priority.LOW, "Needs improvement")

    def print_summary(self, gaps: list[CoverageGap]):
        """Print coverage summary."""
        total = self.data["totals"]

        print("=" * 80)
        print("TEST COVERAGE ANALYSIS")
        print("=" * 80)
        print()
        print(f"Overall Coverage: {total['percent_covered']:.1f}%")
        print(f"Total Files Analyzed: {len(self.data['files'])}")
        print(f"Gaps Identified: {len(gaps)}")
        print()

        # Count by priority
        by_priority = {}
        for gap in gaps:
            by_priority.setdefault(gap.priority, []).append(gap)

        for priority in Priority:
            count = len(by_priority.get(priority, []))
            if count > 0:
                print(f"{priority.value}: {count} files")
        print()

    def print_gaps(self, gaps: list[CoverageGap], limit: int = 50):
        """Print prioritized gaps."""
        print("=" * 80)
        print("PRIORITIZED COVERAGE GAPS")
        print("=" * 80)
        print()

        current_priority = None
        for shown, gap in enumerate(gaps):
            if shown >= limit:
                remaining = len(gaps) - shown
                print(f"\n... and {remaining} more files")
                break

            if gap.priority != current_priority:
                current_priority = gap.priority
                print(f"\n{current_priority.value}")
                print("-" * 80)

            print(gap)

    def export_markdown(self, gaps: list[CoverageGap], output_file: Path):
        """Export gaps as markdown."""
        with output_file.open("w") as f:
            f.write("# Test Coverage Gaps - Action Items\n\n")
            f.write(f"**Generated**: {Path.cwd()}\n\n")

            total = self.data["totals"]
            f.write(f"**Overall Coverage**: {total['percent_covered']:.1f}%\n\n")

            f.write("---\n\n")

            current_priority = None
            for gap in gaps:
                if gap.priority != current_priority:
                    current_priority = gap.priority
                    f.write(f"\n## {current_priority.value}\n\n")

                f.write(f"### {gap.relative_path}\n\n")
                f.write(f"- **Category**: {gap.category}\n")
                f.write(f"- **Lines**: {gap.lines}\n")
                f.write(f"- **Current Coverage**: {gap.current_coverage:.1f}%\n")
                f.write(f"- **Reason**: {gap.reason}\n")
                f.write(
                    f"- **Test File**: `tests/unit/{gap.relative_path.replace('.py', '_test.py')}`\n"
                )
                f.write("\n")

                f.write("**Suggested Tests**:\n")
                f.write("```python\n")
                f.write(
                    f"# tests/unit/{gap.relative_path.replace('.py', '_test.py')}\n"
                )
                f.write("# TODO: Add tests for:\n")
                f.write("# - Happy path scenarios\n")
                f.write("# - Error handling\n")
                f.write("# - Edge cases\n")
                f.write("# - Integration scenarios\n")
                f.write("```\n\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Analyze test coverage gaps")
    parser.add_argument(
        "--coverage-file",
        type=Path,
        default=Path("coverage.json"),
        help="Path to coverage.json file",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=20,
        help="Minimum lines to consider (default: 20)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum gaps to display (default: 50)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for markdown format",
    )

    args = parser.parse_args()

    # Check if coverage file exists
    if not args.coverage_file.exists():
        print(f"Error: Coverage file not found: {args.coverage_file}")
        print("\nRun tests with coverage first:")
        print("  pytest --cov=starboard --cov-report=json")
        return 1

    # Analyze coverage
    analyzer = CoverageAnalyzer(args.coverage_file, args.min_lines)
    gaps = analyzer.analyze()

    # Output results
    if args.format == "text":
        analyzer.print_summary(gaps)
        analyzer.print_gaps(gaps, args.limit)
    elif args.format == "markdown":
        output_file = args.output or Path("COVERAGE_GAPS.md")
        analyzer.export_markdown(gaps, output_file)
        print(f"Markdown report written to: {output_file}")

    return 0


if __name__ == "__main__":
    exit(main())
