#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Vendor the canonical Starboard skills tree into the self-contained plugin.

Single source of truth: ``packages/starboard-skills/skills/starboard/``.
This script mirrors that tree into ``plugin/skills/`` as **real files** (not a
symlink) so a copied/published plugin ships every skill. The skill folders
(``starboard-query/`` … ``starboard-analyze/``) land directly under
``plugin/skills/`` — the same layout the old ``plugin/skills`` symlink exposed
(it pointed straight at the canonical ``starboard`` dir), so the plugin's
``"skills": "./skills/"`` declaration keeps resolving each skill unchanged. The
plugin must be self-contained — no path escaping the plugin root — so the symlink
that used to stand in for this vendoring step is replaced by materialized files
kept in sync by running this script.

Usage::

    python scripts/vendor_plugin_skills.py           # mirror (overwrite + prune)
    python scripts/vendor_plugin_skills.py --check    # verify in sync (CI/drift guard)

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
    raise SystemExit("could not locate repo root containing packages/starboard-skills/skills")


REPO_ROOT = _repo_root()
CANONICAL_SKILLS = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"
# The plugin's skills dir mirrors the *contents* of the canonical ``starboard``
# tree directly (skill folders land under ``plugin/skills/``), matching the old
# symlink target and the plugin's ``"skills": "./skills/"`` declaration.
VENDORED_SKILLS = REPO_ROOT / "plugin" / "skills"


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


def check() -> int:
    """Verify the vendored tree is in sync; return a process exit code."""
    if VENDORED_SKILLS.is_symlink():
        print(
            f"DRIFT: {VENDORED_SKILLS} is a symlink — the plugin must ship real files.\n"
            f"Run: python scripts/vendor_plugin_skills.py",
            file=sys.stderr,
        )
        return 1
    only_source, only_dest, differing = _diff(CANONICAL_SKILLS, VENDORED_SKILLS)
    if only_source or only_dest or differing:
        print("DRIFT: vendored plugin skills are out of sync with the canonical source.")
        if only_source:
            print(f"  missing from plugin:  {sorted(only_source)}")
        if only_dest:
            print(f"  stale in plugin:      {sorted(only_dest)}")
        if differing:
            print(f"  content differs:      {sorted(differing)}")
        print("Run: python scripts/vendor_plugin_skills.py", file=sys.stderr)
        return 1
    print("OK: plugin/skills is in sync with the canonical source.")
    return 0


def vendor() -> int:
    """Mirror the canonical tree into the plugin (overwrite + prune)."""
    if not CANONICAL_SKILLS.is_dir():
        raise SystemExit(f"canonical skills tree missing: {CANONICAL_SKILLS}")
    # Replace whatever is there (symlink or stale tree) with a clean real copy.
    if VENDORED_SKILLS.is_symlink() or VENDORED_SKILLS.is_file():
        VENDORED_SKILLS.unlink()
    elif VENDORED_SKILLS.is_dir():
        shutil.rmtree(VENDORED_SKILLS)
    VENDORED_SKILLS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(CANONICAL_SKILLS, VENDORED_SKILLS)
    count = len(_relative_files(VENDORED_SKILLS))
    print(f"Vendored {count} file(s) -> {VENDORED_SKILLS.relative_to(REPO_ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the vendored tree is in sync (no writes); non-zero on drift.",
    )
    args = parser.parse_args(argv)
    return check() if args.check else vendor()


if __name__ == "__main__":
    raise SystemExit(main())
