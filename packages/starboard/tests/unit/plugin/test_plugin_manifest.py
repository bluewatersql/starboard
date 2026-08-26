# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-1 B3 guardrails: Claude Code plugin + marketplace manifest.

Enforces Task B3 (PHASE_1.md §7) with the *verified* current manifest formats
(code.claude.com/docs/en/plugins-reference + /plugin-marketplaces, 2026-08-26;
agent_integration/technical.md §1.3):

- ``plugin/.claude-plugin/plugin.json`` is valid JSON with the B3 field set
  (``name``/``displayName``/``version``/``description``/``author``/``keywords``/
  ``license``) and **declares ``skills``** — the dual-mode invariant stays intact.
- The committed plugin is **skills-only by default** (review fix #1): it does
  **not** declare ``mcpServers`` and carries no inert ``userConfig.enable_mcp``.
  Claude Code launches any declared bundled ``mcpServers`` on plugin load, so a
  declared server would break a skills-only install (no ``starboard-mcp``, no LLM
  creds). MCP is an explicit opt-in the user wires up themselves (see README).
- ``plugin/.mcp.json`` stays in the repo as a valid-JSON opt-in template: it
  declares the ``starboard`` stdio server (``command: starboard-mcp``) with env
  passthrough for ``DATABRICKS_HOST`` / ``LLM_*`` and **no hard-coded secrets**,
  so users who want the full agent stack can copy it into their own ``.mcp.json``.
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
MCP_JSON = PLUGIN_DIR / ".mcp.json"
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


def test_plugin_json_still_declares_skills_dual_mode_intact() -> None:
    """The skills declaration is the plugin's whole surface (skills-only default).

    The skills-only committed plugin routes every skill through ``starboard-helper``
    with no server present; the skills declaration must always survive.
    """
    manifest = _load_json(PLUGIN_JSON)
    assert "skills" in manifest, "the committed plugin must always declare skills"


# --------------------------------------------------------------------------- #
# skills-only default (review fix #1): no bundled mcpServers, no inert toggle   #
# --------------------------------------------------------------------------- #


def test_plugin_json_is_skills_only_no_mcp_servers() -> None:
    """Review fix #1: the committed plugin must NOT declare ``mcpServers``.

    Claude Code launches declared bundled ``mcpServers`` on plugin load, so a
    committed ``mcpServers`` would break the skills-only install (no ``starboard-mcp``
    binary, no LLM creds). MCP is an explicit, user-wired opt-in (see README).
    """
    manifest = _load_json(PLUGIN_JSON)
    assert "mcpServers" not in manifest, (
        "the committed plugin must be skills-only: drop mcpServers so a skills-only "
        "install does not try to launch starboard-mcp on load (MCP is an opt-in)"
    )


def test_plugin_json_has_no_inert_enable_mcp_toggle() -> None:
    """Review fix #1: the inert ``userConfig.enable_mcp`` toggle is removed.

    The toggle never gated MCP startup (Claude Code launches declared servers
    unconditionally), so it is misleading and must not be shipped.
    """
    manifest = _load_json(PLUGIN_JSON)
    user_config = manifest.get("userConfig")
    if user_config is not None:
        assert "enable_mcp" not in user_config, (
            "remove the inert enable_mcp toggle: it never gated MCP startup"
        )


def test_bundled_mcp_json_declares_starboard_server() -> None:
    """The opt-in ``plugin/.mcp.json`` template parses and declares ``starboard``."""
    mcp = _load_json(MCP_JSON)
    assert "mcpServers" in mcp, ".mcp.json must contain an mcpServers object"
    servers = mcp["mcpServers"]
    assert isinstance(servers, dict) and "starboard" in servers, (
        ".mcp.json must declare the 'starboard' server"
    )
    server = servers["starboard"]
    assert server.get("command") == "starboard-mcp", "starboard server command must be 'starboard-mcp'"
    # stdio transport form: {command, args, env, timeout}.
    assert isinstance(server.get("args"), list), "starboard server must declare args (stdio transport)"
    assert isinstance(server.get("timeout"), int), "starboard server must declare an integer timeout"


def test_bundled_mcp_json_env_passthrough_without_secrets() -> None:
    """Opt-in template: env passes through DATABRICKS_HOST / LLM_* by reference, no secrets."""
    mcp = _load_json(MCP_JSON)
    env = mcp["mcpServers"]["starboard"].get("env", {})
    assert isinstance(env, dict) and env, "starboard server must declare an env block"
    assert "DATABRICKS_HOST" in env, "env must pass through DATABRICKS_HOST"
    assert any(k.startswith("LLM_") for k in env), "env must pass through the LLM_* credentials"
    # Every value must be a ${VAR}/${user_config.*} reference — never a baked-in secret.
    for key, value in env.items():
        assert isinstance(value, str), f"env[{key!r}] must be a string reference"
        assert re.fullmatch(r"\$\{[^}]+\}", value), (
            f"env[{key!r}]={value!r} must be a ${{VAR}} reference, not a hard-coded value"
        )


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
