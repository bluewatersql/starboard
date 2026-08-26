# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Review fix #2: the plugin must be self-contained (vendored real skills).

``plugin/skills`` used to be a symlink to ``../packages/starboard-skills/skills/starboard``,
escaping the plugin root — so a copied/published plugin shipped zero skills. It
must instead be a **materialized real directory** mirroring the canonical tree,
kept in sync by ``scripts/vendor_plugin_skills.py`` (single source of truth stays
``packages/starboard-skills/skills/starboard``). The skill folders land directly
under ``plugin/skills/`` (matching the old symlink target and the plugin's
``"skills": "./skills/"`` declaration).

This is the drift guard:
- ``plugin/skills`` exists as real files (not a symlink), and
- its ``SKILL.md`` set and byte contents match the canonical source.

On failure, run ``python scripts/vendor_plugin_skills.py`` to re-sync.
"""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise AssertionError("could not locate repo root containing packages/starboard-skills/skills")


REPO_ROOT = _repo_root()
VENDORED_SKILLS = REPO_ROOT / "plugin" / "skills"
CANONICAL_SKILLS = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"


def test_plugin_skills_dir_is_not_a_symlink() -> None:
    """The plugin must be self-contained — no symlink escaping the plugin root."""
    assert not VENDORED_SKILLS.is_symlink(), (
        "plugin/skills must be a real directory of vendored files, not a symlink "
        "(self-contained plugin); run `python scripts/vendor_plugin_skills.py`"
    )
    assert VENDORED_SKILLS.is_dir(), f"vendored skills tree missing at {VENDORED_SKILLS}"


def test_vendored_files_are_real_files_not_links() -> None:
    """Every vendored file resolves to a real regular file inside the plugin root."""
    files = [p for p in VENDORED_SKILLS.rglob("*") if not p.is_dir()]
    assert files, "no files vendored into plugin/skills/starboard"
    for path in files:
        assert not path.is_symlink(), f"vendored path is a symlink: {path}"
        assert path.is_file(), f"vendored path is not a real file: {path}"


def test_vendored_skill_md_set_matches_canonical() -> None:
    """The set of SKILL.md files under the plugin equals the canonical source."""
    canonical = {p.relative_to(CANONICAL_SKILLS).as_posix() for p in CANONICAL_SKILLS.rglob("SKILL.md")}
    vendored = {p.relative_to(VENDORED_SKILLS).as_posix() for p in VENDORED_SKILLS.rglob("SKILL.md")}
    assert canonical, "canonical skills tree unexpectedly empty"
    assert vendored == canonical, (
        "vendored SKILL.md set drifted from canonical — run "
        "`python scripts/vendor_plugin_skills.py`. "
        f"only-vendored={sorted(vendored - canonical)}, "
        f"only-canonical={sorted(canonical - vendored)}"
    )


def test_vendored_tree_is_byte_identical_to_canonical() -> None:
    """Every vendored file is byte-identical to its canonical counterpart (and vice-versa)."""
    canonical = {
        p.relative_to(CANONICAL_SKILLS).as_posix(): p.read_bytes()
        for p in CANONICAL_SKILLS.rglob("*")
        if p.is_file()
    }
    vendored = {
        p.relative_to(VENDORED_SKILLS).as_posix(): p.read_bytes()
        for p in VENDORED_SKILLS.rglob("*")
        if p.is_file()
    }
    assert set(vendored) == set(canonical), (
        "vendored file set drifted from canonical — run "
        "`python scripts/vendor_plugin_skills.py`. "
        f"only-vendored={sorted(set(vendored) - set(canonical))}, "
        f"only-canonical={sorted(set(canonical) - set(vendored))}"
    )
    for rel, content in canonical.items():
        assert vendored[rel] == content, (
            f"vendored {rel} is not byte-identical to canonical — run "
            f"`python scripts/vendor_plugin_skills.py`"
        )
