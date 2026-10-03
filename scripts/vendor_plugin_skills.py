#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Vendor the canonical Starboard skills trees into the self-contained plugins.

**Public plugin** (default):
  Source:  ``packages/starboard-skills/skills/starboard/``
  Dest:    ``plugin/skills/``

**Internal plugin** (``--internal``):
  Source:  ``packages/starboard-internal/skills/``
  Dest:    ``plugin-internal/skills/``

The internal plugin is INTERNAL-ONLY — it names internal tools and data sources
that are governance-restricted.  It must never be published to the public mirror,
the aitools distribution, or opencode bundles.

Usage::

    python scripts/vendor_plugin_skills.py              # vendor public plugin
    python scripts/vendor_plugin_skills.py --check      # check public plugin (CI)
    python scripts/vendor_plugin_skills.py --internal   # vendor internal plugin
    python scripts/vendor_plugin_skills.py --internal --check  # check internal (CI)

``--check`` exits non-zero (without writing) when the vendored tree has drifted
from the canonical source, printing what differs.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Walk up until the repo root (holds the canonical skills tree)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise SystemExit(
        "could not locate repo root "
        "(expected packages/starboard-skills/skills or packages/starboard-internal/skills)"
    )


REPO_ROOT = _repo_root()

# ---------------------------------------------------------------------------
# Public plugin: canonical → vendored pair
# ---------------------------------------------------------------------------
# The plugin's skills dir mirrors the *contents* of the canonical ``starboard``
# tree directly (skill folders land under ``plugin/skills/``), matching the old
# symlink target and the plugin's ``"skills": "./skills/"`` declaration.
CANONICAL_SKILLS = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"
VENDORED_SKILLS = REPO_ROOT / "plugin" / "skills"

# ---------------------------------------------------------------------------
# Internal plugin: canonical → vendored pair
# ---------------------------------------------------------------------------
# INTERNAL-ONLY. ``packages/starboard-internal/skills/`` is the source of truth;
# ``plugin-internal/skills/`` is the self-contained copy shipped in the internal
# plugin.  Must never appear in public wheels, aitools, or opencode bundles.
CANONICAL_SKILLS_INTERNAL = REPO_ROOT / "packages" / "starboard-internal" / "skills"
VENDORED_SKILLS_INTERNAL = REPO_ROOT / "plugin-internal" / "skills"


def _relative_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _diff(source: Path, dest: Path) -> tuple[set[str], set[str], set[str]]:
    """Return (only_in_source, only_in_dest, differing) relative-path sets."""
    src_files = _relative_files(source)
    dst_files = _relative_files(dest) if dest.exists() else set()
    only_source = src_files - dst_files
    only_dest = dst_files - src_files
    differing = {
        rel
        for rel in src_files & dst_files
        if not filecmp.cmp(source / rel, dest / rel, shallow=False)
    }
    return only_source, only_dest, differing


def _label(canonical: Path) -> str:
    """Short label for error messages."""
    return canonical.relative_to(REPO_ROOT).as_posix()


def check(canonical: Path, vendored: Path) -> int:
    """Verify the vendored tree is in sync; return a process exit code."""
    if vendored.is_symlink():
        print(
            f"DRIFT: {vendored} is a symlink — the plugin must ship real files.\n"
            f"Run: python scripts/vendor_plugin_skills.py"
            + (" --internal" if canonical == CANONICAL_SKILLS_INTERNAL else ""),
            file=sys.stderr,
        )
        return 1
    only_source, only_dest, differing = _diff(canonical, vendored)
    if only_source or only_dest or differing:
        label = _label(canonical)
        print(f"DRIFT: vendored plugin skills are out of sync with {label}.")
        if only_source:
            print(f"  missing from plugin:  {sorted(only_source)}")
        if only_dest:
            print(f"  stale in plugin:      {sorted(only_dest)}")
        if differing:
            print(f"  content differs:      {sorted(differing)}")
        flag = " --internal" if canonical == CANONICAL_SKILLS_INTERNAL else ""
        print(f"Run: python scripts/vendor_plugin_skills.py{flag}", file=sys.stderr)
        return 1
    dest_rel = vendored.relative_to(REPO_ROOT).as_posix()
    print(f"OK: {dest_rel} is in sync with the canonical source.")
    return 0


def vendor(canonical: Path, vendored: Path) -> int:
    """Mirror the canonical tree into the plugin (overwrite + prune)."""
    if not canonical.is_dir():
        raise SystemExit(f"canonical skills tree missing: {canonical}")
    # Replace whatever is there (symlink or stale tree) with a clean real copy.
    if vendored.is_symlink() or vendored.is_file():
        vendored.unlink()
    elif vendored.is_dir():
        shutil.rmtree(vendored)
    vendored.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(canonical, vendored)
    count = len(_relative_files(vendored))
    dest_rel = vendored.relative_to(REPO_ROOT).as_posix()
    print(f"Vendored {count} file(s) -> {dest_rel}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the vendored tree is in sync (no writes); non-zero on drift.",
    )
    parser.add_argument(
        "--internal",
        action="store_true",
        help=(
            "Operate on the INTERNAL plugin pair "
            "(packages/starboard-internal/skills/ → plugin-internal/skills/). "
            "INTERNAL-ONLY — never publish this bundle."
        ),
    )
    args = parser.parse_args(argv)

    if args.internal:
        canonical, vendored = CANONICAL_SKILLS_INTERNAL, VENDORED_SKILLS_INTERNAL
    else:
        canonical, vendored = CANONICAL_SKILLS, VENDORED_SKILLS

    return check(canonical, vendored) if args.check else vendor(canonical, vendored)


if __name__ == "__main__":
    raise SystemExit(main())
