#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Vendor the canonical Starboard skills tree into the aitools distribution mirror.

Single source of truth: ``packages/starboard-skills/skills/starboard/``.
This script mirrors that tree into ``packages/starboard-distribution/aitools/``
as **real files** (not symlinks) and emits a ``manifest.json`` bundle index.

The mirror layout aligns to the confirmed agent-skills distribution format from
``databricks-solutions/ai-dev-kit`` (https://github.com/databricks-solutions/ai-dev-kit):
each skill is a directory containing ``SKILL.md`` (+ optional ``scripts/``,
``references/``, etc.), with frontmatter validated against the Agent Skills
specification (https://agentskills.io/specification).

The ``manifest.json`` is a generated bundle index (not part of the ai-dev-kit
format itself — see note below) that records every skill's name, path, and
description extracted from its ``SKILL.md`` frontmatter.

Note on ai-dev-kit format:
    Confirmed (2026-08-27) from databricks-solutions/ai-dev-kit @main:
    - Distribution format: skill directories under ``<host>/skills/<name>/SKILL.md``
    - Frontmatter: ``name`` (required, ≤64 chars, lowercase alnum+hyphens) and
      ``description`` (required, ≤1024 chars, non-empty) — same as Agent Skills spec.
    - ``validate_skills.py`` in ai-dev-kit enforces these constraints.
    - The ``.claude-plugin/plugin.json`` is deprecated; skills now ship via
      ``databricks aitools install`` from a separate ``databricks-agent-skills``
      repo.  No bundle-level ``manifest.json`` exists in ai-dev-kit itself.
    - The ``.test/skills/<name>/manifest.yaml`` files are internal evaluation
      manifests (scorers, trace_expectations, quality_gates) — not distribution.
    - ``manifest.json`` here is a best-effort bundle index we generate for
      downstream tooling (drift-check CI, discovery, docs).

Usage::

    python scripts/skills.py            # vendor + generate manifest
    python scripts/skills.py --check    # verify mirror in sync (CI/drift guard)

``--check`` exits non-zero (without writing) when the mirror has drifted from
the canonical source or when any frontmatter validation error is found.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Paths (resolved from script location so the script works from any cwd)
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Walk up from this file until we find the monorepo root."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise SystemExit(
        "could not locate repo root containing packages/starboard-skills/skills"
    )


REPO_ROOT = _repo_root()
CANONICAL_SKILLS = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"
MIRROR_ROOT = REPO_ROOT / "packages" / "starboard-distribution" / "aitools"
MANIFEST_PATH = MIRROR_ROOT / "manifest.json"

# Bundle metadata (bump alongside skills package version)
_BUNDLE_VERSION = "0.1.0"
_BUNDLE_NAME = "starboard"

# ---------------------------------------------------------------------------
# Frontmatter validation (mirrors ai-dev-kit validate_skills.py rules +
# Agent Skills spec constraints — agentskills.io/specification)
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_XML_TAG_RE = re.compile(r"<[^>]+>")
_RESERVED_WORDS = {"anthropic", "claude"}
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---\r?\n", re.DOTALL)

NAME_MAX = 64
DESCRIPTION_MAX = 1024


def _parse_frontmatter(text: str, path: Path) -> dict[str, Any]:
    """Parse and return YAML frontmatter; raise ValueError on failure."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError(f"{path}: SKILL.md must open with fenced YAML frontmatter")
    data = yaml.safe_load(match.group("yaml"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: frontmatter must parse to a YAML mapping")
    return data


def _validate_frontmatter(fm: dict[str, Any], skill_dir_name: str) -> list[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: list[str] = []

    # name — required
    name = fm.get("name")
    if not name:
        errors.append(f"{skill_dir_name}: 'name' is required")
    else:
        name = str(name)
        if len(name) > NAME_MAX:
            errors.append(
                f"{skill_dir_name}: name '{name}' exceeds {NAME_MAX} chars ({len(name)})"
            )
        if not _NAME_RE.match(name):
            errors.append(
                f"{skill_dir_name}: name '{name}' must be lowercase alnum + single hyphens"
            )
        if _XML_TAG_RE.search(name):
            errors.append(f"{skill_dir_name}: name '{name}' must not contain XML tags")
        for word in _RESERVED_WORDS:
            if word in name:
                errors.append(
                    f"{skill_dir_name}: name '{name}' must not contain reserved word '{word}'"
                )
        if name != skill_dir_name:
            errors.append(
                f"{skill_dir_name}: spec requires name to match directory name "
                f"(got '{name}', expected '{skill_dir_name}')"
            )

    # description — required
    desc = fm.get("description")
    if not desc or not str(desc).strip():
        errors.append(f"{skill_dir_name}: 'description' is required and non-empty")
    else:
        desc = str(desc)
        if len(desc) > DESCRIPTION_MAX:
            errors.append(
                f"{skill_dir_name}: description exceeds {DESCRIPTION_MAX} chars ({len(desc)})"
            )
        if _XML_TAG_RE.search(desc):
            errors.append(f"{skill_dir_name}: description must not contain XML tags")

    return errors


# ---------------------------------------------------------------------------
# Diff helpers (same approach as vendor_plugin_skills.py)
# ---------------------------------------------------------------------------

def _relative_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _diff_trees(source: Path, dest: Path) -> tuple[set[str], set[str], set[str]]:
    """Return (only_in_source, only_in_dest, content_differs) relative path sets."""
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


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def _build_manifest(skill_dirs: list[Path]) -> dict[str, Any]:
    """Generate the bundle manifest.json from the skill directories.

    Schema (best-effort bundle index — no formal ai-dev-kit bundle manifest):
    {
      "schema_version": "1.0",
      "bundle_name": "starboard",
      "bundle_version": "<version>",
      "description": "...",
      "format": "agent-skills",
      "repository": "https://github.com/databricks/starboard",
      "generated_at": "<ISO-8601 UTC>",
      "skills": [
        {
          "name": "<skill-name>",
          "path": "<skill-name>/",
          "description": "<frontmatter description>",
          "allowed_tools": "<frontmatter allowed-tools or null>"
        },
        ...
      ]
    }
    """
    skills: list[dict[str, Any]] = []
    for skill_dir in sorted(skill_dirs, key=lambda d: d.name):
        skill_md = skill_dir / "SKILL.md"
        fm = _parse_frontmatter(skill_md.read_text(encoding="utf-8"), skill_md)
        entry: dict[str, Any] = {
            "name": fm["name"],
            "path": f"{skill_dir.name}/",
            "description": str(fm.get("description", "")).strip(),
        }
        allowed = fm.get("allowed-tools")
        if allowed:
            entry["allowed_tools"] = str(allowed)
        skills.append(entry)

    return {
        "schema_version": "1.0",
        "bundle_name": _BUNDLE_NAME,
        "bundle_version": _BUNDLE_VERSION,
        "description": (
            "AI-powered Databricks workload analysis: queries, jobs, Unity Catalog, "
            "clusters, FinOps, warehouses, and diagnostics. Skills-only bundle — "
            "no MCP server required."
        ),
        "format": "agent-skills",
        "repository": "https://github.com/databricks/starboard",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "skills": skills,
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def vendor() -> int:
    """Mirror the canonical skills tree to the aitools distribution dir + generate manifest."""
    if not CANONICAL_SKILLS.is_dir():
        print(f"ERROR: canonical skills tree missing: {CANONICAL_SKILLS}", file=sys.stderr)
        return 1

    skill_dirs = sorted(
        [d for d in CANONICAL_SKILLS.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )
    if not skill_dirs:
        print(f"ERROR: no skill directories found under {CANONICAL_SKILLS}", file=sys.stderr)
        return 1

    # Validate all frontmatter before touching the mirror
    all_errors: list[str] = []
    for skill_dir in skill_dirs:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            all_errors.append(f"{skill_dir.name}: SKILL.md missing")
            continue
        try:
            fm = _parse_frontmatter(skill_md.read_text(encoding="utf-8"), skill_md)
        except ValueError as exc:
            all_errors.append(str(exc))
            continue
        all_errors.extend(_validate_frontmatter(fm, skill_dir.name))

    if all_errors:
        print("Frontmatter validation failed:", file=sys.stderr)
        for err in all_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    # Replace mirror with a clean copy of the canonical tree
    if MIRROR_ROOT.is_symlink() or MIRROR_ROOT.is_file():
        MIRROR_ROOT.unlink()
    elif MIRROR_ROOT.is_dir():
        # Remove skill dirs + manifest; preserve anything else (e.g. README.md)
        for item in list(MIRROR_ROOT.iterdir()):
            if item.is_dir():
                shutil.rmtree(item)
            elif item.name in ("manifest.json",):
                item.unlink()
    MIRROR_ROOT.mkdir(parents=True, exist_ok=True)

    # Copy each skill directory
    for skill_dir in skill_dirs:
        dest = MIRROR_ROOT / skill_dir.name
        shutil.copytree(skill_dir, dest)

    # Generate manifest.json
    manifest = _build_manifest([MIRROR_ROOT / d.name for d in skill_dirs])
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    file_count = len(_relative_files(MIRROR_ROOT))
    print(
        f"Vendored {len(skill_dirs)} skill(s), {file_count} file(s) -> "
        f"{MIRROR_ROOT.relative_to(REPO_ROOT)}"
    )
    print(f"Generated manifest.json ({len(skill_dirs)} skills).")
    return 0


def check() -> int:
    """Verify the mirror is in sync with the canonical source (no writes)."""
    if not MIRROR_ROOT.exists():
        print(
            f"DRIFT: mirror not found at {MIRROR_ROOT}\n"
            "Run: python scripts/skills.py",
            file=sys.stderr,
        )
        return 1

    # Compare skill file trees (canonical vs mirror; exclude manifest.json)
    only_source, only_dest, differing = _diff_trees(CANONICAL_SKILLS, MIRROR_ROOT)
    # Exclude manifest.json from only_dest (it's generated, not in canonical)
    only_dest.discard("manifest.json")

    if only_source or only_dest or differing:
        print("DRIFT: aitools mirror is out of sync with the canonical source.")
        if only_source:
            print(f"  missing from mirror:  {sorted(only_source)}")
        if only_dest:
            print(f"  stale in mirror:      {sorted(only_dest)}")
        if differing:
            print(f"  content differs:      {sorted(differing)}")
        print("Run: python scripts/skills.py", file=sys.stderr)
        return 1

    # Validate manifest.json exists and is well-formed
    if not MANIFEST_PATH.exists():
        print(
            f"DRIFT: manifest.json missing at {MANIFEST_PATH}\n"
            "Run: python scripts/skills.py",
            file=sys.stderr,
        )
        return 1

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: manifest.json is invalid JSON: {exc}", file=sys.stderr)
        return 1

    # Basic schema check
    missing_keys = {"schema_version", "bundle_name", "skills"} - set(manifest)
    if missing_keys:
        print(f"ERROR: manifest.json missing keys: {sorted(missing_keys)}", file=sys.stderr)
        return 1

    canonical_names = {d.name for d in CANONICAL_SKILLS.iterdir() if d.is_dir()}
    manifest_names = {s["name"] for s in manifest.get("skills", [])}
    if canonical_names != manifest_names:
        extra = manifest_names - canonical_names
        missing = canonical_names - manifest_names
        if missing:
            print(f"ERROR: manifest missing skills: {sorted(missing)}", file=sys.stderr)
        if extra:
            print(f"ERROR: manifest has unknown skills: {sorted(extra)}", file=sys.stderr)
        return 1

    skill_count = len(manifest["skills"])
    print(
        f"OK: aitools mirror in sync with canonical source "
        f"({skill_count} skill(s), manifest valid)."
    )
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the mirror is in sync (no writes); exits non-zero on drift.",
    )
    args = parser.parse_args(argv)
    return check() if args.check else vendor()


if __name__ == "__main__":
    raise SystemExit(main())
