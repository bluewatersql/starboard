#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Update coverage badge in README.md based on coverage.json."""

import json
import re
import sys
from pathlib import Path


def get_coverage_percentage() -> float:
    """Read coverage percentage from coverage.json."""
    coverage_file = Path(__file__).parent.parent / "coverage.json"

    if not coverage_file.exists():
        print("Error: coverage.json not found. Run tests with coverage first:")
        print(
            "  uv run pytest tests/unit/ --cov=starboard --cov=starboard_core --cov-report=json"
        )
        sys.exit(1)

    with open(coverage_file) as f:
        data = json.load(f)

    return data["totals"]["percent_covered"]


def get_badge_color(coverage: float) -> str:
    """Get badge color based on coverage percentage."""
    if coverage >= 80:
        return "brightgreen"
    elif coverage >= 60:
        return "green"
    elif coverage >= 40:
        return "yellow"
    elif coverage >= 20:
        return "orange"
    else:
        return "red"


def update_readme(coverage: float) -> None:
    """Update README.md with new coverage badge."""
    readme_file = Path(__file__).parent.parent / "README.md"

    if not readme_file.exists():
        print("Error: README.md not found")
        sys.exit(1)

    with open(readme_file) as f:
        content = f.read()

    # Find and replace coverage badge
    coverage_str = f"{coverage:.2f}"
    color = get_badge_color(coverage)
    new_badge = f"[![Coverage](https://img.shields.io/badge/coverage-{coverage_str}%25-{color}.svg)](./htmlcov/index.html)"

    # Pattern to match existing coverage badge
    pattern = r"\[!\[Coverage\]\(https://img\.shields\.io/badge/coverage-[\d.]+%25-\w+\.svg\)\]\(.*?\)"

    if re.search(pattern, content):
        # Replace existing badge
        new_content = re.sub(pattern, new_badge, content)
        print(f"✓ Updated coverage badge: {coverage_str}% ({color})")
    else:
        print("Warning: Coverage badge not found in README.md")
        print("Please add the badge manually or ensure it follows the expected format.")
        sys.exit(1)

    with open(readme_file, "w") as f:
        f.write(new_content)


def main() -> None:
    """Main entry point."""
    coverage = get_coverage_percentage()
    print(f"Current coverage: {coverage:.2f}%")

    update_readme(coverage)

    print("\n✓ Coverage badge updated successfully!")
    print("  View coverage report: open htmlcov/index.html")


if __name__ == "__main__":
    main()
