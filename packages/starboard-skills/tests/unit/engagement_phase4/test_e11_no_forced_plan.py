"""E11 No forced eight-item plan (spec §H.11, B2, D4-9, D4-10).

* ``health_check`` and ``troubleshooting`` runs with zero verify pairs, no
  backlog and no notebooks pass ``run check``.
* The same inputs under ``action_plan`` fail item 5 (the verify-pair floor).
* The two entry skills carry no ``~8`` / ``eight`` / ``min(8`` and no
  "notebook per"; the engagement and action-plan floor sentences name the
  ``action_plan`` task.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from . import _fixtures
from ._support import (
    CASE_REPORT,
    HEALTH_READ,
    QUESTION,
    Ctx,
    Run,
    analyze,
    case_report,
    commit,
    engagement_ok,
    failed_ids,
    has,
    health_body,
    host_put,
    new_run,
    readme,
    records,
    report,
    run_check,
    run_recur,
    write_inputs,
)

DRIVE = pytest.mark.parametrize("mode", ["drive_backed"])

SKILLS = Path(__file__).resolve().parents[3] / "skills" / "starboard"
ENTRY_SKILLS = ("starboard-health-review", "starboard-troubleshoot")
FLOOR_FILES = (
    SKILLS / "starboard-engagement" / "SKILL.md",
    SKILLS / "starboard-action-plan" / "SKILL.md",
)
FORBIDDEN = re.compile(r"~\s?8|\beight\b|min\(8|notebook per", re.IGNORECASE)
TROUBLE_README = "not applicable: troubleshooting run"
NO_PLAN_FILES = ("analysis/backlog.json", "deliverables/action-plan.md")


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
def _health_inputs(ctx: Ctx, task: str) -> Run:
    """Capture -> analyze (no verify) -> recur -> health read -> report."""
    run = new_run(ctx, task=task, task_name=f"ws-{task}")
    write_inputs(
        ctx, run, facts=_fixtures.current_facts(), review=_fixtures.review_manifest()
    )
    analyze(ctx, run, _fixtures.CURRENT)
    commit(ctx, run)
    code, _data, raw = run_recur(ctx, run, baseline=True)
    assert code == 0, raw
    host_put(ctx, run, HEALTH_READ, health_body(records(ctx, run).health))
    readme(ctx, run)
    commit(ctx, run)
    code, _env, raw = report(ctx, run, "health-read", HEALTH_READ, "internal")
    assert code == 0, raw
    return run


def _case_inputs(ctx: Ctx, task: str) -> Run:
    """Clue case -> revise (hypothesis only) -> case report; zero verify pairs.

    A customer-workspace Drive run: ``verify-identity`` scopes the one workspace
    the clue case needs, so no acquiring verb (and so no verify pair) is needed.
    """
    run = new_run(ctx, task=task, task_name="job-42")
    opened = engagement_ok(
        ctx,
        run,
        "case",
        "open",
        *run.flags(),
        "--clue",
        f"job:{_fixtures.JOB}",
        "--question",
        QUESTION,
    )
    engagement_ok(
        ctx,
        run,
        "case",
        "revise",
        *run.flags(),
        "--case-id",
        opened["case_id"],
        "--hypothesis",
        "the 2026-09-22 change broke job 42",
    )
    host_put(ctx, run, CASE_REPORT, case_report([opened["case_id"]]))
    readme(ctx, run, delivery=f"- {CASE_REPORT}", recur=TROUBLE_README)
    commit(ctx, run)
    return run


INPUTS = {"health_check": _health_inputs, "troubleshooting": _case_inputs}


def _no_plan(ctx: Ctx, run: Run) -> None:
    """Zero verify pairs, no backlog, no notebooks."""
    for rel in NO_PLAN_FILES:
        assert not has(ctx, run, rel), rel


@DRIVE
@pytest.mark.parametrize("task", sorted(INPUTS))
def test_a_focused_run_without_a_plan_passes_run_check(ctx: Ctx, task: str) -> None:
    run = INPUTS[task](ctx, task)
    _no_plan(ctx, run)
    code, data, raw = run_check(ctx, run)
    assert data.get("profile") == task, raw[:2000]
    assert "5" not in failed_ids(data)
    assert failed_ids(data) == set(), raw[:2000]
    assert code == 0


@DRIVE
@pytest.mark.parametrize("inputs", sorted(INPUTS))
def test_the_same_inputs_under_action_plan_fail_item_5(ctx: Ctx, inputs: str) -> None:
    run = INPUTS[inputs](ctx, "action_plan")
    _no_plan(ctx, run)
    code, data, raw = run_check(ctx, run)
    assert data.get("profile") == "action_plan", raw[:2000]
    assert "5" in failed_ids(data), raw[:2000]
    assert code == 1


# --------------------------------------------------------------------------- #
# Skill text
# --------------------------------------------------------------------------- #
def _skill_text(skill: str) -> str:
    root = SKILLS / skill
    assert (root / "SKILL.md").is_file(), f"{skill}/SKILL.md does not exist"
    return "\n".join(p.read_text("utf-8") for p in sorted(root.rglob("*.md")))


@pytest.mark.parametrize("skill", ENTRY_SKILLS)
def test_entry_skills_carry_no_eight_item_plan(skill: str) -> None:
    text = _skill_text(skill)
    assert FORBIDDEN.findall(text) == []


def _body(path: Path) -> str:
    """The text after the YAML front matter."""
    text = path.read_text("utf-8")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        return text[end + 4 :] if end >= 0 else text
    return text


FLOOR = re.compile(r"~\s?\**8|\beight is a floor|min\(8", re.IGNORECASE)
WINDOW = 400


def _floor_windows(text: str) -> list[str]:
    """The text around each eight-item floor mention (±``WINDOW`` characters)."""
    return [
        text[max(0, m.start() - WINDOW) : m.end() + WINDOW]
        for m in FLOOR.finditer(text)
    ]


@pytest.mark.parametrize("path", FLOOR_FILES, ids=lambda p: p.parent.name)
def test_the_floor_sentences_name_the_action_plan_task(path: Path) -> None:
    floors = _floor_windows(_body(path))
    assert floors, f"{path.parent.name}: no eight-item floor sentence"
    unscoped = [" ".join(w.split())[:240] for w in floors if "action_plan" not in w]
    assert unscoped == []
