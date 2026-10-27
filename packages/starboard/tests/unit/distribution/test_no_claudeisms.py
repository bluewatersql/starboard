# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Claude-ism drift-lint for the GENERATED non-Claude distribution bundles.

The canonical skills tree is authored for Claude Code / Isaac. The generated
``aitools`` and ``opencode`` bundles ship to non-Claude hosts (Codex, OpenCode,
``databricks aitools``), so the mirror generators (``scripts/skills.py``,
``scripts/port_to_opencode.py``) must *adapt* the bodies — not copy them
verbatim — rewriting Claude-Code-only constructs to their portable equivalents
(see ``scripts/skill_transform.py``).

This test fails if any Claude-ism leaks into those generated bundles:

* ``CLAUDE_SKILL_DIR``     — set only by Claude Code; the ``run.sh`` wrapper path
  breaks everywhere else (must be rewritten to ``python -m starboard_x.<cap>`` /
  ``starboard <verb>``).
* ``artifact-design``      — a Claude-Code skill name.
* the ``Artifact`` tool    — a Claude-Code-only tool (matched as the backtick
  token ```Artifact``` or the phrase "Artifact tool"; the generic word
  "artifact"/"Artifact selection" as a deliverable is host-neutral and allowed).
* ``Isaac``                — a specific host product name.

Not yet failed on (deferred to the tool-profile design): ``mcp__google__*``
bindings may still appear as documented tool references for now.

Rides ``make test-unit``. If it fails, re-run the generators
(``make vendor-skills`` / ``python scripts/skills.py`` /
``python scripts/port_to_opencode.py``) after fixing the canonical source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise AssertionError(
        "could not locate repo root containing packages/starboard-skills/skills"
    )


REPO_ROOT = _repo_root()
DISTRIBUTION_ROOT = REPO_ROOT / "packages" / "starboard-distribution"
GENERATED_BUNDLES = ("aitools", "opencode")

#: Text extensions whose content is scanned. (The bundles contain only these.)
_TEXT_SUFFIXES = frozenset({".md", ".sh", ".json", ".txt"})

#: (label, compiled pattern) for each Claude-ism. Patterns are precise so the
#: generic word "artifact" (a deliverable) does not false-positive.
_CLAUDEISM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CLAUDE_SKILL_DIR", re.compile(r"CLAUDE_SKILL_DIR")),
    ("artifact-design skill", re.compile(r"artifact-design")),
    ("Artifact tool", re.compile(r"`Artifact`|Artifact tool")),
    ("Isaac (host product name)", re.compile(r"Isaac")),
    # An unstripped claude-only fence proves the marker-stripping transform did
    # not run — the Claude-only convenience note leaked into a non-Claude bundle.
    ("claude-only marker (unstripped)", re.compile(r"claude-only")),
)


def _generated_files() -> list[Path]:
    files: list[Path] = []
    for bundle in GENERATED_BUNDLES:
        root = DISTRIBUTION_ROOT / bundle
        if not root.is_dir():
            continue
        files.extend(
            p
            for p in sorted(root.rglob("*"))
            if p.is_file() and p.suffix in _TEXT_SUFFIXES
        )
    return files


_GENERATED_FILES = _generated_files()


def test_generated_bundles_exist() -> None:
    """Guard against a silently-empty scan (e.g. bundles not generated)."""
    assert _GENERATED_FILES, (
        "no generated bundle files found under "
        f"{DISTRIBUTION_ROOT} — run the mirror generators"
    )


@pytest.mark.parametrize("path", _GENERATED_FILES, ids=lambda p: str(p.relative_to(DISTRIBUTION_ROOT)))
def test_no_claudeisms_in_generated_bundle(path: Path) -> None:
    """No Claude-ism may appear in a generated non-Claude bundle file."""
    text = path.read_text(encoding="utf-8")
    hits: list[str] = []
    for label, pattern in _CLAUDEISM_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    assert not hits, (
        f"{path.relative_to(DISTRIBUTION_ROOT)} ships Claude-ism(s) {hits} to a "
        "non-Claude bundle. Fix the canonical source and/or the mirror transform "
        "(scripts/skill_transform.py), then re-run the generators."
    )
