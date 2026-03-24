#!/usr/bin/env python3
"""
Validate documentation links.

Checks all markdown files for broken internal links, missing files,
and reports issues.
"""

import re
import sys
from pathlib import Path

# Root directories to search
DOC_ROOTS = ["docs", "packages"]
# File extensions to check
EXTENSIONS = [".md"]


def find_markdown_files(root: Path) -> list[Path]:
    """Find all markdown files in directory tree."""
    files = []
    for ext in EXTENSIONS:
        files.extend(root.rglob(f"*{ext}"))
    return files


def extract_links(content: str, file_path: Path) -> list[tuple[str, int]]:
    """
    Extract markdown links from content.

    Returns list of (link_target, line_number) tuples.
    """
    links = []

    # Match [text](link) style links
    pattern = r"\[([^\]]+)\]\(([^)]+)\)"

    for line_num, line in enumerate(content.split("\n"), 1):
        for match in re.finditer(pattern, line):
            link = match.group(2)

            # Skip external links, anchors, and mailto
            if link.startswith(("http://", "https://", "#", "mailto:")):
                continue

            # Remove anchor from link
            if "#" in link:
                link = link.split("#")[0]

            if link:  # Only include non-empty links
                links.append((link, line_num))

    return links


def validate_link(link: str, source_file: Path, project_root: Path) -> tuple[bool, str]:
    """
    Validate a single link.

    Returns (is_valid, error_message).
    """
    # Resolve link relative to source file
    if link.startswith("/"):
        # Absolute from project root
        target = project_root / link.lstrip("/")
    else:
        # Relative to source file
        target = (source_file.parent / link).resolve()

    if not target.exists():
        return False, f"File not found: {target.relative_to(project_root)}"

    return True, ""


def main():
    """Main validation function."""
    project_root = Path(__file__).parent.parent

    print("🔍 Validating documentation links...")
    print(f"   Project root: {project_root}")
    print()

    total_files = 0
    total_links = 0
    broken_links = []

    # Check each documentation root
    for doc_root in DOC_ROOTS:
        root_path = project_root / doc_root
        if not root_path.exists():
            print(f"⚠️  Skipping {doc_root}/ (not found)")
            continue

        print(f"📂 Checking {doc_root}/")

        # Find all markdown files
        files = find_markdown_files(root_path)
        total_files += len(files)

        for file_path in files:
            # Read file content
            try:
                content = file_path.read_text()
            except Exception as e:
                print(f"   ❌ Error reading {file_path.relative_to(project_root)}: {e}")
                continue

            # Extract links
            links = extract_links(content, file_path)
            total_links += len(links)

            # Validate each link
            for link, line_num in links:
                is_valid, error = validate_link(link, file_path, project_root)

                if not is_valid:
                    broken_links.append(
                        {
                            "file": file_path.relative_to(project_root),
                            "line": line_num,
                            "link": link,
                            "error": error,
                        }
                    )

    # Report results
    print()
    print("=" * 70)
    print("📊 Results:")
    print(f"   Files checked: {total_files}")
    print(f"   Links checked: {total_links}")
    print(f"   Broken links: {len(broken_links)}")
    print("=" * 70)

    if broken_links:
        print()
        print("❌ Broken links found:")
        print()

        for issue in broken_links:
            print(f"   {issue['file']}:{issue['line']}")
            print(f"      Link: {issue['link']}")
            print(f"      Error: {issue['error']}")
            print()

        sys.exit(1)
    else:
        print()
        print("✅ All links are valid!")
        sys.exit(0)


if __name__ == "__main__":
    main()
