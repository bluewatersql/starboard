# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-1 B3 + B6 guardrails: Claude Code plugin + marketplace manifest.

Enforces Task B3 (PHASE_1.md §7) and Task B6 (PHASE_1.md §9b) with the *verified*
current manifest formats (code.claude.com/docs/en/plugins-reference +
/plugin-marketplaces, 2026-08-26; agent_integration/technical.md §1.3):

- ``plugin/.claude-plugin/plugin.json`` is valid JSON with the B3 field set
  (``name``/``displayName``/``version``/``description``/``author``/``keywords``/
  ``license``) and **declares ``skills``** — the dual-mode invariant stays intact.
- B6 optional-MCP toggle: ``plugin.json`` declares ``mcpServers`` (pointing at the
  bundled ``./.mcp.json``) and a ``userConfig.enable_mcp`` boolean (``title`` +
  ``description``, ``required: false``) so users opt into the full agent stack.
- ``plugin/.mcp.json`` is valid JSON declaring the ``starboard`` stdio server
  (``command: starboard-mcp``) with env passthrough for ``DATABRICKS_HOST`` /
  ``LLM_*`` and **no hard-coded secrets**.
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
    """B6 layers the MCP toggle ON TOP OF the skills — the dual-mode invariant holds.

    The skills declaration (and the vendored tree) must survive the B6 change so the
    ``enable_mcp: false`` / server-absent path still routes through ``starboard-helper``.
    """
    manifest = _load_json(PLUGIN_JSON)
    assert "skills" in manifest, "B6 must not drop the skills declaration (dual-mode fallback)"


# --------------------------------------------------------------------------- #
# B6 optional-MCP toggle (PHASE_1.md §9b, agent_integration §1.3)             #
# --------------------------------------------------------------------------- #


def test_plugin_json_declares_mcp_servers_pointing_at_bundled_file() -> None:
    """B6: ``plugin.json`` opts into MCP by pointing ``mcpServers`` at ``./.mcp.json``."""
    manifest = _load_json(PLUGIN_JSON)
    assert "mcpServers" in manifest, "B6 must declare mcpServers for the optional-MCP toggle"
    mcp_servers = manifest["mcpServers"]
    # Verified form: a string path to a bundled .mcp.json (agent_integration §1.3).
    assert isinstance(mcp_servers, str), "mcpServers should be a string path to the bundled .mcp.json"
    resolved = (PLUGIN_DIR / mcp_servers).resolve()
    assert resolved == MCP_JSON.resolve(), f"mcpServers {mcp_servers!r} must resolve to plugin/.mcp.json"
    assert resolved.is_file(), "the bundled .mcp.json must exist"


def test_plugin_json_declares_user_config_enable_mcp() -> None:
    """B6: a ``userConfig.enable_mcp`` boolean lets users opt into the full agent stack."""
    manifest = _load_json(PLUGIN_JSON)
    assert "userConfig" in manifest, "B6 must declare userConfig"
    user_config = manifest["userConfig"]
    assert isinstance(user_config, dict), "userConfig must be an object"
    assert "enable_mcp" in user_config, "userConfig must define the enable_mcp toggle"
    entry = user_config["enable_mcp"]
    assert entry.get("type") == "boolean", "enable_mcp must be a boolean userConfig entry"
    assert entry.get("title"), "enable_mcp must carry a human-readable title"
    assert isinstance(entry.get("description"), str) and entry["description"].strip(), (
        "enable_mcp must carry a non-empty description"
    )
    # Opt-in: not required so the skills-only path stays the default.
    assert entry.get("required") is False, "enable_mcp must be required: false (opt-in)"


def test_bundled_mcp_json_declares_starboard_server() -> None:
    """B6: ``plugin/.mcp.json`` parses and declares the ``starboard`` stdio server."""
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
    """B6: env passes through DATABRICKS_HOST / LLM_* by reference, no hard-coded secrets."""
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
