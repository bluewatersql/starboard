# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for Q1 agent/subagent definitions and gen_agents.py generator.

Test coverage:
  1. Canonical YAML validity — required fields, valid enum values, correct counts.
  2. Skill/tool mapping — skill_ref exists in the canonical skills tree.
  3. Orchestrator integrity — dispatches_to references only real agent names.
  4. Generated .md validity — valid YAML frontmatter, required fields, non-empty body.
  5. Regenerate stability — generate(check=True) reports no drift.
  6. Governance grep — no forbidden internal namespace strings in any output.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
import yaml

# ---------------------------------------------------------------------------
# Repository layout constants
# ---------------------------------------------------------------------------

# packages/starboard/tests/unit/agents_defs/test_gen_agents.py
#   → agents_defs/  [0]
#   → unit/         [1]
#   → tests/        [2]
#   → starboard/    [3]  (package dir)
#   → packages/     [4]
#   → repo root     [5]
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_CANONICAL_DIR = _REPO_ROOT / "packages" / "starboard-skills" / "agents"
_OUTPUT_DIR = _REPO_ROOT / "plugin" / "agents"
_SKILLS_DIR = _REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"

# ---------------------------------------------------------------------------
# Import gen_agents from scripts/ (not a package; load via importlib)
# ---------------------------------------------------------------------------


def _load_gen_agents() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gen_agents", _SCRIPTS_DIR / "gen_agents.py"
    )
    assert spec is not None and spec.loader is not None, (
        f"Could not load gen_agents.py from {_SCRIPTS_DIR}"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_gen = _load_gen_agents()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Compute canonical agent names at collection time (files must exist by then)
_CANONICAL_YAML_FILES = sorted(_CANONICAL_DIR.glob("*.yaml")) if _CANONICAL_DIR.exists() else []
_OUTPUT_MD_FILES = sorted(_OUTPUT_DIR.glob("*.md")) if _OUTPUT_DIR.exists() else []
_CANONICAL_AGENT_NAMES: frozenset[str] = frozenset(
    yaml.safe_load(p.read_text(encoding="utf-8"))["name"]
    for p in _CANONICAL_YAML_FILES
)

# Governance: forbidden internal namespace identifiers (CLAUDE.md red-lines)
_FORBIDDEN_PATTERNS = [
    "centralized_system_tables",
    "fin_live_gold",
    "logfood",
    "ClickHouse",
    "hmr_stack_hash",
]
_FORBIDDEN_RE = re.compile("|".join(re.escape(p) for p in _FORBIDDEN_PATTERNS))


def _parse_frontmatter(content: str) -> dict[str, object]:
    """Parse YAML frontmatter from a ``---…---`` block at the start of content."""
    assert content.startswith("---\n"), "Content does not start with YAML frontmatter"
    end = content.index("\n---\n", 3)
    return yaml.safe_load(content[4:end])  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 1. Canonical YAML validity
# ---------------------------------------------------------------------------


class TestCanonicalYAMLValidity:
    """Every canonical YAML must load cleanly and carry valid field values."""

    def test_canonical_dir_exists(self) -> None:
        assert _CANONICAL_DIR.is_dir(), f"Canonical agent dir missing: {_CANONICAL_DIR}"

    def test_canonical_dir_has_twelve_yaml_files(self) -> None:
        assert len(_CANONICAL_YAML_FILES) == 12, (
            f"Expected 12 canonical YAML files, found {len(_CANONICAL_YAML_FILES)}"
        )

    @pytest.mark.parametrize("src", _CANONICAL_YAML_FILES, ids=lambda p: p.stem)
    def test_required_fields_present(self, src: Path) -> None:
        agent: dict[str, object] = yaml.safe_load(src.read_text(encoding="utf-8"))
        # Reuse the generator's own validator — if it raises, the test fails.
        _gen._validate(agent, src)  # type: ignore[attr-defined]

    @pytest.mark.parametrize("src", _CANONICAL_YAML_FILES, ids=lambda p: p.stem)
    def test_valid_kind(self, src: Path) -> None:
        agent: dict[str, object] = yaml.safe_load(src.read_text(encoding="utf-8"))
        assert agent["kind"] in ("subagent", "orchestrator", "autonomous"), (
            f"{src.name}: invalid kind={agent['kind']!r}"
        )

    @pytest.mark.parametrize("src", _CANONICAL_YAML_FILES, ids=lambda p: p.stem)
    def test_valid_model(self, src: Path) -> None:
        agent: dict[str, object] = yaml.safe_load(src.read_text(encoding="utf-8"))
        assert agent["model"] in ("sonnet", "opus", "haiku", "inherit"), (
            f"{src.name}: invalid model={agent['model']!r}"
        )

    def test_exactly_nine_subagents(self) -> None:
        agents = _gen._load_agents(_CANONICAL_DIR)  # type: ignore[attr-defined]
        subagents = [a for a in agents if a["kind"] == "subagent"]
        assert len(subagents) == 9, (
            f"Expected 9 subagents, got {len(subagents)}: {[a['name'] for a in subagents]}"
        )

    def test_exactly_one_orchestrator(self) -> None:
        agents = _gen._load_agents(_CANONICAL_DIR)  # type: ignore[attr-defined]
        orchestrators = [a for a in agents if a["kind"] == "orchestrator"]
        assert len(orchestrators) == 1, (
            f"Expected 1 orchestrator, got {len(orchestrators)}"
        )

    def test_exactly_two_autonomous_agents(self) -> None:
        agents = _gen._load_agents(_CANONICAL_DIR)  # type: ignore[attr-defined]
        autonomous = [a for a in agents if a["kind"] == "autonomous"]
        assert len(autonomous) == 2, (
            f"Expected 2 autonomous agents, got {len(autonomous)}: "
            f"{[a['name'] for a in autonomous]}"
        )

    def test_no_duplicate_names(self) -> None:
        agents = _gen._load_agents(_CANONICAL_DIR)  # type: ignore[attr-defined]
        names = [a["name"] for a in agents]
        duplicates = [n for n in names if names.count(n) > 1]
        assert not duplicates, f"Duplicate agent names: {duplicates}"

    def test_subagent_domains_cover_all_nine(self) -> None:
        agents = _gen._load_agents(_CANONICAL_DIR)  # type: ignore[attr-defined]
        subagent_names = {a["name"] for a in agents if a["kind"] == "subagent"}
        expected = {
            "starboard-query",
            "starboard-job",
            "starboard-uc",
            "starboard-cluster",
            "starboard-warehouse",
            "starboard-finops",
            "starboard-diagnostic",
            "starboard-discovery",
            "starboard-workload-review",
        }
        assert subagent_names == expected, (
            f"Subagent set mismatch.\n  Expected: {sorted(expected)}\n  Got: {sorted(subagent_names)}"
        )


# ---------------------------------------------------------------------------
# 2. Skill / tool mapping
# ---------------------------------------------------------------------------


class TestSkillMapping:
    """Each agent's skill_ref must point to a real skill directory in the canonical tree."""

    @pytest.mark.parametrize("src", _CANONICAL_YAML_FILES, ids=lambda p: p.stem)
    def test_skill_ref_points_to_existing_skill(self, src: Path) -> None:
        agent: dict[str, object] = yaml.safe_load(src.read_text(encoding="utf-8"))
        skill_ref = agent.get("skill_ref")
        if not skill_ref:
            pytest.skip(f"{src.name}: no skill_ref declared")
        skill_dir = _SKILLS_DIR / str(skill_ref)
        assert skill_dir.is_dir(), (
            f"{src.name}: skill_ref={skill_ref!r} not found at {skill_dir}"
        )

    def test_orchestrator_dispatches_to_existing_agents(self) -> None:
        agents = _gen._load_agents(_CANONICAL_DIR)  # type: ignore[attr-defined]
        orchestrators = [a for a in agents if a["kind"] == "orchestrator"]
        assert orchestrators, "No orchestrator agent found in canonical source"
        orch = orchestrators[0]
        for ref in orch.get("dispatches_to", []):
            assert ref in _CANONICAL_AGENT_NAMES, (
                f"Orchestrator dispatches_to={ref!r} but no agent with that name exists "
                f"in the canonical source"
            )


# ---------------------------------------------------------------------------
# 3. Generated Claude Code .md validity
# ---------------------------------------------------------------------------


class TestGeneratedAgentFiles:
    """Every plugin/agents/*.md must have valid YAML frontmatter with required fields."""

    def test_output_dir_exists(self) -> None:
        assert _OUTPUT_DIR.is_dir(), f"Generated agents dir missing: {_OUTPUT_DIR}"

    def test_output_has_twelve_md_files(self) -> None:
        assert len(_OUTPUT_MD_FILES) == 12, (
            f"Expected 12 generated .md files, got {len(_OUTPUT_MD_FILES)}"
        )

    @pytest.mark.parametrize("md", _OUTPUT_MD_FILES, ids=lambda p: p.stem)
    def test_valid_yaml_frontmatter(self, md: Path) -> None:
        content = md.read_text(encoding="utf-8")
        assert content.startswith("---\n"), f"{md.name}: missing YAML frontmatter"
        fm = _parse_frontmatter(content)
        assert isinstance(fm, dict), f"{md.name}: frontmatter is not a YAML mapping"
        for field in ("name", "description", "tools", "model"):
            assert field in fm, f"{md.name}: missing required frontmatter field {field!r}"

    @pytest.mark.parametrize("md", _OUTPUT_MD_FILES, ids=lambda p: p.stem)
    def test_frontmatter_name_matches_filename(self, md: Path) -> None:
        content = md.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        assert fm["name"] == md.stem, (
            f"{md.name}: frontmatter name={fm['name']!r} != filename stem {md.stem!r}"
        )

    @pytest.mark.parametrize("md", _OUTPUT_MD_FILES, ids=lambda p: p.stem)
    def test_tools_is_nonempty_list_in_frontmatter(self, md: Path) -> None:
        content = md.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        tools = fm.get("tools")
        assert isinstance(tools, list) and tools, (
            f"{md.name}: 'tools' must be a non-empty list, got {tools!r}"
        )

    @pytest.mark.parametrize("md", _OUTPUT_MD_FILES, ids=lambda p: p.stem)
    def test_model_is_valid(self, md: Path) -> None:
        content = md.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        assert fm.get("model") in ("sonnet", "opus", "haiku", "inherit"), (
            f"{md.name}: invalid model={fm.get('model')!r}"
        )

    @pytest.mark.parametrize("md", _OUTPUT_MD_FILES, ids=lambda p: p.stem)
    def test_body_content_is_substantive(self, md: Path) -> None:
        content = md.read_text(encoding="utf-8")
        end = content.index("\n---\n", 3)
        body = content[end + 5:].strip()
        assert len(body) > 100, (
            f"{md.name}: body is suspiciously short ({len(body)} chars)"
        )

    @pytest.mark.parametrize("md", _OUTPUT_MD_FILES, ids=lambda p: p.stem)
    def test_description_is_nonempty_string(self, md: Path) -> None:
        content = md.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        desc = fm.get("description", "")
        assert isinstance(desc, str) and len(str(desc).strip()) > 20, (
            f"{md.name}: description is missing or too short"
        )

    def test_every_canonical_agent_has_a_generated_file(self) -> None:
        generated_stems = {p.stem for p in _OUTPUT_MD_FILES}
        for name in _CANONICAL_AGENT_NAMES:
            assert name in generated_stems, (
                f"Canonical agent {name!r} has no generated .md file in {_OUTPUT_DIR}"
            )


# ---------------------------------------------------------------------------
# 4. Regenerate-and-diff stability
# ---------------------------------------------------------------------------


class TestRegenerateStability:
    """Running generate(check=True) must report no drift against the committed files."""

    def test_generated_files_are_up_to_date(self) -> None:
        drift: list[str] = _gen.generate(  # type: ignore[attr-defined]
            canonical_dir=_CANONICAL_DIR,
            output_dir=_OUTPUT_DIR,
            check=True,
        )
        assert drift == [], (
            "Generated agent files are stale — run `python scripts/gen_agents.py`.\n"
            f"Drift: {drift}"
        )

    def test_render_is_deterministic(self) -> None:
        """Rendering the same agent dict twice must produce identical output."""
        agents: list[dict[str, object]] = _gen._load_agents(_CANONICAL_DIR)  # type: ignore[attr-defined]
        for agent in agents:
            first: str = _gen.render_claude_code(agent)  # type: ignore[attr-defined]
            second: str = _gen.render_claude_code(agent)  # type: ignore[attr-defined]
            assert first == second, (
                f"render_claude_code is not deterministic for agent {agent['name']!r}"
            )


# ---------------------------------------------------------------------------
# 5. Governance grep
# ---------------------------------------------------------------------------


class TestGovernanceGrep:
    """Agent definitions must not contain internal namespace identifiers (CLAUDE.md red-lines)."""

    @pytest.mark.parametrize("src", _CANONICAL_YAML_FILES, ids=lambda p: p.stem)
    def test_canonical_yaml_clean(self, src: Path) -> None:
        content = src.read_text(encoding="utf-8")
        match = _FORBIDDEN_RE.search(content)
        assert match is None, (
            f"{src.name}: forbidden internal namespace {match.group()!r} "
            f"at position {match.start()}"
        )

    @pytest.mark.parametrize("md", _OUTPUT_MD_FILES, ids=lambda p: p.stem)
    def test_generated_md_clean(self, md: Path) -> None:
        content = md.read_text(encoding="utf-8")
        match = _FORBIDDEN_RE.search(content)
        assert match is None, (
            f"{md.name}: forbidden internal namespace {match.group()!r} "
            f"at position {match.start()}"
        )
