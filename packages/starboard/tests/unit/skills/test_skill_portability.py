# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-1 B4 guardrail: canonical skills conform to the Agent Skills open standard.

Task B4 ships the skills-only bundle down the external-customer distribution
channel (``databricks aitools`` / the open-source Skills CLI — see
``docs/distribution/databricks-aitools.md``). Those channels install skills into
*many* non-Claude agents (Copilot, Cursor, Codex, …), so a skill that leans on
Claude-Code-only frontmatter is a portability hazard.

This test pins the bundle to the **portable field set** defined by the Agent
Skills specification (agentskills.io/specification, verified 2026-08-26):

    name          required   max 64,  lowercase alnum + single hyphens, == dir name
    description   required   max 1024, non-empty
    license       optional
    compatibility optional   max 500
    metadata      optional   map<str, str>
    allowed-tools optional   space-separated string (experimental)

Any frontmatter key outside that set is a Claude-Code-only (or otherwise
non-portable) field and fails the test, so drift is caught before it ships to
external customers. The channel/manifest specifics that remain UNCONFIRMED are
documented (with owner questions) in ``docs/distribution/databricks-aitools.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# The complete portable frontmatter field set per the Agent Skills spec.
# Nothing outside this set may appear in a canonical SKILL.md.
PORTABLE_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)

# Spec constraints (agentskills.io/specification).
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
# name: 1-64 chars, lowercase alnum + hyphens, no leading/trailing/consecutive hyphens.
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---\r?\n", re.DOTALL)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise AssertionError("could not locate repo root containing packages/starboard-skills/skills")


REPO_ROOT = _repo_root()
CANONICAL_SKILLS_ROOT = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"


def _parse_frontmatter(text: str) -> dict:
    match = _FRONTMATTER_RE.match(text)
    assert match is not None, "SKILL.md must open with fenced YAML frontmatter ('---' ... '---')"
    data = yaml.safe_load(match.group("yaml"))
    assert isinstance(data, dict), "frontmatter must parse to a YAML mapping"
    return data


def _skill_dir_ids() -> list[str]:
    if not CANONICAL_SKILLS_ROOT.is_dir():
        return []
    return sorted(p.name for p in CANONICAL_SKILLS_ROOT.iterdir() if p.is_dir())


@pytest.mark.parametrize("skill_dir_id", _skill_dir_ids())
def test_frontmatter_uses_only_portable_fields(skill_dir_id: str) -> None:
    """Only Agent-Skills-standard fields may appear (flags Claude-Code-only keys)."""
    skill_file = CANONICAL_SKILLS_ROOT / skill_dir_id / "SKILL.md"
    fm = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    extra = set(fm) - PORTABLE_FIELDS
    assert not extra, (
        f"{skill_dir_id}: non-portable frontmatter field(s) {sorted(extra)} — the Agent Skills "
        f"standard only defines {sorted(PORTABLE_FIELDS)}; Claude-Code-only fields break the "
        f"`databricks aitools` / Skills-CLI external-customer install (see "
        f"docs/distribution/databricks-aitools.md)"
    )


@pytest.mark.parametrize("skill_dir_id", _skill_dir_ids())
def test_name_conforms_to_spec(skill_dir_id: str) -> None:
    """`name` is required, spec-shaped, and equals the parent directory name."""
    skill_file = CANONICAL_SKILLS_ROOT / skill_dir_id / "SKILL.md"
    fm = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    name = fm.get("name")
    assert isinstance(name, str) and name, f"{skill_dir_id}: 'name' is required"
    assert len(name) <= NAME_MAX, f"{skill_dir_id}: name exceeds {NAME_MAX} chars"
    assert _NAME_RE.match(name), (
        f"{skill_dir_id}: name {name!r} must be lowercase alphanumerics + single hyphens "
        f"(no leading/trailing/consecutive hyphens)"
    )
    assert name == skill_dir_id, (
        f"{skill_dir_id}: spec requires name to match the parent directory ({name!r})"
    )


@pytest.mark.parametrize("skill_dir_id", _skill_dir_ids())
def test_description_conforms_to_spec(skill_dir_id: str) -> None:
    """`description` is required, non-empty, and within the 1024-char cap."""
    skill_file = CANONICAL_SKILLS_ROOT / skill_dir_id / "SKILL.md"
    fm = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    desc = fm.get("description")
    assert isinstance(desc, str) and desc.strip(), f"{skill_dir_id}: 'description' is required"
    assert len(desc) <= DESCRIPTION_MAX, (
        f"{skill_dir_id}: description is {len(desc)} chars, exceeds spec max {DESCRIPTION_MAX}"
    )


@pytest.mark.parametrize("skill_dir_id", _skill_dir_ids())
def test_optional_fields_conform_to_spec(skill_dir_id: str) -> None:
    """When present, optional fields obey their spec constraints."""
    skill_file = CANONICAL_SKILLS_ROOT / skill_dir_id / "SKILL.md"
    fm = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))

    if "compatibility" in fm:
        compat = fm["compatibility"]
        assert isinstance(compat, str) and compat.strip(), (
            f"{skill_dir_id}: compatibility must be a non-empty string"
        )
        assert len(compat) <= COMPATIBILITY_MAX, (
            f"{skill_dir_id}: compatibility exceeds spec max {COMPATIBILITY_MAX}"
        )

    if "metadata" in fm:
        meta = fm["metadata"]
        assert isinstance(meta, dict), f"{skill_dir_id}: metadata must be a mapping"
        for key, value in meta.items():
            assert isinstance(key, str) and isinstance(value, str), (
                f"{skill_dir_id}: metadata must map string keys to string values"
            )

    if "allowed-tools" in fm:
        # The spec models allowed-tools as a single space-separated string.
        assert isinstance(fm["allowed-tools"], str), (
            f"{skill_dir_id}: allowed-tools must be a string (space-separated per spec)"
        )
