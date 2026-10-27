#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Check documentation staleness.

Detects documentation that may be outdated based on:
- Last modified date
- Code changes without doc updates
- Missing documentation for new code
"""

import re
import sys
from datetime import datetime
from pathlib import Path

# Staleness threshold (days)
STALE_THRESHOLD_DAYS = 90

# Directories to check
CODE_DIRS = ["packages/starboard-server", "packages/starboard-core"]
DOC_DIRS = ["docs"]


def get_file_age(file_path: Path) -> int:
    """Get file age in days since last modification."""
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
    age = datetime.now() - mtime
    return age.days


def find_undocumented_tools(project_root: Path) -> list[str]:
    """Find tools that aren't documented in tool catalog."""
    tool_catalog = project_root / "docs" / "tools" / "TOOL_CATALOG.md"

    if not tool_catalog.exists():
        return []

    # Read tool catalog
    catalog_content = tool_catalog.read_text()

    # Find tool adapter files
    tools_dir = (
        project_root
        / "packages"
        / "starboard-server"
        / "starboard"
        / "tools"
        / "adapters"
    )
    undocumented = []

    if tools_dir.exists():
        for tool_file in tools_dir.glob("*.py"):
            if tool_file.name == "__init__.py":
                continue

            # Read tool file and find async def methods
            # Use stricter regex to only match actual method definitions
            # (indented with spaces, not in docstrings)
            content = tool_file.read_text()
            # Match class method definitions (indented async def at start of line)
            methods = re.findall(r"^\s{4}async def (\w+)\(", content, re.MULTILINE)

            for method in methods:
                if method.startswith("_"):  # Skip private methods
                    continue

                # Check if documented (support numbered headings like ### 1. method_name)
                # Also check for backtick references
                is_documented = (
                    re.search(rf"### \d+\. {method}\b", catalog_content)
                    or f"### {method}" in catalog_content
                    or f"`{method}`" in catalog_content
                )
                if not is_documented:
                    undocumented.append(f"{tool_file.stem}.{method}")

    return undocumented


def find_stale_docs(project_root: Path) -> list[tuple[Path, int]]:
    """Find documentation files that haven't been updated recently."""
    stale_docs = []

    for doc_dir in DOC_DIRS:
        doc_path = project_root / doc_dir
        if not doc_path.exists():
            continue

        for md_file in doc_path.rglob("*.md"):
            age = get_file_age(md_file)

            if age > STALE_THRESHOLD_DAYS:
                stale_docs.append((md_file.relative_to(project_root), age))

    return sorted(stale_docs, key=lambda x: x[1], reverse=True)


def check_version_mentions(project_root: Path) -> list[tuple[Path, str]]:
    """Find documentation with old version mentions."""
    old_versions = []
    current_year = datetime.now().year

    for doc_dir in DOC_DIRS:
        doc_path = project_root / doc_dir
        if not doc_path.exists():
            continue

        for md_file in doc_path.rglob("*.md"):
            content = md_file.read_text()

            # Check for old year mentions
            for match in re.finditer(
                r"(Last Updated|Date|Updated):\s*(\d{4})", content
            ):
                year = int(match.group(2))
                if year < current_year - 1:  # More than 1 year old
                    old_versions.append(
                        (md_file.relative_to(project_root), f"References year {year}")
                    )
                    break

    return old_versions


def main():
    """Main staleness check function."""
    project_root = Path(__file__).parent.parent

    print("📅 Checking documentation staleness...")
    print(f"   Project root: {project_root}")
    print(f"   Stale threshold: {STALE_THRESHOLD_DAYS} days")
    print()

    # Check for undocumented tools
    print("🔧 Checking for undocumented tools...")
    undocumented = find_undocumented_tools(project_root)

    if undocumented:
        print(f"   ⚠️  Found {len(undocumented)} potentially undocumented tools:")
        for tool in undocumented[:50]:  # Show first 50
            print(f"      - {tool}")
        if len(undocumented) > 50:
            print(f"      ... and {len(undocumented) - 50} more")
    else:
        print("   ✅ All tools appear to be documented")

    print()

    # Check for stale documentation
    print(f"📄 Checking for stale documentation (>{STALE_THRESHOLD_DAYS} days old)...")
    stale_docs = find_stale_docs(project_root)

    if stale_docs:
        print(f"   ⚠️  Found {len(stale_docs)} stale documents:")
        for doc, age in stale_docs[:50]:  # Show first 50
            print(f"      - {doc} ({age} days old)")
        if len(stale_docs) > 50:
            print(f"      ... and {len(stale_docs) - 50} more")
    else:
        print("   ✅ All documentation is recent")

    print()

    # Check for old version mentions
    print("🗓️  Checking for old version mentions...")
    old_versions = check_version_mentions(project_root)

    if old_versions:
        print(f"   ⚠️  Found {len(old_versions)} documents with old dates:")
        for doc, issue in old_versions[:50]:  # Show first 50
            print(f"      - {doc}: {issue}")
        if len(old_versions) > 50:
            print(f"      ... and {len(old_versions) - 50} more")
    else:
        print("   ✅ All version mentions are current")

    print()
    print("=" * 70)

    # Summary
    total_issues = len(undocumented) + len(stale_docs) + len(old_versions)

    if total_issues == 0:
        print("✅ No staleness issues found!")
        sys.exit(0)
    else:
        print(f"⚠️  Found {total_issues} potential staleness issues")
        print()
        print("Note: These are warnings, not errors. Review and update as needed.")
        sys.exit(0)  # Don't fail CI, just warn


if __name__ == "__main__":
    main()
