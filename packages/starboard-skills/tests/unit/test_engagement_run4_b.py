# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 4 (group B): the analyze digest and the run target of printed commands."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_skills.helpers.engagement import analysis_cmds as ac

pytestmark = pytest.mark.unit


def _play(pid: str, code: str, kind: str, eid: str, **over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "play_id": pid,
        "play_code": code,
        "interaction_type": "working_session",
        "next_step_kind": "act",
        "target_entity_kind": kind,
        "target_entity_id": eid,
        "finding_ids": (f"f-{pid}",),
        "urgency": "high",
        "exposure": {
            "failed_runs": 3,
            "failed_run_dbus": 10.0,
            "exposure_dbus": None,
            "exposure_dbus_per_day": None,
        },
        "host_rank": None,
        "reason": "r",
        "next_commands": ("cmd",),
        "placeholders": ("warehouse_id",),
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_top_plays_one_entry_per_entity_target() -> None:
    plays = [
        _play("p1", "job_reliability_session", "job", "42"),
        _play("p2", "rule_finding_review", "job", "42"),
        _play("p3", "rule_finding_review", "job", "77"),
        _play("w1", "acquire_family_evidence", "workspace", "123"),
        _play("w2", "acquire_family_evidence", "workspace", "123"),
    ]
    top = ac.top_plays(plays, {"f-p1": "serious"}, {"p1": "act_1", "p2": "act_2"})
    assert [t["play_id"] for t in top] == ["p1", "p3", "w1", "w2"]
    lead = top[0]
    assert lead["action_id"] == "act_1" and lead["severity"] == "serious"
    assert lead["same_target_plays"] == [
        {
            "play_id": "p2",
            "play_code": "rule_finding_review",
            "action_id": "act_2",
            "effective_rank": 2,
            "acceptance_state": None,
        }
    ]
    assert lead["placeholders"] == ["warehouse_id"]
    # Exposure is counted once per target: the lead's only.
    total = sum(t["exposure"]["failed_run_dbus"] or 0 for t in top)
    assert total == 40.0
    assert top[1]["action_id"] is None and top[1]["same_target_plays"] == []


def test_top_plays_limit_counts_distinct_targets_and_keeps_later_same_target_plays() -> (
    None
):
    plays = [_play(f"p{i}", "c", "job", str(i)) for i in range(12)]
    plays.append(_play("late", "d", "job", "0"))
    top = ac.top_plays(plays, {}, {}, limit=10)
    assert [t["target"] for t in top] == [f"job:{i}" for i in range(10)]
    assert [s["play_id"] for s in top[0]["same_target_plays"]] == ["late"]


def test_top_plays_follow_host_rank() -> None:
    plays = [
        _play("a", "c", "job", "1"),
        _play("b", "c", "job", "1", host_rank=1, host_reorder_reason="owner"),
    ]
    (entry,) = ac.top_plays(plays, {}, {})
    assert entry["play_id"] == "b" and entry["effective_rank"] == 1
    assert entry["same_target_plays"][0]["play_id"] == "a"


def test_plays_by_code_counts_and_bounded_ids() -> None:
    plays = [_play(f"p{i}", "c", "job", str(i)) for i in range(30)]
    plays.append(_play("x", "other", "job", "x", host_rank=1))
    out = ac.plays_by_code(plays)
    assert out["other"]["count"] == 1 and out["other"]["play_ids"] == ["x"]
    assert [s["play_id"] for s in out["other"]["samples"]] == ["x"]
    assert out["c"]["count"] == 30
    assert out["c"]["play_ids"] == [f"p{i}" for i in range(25)]


def _overlay(home: Path, rel: str, *, templates: bool = True) -> Path:
    skill = home / rel / "starboard-internal-overlay"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("x", encoding="utf-8")
    if templates:
        (skill / ac.MIRROR_TEMPLATES_NAME).write_text("x", encoding="utf-8")
    return skill


def test_mirror_templates_is_home_relative(tmp_path: Path) -> None:
    _overlay(tmp_path, ".claude/skills")
    assert ac.mirror_templates(tmp_path) == (
        "~/.claude/skills/starboard-internal-overlay/mirror-verify.md"
    )


def test_mirror_templates_none_without_overlay_or_file(tmp_path: Path) -> None:
    assert ac.mirror_templates(tmp_path) is None
    _overlay(tmp_path, ".claude/skills", templates=False)
    assert ac.mirror_templates(tmp_path) is None


def _view(**args: Any) -> Any:
    auth = SimpleNamespace(
        source_mode=SimpleNamespace(value=args.pop("mode", "customer_workspace")),
        workspace_profile=args.pop("profile", None),
    )
    folder = args.pop("folder", None)
    return SimpleNamespace(
        helper=SimpleNamespace(run_folder=folder),
        auth=auth,
        args=SimpleNamespace(**args),
        internal=auth.source_mode.value == "internal_only",
    )


def test_run_target_drive_public() -> None:
    target = ac.run_target(
        _view(folder="F1", run_dir=None, warehouse_id="wh1", profile="p")
    )
    assert (target.run_folder, target.run_dir, target.warehouse_id) == (
        "F1",
        None,
        "wh1",
    )
    assert (
        target.profile == "p"
        and not target.internal
        and target.mirror_templates is None
    )


def test_run_target_local_internal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ac, "mirror_templates", lambda home=None: "~/m.md")
    target = ac.run_target(
        _view(
            mode="internal_only", run_dir=str(tmp_path), warehouse_id="wh1", profile="p"
        )
    )
    assert target.internal and target.run_dir == str(tmp_path.resolve())
    assert (target.warehouse_id, target.profile, target.mirror_templates) == (
        None,
        None,
        "~/m.md",
    )


def test_run_target_without_warehouse_flag_prints_the_placeholder() -> None:
    target = ac.run_target(_view(folder="F1"))
    assert target.warehouse_id is None and target.warehouse == "<warehouse_id>"
