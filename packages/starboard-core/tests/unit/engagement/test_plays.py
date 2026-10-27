# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for play_rules_v1 candidates (WP3-7, D3-9, OD-1)."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.changes import ChangeContext, build
from starboard_core.engagement.health import (
    RunTarget,
    project,
    targeted_requests,
)
from starboard_core.engagement.plays import (
    QUERY_LIMIT,
    RULE_VERIFY_TEMPLATES,
    PlayContext,
    candidates,
)
from starboard_core.engagement.records import Observation, Play, play_id

from .test_concerns import (
    CUR,
    INTERVAL,
    job_triplet,
    manifest,
    obs,
    present,
    prior,
    run,
    selection_for,
)

pytestmark = pytest.mark.unit

_VERIFY_SQL = (
    Path(__file__).resolve().parents[5]
    / "packages/starboard-skills/skills/starboard/starboard-engagement/references/verify-sql.md"
)
_SUPPORTED_PLACEHOLDERS = {
    "ws",
    "start",
    "end",
    "qh_start",
    "qh_end",
    "job_id",
    "job_ids",
    "warehouse_id",
    "lookback_days",  # derived from --start/--end (verify DERIVED_PLACEHOLDERS)
}


def plays_for(
    cur: list[Observation], base: list[Observation], **kw: Any
) -> tuple[tuple[Play, ...], Any]:
    manifest_doc = kw.pop("manifest", None)
    result = run(cur, base, manifest=manifest_doc)
    changes = build(
        cur, selection_for(cur, base), context=ChangeContext(baselines=base)
    )
    health = project(
        cur,
        result.findings,
        changes,
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
    )
    plays = candidates(
        result.findings,
        health,
        cur,
        run_id=CUR,
        interval=INTERVAL,
        changes=changes,
        review_severities=result.review_severities,
        **kw,
    )
    return plays, result


def non_acquire(plays: tuple[Play, ...]) -> list[Play]:
    return [p for p in plays if p.play_code != "acquire_family_evidence"]


def test_j42_serious_rise_is_one_working_session() -> None:
    cur, base = job_triplet(100, 8, 8.0), job_triplet(100, 1, 1.0, maker=prior)
    plays, result = plays_for(cur, base)
    (play,) = non_acquire(plays)
    fid = result.findings[0].finding_id
    assert play.play_id == play_id("job_reliability_session", fid)
    assert (play.interaction_type, play.owner_role, play.next_step_kind) == (
        "working_session",
        "job_owner",
        "act",
    )
    assert play.urgency == "high" and play.target_entity_id == "42"
    assert play.reason == (
        "job 42 failure rate 1.0% → 8.0% (+7.0 pp), 100 runs, "
        "windows 2026-09-08..2026-09-22 + 2026-09-23..2026-10-07"
    )
    assert dict(play.exposure) == {
        "failed_runs": 8,
        "failed_run_dbus": None,
        "exposure_dbus": None,
        "exposure_dbus_per_day": None,
    }
    assert play.evidence_strength == "strong"
    assert play.next_commands == (
        "starboard-helper verify run vt-job-run-states --ws 123 --job-ids 42 "
        "--start 2026-09-23 --end 2026-10-07 --limit 20000 "
        "--warehouse-id <warehouse_id> --suffix 42 --out analysis/verify",
        "starboard-helper job runs --job-id 42 --limit 25",
    )
    assert play.placeholders == ("warehouse_id",)
    assert "job_run_output" in play.missing_evidence
    assert "error_signature" in play.missing_evidence
    assert "criticality" not in play.missing_evidence
    check = play.follow_up_check
    assert check is not None and check["template"] == "vt-job-runs"
    assert dict(check["params"]) == {
        "ws": "123",
        "job_ids": "42",
        "limit": QUERY_LIMIT,
    }
    assert check["success_criterion"] == (
        "failure rate <= 3.0% (baseline 1.0% + 2.0 pp) over >= 50 runs"
    )
    assert play.audience_class == "customer_shareable"


def test_latest_failed_run_adds_run_output_command() -> None:
    cur, base = job_triplet(100, 8, 8.0), job_triplet(100, 1, 1.0, maker=prior)
    plays, _ = plays_for(cur, base, latest_failed_runs={"42": "987654"})
    (play,) = non_acquire(plays)
    assert play.next_commands[-1] == "starboard-helper job run-output --run-id 987654"
    assert "job_run_output" not in play.missing_evidence


def test_watch_is_investigation_without_baseline() -> None:
    plays, _ = plays_for(job_triplet(100, 8, 8.0), [])
    (play,) = non_acquire(plays)
    assert play.play_code == "job_reliability_investigation"
    assert (play.interaction_type, play.next_step_kind, play.urgency) == (
        "investigation",
        "investigate",
        "medium",
    )
    assert "(no eligible baseline)" in play.reason
    assert play.follow_up_check["success_criterion"] == (
        "failure rate < 5.0% over >= 50 runs"
    )


def test_serious_without_exposure_is_investigation() -> None:
    cur, base = job_triplet(100, 8, 8.0), job_triplet(100, 1, 1.0, maker=prior)
    result = run(cur, base)
    failed_id = cur[1].observation_id
    stripped = [
        replace(
            f, observation_ids=tuple(o for o in f.observation_ids if o != failed_id)
        )
        for f in result.findings
    ]
    health = project(
        cur,
        stripped,
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
    )
    (play,) = non_acquire(
        candidates(stripped, health, cur, run_id=CUR, interval=INTERVAL)
    )
    assert play.play_code == "job_reliability_investigation"
    assert {"exposure", "criticality"} <= set(play.missing_evidence)
    assert play.exposure["failed_runs"] is None


def test_workspace_grain_finding_gets_no_play() -> None:
    cur = job_triplet(500, 40, 8.0, entity_kind="workspace", entity_id="123")
    plays, result = plays_for(cur, [])
    assert result.findings and non_acquire(plays) == []


def test_acquisition_play_per_unknown_family() -> None:
    plays, _ = plays_for(job_triplet(100, 8, 8.0), [])
    acquire = [p for p in plays if p.play_code == "acquire_family_evidence"]
    families = {
        "consumption_trajectory",
        "efficiency",
        "governance",
        "adoption_breadth",
        "concentration",
    }
    assert {p.play_id for p in acquire} == {
        play_id("acquire_family_evidence", f) for f in families
    }
    for p in acquire:
        assert p.finding_ids == () and p.interaction_type == "acquisition"
        assert (p.owner_role, p.next_step_kind) == ("operator", "acquire")
        assert (p.target_entity_kind, p.target_entity_id) == ("workspace", "123")
    assert plays[-len(acquire) :] == tuple(acquire)


def test_internal_observation_makes_play_internal_only() -> None:
    cur, base = job_triplet(100, 8, 8.0), job_triplet(100, 1, 1.0, maker=prior)
    cur[1] = replace(
        cur[1], source_kind="internal_mirror", audience_class="internal_only"
    )
    (play,) = non_acquire(plays_for(cur, base)[0])
    assert play.audience_class == "internal_only"


def test_aggregate_evidence_is_moderate() -> None:
    cur = [
        replace(o, dedupe_key="job_aggregate_slice|123|42|a|b|v1")
        for o in job_triplet(100, 8, 8.0)
    ]
    (play,) = non_acquire(plays_for(cur, [])[0])
    assert play.evidence_strength == "moderate"


def _rule(rule_id: str, eid: str, severity: str) -> dict[str, Any]:
    return {"rule_id": rule_id, "entity_id": eid, "severity": severity}


def test_rule_play_mapped_verify_command_and_owner() -> None:
    entry = _rule("warehouse_queueing", "wh-1", "high")
    plays, _ = plays_for(
        [present("warehouse_queueing::wh-1")], [], manifest=manifest(entry)
    )
    (play,) = non_acquire(plays)
    assert play.play_code == "rule_finding_review"
    assert (play.interaction_type, play.owner_role) == (
        "working_session",
        "warehouse_owner",
    )
    assert play.next_commands == (
        "starboard-helper verify run vt-warehouse-queue --ws 123 --warehouse-ids wh-1 "
        "--start 2026-09-23 --end 2026-10-07 --limit 1000 "
        "--warehouse-id <warehouse_id> --suffix wh-1 --out analysis/verify",
        "starboard-helper warehouse fetch --warehouse-id wh-1",
    )
    assert play.follow_up_check["template"] == "vt-warehouse-queue"
    assert dict(play.follow_up_check["params"]) == {
        "ws": "123",
        "limit": QUERY_LIMIT,
        "warehouse_ids": "wh-1",
    }
    assert "review severity high" in play.reason


def test_unmapped_rule_lists_missing_verify_template() -> None:
    entry = _rule("job_wait_tasks", "77", "medium")
    plays, _ = plays_for([present("job_wait_tasks::77")], [], manifest=manifest(entry))
    (play,) = non_acquire(plays)
    assert play.interaction_type == "monitor" and play.follow_up_check is None
    assert "verify_template" in play.missing_evidence
    assert play.next_commands == ("starboard-helper job fetch --job-id 77",)


_HEALTH = PlayContext(task="health_check")
_INTERNAL = PlayContext(task="troubleshooting", target=RunTarget(internal=True))


def test_health_run_plays_list_no_single_entity_fetch() -> None:
    cur, base = job_triplet(100, 8, 8.0), job_triplet(100, 1, 1.0, maker=prior)
    plays, _ = plays_for(
        cur, base, latest_failed_runs={"42": "987654"}, context=_HEALTH
    )
    (play,) = non_acquire(plays)
    assert play.next_commands == (
        "starboard-helper verify run vt-job-run-states --ws 123 --job-ids 42 "
        "--start 2026-09-23 --end 2026-10-07 --limit 20000 "
        "--warehouse-id <warehouse_id> --suffix 42 --out analysis/verify",
    )
    assert "job_run_output" not in play.missing_evidence


@pytest.mark.parametrize(
    ("rule_id", "eid", "expected"),
    [
        (
            "warehouse_queueing",
            "wh-1",
            "starboard-helper verify run vt-warehouse-queue --ws 123 "
            "--warehouse-ids wh-1 --start 2026-09-23 --end 2026-10-07 --limit 1000 "
            "--warehouse-id <warehouse_id> --suffix wh-1 --out analysis/verify",
        ),
        # No verify template and no fetch on a health run: the job-run timeline,
        # never a review re-run (run 5).
        (
            "job_wait_tasks",
            "77",
            "starboard-helper verify run vt-job-runs --ws 123 --job-ids 77 "
            "--start 2026-09-23 --end 2026-10-07 --limit 1000 "
            "--warehouse-id <warehouse_id> --suffix 77 --out analysis/verify",
        ),
    ],
)
def test_health_run_rule_plays_drop_the_entity_fetch(
    rule_id: str, eid: str, expected: str
) -> None:
    entry = _rule(rule_id, eid, "high")
    plays, _ = plays_for(
        [present(f"{rule_id}::{eid}")], [], manifest=manifest(entry), context=_HEALTH
    )
    (play,) = non_acquire(plays)
    assert play.next_commands == (expected,)


def test_internal_run_plays_use_the_mirror_verify_form() -> None:
    cur, base = job_triplet(100, 8, 8.0), job_triplet(100, 1, 1.0, maker=prior)
    plays, _ = plays_for(
        cur, base, latest_failed_runs={"42": "987654"}, context=_INTERNAL
    )
    (play,) = non_acquire(plays)
    assert play.next_commands == (
        "starboard-helper verify run vt-job-run-states --internal-workspace-id 123 "
        "--job-ids 42 --start 2026-09-23 --end 2026-10-07 --limit 20000 "
        "--suffix 42 --out analysis/verify",
    )
    assert play.placeholders == ()
    assert not any(
        " fetch " in c or " --ws " in c or "<" in c or "--warehouse-id" in c
        for p in plays
        for c in p.next_commands
    )


def test_internal_run_rule_and_acquire_plays_use_internal_forms() -> None:
    entry = _rule("job_wait_tasks", "77", "medium")
    plays, _ = plays_for(
        [present("job_wait_tasks::77")], [], manifest=manifest(entry), context=_INTERNAL
    )
    (play,) = non_acquire(plays)
    # The mirror verify form of the job-run timeline, never a review re-run.
    assert play.next_commands == (
        "starboard-helper verify run vt-job-runs --internal-workspace-id 123 "
        "--job-ids 77 --start 2026-09-23 --end 2026-10-07 --limit 1000 "
        "--suffix 77 --out analysis/verify",
    )


def test_targeted_requests_give_acquisition_plays_internal_forms() -> None:
    cur = job_triplet(100, 8, 8.0)
    result = run(cur, [])
    target = RunTarget(internal=True)
    health = targeted_requests(
        project(
            cur,
            result.findings,
            (),
            run_id=CUR,
            account_key="acme",
            workspace_id="123",
            interval=INTERVAL,
        ),
        target,
    )
    plays = candidates(
        result.findings,
        health,
        cur,
        run_id=CUR,
        interval=INTERVAL,
        context=PlayContext(task="troubleshooting", target=target),
    )
    acquire = [p for p in plays if p.play_code == "acquire_family_evidence"]
    assert acquire
    for p in acquire:
        (command,) = p.next_commands
        assert command.split()[:4] in (
            ["starboard", "--discover", "--internal-workspace-id", "123"],
            ["starboard", "review", "--from-discovery", "discovery"],
        )
        assert "--from-discovery" not in command or "--internal-workspace-id" not in command
        assert p.placeholders == ()
    # Idempotent: a targeted form is the same when targeted again.
    assert targeted_requests(health, target) == health


def test_public_run_of_another_task_keeps_entity_fetches() -> None:
    entry = _rule("job_wait_tasks", "77", "medium")
    plays, _ = plays_for(
        [present("job_wait_tasks::77")],
        [],
        manifest=manifest(entry),
        context=PlayContext(task="troubleshooting"),
    )
    (play,) = non_acquire(plays)
    assert play.next_commands == ("starboard-helper job fetch --job-id 77",)


def test_dbu_exposure_labelled_list_price_estimate() -> None:
    entry = _rule("warehouse_queueing", "wh-1", "high")
    dbu = obs(
        family="efficiency",
        entity_kind="finding",
        entity_id="warehouse_queueing::wh-1",
        metric="evidence_dbu_estimate",
        unit="DBU",
        value=1234.0,
        method_version="findings_manifest_v2",
    )
    plays, _ = plays_for(
        [present("warehouse_queueing::wh-1"), dbu], [], manifest=manifest(entry)
    )
    (play,) = non_acquire(plays)
    # A non-job rule: the DBU is exposure, not failed-run DBU.
    assert dict(play.exposure) == {
        "failed_runs": None,
        "failed_run_dbus": None,
        "exposure_dbus": 1234.0,
        "exposure_dbus_per_day": None,
    }
    assert "1,234 DBU (list-price estimate)" in play.reason and "$" not in play.reason


def test_job_failure_rule_without_failed_runs_has_no_failed_run_dbus() -> None:
    entry = _rule("job_high_failure_rate", "77", "high")
    dbu = obs(
        family="reliability",
        entity_kind="finding",
        entity_id="job_high_failure_rate::77",
        metric="evidence_dbu_estimate",
        unit="DBU",
        value=50.0,
        method_version="findings_manifest_v2",
    )
    plays, _ = plays_for(
        [present("job_high_failure_rate::77"), dbu], [], manifest=manifest(entry)
    )
    (play,) = non_acquire(plays)
    # No failed-run count cited: failed_run_dbus stays None with failed_runs.
    assert play.exposure["failed_runs"] is None
    assert play.exposure["failed_run_dbus"] is None
    assert play.exposure["exposure_dbus"] == 50.0


def test_ordering_ranks_non_job_exposure_dbus() -> None:
    entries = [
        _rule("warehouse_queueing", "wh-small", "high"),
        _rule("warehouse_queueing", "wh-big", "high"),
    ]
    cur = [present("warehouse_queueing::wh-small"), present("warehouse_queueing::wh-big")]
    for eid, value in (("wh-small", 10.0), ("wh-big", 900.0)):
        cur.append(
            obs(
                family="efficiency",
                entity_kind="finding",
                entity_id=f"warehouse_queueing::{eid}",
                metric="evidence_dbu_estimate",
                unit="DBU",
                value=value,
                method_version="findings_manifest_v2",
            )
        )
    plays, _ = plays_for(cur, [], manifest=manifest(*entries))
    assert [p.target_entity_id for p in non_acquire(plays)] == ["wh-big", "wh-small"]


def test_ordering_severity_then_od1_low_last_then_exposure() -> None:
    entries = [
        _rule("warehouse_queueing", "wh-1", "low"),
        _rule("warehouse_queueing", "wh-2", "medium"),
        _rule("warehouse_auto_stop_disabled", "wh-3", "critical"),
    ]
    cur = [
        present("warehouse_queueing::wh-1"),
        present("warehouse_queueing::wh-2"),
        present("warehouse_auto_stop_disabled::wh-3"),
    ]
    cur += job_triplet(100, 8, 8.0)  # watch, failed_runs 8
    plays, result = plays_for(cur, [], manifest=manifest(*entries))
    order = [p.target_entity_id for p in non_acquire(plays)]
    assert order == ["wh-3", "42", "wh-2", "wh-1"]
    assert result.review_severities  # low origin recorded


def test_mapped_templates_exist_with_supported_placeholders() -> None:
    text = _VERIFY_SQL.read_text(encoding="utf-8")
    templates = {t for t, _ in RULE_VERIFY_TEMPLATES.values()} | {
        "vt-job-runs",
        "vt-job-run-states",
    }
    for template in sorted(templates):
        match = re.search(
            rf"^### {re.escape(template)}:.*?```sql\n(.*?)```", text, re.S | re.M
        )
        assert match, f"{template} missing from verify-sql.md"
        placeholders = set(re.findall(r"\{([a-z_]+)\}", match.group(1)))
        assert placeholders <= _SUPPORTED_PLACEHOLDERS, (template, placeholders)
