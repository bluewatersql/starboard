"""E12 Reachability, skill text and bundles (spec §H.12, §F, D4-7, D4-9, D4-10).

* Every §F command appears in its named skill (and the auto agent), and the
  phase-2 ``command_flag_errors`` checker (3-word verbs) finds nothing.
* ``starboard-health-review`` and ``starboard-troubleshoot`` ship in
  ``plugin/skills``, both distribution bundles and the aitools manifest.
* The overlay names the internal-only leg of both skills.
* The troubleshoot and health-review texts name their D4-10 / D4-13 steps;
  the auto agent says local ``run recur`` writes ``analysis/health.json``.
* On Drive-run paths the deliver text and capability-bind never say
  ``local: <reason>`` or offer a "local-Markdown fallback"; they say
  ``not delivered:``.
* The writer inventory is unchanged and green.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest

from ._support import helper

PKG = Path(__file__).resolve().parents[3]
REPO = PKG.parents[1]
SKILLS = PKG / "skills" / "starboard"
AGENTS = PKG / "agents"
OVERLAY = (
    REPO / "packages" / "starboard-internal" / "skills" / "starboard-internal-overlay"
)
DIST = REPO / "packages" / "starboard-distribution"
HELPER = "starboard-helper"
NEW_SKILLS = ("starboard-health-review", "starboard-troubleshoot")
FOCUSED = (
    "starboard-discovery",
    "starboard-workload-review",
    "starboard-diagnostic",
    "starboard-job",
    "starboard-query",
)

ENG = "starboard-engagement"
HEALTH = "starboard-health-review"
TROUBLE = "starboard-troubleshoot"
DELIVER = "starboard-deliver"
AUTO = "auto-agent"
OVERLAY_KEY = "overlay"
CAPABILITY_BIND = "capability-bind"
RUN_CHECKLIST = "run-checklist"

#: one ``engagement`` verb that takes ``--run-dir DIR --workspace-root CASE_ROOT`` (B7)
RUN_DIR_VERBS = (
    ("engagement", "analyze"),
    ("engagement", "case"),
    ("engagement", "action"),
    ("engagement", "play"),
)
#: (cli, alternative word prefixes, needles every one of which is in the segment)
Want = tuple[str, tuple[tuple[str, ...], ...], tuple[str, ...]]
SOURCE_OPTIONS: Want = (HELPER, (("engagement", "source-options"),), ())
RUN_CHECK: Want = (HELPER, (("run", "check"),), ())
RUN_DIR: Want = (HELPER, RUN_DIR_VERBS, ("--run-dir", "--workspace-root"))
RECUR: Want = (HELPER, (("run", "recur"),), ("--workspace-root",))
DRIVE_OBJECT: Want = (HELPER, (("engagement", "case", "open"),), ("--drive-object",))
DERIVED_FROM: Want = (HELPER, (("engagement", "report"),), ("--derived-from",))
HEALTH_REPORT: Want = (
    HELPER,
    (("engagement", "report"),),
    ("--report-id health-read",),
)

WIRING: dict[str, tuple[Want, ...]] = {
    ENG: (SOURCE_OPTIONS, RUN_CHECK, RUN_DIR, RECUR),
    HEALTH: (
        SOURCE_OPTIONS,
        (
            HELPER,
            (("engagement", "preflight"),),
            ("--task health_check", "--source-mode"),
        ),
        RUN_DIR,
        RUN_CHECK,
        HEALTH_REPORT,
        RECUR,
    ),
    TROUBLE: (
        SOURCE_OPTIONS,
        (
            HELPER,
            (("engagement", "preflight"),),
            ("--task troubleshooting", "--source-mode"),
        ),
        RUN_DIR,
        RUN_CHECK,
        DRIVE_OBJECT,
    ),
    OVERLAY_KEY: (
        SOURCE_OPTIONS,
        DRIVE_OBJECT,
        (HELPER, (("engagement", "case", "open"),), ("--clue",)),
    ),
    AUTO: (RUN_DIR, RECUR),
    DELIVER: (DERIVED_FROM,),
    CAPABILITY_BIND: (DERIVED_FROM,),
    RUN_CHECKLIST: (RUN_CHECK,),
}

PHRASES: dict[str, tuple[str, ...]] = {
    ENG: (
        "deliverables/health-read.md",
        "deliverables/case-report.md",
        "skipped_by_profile",
        HEALTH,
        TROUBLE,
    ),
    RUN_CHECKLIST: ("deliverables/health-read.md", "skipped_by_profile"),
    HEALTH: (
        "deliverables/health-read.md",
        "engagement history",
        "engagement status",
        TROUBLE,
        "--finding-id",
    ),
    TROUBLE: (
        "--drive-object",
        "internal_only",
        "Unknowns",
        "not acquired (no customer profile)",
        "deliverables/case-report.md",
    ),
    OVERLAY_KEY: (HEALTH, TROUBLE, "--source-mode internal_only", "--storage local"),
    "starboard-analyze": (HEALTH, TROUBLE),
    **dict.fromkeys(FOCUSED, (HEALTH, TROUBLE)),
}

AUTO_HEALTH = re.compile(r"analysis/(?:health\.json|\{[^}]*\bhealth\b[^}]*\}\.json)")
DRIVE_FORBIDDEN = re.compile(r"local: <reason>|local-Markdown fallback", re.IGNORECASE)
LOCAL_QUALIFIER = re.compile(
    r"\blocal run|\blocal-run|internal-only-local", re.IGNORECASE
)


@cache
def _checks() -> ModuleType:
    """The phase-2 D-28 extractor (``tests/test_engagement_phase2_skill_text.py``)."""
    name = "_phase2_skill_text_p4"
    path = PKG / "tests" / "test_engagement_phase2_skill_text.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _skill_sources(skill: str) -> list[Path]:
    root = SKILLS / skill
    assert (root / "SKILL.md").is_file(), f"{skill}/SKILL.md does not exist"
    return [root / "SKILL.md", *sorted((root / "references").glob("*.md"))]


def _sources(key: str) -> list[Path]:
    refs = SKILLS / ENG / "references"
    if key == AUTO:
        return [AGENTS / "starboard-workload-review-auto.yaml"]
    if key == OVERLAY_KEY:
        assert (OVERLAY / "SKILL.md").is_file()
        return sorted(OVERLAY.glob("*.md"))
    if key == CAPABILITY_BIND:
        return [refs / "capability-bind.md"]
    if key == RUN_CHECKLIST:
        return [refs / "run-checklist.md"]
    return _skill_sources(key)


def _text(key: str) -> str:
    return "\n".join(p.read_text("utf-8") for p in _sources(key))


def _commands(key: str) -> list[tuple[str, tuple[str, ...], str]]:
    """``(cli, words, flattened segment)`` for every command, in text order."""
    checks = _checks()
    return [
        (cli, tuple(words), " ".join(seg.split()))
        for path in _sources(key)
        for cli, words, seg in checks.iter_commands(path, path.read_text("utf-8"))
    ]


def _matches(command: tuple[str, tuple[str, ...], str], want: Want) -> bool:
    cli, words, seg = command
    want_cli, prefixes, needles = want
    return (
        cli == want_cli
        and any(words[: len(p)] == p for p in prefixes)
        and all(n in seg for n in needles)
    )


# --------------------------------------------------------------------------- #
# §F commands and flags
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", sorted(WIRING), ids=str)
def test_each_surface_names_its_phase4_commands(key: str) -> None:
    seen = _commands(key)
    missing = [
        " | ".join(" ".join(p) for p in want[1]) + f" [{' '.join(want[2])}]"
        for want in WIRING[key]
        if not any(_matches(c, want) for c in seen)
    ]
    assert missing == [], f"{key} does not name: {missing}"


@pytest.mark.parametrize("key", sorted(PHRASES), ids=str)
def test_each_surface_carries_its_phase4_phrases(key: str) -> None:
    text = _text(key)
    assert [p for p in PHRASES[key] if p not in text] == []


@pytest.mark.parametrize(
    "key", sorted({*NEW_SKILLS, ENG, DELIVER, OVERLAY_KEY, AUTO}), ids=str
)
def test_every_flag_named_exists(key: str) -> None:
    checks = _checks()
    errors = [
        e
        for path in _sources(key)
        for e in checks.command_flag_errors(path, path.read_text("utf-8"))
    ]
    assert errors == [], "\n".join(errors)


@pytest.mark.usefixtures("public")
def test_source_options_has_help(capsys: pytest.CaptureFixture[str]) -> None:
    code, _env, raw = helper(capsys, "engagement", "source-options", "--help")
    assert code == 0, raw
    assert "usage:" in raw
    assert "--task" in raw


# --------------------------------------------------------------------------- #
# Bundles
# --------------------------------------------------------------------------- #
def _manifest_names() -> set[str]:
    doc = json.loads((DIST / "aitools" / "manifest.json").read_text("utf-8"))
    return {s.get("name") for s in doc.get("skills") or ()}


@pytest.mark.parametrize("skill", NEW_SKILLS)
def test_the_new_skill_ships_in_every_bundle(skill: str) -> None:
    for root in (
        SKILLS,
        REPO / "plugin" / "skills",
        DIST / "aitools",
        DIST / "opencode" / "skills",
    ):
        assert (root / skill / "SKILL.md").is_file(), root / skill
    assert skill in _manifest_names()


def test_the_readme_skill_table_lists_both_skills() -> None:
    text = (PKG / "README.md").read_text("utf-8")
    for skill in NEW_SKILLS:
        assert re.search(rf"^\|\s*`{re.escape(skill)}`\s*\|", text, re.MULTILINE), skill


# --------------------------------------------------------------------------- #
# Entry-skill steps
# --------------------------------------------------------------------------- #
def test_health_review_registers_the_health_read_before_run_check() -> None:
    seen = _commands(HEALTH)
    reports = [i for i, c in enumerate(seen) if _matches(c, HEALTH_REPORT)]
    checks = [i for i, c in enumerate(seen) if _matches(c, RUN_CHECK)]
    assert reports and checks, (reports, checks)
    assert reports[0] < checks[0], (
        "engagement report --report-id health-read after run check"
    )


def test_the_overlay_names_the_internal_only_leg() -> None:
    text = _text(OVERLAY_KEY)
    for skill in NEW_SKILLS:
        assert skill in text
    assert "--source-mode internal_only" in text
    assert "--storage local" in text


def test_the_auto_agent_says_local_recur_writes_health() -> None:
    text = _text(AUTO)
    assert AUTO_HEALTH.search(text), "auto agent does not name analysis/health.json"


# --------------------------------------------------------------------------- #
# D4-7 no local fallback on Drive runs
# --------------------------------------------------------------------------- #
def _paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _unqualified(text: str) -> list[str]:
    """Paragraphs that say a local-fallback phrase without a local-run qualifier."""
    out: list[str] = []
    heading = ""
    for para in _paragraphs(text):
        first = para.lstrip()
        if first.startswith("#"):
            heading = first.splitlines()[0]
        if not DRIVE_FORBIDDEN.search(para):
            continue
        if LOCAL_QUALIFIER.search(para) or LOCAL_QUALIFIER.search(heading):
            continue
        out.append(" ".join(para.split())[:240])
    return out


@pytest.mark.parametrize("key", (DELIVER, CAPABILITY_BIND))
def test_drive_runs_never_fall_back_to_local(key: str) -> None:
    text = _text(key)
    assert _unqualified(text) == []
    assert "not delivered:" in text
    assert "local: <reason>" in text, "the local-run path keeps its local: lines"


# --------------------------------------------------------------------------- #
# Writer inventory
# --------------------------------------------------------------------------- #
def test_writer_inventory_is_unchanged_and_green() -> None:
    from ..engagement_phase2 import test_exit_10_writer_inventory as inv

    found = inv._inventory()
    classified = set().union(*inv.TABLES.values())
    assert sorted(k for k in found if k not in classified) == []
    assert [k for k in found if "source-options" in " ".join(map(str, k))] == []
