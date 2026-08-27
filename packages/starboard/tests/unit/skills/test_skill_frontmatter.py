# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-0 A2 guardrails: one canonical skill tree with valid fenced frontmatter.

Enforces the locked decision D-0.1: the single canonical skills location is
``packages/starboard-skills/skills/starboard/<domain>/SKILL.md``. Each ``SKILL.md``
must open with fenced YAML frontmatter carrying ``name``, ``description``, and
``allowed-tools``. The duplicate tree ``packages/starboard/skills/`` must not exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


def _repo_root() -> Path:
    """Walk up from this file until the canonical skills package is found."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise AssertionError("could not locate repo root containing packages/starboard-skills/skills")


REPO_ROOT = _repo_root()
CANONICAL_SKILLS_ROOT = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"
DUPLICATE_SKILLS_ROOT = REPO_ROOT / "packages" / "starboard" / "skills"

# The 9 domains locked for Phase 0 (D-0.1).
EXPECTED_DOMAINS = {
    "analyze",
    "cluster",
    "diagnostic",
    "discovery",
    "finops",
    "job",
    "query",
    "uc",
    "warehouse",
    "workload-review",  # Phase-3 D1b flagship review skill
}

# Fenced YAML frontmatter: a leading '---' line, a body, and a closing '---' line.
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---\r?\n", re.DOTALL)


def _domain_dirs() -> list[Path]:
    return sorted(p for p in CANONICAL_SKILLS_ROOT.iterdir() if p.is_dir())


def _domain_of(dir_path: Path) -> str:
    """Bare domain name, e.g. 'starboard-query' -> 'query'."""
    return dir_path.name.removeprefix("starboard-")


def _parse_frontmatter(text: str) -> dict:
    match = _FRONTMATTER_RE.match(text)
    assert match is not None, "SKILL.md must open with fenced YAML frontmatter ('---' ... '---')"
    data = yaml.safe_load(match.group("yaml"))
    assert isinstance(data, dict), "frontmatter must parse to a YAML mapping"
    return data


def _skill_dir_ids() -> list[str]:
    if not CANONICAL_SKILLS_ROOT.is_dir():
        return []
    return [p.name for p in _domain_dirs()]


def test_canonical_tree_exists() -> None:
    assert CANONICAL_SKILLS_ROOT.is_dir(), (
        f"canonical skills tree missing at {CANONICAL_SKILLS_ROOT}"
    )


def test_duplicate_tree_removed() -> None:
    assert not DUPLICATE_SKILLS_ROOT.exists(), (
        f"duplicate skill tree must be deleted (D-0.1): {DUPLICATE_SKILLS_ROOT}"
    )


def test_exactly_ten_domains() -> None:
    domains = {_domain_of(d) for d in _domain_dirs()}
    assert domains == EXPECTED_DOMAINS, (
        f"expected domains {sorted(EXPECTED_DOMAINS)}, got {sorted(domains)}"
    )


def test_no_leftover_lowercase_skill_md() -> None:
    leftovers = list(CANONICAL_SKILLS_ROOT.rglob("skill.md"))
    assert not leftovers, f"lowercase skill.md must be renamed to SKILL.md: {leftovers}"


@pytest.mark.parametrize("skill_dir_id", _skill_dir_ids())
def test_exactly_one_skill_md_per_domain(skill_dir_id: str) -> None:
    skill_dir = CANONICAL_SKILLS_ROOT / skill_dir_id
    skill_files = list(skill_dir.glob("SKILL.md"))
    assert len(skill_files) == 1, f"{skill_dir_id} must have exactly one SKILL.md, found {skill_files}"


@pytest.mark.parametrize("skill_dir_id", _skill_dir_ids())
def test_frontmatter_valid_and_named(skill_dir_id: str) -> None:
    skill_dir = CANONICAL_SKILLS_ROOT / skill_dir_id
    skill_file = skill_dir / "SKILL.md"
    assert skill_file.is_file(), f"missing {skill_file}"

    fm = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))

    # Required fields.
    assert "name" in fm, f"{skill_dir_id}: frontmatter missing 'name'"
    assert "description" in fm, f"{skill_dir_id}: frontmatter missing 'description'"
    assert "allowed-tools" in fm, f"{skill_dir_id}: frontmatter missing 'allowed-tools'"

    # name == starboard-<domain> (== the directory name).
    domain = _domain_of(skill_dir)
    assert fm["name"] == f"starboard-{domain}", (
        f"{skill_dir_id}: name should be 'starboard-{domain}', got {fm['name']!r}"
    )

    # description is non-empty and drives auto-invocation.
    assert isinstance(fm["description"], str) and fm["description"].strip(), (
        f"{skill_dir_id}: description must be a non-empty string"
    )

    # allowed-tools pre-approves the helper CLI + Read.
    assert "starboard-helper" in str(fm["allowed-tools"]), (
        f"{skill_dir_id}: allowed-tools should pre-approve starboard-helper"
    )


@pytest.mark.parametrize("skill_dir_id", _skill_dir_ids())
def test_dual_mode_body_preserved(skill_dir_id: str) -> None:
    """The richer dual-mode body (MCP path vs starboard-helper) must survive."""
    skill_file = CANONICAL_SKILLS_ROOT / skill_dir_id / "SKILL.md"
    body = skill_file.read_text(encoding="utf-8")
    assert "starboard-helper" in body, f"{skill_dir_id}: dual-mode CLI path lost"
    assert "MCP" in body, f"{skill_dir_id}: dual-mode MCP path lost"
