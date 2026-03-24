#!/usr/bin/env python3
"""Validate that all agents use shared prompt modules correctly.

This script checks that:
1. All agent prompts import required shared modules
2. No inline handoff sections exist (should use shared module)
3. All prompts have PROMPT_VERSION exported

Run: python scripts/validate_prompt_alignment.py
"""

import sys
from pathlib import Path

# Required imports for all agent prompts
REQUIRED_IMPORTS = [
    "DATA_LISTING_GUIDELINES",
    "TOOL_EXECUTION_GUIDELINES",
    "build_handoff_section",
]

# Agent prompt files to validate
AGENT_FILES = [
    "prompts/query/v1.py",
    "prompts/job/v1.py",
    "prompts/uc/v1.py",
    "prompts/compute/v1.py",
    "prompts/diagnostic/v1.py",
    "prompts/analytics/v1.py",
    "prompts/warehouse/v1.py",
]

# Pattern indicating inline handoff (should be removed)
INLINE_HANDOFF_PATTERN = "**Resource IDs (use directly without asking user):**"


def check_imports(file_path: Path) -> list[str]:
    """Check if file imports all required shared modules."""
    content = file_path.read_text()
    missing = []
    for imp in REQUIRED_IMPORTS:
        if imp not in content:
            missing.append(imp)
    return missing


def check_no_inline_handoff(file_path: Path) -> bool:
    """Check that file doesn't have inline handoff section."""
    content = file_path.read_text()
    return INLINE_HANDOFF_PATTERN not in content


def check_prompt_version(file_path: Path) -> bool:
    """Check that file exports PROMPT_VERSION."""
    content = file_path.read_text()
    return "PROMPT_VERSION" in content


def main() -> int:
    """Run validation checks on all agent prompts."""
    base_path = Path("packages/starboard-server/starboard_server")
    errors: list[str] = []
    warnings: list[str] = []

    print("=" * 60)
    print("Prompt Alignment Validation")
    print("=" * 60)

    for agent_file in AGENT_FILES:
        file_path = base_path / agent_file
        agent_name = agent_file.split("/")[1]

        if not file_path.exists():
            errors.append(f"❌ {agent_name}: File not found: {agent_file}")
            continue

        print(f"\nChecking {agent_name}...")

        # Check imports
        missing = check_imports(file_path)
        if missing:
            errors.append(f"❌ {agent_name}: Missing imports: {missing}")
        else:
            print("  ✅ All required imports present")

        # Check for inline handoff
        if not check_no_inline_handoff(file_path):
            errors.append(
                f"❌ {agent_name}: Contains inline handoff (should use shared module)"
            )
        else:
            print("  ✅ No inline handoff section")

        # Check PROMPT_VERSION
        if not check_prompt_version(file_path):
            warnings.append(f"⚠️  {agent_name}: Missing PROMPT_VERSION")
        else:
            print("  ✅ PROMPT_VERSION defined")

    print("\n" + "=" * 60)
    print("Results")
    print("=" * 60)

    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  {warning}")

    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  {error}")
        print(f"\n❌ Validation FAILED with {len(errors)} error(s)")
        return 1
    else:
        print("\n✅ All agents correctly use shared modules")
        return 0


if __name__ == "__main__":
    sys.exit(main())
