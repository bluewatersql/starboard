# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``starboard-diagnostic`` SKILL.md three-branch dual-mode (Phase-1 B2).

Assert the canonical skill:
- parses as fenced YAML frontmatter with ``name`` + ``description``,
- pre-approves the bundled Tier-1 script via an ``allowed-tools`` prefix that
  matches the body command (prompt-free contract),
- is deterministic-first: documents the Tier-1 bundled script + Tier-0 helper as
  the data paths and states the no-second-LLM contract (no MCP-agent handoff),
- ships an executable ``scripts/run.sh`` that execs ``python -m starboard_x.diagnostic``,
- stays under 500 lines with a description under 1,536 chars.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SKILL_DIR = (
    Path(__file__).parents[1]
    / "skills"
    / "starboard"
    / "starboard-diagnostic"
)
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_RUN_SH = _SKILL_DIR / "scripts" / "run.sh"

_ALLOWED_TOOLS_PREFIX = "Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)"
_BODY_COMMAND_PREFIX = "${CLAUDE_SKILL_DIR}/scripts/run.sh"


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_yaml, body) from a fenced ``---`` frontmatter file."""
    assert text.startswith("---"), "SKILL.md must start with a fenced --- frontmatter"
    parts = text.split("---", 2)
    assert len(parts) == 3, "SKILL.md frontmatter must be closed with ---"
    return parts[1], parts[2]


@pytest.fixture()
def skill_text() -> str:
    return _SKILL_MD.read_text()


@pytest.mark.unit
class TestFrontmatter:
    def test_frontmatter_parses_as_yaml(self, skill_text: str) -> None:
        yaml = pytest.importorskip("yaml")
        fm, _ = _split_frontmatter(skill_text)
        data = yaml.safe_load(fm)
        assert isinstance(data, dict)
        assert data.get("name") == "starboard-diagnostic"
        assert isinstance(data.get("description"), str) and data["description"]

    def test_allowed_tools_preapproves_tier1_script(self, skill_text: str) -> None:
        yaml = pytest.importorskip("yaml")
        fm, _ = _split_frontmatter(skill_text)
        data = yaml.safe_load(fm)
        allowed = data.get("allowed-tools")
        assert allowed, "allowed-tools must be present"
        assert _ALLOWED_TOOLS_PREFIX in allowed, allowed
        assert "Read" in allowed, allowed

    def test_description_within_1536_chars(self, skill_text: str) -> None:
        yaml = pytest.importorskip("yaml")
        fm, _ = _split_frontmatter(skill_text)
        data = yaml.safe_load(fm)
        combined = str(data.get("description", "")) + str(data.get("when_to_use", ""))
        assert len(combined) <= 1536, len(combined)


@pytest.mark.unit
class TestBody:
    def test_body_under_500_lines(self, skill_text: str) -> None:
        assert len(skill_text.splitlines()) <= 500

    def test_deterministic_first_no_second_llm(self, skill_text: str) -> None:
        _, body = _split_frontmatter(skill_text)
        # Deterministic-first: the bundled Tier-1 script and the Tier-0 helper are
        # the documented data paths; the host (this LLM) analyzes the results.
        assert _BODY_COMMAND_PREFIX in body
        assert "starboard-helper" in body
        # The old MCP-agent branch is removed — the skill must not hand analysis
        # to a second, server-side LLM.
        assert "mcp__starboard__diagnostic_agent" not in body
        # The no-second-LLM contract is stated explicitly.
        assert "no second LLM" in body

    def test_body_invokes_preapproved_prefix(self, skill_text: str) -> None:
        """The command the body tells Claude to run must match the allowed-tools prefix."""
        _, body = _split_frontmatter(skill_text)
        assert f"{_BODY_COMMAND_PREFIX} triage-exit" in body
        assert f"{_BODY_COMMAND_PREFIX} extract-evidence" in body
        assert f"{_BODY_COMMAND_PREFIX} rca" in body


@pytest.mark.unit
class TestRunScript:
    def test_run_sh_exists_and_executable(self) -> None:
        assert _RUN_SH.exists(), _RUN_SH
        mode = _RUN_SH.stat().st_mode
        assert mode & 0o111, "scripts/run.sh must be executable"

    def test_run_sh_execs_python_module(self) -> None:
        text = _RUN_SH.read_text()
        assert "python -m starboard_x.diagnostic" in text
        assert 'exec' in text
        assert '"$@"' in text

    def test_supporting_files_present(self) -> None:
        assert (_SKILL_DIR / "reference.md").exists()
        assert (_SKILL_DIR / "examples.md").exists()
