# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-1 B3 guardrails: skills-only Claude Code plugin + marketplace manifest.

Enforces Task B3 (PHASE_1.md §7) with the *verified* current manifest formats
(code.claude.com/docs/en/plugins-reference + /plugin-marketplaces, 2026-08-26):

- ``plugin/.claude-plugin/plugin.json`` is valid JSON with the B3 field set
  (``name``/``displayName``/``version``/``description``/``author``/``keywords``/
  ``license``) and **declares ``skills`` but NOT ``mcpServers``** — the skills-only
  invariant for B3 (MCP is the later Task B6).
- ``.claude-plugin/marketplace.json`` (repo root) is valid JSON with ``name``,
  an ``owner`` **object**, and a ``plugins`` array listing the ``starboard`` plugin
  whose ``source`` (``./plugin``) resolves to a dir containing
  ``.claude-plugin/plugin.json`` (D-1.4).
- every skill vendored into ``plugin/skills`` resolves to a real ``SKILL.md`` with
  valid fenced frontmatter (``name`` + ``description``), and the vendored tree is
  byte-identical to the canonical source of truth
  ``packages/starboard-skills/skills/starboard`` (D-1.5, built/symlinked — not a
  hand copy).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml


def _repo_root() -> Path:
    """Walk up until the repo root (holds both the plugin and the canonical skills)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise AssertionError("could not locate repo root containing packages/starboard-skills/skills")


REPO_ROOT = _repo_root()
PLUGIN_DIR = REPO_ROOT / "plugin"
PLUGIN_JSON = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_SKILLS = PLUGIN_DIR / "skills"
CANONICAL_SKILLS = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"

# Fenced YAML frontmatter: a leading '---' line, a body, and a closing '---' line.
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---\r?\n", re.DOTALL)


def _load_json(path: Path) -> dict:
    assert path.is_file(), f"missing manifest: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_frontmatter(text: str) -> dict:
    match = _FRONTMATTER_RE.match(text)
    assert match is not None, "SKILL.md must open with fenced YAML frontmatter ('---' ... '---')"
    data = yaml.safe_load(match.group("yaml"))
    assert isinstance(data, dict), "frontmatter must parse to a YAML mapping"
    return data


# --------------------------------------------------------------------------- #
# plugin.json                                                                  #
# --------------------------------------------------------------------------- #


def test_plugin_json_is_valid_json_with_required_fields() -> None:
    manifest = _load_json(PLUGIN_JSON)
    # `name` is the only field Claude Code requires; B3 also locks the metadata set.
    for key in ("name", "displayName", "version", "description", "author", "keywords", "license"):
        assert key in manifest, f"plugin.json missing required B3 field: {key!r}"
    assert manifest["name"] == "starboard"
    # kebab-case identifier.
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", manifest["name"])
    # author is an object {name, email?, url?} per the verified schema (not a string).
    assert isinstance(manifest["author"], dict), "author must be an object, not a string"
    assert manifest["author"].get("name"), "author.name must be set"
    assert isinstance(manifest["keywords"], list) and manifest["keywords"], "keywords must be a non-empty list"


def test_plugin_json_declares_skills() -> None:
    manifest = _load_json(PLUGIN_JSON)
    assert "skills" in manifest, "plugin.json must declare a skills path"
    skills_val = manifest["skills"]
    # `skills` is a string | array; each must resolve under the plugin dir.
    paths = [skills_val] if isinstance(skills_val, str) else skills_val
    assert paths, "skills declaration must be non-empty"
    for rel in paths:
        resolved = (PLUGIN_DIR / rel).resolve()
        assert resolved.is_dir(), f"declared skills path does not resolve to a dir: {rel}"


def test_plugin_json_is_skills_only_no_mcp() -> None:
    """B3 is pre-B6: the skills-only plugin must NOT declare an MCP server."""
    manifest = _load_json(PLUGIN_JSON)
    assert "mcpServers" not in manifest, "B3 is skills-only; mcpServers is the later Task B6"
    # No stray bundled .mcp.json either (convention discovery would auto-wire it).
    assert not (PLUGIN_DIR / ".mcp.json").exists(), "B3 must not bundle a .mcp.json (that is B6)"


# --------------------------------------------------------------------------- #
# marketplace.json                                                             #
# --------------------------------------------------------------------------- #


def test_marketplace_json_is_valid_json_with_required_keys() -> None:
    manifest = _load_json(MARKETPLACE_JSON)
    for key in ("name", "owner", "plugins"):
        assert key in manifest, f"marketplace.json missing required key: {key!r}"
    # owner is an OBJECT {name, email?, url?} per the verified 2026 schema.
    assert isinstance(manifest["owner"], dict), "marketplace owner must be an object"
    assert manifest["owner"].get("name"), "marketplace owner.name must be set"
    assert isinstance(manifest["plugins"], list) and manifest["plugins"], "plugins must be a non-empty list"


def test_marketplace_lists_starboard_with_resolvable_source() -> None:
    manifest = _load_json(MARKETPLACE_JSON)
    entries = {p["name"]: p for p in manifest["plugins"]}
    assert "starboard" in entries, "marketplace must list the 'starboard' plugin"
    entry = entries["starboard"]

    source = entry["source"]
    # D-1.4: source is the relative path './plugin' (identical for public GitHub / Isaac).
    # Marketplace `source` paths are relative to the marketplace root — the directory that
    # *contains* .claude-plugin/ (i.e. the repo root), not the .claude-plugin dir itself.
    assert isinstance(source, str), "B3 uses the relative-path source form"
    resolved = (REPO_ROOT / source).resolve()
    assert resolved == PLUGIN_DIR.resolve(), f"source {source!r} must resolve to the plugin dir"
    assert (resolved / ".claude-plugin" / "plugin.json").is_file(), (
        "source must resolve to a dir containing .claude-plugin/plugin.json"
    )


# --------------------------------------------------------------------------- #
# vendored skills (D-1.5 single source of truth)                              #
# --------------------------------------------------------------------------- #


def _vendored_skill_dirs() -> list[str]:
    if not PLUGIN_SKILLS.is_dir():
        return []
    return sorted(p.name for p in PLUGIN_SKILLS.iterdir() if p.is_dir())


def test_vendored_skills_present() -> None:
    assert PLUGIN_SKILLS.is_dir(), f"plugin skills tree missing at {PLUGIN_SKILLS}"
    assert _vendored_skill_dirs(), "no skills vendored into the plugin"


@pytest.mark.parametrize("skill_dir_id", _vendored_skill_dirs())
def test_vendored_skill_has_valid_frontmatter(skill_dir_id: str) -> None:
    skill_file = PLUGIN_SKILLS / skill_dir_id / "SKILL.md"
    assert skill_file.is_file(), f"missing vendored {skill_file}"
    fm = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    assert fm.get("name"), f"{skill_dir_id}: frontmatter missing 'name'"
    assert isinstance(fm.get("description"), str) and fm["description"].strip(), (
        f"{skill_dir_id}: frontmatter missing non-empty 'description'"
    )


def test_vendored_tree_matches_canonical_source_of_truth() -> None:
    """D-1.5: the plugin vendors the canonical tree (built/symlinked, not hand-copied).

    Byte-identity is the drift guard: the set of SKILL.md files and their content
    under ``plugin/skills`` must equal ``packages/starboard-skills/skills/starboard``.
    """
    canonical = {
        p.relative_to(CANONICAL_SKILLS).as_posix(): p.read_bytes()
        for p in CANONICAL_SKILLS.rglob("SKILL.md")
    }
    vendored = {
        p.relative_to(PLUGIN_SKILLS).as_posix(): p.read_bytes()
        for p in PLUGIN_SKILLS.rglob("SKILL.md")
    }
    assert canonical, "canonical skills tree unexpectedly empty"
    assert set(vendored) == set(canonical), (
        f"vendored skills drifted from canonical: "
        f"only-vendored={sorted(set(vendored) - set(canonical))}, "
        f"only-canonical={sorted(set(canonical) - set(vendored))}"
    )
    for rel, content in canonical.items():
        assert vendored[rel] == content, f"vendored {rel} is not byte-identical to canonical"
