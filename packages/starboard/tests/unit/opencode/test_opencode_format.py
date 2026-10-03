# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for the OpenCode distribution bundle.

Validates that:
1. The committed bundle at ``packages/starboard-distribution/opencode/`` has the
   correct file count and structure (skills dir, agents dir, AGENTS.md).
2. Every generated skill has valid OpenCode frontmatter (name, description,
   compatibility, no ``allowed-tools``).
3. Every generated agent has valid OpenCode frontmatter (description, mode, model
   in ``provider/model-id`` format, optional permission map).
4. The combined AGENTS.md is non-empty and contains content from all six domain
   rule files.
5. Conversion functions handle edge cases: multi-entry ``allowed-tools`` stripped;
   model hints mapped; orchestrator→primary, subagent→subagent, autonomous→subagent.
6. The ``--check`` flag is idempotent: regenerate-and-diff on the committed bundle
   exits 0 (no drift).

These tests ride ``make test-unit`` (CI-collected) and are side-effect-free —
they read from the committed bundle/canonical sources but do NOT write outside
of a temp dir (used only by the drift check).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise AssertionError("Could not locate repo root containing packages/starboard-skills/skills")


REPO_ROOT = _repo_root()
OC_BUNDLE = REPO_ROOT / "packages" / "starboard-distribution" / "opencode"
CANONICAL_SKILLS = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"
CANONICAL_AGENTS = REPO_ROOT / "packages" / "starboard-skills" / "agents"
RULES_DIR = REPO_ROOT / "plugin" / "rules"

#: OpenCode name regex (per spec: ^[a-z0-9]+(-[a-z0-9]+)*$, 1–64 chars)
_OC_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

#: Domain slugs that must appear somewhere in AGENTS.md
_EXPECTED_DOMAINS = ("jobs", "cluster", "sql", "uc", "warehouse", "discovery")


# ---------------------------------------------------------------------------
# Module-level import of converter (avoids subprocess overhead in unit tests)
# ---------------------------------------------------------------------------

def _load_converter() -> types.ModuleType:
    script = REPO_ROOT / "scripts" / "port_to_opencode.py"
    assert script.exists(), f"converter not found: {script}"
    spec = importlib.util.spec_from_file_location("port_to_opencode", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


CONV = _load_converter()


# ---------------------------------------------------------------------------
# Frontmatter parser (duplicates the converter's helper for test isolation)
# ---------------------------------------------------------------------------

def _parse_fm(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[3:end]) or {}
    body = text[end + 4:].lstrip("\n")
    return fm, body


# ---------------------------------------------------------------------------
# 1. Bundle structure
# ---------------------------------------------------------------------------

class TestBundleStructure:
    def test_skills_dir_exists(self) -> None:
        assert (OC_BUNDLE / "skills").is_dir(), "opencode/skills/ missing"

    def test_agents_dir_exists(self) -> None:
        assert (OC_BUNDLE / "agents").is_dir(), "opencode/agents/ missing"

    def test_agents_md_exists(self) -> None:
        assert (OC_BUNDLE / "AGENTS.md").exists(), "opencode/AGENTS.md missing"

    def test_skill_count_matches_canonical(self) -> None:
        canonical = list(CANONICAL_SKILLS.glob("*/SKILL.md"))
        generated = list((OC_BUNDLE / "skills").glob("*/SKILL.md"))
        assert len(generated) == len(canonical), (
            f"skill count mismatch: generated={len(generated)}, canonical={len(canonical)}"
        )

    def test_agent_count_matches_canonical(self) -> None:
        canonical = list(CANONICAL_AGENTS.glob("*.yaml"))
        generated = list((OC_BUNDLE / "agents").glob("*.md"))
        assert len(generated) == len(canonical), (
            f"agent count mismatch: generated={len(generated)}, canonical={len(canonical)}"
        )


# ---------------------------------------------------------------------------
# 2. Skill format validation — parametrised over every generated skill dir
# ---------------------------------------------------------------------------

def _skill_dirs() -> list[Path]:
    d = OC_BUNDLE / "skills"
    return sorted(d.iterdir()) if d.is_dir() else []


@pytest.mark.parametrize("skill_dir", _skill_dirs(), ids=lambda p: p.name)
class TestSkillFormat:
    def test_skill_file_exists(self, skill_dir: Path) -> None:
        assert (skill_dir / "SKILL.md").is_file()

    def test_has_frontmatter(self, skill_dir: Path) -> None:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        assert fm, "SKILL.md has no frontmatter"

    def test_name_valid(self, skill_dir: Path) -> None:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        name = fm.get("name", "")
        assert _OC_NAME_RE.match(name), f"name {name!r} fails OC name regex"

    def test_name_matches_dir(self, skill_dir: Path) -> None:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        assert fm.get("name") == skill_dir.name, (
            f"name {fm.get('name')!r} != dir name {skill_dir.name!r}"
        )

    def test_description_present_and_bounded(self, skill_dir: Path) -> None:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        desc = fm.get("description", "")
        assert 1 <= len(desc) <= 1024, f"description length {len(desc)} out of [1, 1024]"

    def test_compatibility_opencode(self, skill_dir: Path) -> None:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        assert fm.get("compatibility") == "opencode"

    def test_no_allowed_tools_key(self, skill_dir: Path) -> None:
        """allowed-tools is Claude Code–specific and must be stripped in OC output."""
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        assert "allowed-tools" not in fm

    def test_body_nonempty(self, skill_dir: Path) -> None:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        _, body = _parse_fm(text)
        assert body.strip(), "SKILL.md body is empty"


# ---------------------------------------------------------------------------
# 3. Agent format validation — parametrised over every generated agent file
# ---------------------------------------------------------------------------

def _agent_files() -> list[Path]:
    d = OC_BUNDLE / "agents"
    return sorted(d.glob("*.md")) if d.is_dir() else []


@pytest.mark.parametrize("agent_file", _agent_files(), ids=lambda p: p.stem)
class TestAgentFormat:
    def test_has_frontmatter(self, agent_file: Path) -> None:
        text = agent_file.read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        assert fm, "agent has no frontmatter"

    def test_description_present(self, agent_file: Path) -> None:
        text = agent_file.read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        assert fm.get("description"), "agent description is empty"

    def test_mode_valid(self, agent_file: Path) -> None:
        text = agent_file.read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        assert fm.get("mode") in ("primary", "subagent", "all"), (
            f"invalid mode {fm.get('mode')!r}"
        )

    def test_model_provider_slash_format(self, agent_file: Path) -> None:
        """Model must use provider/model-id format (https://opencode.ai/docs/models/)."""
        text = agent_file.read_text(encoding="utf-8")
        fm, _ = _parse_fm(text)
        model = fm.get("model", "")
        assert "/" in model, f"model {model!r} not in provider/model-id format"

    def test_body_nonempty(self, agent_file: Path) -> None:
        text = agent_file.read_text(encoding="utf-8")
        _, body = _parse_fm(text)
        assert body.strip(), "agent body is empty"


# ---------------------------------------------------------------------------
# 4. AGENTS.md content
# ---------------------------------------------------------------------------

class TestAgentsMd:
    def test_nonempty(self) -> None:
        text = (OC_BUNDLE / "AGENTS.md").read_text(encoding="utf-8")
        assert len(text) > 200

    def test_contains_generated_comment(self) -> None:
        text = (OC_BUNDLE / "AGENTS.md").read_text(encoding="utf-8")
        assert "port_to_opencode.py" in text

    @pytest.mark.parametrize("domain", _EXPECTED_DOMAINS)
    def test_contains_domain(self, domain: str) -> None:
        text = (OC_BUNDLE / "AGENTS.md").read_text(encoding="utf-8").lower()
        assert domain in text, f"domain {domain!r} missing from AGENTS.md"


# ---------------------------------------------------------------------------
# 5. Converter edge-case unit tests
# ---------------------------------------------------------------------------

class TestConverterEdgeCases:
    # Skills ------------------------------------------------------------------

    def test_diagnostic_skill_strips_multi_allowed_tools(self) -> None:
        """Diagnostic has two Bash(...) entries in allowed-tools — all must be stripped."""
        skill_path = CANONICAL_SKILLS / "starboard-diagnostic" / "SKILL.md"
        _, content = CONV.convert_skill(skill_path)
        fm, _ = _parse_fm(content)
        assert "allowed-tools" not in fm

    def test_skill_sets_compatibility_opencode(self) -> None:
        skill_path = CANONICAL_SKILLS / "starboard-analyze" / "SKILL.md"
        _, content = CONV.convert_skill(skill_path)
        fm, _ = _parse_fm(content)
        assert fm.get("compatibility") == "opencode"

    def test_skill_preserves_description_substring(self) -> None:
        skill_path = CANONICAL_SKILLS / "starboard-job" / "SKILL.md"
        name, content = CONV.convert_skill(skill_path)
        fm, _ = _parse_fm(content)
        assert "job" in fm["description"].lower()
        assert name == "starboard-job"

    def test_skill_metadata_source_present(self) -> None:
        skill_path = CANONICAL_SKILLS / "starboard-cluster" / "SKILL.md"
        _, content = CONV.convert_skill(skill_path)
        fm, _ = _parse_fm(content)
        assert fm.get("metadata", {}).get("source"), "metadata.source not set"

    def test_skill_body_preserved(self) -> None:
        skill_path = CANONICAL_SKILLS / "starboard-analyze" / "SKILL.md"
        src_text = skill_path.read_text(encoding="utf-8")
        _, src_body = _parse_fm(src_text)
        _, content = CONV.convert_skill(skill_path)
        _, out_body = _parse_fm(content)
        assert src_body.strip() == out_body.strip()

    # Agents ------------------------------------------------------------------

    def test_sonnet_model_hint_mapped(self) -> None:
        agent_path = CANONICAL_AGENTS / "starboard-analyze.yaml"
        _, content = CONV.convert_agent(agent_path)
        fm, _ = _parse_fm(content)
        assert fm["model"] == "anthropic/claude-sonnet-4-20250514"

    def test_orchestrator_maps_to_primary_mode(self) -> None:
        agent_path = CANONICAL_AGENTS / "starboard-analyze.yaml"
        _, content = CONV.convert_agent(agent_path)
        fm, _ = _parse_fm(content)
        assert fm["mode"] == "primary"

    def test_subagent_maps_to_subagent_mode(self) -> None:
        agent_path = CANONICAL_AGENTS / "starboard-job.yaml"
        _, content = CONV.convert_agent(agent_path)
        fm, _ = _parse_fm(content)
        assert fm["mode"] == "subagent"

    def test_autonomous_maps_to_subagent_mode(self) -> None:
        """Autonomous agents have no native OC mode → subagent with note."""
        agent_path = CANONICAL_AGENTS / "starboard-cluster-monitor.yaml"
        _, content = CONV.convert_agent(agent_path)
        fm, _ = _parse_fm(content)
        assert fm["mode"] == "subagent"

    def test_autonomous_body_contains_scheduling_note(self) -> None:
        agent_path = CANONICAL_AGENTS / "starboard-cluster-monitor.yaml"
        _, content = CONV.convert_agent(agent_path)
        _, body = _parse_fm(content)
        assert "scheduling note" in body.lower()

    def test_multi_tool_list_becomes_permissions(self) -> None:
        """[Bash, Read, Task] → permission.bash/read/task = allow."""
        agent_path = CANONICAL_AGENTS / "starboard-analyze.yaml"
        _, content = CONV.convert_agent(agent_path)
        fm, _ = _parse_fm(content)
        perms = fm.get("permission", {})
        assert perms.get("bash") == "allow"
        assert perms.get("read") == "allow"
        assert perms.get("task") == "allow"

    def test_two_tool_agent_permissions(self) -> None:
        """[Bash, Read] (no Task) → permission has bash and read but not task."""
        agent_path = CANONICAL_AGENTS / "starboard-cluster.yaml"
        _, content = CONV.convert_agent(agent_path)
        fm, _ = _parse_fm(content)
        perms = fm.get("permission", {})
        assert perms.get("bash") == "allow"
        assert perms.get("read") == "allow"
        assert "task" not in perms

    # Rules -------------------------------------------------------------------

    def test_convert_rules_contains_all_domains(self) -> None:
        rule_paths = [
            p for p in RULES_DIR.glob("*.md")
            if p.name not in ("README.md", "starboard.md")
        ]
        index = RULES_DIR / "starboard.md"
        content = CONV.convert_rules(rule_paths, index)
        for domain in _EXPECTED_DOMAINS:
            assert domain in content.lower(), f"domain {domain!r} missing from rules output"

    def test_convert_rules_has_generated_comment(self) -> None:
        rule_paths = [
            p for p in RULES_DIR.glob("*.md")
            if p.name not in ("README.md", "starboard.md")
        ]
        content = CONV.convert_rules(rule_paths, None)
        assert "port_to_opencode.py" in content

    # Model map ---------------------------------------------------------------

    def test_map_model_unknown_hint_passes_through(self) -> None:
        result = CONV._map_model("custom-model-xyz")
        assert result == "anthropic/custom-model-xyz"

    def test_map_model_none_defaults_to_sonnet(self) -> None:
        result = CONV._map_model(None)
        assert result == "anthropic/claude-sonnet-4-20250514"

    def test_map_model_haiku(self) -> None:
        assert CONV._map_model("haiku") == "anthropic/claude-haiku-4-5-20251001"

    def test_map_model_opus(self) -> None:
        assert CONV._map_model("opus") == "anthropic/claude-opus-4-20250514"

    def test_model_map_ids_well_formed(self) -> None:
        """Every mapped id is ``anthropic/claude-<family>-...`` (family-first).

        Guards against the reversed ``claude-haiku-3-...`` form (a Claude-3-era
        ``claude-3-haiku-...`` id written with the family and generation
        swapped), which OpenCode cannot resolve.
        """
        family_first = re.compile(r"^anthropic/claude-(sonnet|haiku|opus)-\d")
        for hint, model_id in CONV.MODEL_MAP.items():
            assert family_first.match(model_id), (
                f"{hint!r} maps to a malformed model id {model_id!r}"
            )


# ---------------------------------------------------------------------------
# 6. Idempotency / drift check
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_check_flag_exits_zero_on_committed_bundle(self) -> None:
        """``python scripts/port_to_opencode.py --check`` must exit 0 (no drift)."""
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "port_to_opencode.py"),
                "--check",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"--check reported drift or error.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
