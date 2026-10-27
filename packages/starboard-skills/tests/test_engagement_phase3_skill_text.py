# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-3 skill text: the health read, plays, cases and actions are reachable from prompts.

Reuses the phase-2 D-28 extractor (``iter_commands`` / ``command_flag_errors``) so every phase-3
command written in a skill is checked against the real parser. It also pins the phase-3 rules the
host must see: the analyze beat sits between verify and present, the insufficient-evidence and
unknowns rule, the host rubric (six factors, reorder only with a reason), the action/outcome rules
(improvement is not adoption), the cross-run case sub-flow, and ``--limit`` on every engagement
``verify run``. Surfaces not shipped yet stay out of the text. (The overlay's phase-3 text is pinned in
``starboard-internal/tests/test_overlay_skill.py``.)
"""

from __future__ import annotations

import importlib.util
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest

_PKG = Path(__file__).parents[1]
_SKILLS = _PKG / "skills" / "starboard"
_SCAFFOLD = _SKILLS / "starboard-engagement"
_ENGAGEMENT = _SCAFFOLD / "SKILL.md"
_PHASE3_SKILLS = ("engagement", "query", "job", "diagnostic", "discovery")
_FILES = (
    *(_SKILLS / f"starboard-{n}" / "SKILL.md" for n in _PHASE3_SKILLS),
    _SCAFFOLD / "references" / "capability-bind.md",
    _SCAFFOLD / "references" / "run-checklist.md",
    _SCAFFOLD / "references" / "verify-sql.md",
)

# (skill, cli, sub-command words, a flag or token the command must carry)
_COMMANDS = (
    ("query", "starboard-helper", "query fetch", "--query-id"),
    ("query", "starboard_x.diagnostic", "profile", "--input"),
    ("job", "starboard-helper", "job run-output", "--task-key"),
    ("job", "starboard-helper", "job code", "--job-id"),
    ("job", "starboard-helper", "verify run", "vt-job-run-states"),
    ("job", "starboard-helper", "engagement case open", "--clue"),
    ("job", "starboard-helper", "engagement case revise", "--case-id"),
    ("job", "starboard-helper", "engagement commit", "--stage analysis"),
    ("diagnostic", "starboard-helper", "job run-output", "--run-id"),
    ("diagnostic", "starboard-helper", "job code", "--job-id"),
    ("diagnostic", "starboard-helper", "query fetch", "--query-id"),
    ("diagnostic", "starboard-helper", "diagnostic driver-log", "--cluster-id"),
    ("diagnostic", "starboard_x.diagnostic", "profile", "--input"),
    ("diagnostic", "starboard_x.sparklog", "parse", "--input"),
    ("diagnostic", "starboard_x.diff", "settings", "--a"),
    ("diagnostic", "starboard_x.diff", "metrics", "--b"),
    ("diagnostic", "starboard-helper", "engagement case open", "--question"),
    ("diagnostic", "starboard-helper", "engagement case revise", "--case-id"),
    ("engagement", "starboard-helper", "verify run", "vt-job-run-states"),
    ("engagement", "starboard-helper", "verify run", "vt-job-runs "),
    ("engagement", "starboard-helper", "engagement analyze", "--run-folder"),
    ("engagement", "starboard-helper", "engagement case open", "--finding-id"),
    ("engagement", "starboard-helper", "engagement case open", "--clue"),
    ("engagement", "starboard-helper", "engagement case revise", "--case-id"),
    ("engagement", "starboard-helper", "engagement case show", "--case-id"),
    ("engagement", "starboard-helper", "engagement action accept", "--action-id"),
    ("engagement", "starboard-helper", "engagement action execute", "--executed-at"),
    ("engagement", "starboard-helper", "engagement play rank", "--reason"),
    ("engagement", "starboard-helper", "engagement commit", "--stage analysis"),
    ("engagement", "starboard_x.diff", "settings", "--run-folder"),
)

#: phase-3 surfaces stay free of these; phase 4 ships the two task entry skills, so only the
#: still-unshipped surfaces remain forbidden here.
_FORBIDDEN = (
    "diff text",
    "--source local",
)


@cache
def _d28() -> ModuleType:
    path = Path(__file__).with_name("test_engagement_phase2_skill_text.py")
    spec = importlib.util.spec_from_file_location("_phase2_skill_text_for_phase3", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _segments(path: Path) -> list[tuple[str, str, str]]:
    return [
        (cli, " ".join(words), seg.replace("\\\n", " "))
        for cli, words, seg in _d28().iter_commands(path, _text(path))
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("skill", "cli", "words", "token"), _COMMANDS, ids=lambda v: str(v).strip()
)
def test_skill_names_the_phase3_command(
    skill: str, cli: str, words: str, token: str
) -> None:
    path = _SKILLS / f"starboard-{skill}" / "SKILL.md"
    found = [seg for c, w, seg in _segments(path) if c == cli and w == words]
    assert any(token in seg for seg in found), (
        f"starboard-{skill}: no `{cli} {words} … {token}`"
    )


@pytest.mark.unit
@pytest.mark.parametrize("path", _FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_named_flag_exists(path: Path) -> None:
    errors = _d28().command_flag_errors(path, _text(path))
    assert not errors, "\n".join(errors)


@pytest.mark.unit
def test_analyze_beat_sits_between_verify_and_present() -> None:
    text = _text(_ENGAGEMENT)
    assert "→ verify → analyze" in text
    verify = text.index("3. **verify**")
    analyze = text.index("4. **analyze")
    present = text.index("5. **present")
    assert verify < analyze < present
    beat = text[analyze:present]
    assert "starboard-helper engagement analyze --run-folder $RUN_FOLDER" in beat
    for phrase in (
        "analysis/health.json",
        "Insufficient evidence",
        "## Unknowns",
        "- <family>: unknown",
        "health_read",
    ):
        assert phrase in beat, phrase
    assert "analysis/plays.json" in text[present:]


@pytest.mark.unit
def test_host_rubric_names_six_factors_and_the_reorder_reason() -> None:
    text = _text(_ENGAGEMENT)
    rubric = text[text.index("## Host rubric") : text.index("## Cases")]
    for factor in (
        "urgency",
        "criticality",
        "exposure",
        "evidence_strength",
        "reversibility",
        "owner_availability",
    ):
        assert f"`{factor}`" in rubric, factor
    assert "engagement play rank" in rubric and "--reason" in rubric
    assert "only with a stated reason" in rubric


@pytest.mark.unit
def test_recur_beat_states_the_action_and_outcome_rules() -> None:
    text = _text(_ENGAGEMENT)
    recur = text[text.index("10. **recur**") : text.index("## Host rubric")]
    for phrase in (
        "INVALID_TRANSITION",
        "consistent_with_action",
        "not_established",
        "never `improved`",
        "Improvement is not adoption",
        "`acceptance_state`",
    ):
        assert phrase in recur, phrase


@pytest.mark.unit
def test_case_sub_flow_spans_a_troubleshooting_and_a_health_check_run() -> None:
    text = _text(_ENGAGEMENT)
    cases = text[text.index("## Cases") :]
    for phrase in (
        "troubleshooting/",
        "health_check/",
        "revision + 1",
        "case:<kind>",
        "never makes a health family assessed",
    ):
        assert phrase in cases, phrase


def _next_command(path: Path, words: str) -> list[str]:
    """The sub-command words of the command after each ``words`` command, in order."""
    segs = [(c, w) for c, w, _ in _segments(path) if c == "starboard-helper"]
    return [
        segs[i + 1][1] if i + 1 < len(segs) else ""
        for i, (_, w) in enumerate(segs)
        if w == words
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "words",
    [
        "engagement case revise",
        "engagement action propose",
        "engagement action execute",
        "engagement play rank",
    ],
)
def test_engagement_analysis_writes_are_followed_by_an_analysis_commit(
    words: str,
) -> None:
    """``case revise``, ``action …`` and ``play rank`` rewrite ``analysis/*.json``."""
    after = _next_command(_ENGAGEMENT, words)
    assert after and all(w == "engagement commit" for w in after), (words, after)
    cases = _text(_ENGAGEMENT)[_text(_ENGAGEMENT).index("## Cases") :]
    assert "engagement commit --run-folder $RUN_FOLDER --stage analysis" in cases


@pytest.mark.unit
def test_job_skill_routes_a_failure_to_a_case_and_commits() -> None:
    path = _SKILLS / "starboard-job" / "SKILL.md"
    words = [w for c, w, _ in _segments(path) if c == "starboard-helper"]
    opened = words.index("engagement case open")
    assert words[opened + 1 : opened + 3] == [
        "engagement case revise",
        "engagement commit",
    ]


@pytest.mark.unit
def test_hypothesis_states_match_the_parser() -> None:
    from starboard_skills.helpers.engagement.case_cmds import HYPOTHESIS_STATES

    assert "inconclusive" not in HYPOTHESIS_STATES
    cases = _text(_ENGAGEMENT)[_text(_ENGAGEMENT).index("## Cases") :]
    assert "inconclusive" not in cases
    assert all(f"`{state}`" in cases for state in HYPOTHESIS_STATES)


def _vt_id(seg: str) -> str:
    rest = seg.split("verify run", 1)[1].split()
    return rest[0] if rest else ""


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        _ENGAGEMENT,
        _SCAFFOLD / "references" / "verify-sql.md",
        _SCAFFOLD / "references" / "run-checklist.md",
        _SKILLS / "starboard-job" / "SKILL.md",
    ],
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_every_engagement_verify_run_carries_a_limit(path: Path) -> None:
    """Every runnable example (a real template id or the recipe line) passes ``--limit``."""
    missing = [
        seg.strip()
        for c, w, seg in _segments(path)
        if c == "starboard-helper"
        and w == "verify run"
        and "--limit" not in seg
        and _vt_id(seg).startswith("vt-")
        and "$ARGS" not in seg  # a real id; not the pitfall
    ]
    assert missing == [], missing
    if path == _ENGAGEMENT:
        recipe = [
            seg
            for c, w, seg in _segments(path)
            if w == "verify run" and _vt_id(seg) == "<vt-id>"
        ]
        assert recipe and all("--limit" in seg for seg in recipe)


@pytest.mark.unit
def test_discovery_documents_the_per_job_reliability_field() -> None:
    text = _text(_SKILLS / "starboard-discovery" / "SKILL.md")
    for phrase in (
        "job_reliability_by_job",
        "F-12",
        "top 25",
        "per_job_cap_25",
        "F-06",
    ):
        assert phrase in text, phrase


@pytest.mark.unit
@pytest.mark.parametrize("path", _FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_phase4_names(path: Path) -> None:
    text = _text(path)
    assert [f for f in _FORBIDDEN if f in text] == []
