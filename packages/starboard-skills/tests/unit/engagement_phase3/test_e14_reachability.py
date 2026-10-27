"""E14: every phase-3 command is named by its skill and exists in argparse (spec §F)."""

from __future__ import annotations

import importlib.util
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest

from ._support import helper, module

PKG = Path(__file__).resolve().parents[3]
SKILLS = PKG / "skills" / "starboard"
HELPER = "starboard-helper"

#: skill -> commands it must name: (cli, sub-command words, a substring of the command).
WIRING: dict[str, tuple[tuple[str, tuple[str, ...], str], ...]] = {
    "starboard-query": (
        (HELPER, ("query", "fetch"), "--query-id"),
        ("starboard_x.diagnostic", ("profile",), "--input"),
    ),
    "starboard-job": (
        (HELPER, ("job", "run-output"), "--task-key"),
        (HELPER, ("job", "code"), "--job-id"),
        (HELPER, ("verify", "run"), "vt-job-run-states"),
    ),
    "starboard-diagnostic": (
        (HELPER, ("query", "fetch"), ""),
        (HELPER, ("job", "run-output"), ""),
        (HELPER, ("job", "code"), ""),
        (HELPER, ("diagnostic", "driver-log"), "--cluster-id"),
        ("starboard_x.diagnostic", ("profile",), "--input"),
        ("starboard_x.sparklog", ("parse",), "--input"),
        ("starboard_x.diff", ("settings",), "--a"),
        ("starboard_x.diff", ("metrics",), "--a"),
        (HELPER, ("engagement", "case", "open"), "--question"),
        (HELPER, ("engagement", "case", "revise"), "--case-id"),
        (HELPER, ("engagement", "action", "propose"), "--case-id"),
    ),
    "starboard-engagement": (
        (HELPER, ("verify", "run"), "vt-job-run-states"),
        (HELPER, ("verify", "run"), "--limit 20000"),
        (HELPER, ("verify", "run"), "vt-job-runs"),
        (HELPER, ("engagement", "analyze"), ""),
        (HELPER, ("engagement", "case", "open"), "--finding-id"),
        (HELPER, ("engagement", "case", "open"), "--clue"),
        (HELPER, ("engagement", "case", "revise"), ""),
        (HELPER, ("engagement", "action", "propose"), "--next-step"),
        (HELPER, ("engagement", "action", "accept"), "--action-id"),
        (HELPER, ("engagement", "action", "execute"), "--executed-at"),
        (HELPER, ("engagement", "play", "rank"), "--reason"),
        ("starboard_x.diff", (), ""),
    ),
}

#: skill -> literal phrases its text must carry.
PHRASES: dict[str, tuple[str, ...]] = {
    "starboard-engagement": (
        "Insufficient evidence",
        "analysis/health.json",
        "analysis/plays.json",
        "troubleshooting/",
    ),
    "starboard-discovery": ("job_reliability_by_job", "F-12"),
}

NEW_HELPER_VERBS = (
    ("query", "fetch"),
    ("job", "run-output"),
    ("job", "code"),
    ("diagnostic", "driver-log"),
    ("engagement", "analyze"),
    ("engagement", "case", "open"),
    ("engagement", "case", "revise"),
    ("engagement", "case", "show"),
    ("engagement", "play", "rank"),
    *(
        ("engagement", "action", verb)
        for verb in ("propose", "accept", "reject", "execute", "withdraw")
    ),
)
NEW_MODULE_VERBS = (
    ("diagnostic", "profile"),
    ("sparklog", "parse"),
    ("diff", "settings"),
    ("diff", "metrics"),
)


@cache
def _skill_text_checks() -> ModuleType:
    """The phase-2 D-28 extractor (``tests/test_engagement_phase2_skill_text.py``)."""
    name = "_phase2_skill_text"
    path = PKG / "tests" / "test_engagement_phase2_skill_text.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _sources(skill: str) -> list[Path]:
    root = SKILLS / skill
    return [root / "SKILL.md", *sorted((root / "references").glob("*.md"))]


def _text(skill: str) -> str:
    return "\n".join(p.read_text("utf-8") for p in _sources(skill))


@pytest.mark.parametrize("skill", sorted(WIRING), ids=str)
def test_skill_names_its_phase3_commands(skill: str) -> None:
    checks = _skill_text_checks()
    seen = [
        (cli, tuple(words), " ".join(seg.split()))
        for path in _sources(skill)
        for cli, words, seg in checks.iter_commands(path, path.read_text("utf-8"))
    ]
    missing = [
        " ".join([cli, *words, f"[{needle}]"])
        for cli, words, needle in WIRING[skill]
        if not any(
            c == cli and w[: len(words)] == words and needle in s for c, w, s in seen
        )
    ]
    assert missing == [], f"{skill} does not name: {missing}"


@pytest.mark.parametrize("skill", sorted(PHRASES), ids=str)
def test_skill_carries_its_phase3_phrases(skill: str) -> None:
    text = _text(skill)
    assert [p for p in PHRASES[skill] if p not in text] == []


def test_verify_sql_documents_the_run_states_template() -> None:
    text = (SKILLS / "starboard-engagement" / "references" / "verify-sql.md").read_text(
        "utf-8"
    )
    assert "### vt-job-run-states:" in text
    assert "### vt-job-runs:" in text


@pytest.mark.parametrize("skill", sorted({*WIRING, *PHRASES}), ids=str)
def test_every_flag_named_in_the_skill_exists(skill: str) -> None:
    checks = _skill_text_checks()
    errors = [
        e
        for path in _sources(skill)
        for e in checks.command_flag_errors(path, path.read_text("utf-8"))
    ]
    assert errors == [], "\n".join(errors)


@pytest.mark.usefixtures("public")
@pytest.mark.parametrize("verb", NEW_HELPER_VERBS, ids=" ".join)
def test_new_helper_verbs_have_help(verb, capsys) -> None:
    code, _env, raw = helper(capsys, *verb, "--help")
    assert code == 0, raw
    assert "usage:" in raw


@pytest.mark.usefixtures("public")
@pytest.mark.parametrize("verb", NEW_MODULE_VERBS, ids=" ".join)
def test_new_module_verbs_have_help(verb, capsys) -> None:
    code, _env, raw = module(verb[0], capsys, verb[1], "--help")
    assert code == 0, raw
    assert "usage:" in raw


def test_writer_inventory_walks_the_new_surfaces() -> None:
    from ..engagement_phase2 import test_exit_10_writer_inventory as inv

    assert "starboard_x.diff" in inv.SURFACES
    assert "packages/starboard-core/starboard_x/diff/__main__.py" in inv.PARSER_MODULES
    found = inv._inventory()
    classified = set().union(*inv.TABLES.values())
    assert sorted(k for k in found if k not in classified) == []
    for key in (
        ("starboard_x.diff", "settings", "--a"),
        ("starboard_x.diff", "metrics", "--b"),
        ("starboard_x.diagnostic", "profile", "--input"),
        ("starboard_x.sparklog", "parse", "--input"),
    ):
        assert key in classified, key
