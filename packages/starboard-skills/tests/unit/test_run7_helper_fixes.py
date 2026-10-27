"""Live run 7 fixes to the engagement helper.

* ``play rank`` returns the play's ``action_id``: the skill says it refreshes on
  ``play rank``, but the envelope had none, so hosts read ``action_id: null``
  and had to open ``plays.json`` for it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from .conftest import drive_files, run_main
from .test_run_recur_drive import _current


def _eng(run, capsys, *argv: str) -> dict[str, Any]:
    code, out = run_main(["engagement", *argv, "--run-folder", run.folder_id], capsys)
    assert code == 0, out
    return json.loads(out)["data"]


def _plays(run) -> list[dict[str, Any]]:
    return json.loads(drive_files(run)["analysis/plays.json"])


@pytest.mark.unit
def test_play_rank_returns_the_plays_action_id(covered_env, drive_run, capsys) -> None:
    _current(drive_run)
    _eng(drive_run, capsys, "analyze")
    play = next(p for p in _plays(drive_run) if p["action_id"])
    data = _eng(
        drive_run,
        capsys,
        "play",
        "rank",
        "--play-id",
        play["play_id"],
        "--rank",
        "1",
        "--reason",
        "owner asked first",
    )
    assert data["action_id"] == play["action_id"]
    assert data["effective_rank"] == 1


def _rule_of(finding: dict[str, Any]) -> str | None:
    code = finding["concern_code"]
    return code.removeprefix("rule:") if code.startswith("rule:") else None


@pytest.mark.unit
def test_plays_json_rows_carry_severity_and_review_rule_id(
    covered_env, drive_run, capsys
) -> None:
    # Run 7: plays.json rows had no severity (hosts read null) and a play's
    # rule_id is the play rule set, so a review rule's play could not be found.
    _current(drive_run)
    _eng(drive_run, capsys, "analyze")
    findings = {
        f["finding_id"]: f
        for f in json.loads(drive_files(drive_run)["analysis/findings.json"])
    }
    plays = [p for p in _plays(drive_run) if p["finding_ids"]]
    assert plays and any(p["review_rule_id"] for p in plays)
    for p in plays:
        finding = findings[p["finding_ids"][0]]
        assert p["severity"] == finding["severity"]
        assert p["review_rule_id"] == _rule_of(finding)
        assert p["rule_id"] == "play_rules_v1"


@pytest.mark.unit
def test_the_digest_carries_acceptance_state_and_review_rule_id(
    covered_env, drive_run, capsys
) -> None:
    # Run 7: "accept one still pending" had no state in the digest.
    _current(drive_run)
    data = _eng(drive_run, capsys, "analyze")
    actions = {
        a["action_id"]: a
        for a in json.loads(drive_files(drive_run)["analysis/actions.json"])
    }
    by_id = {p["play_id"]: p for p in _plays(drive_run)}
    for entry in data["top_plays"]:
        assert entry["review_rule_id"] == by_id[entry["play_id"]]["review_rule_id"]
        expected = (
            actions[entry["action_id"]]["acceptance_state"]
            if entry["action_id"]
            else None
        )
        assert entry["acceptance_state"] == expected
        for other in entry["same_target_plays"]:
            assert "acceptance_state" in other
    accepted = next(e for e in data["top_plays"] if e["action_id"])
    _eng(
        drive_run,
        capsys,
        "action",
        "accept",
        "--action-id",
        accepted["action_id"],
        "--note",
        "owner agreed",
    )
    again = _eng(drive_run, capsys, "analyze")
    entry = next(e for e in again["top_plays"] if e["play_id"] == accepted["play_id"])
    assert entry["acceptance_state"] == "accepted"
