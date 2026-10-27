# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 4 (group B): runnable play commands, collapsed exposure, governance gaps."""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement.families import rule_coverage
from starboard_core.engagement.health import (
    DISCOVERY_COMMAND,
    REVIEW_COMMAND,
    WAREHOUSE_PLACEHOLDER,
    RunTarget,
    discovery_command,
    finding_exposure,
    placeholders,
    project,
    review_command,
    targeted_requests,
)
from starboard_core.engagement.plays import (
    QUERY_LIMIT,
    VERIFY_LIMIT,
    PlayContext,
    verify_limit,
)
from starboard_core.engagement.records import Play

from .test_concerns import (
    CUR,
    EV,
    INTERVAL,
    job_triplet,
    manifest,
    obs,
    present,
    prior,
    run,
)
from .test_families import manifest as review_manifest
from .test_plays import non_acquire, plays_for

pytestmark = pytest.mark.unit

_DRIVE = RunTarget(run_folder="F1", warehouse_id="wh9")
_LOCAL = RunTarget(run_dir="/r/acme/health_check/ws/run 1", profile="cust")
_LOCAL_INTERNAL = RunTarget(
    internal=True,
    run_dir="/r/acme/run1",
    mirror_templates="~/.claude/skills/o/mirror-verify.md",
)


def _job_play(target: RunTarget, task: str | None = None) -> Play:
    cur, base = job_triplet(100, 8, 8.0), job_triplet(100, 1, 1.0, maker=prior)
    plays, _ = plays_for(cur, base, context=PlayContext(task=task, target=target))
    (play,) = non_acquire(plays)
    return play


# ---- B1: verify lines carry the run target, warehouse and a capped limit -------


def test_drive_verify_line_carries_run_folder_and_known_warehouse() -> None:
    play = _job_play(_DRIVE, "health_check")
    assert play.next_commands == (
        "starboard-helper verify run vt-job-run-states --ws 123 --job-ids 42 "
        "--start 2026-09-23 --end 2026-10-07 --limit 20000 --warehouse-id wh9 "
        "--suffix 42 --run-folder F1 --out analysis/verify",
    )
    assert play.placeholders == ()


def test_local_public_verify_line_uses_run_dir_paths_and_profile() -> None:
    play = _job_play(_LOCAL, "health_check")
    (command,) = play.next_commands
    assert command.endswith(
        "--warehouse-id <warehouse_id> --profile cust --suffix 42 "
        "--out '/r/acme/health_check/ws/run 1/analysis/verify'"
    )
    assert "--run-folder" not in command and "--templates" not in command
    assert play.placeholders == ("warehouse_id",)


def test_local_internal_verify_line_has_mirror_templates_and_no_warehouse() -> None:
    play = _job_play(_LOCAL_INTERNAL, "health_check")
    (command,) = play.next_commands
    assert command == (
        "starboard-helper verify run vt-job-run-states "
        "--templates ~/.claude/skills/o/mirror-verify.md --internal-workspace-id 123 "
        "--job-ids 42 --start 2026-09-23 --end 2026-10-07 --limit 20000 --suffix 42 "
        "--out /r/acme/run1/analysis/verify"
    )
    assert "<" not in command and play.placeholders == ()


def test_internal_without_mirror_templates_omits_the_flag() -> None:
    (command,) = _job_play(
        RunTarget(internal=True, run_folder="F1"), "health_check"
    ).next_commands
    assert "--templates" not in command and "--run-folder F1" in command


@pytest.mark.parametrize(
    ("template", "limit"),
    [
        ("vt-job-run-states", VERIFY_LIMIT),
        ("vt-job-runs", QUERY_LIMIT),
        ("vt-warehouse-dbu", QUERY_LIMIT),
    ],
)
def test_verify_limit_within_the_verb_cap(template: str, limit: int) -> None:
    assert verify_limit(template) == limit
    assert VERIFY_LIMIT == 20000 and QUERY_LIMIT == 1000


def test_rule_verify_and_follow_up_limits_stay_within_cap() -> None:
    entry = {"rule_id": "job_high_failure_rate", "entity_id": "77", "severity": "high"}
    plays, _ = plays_for(
        [present("job_high_failure_rate::77", family="reliability")],
        [],
        manifest=manifest(entry),
        context=PlayContext(task="health_check", target=_DRIVE),
    )
    (play,) = non_acquire(plays)
    (command,) = play.next_commands
    assert command.startswith("starboard-helper verify run vt-job-runs ")
    assert f"--limit {QUERY_LIMIT} " in command
    assert play.follow_up_check["params"]["limit"] == QUERY_LIMIT


def test_placeholders_lists_only_the_warehouse() -> None:
    assert placeholders([f"x --warehouse-id {WAREHOUSE_PLACEHOLDER}"]) == (
        "warehouse_id",
    )
    assert placeholders(["x --warehouse-id wh1"]) == ()


# ---- B1: review / discovery commands in the run's form ------------------------


def test_review_command_forms() -> None:
    assert review_command(None) == REVIEW_COMMAND
    assert review_command(RunTarget(internal=True)) == REVIEW_COMMAND
    drive = review_command(_DRIVE)
    assert drive == (
        "starboard review --from-discovery discovery --domains "
        "jobs,sql,warehouse,uc,portfolio-readiness --run-folder F1 --json "
        "--out analysis/review.json --manifest-out findings-manifest.json"
    )
    local_internal = review_command(_LOCAL_INTERNAL)
    assert local_internal == (
        "starboard review --run-dir /r/acme/run1 --from-discovery /r/acme/run1/discovery "
        "--domains jobs,sql,warehouse,uc,portfolio-readiness --json "
        "--out /r/acme/run1/analysis/review.json "
        "--manifest-out /r/acme/run1/findings-manifest.json"
    )
    local = review_command(_LOCAL)
    assert "--run-dir" not in local
    assert "--from-discovery '/r/acme/health_check/ws/run 1/discovery'" in local
    for command in (drive, local_internal, local):
        assert (
            "--internal-workspace-id" not in command and "<overlay-dir>" not in command
        )


def test_discovery_command_forms_keep_the_window() -> None:
    thirty = ("2026-09-08", "2026-10-07")
    assert discovery_command("123", thirty) == DISCOVERY_COMMAND
    assert discovery_command("123", thirty, _DRIVE) == (
        "starboard --discover --warehouse-id wh9 --lookback-days 30 --data-only --json "
        "--out-dir discovery --run-folder F1"
    )
    assert discovery_command("123", thirty, _LOCAL_INTERNAL) == (
        "starboard --discover --internal-workspace-id 123 --lookback-days 30 --no-cache "
        "--data-only --json --out-dir /r/acme/run1/discovery --authorization /r/acme/run1"
    )
    local = discovery_command("123", ("2026-09-23", "2026-10-07"), _LOCAL)
    # 15 days is no --lookback-days choice: the default window.
    assert "--lookback-days" not in local
    assert local.startswith(
        "starboard --discover --warehouse-id <warehouse_id> --profile cust "
    )


# ---- B2: a collapsed workspace-grain rule sums its exposure -------------------


def _portfolio(
    products: dict[str, tuple[float, str]],
) -> tuple[list[Any], dict[str, Any]]:
    cur: list[Any] = []
    entries = []
    for product, (dbus, severity) in products.items():
        eid = f"portfolio_untracked_production_consumption::ws:{product}"
        cur.append(present(eid, family="governance"))
        cur.append(
            obs(
                family="governance",
                entity_kind="finding",
                entity_id=eid,
                metric="evidence_dbu_estimate",
                unit="DBU",
                value=dbus,
                method_version="findings_manifest_v2",
            )
        )
        entries.append(
            {
                "composite_key": eid,
                "rule_id": "portfolio_untracked_production_consumption",
                "entity_id": f"ws:{product}",
                "severity": severity,
            }
        )
    return cur, manifest(*entries)


def test_collapsed_portfolio_finding_cites_every_product_and_sums_dbu() -> None:
    cur, doc = _portfolio(
        {"JOBS": (100.0, "medium"), "SQL": (250.0, "high"), "DLT": (10.0, "low")}
    )
    result = run(cur, [], manifest=doc)
    (finding,) = result.findings
    assert finding.severity == "serious"  # the highest review severity (high)
    assert len(finding.observation_ids) == 6
    by_id = {o.observation_id: o for o in cur}
    assert finding_exposure(finding, by_id) == (None, 360.0)
    plays, _ = plays_for(cur, [], manifest=doc)
    (play,) = non_acquire(plays)
    assert play.finding_ids == (finding.finding_id,)
    assert play.exposure["exposure_dbus"] == 360.0
    assert "~360 DBU (list-price estimate)" in play.reason


# ---- B3: governance missing / uncertainty from the real state ----------------


def _gov(m: dict[str, Any], **kw: Any) -> Any:
    from .test_health import family, health

    cur = rule_coverage(
        m,
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
        evidence_ids=(EV,),
        **kw,
    )
    return family(health(list(cur)), "governance")


def test_partial_governance_names_failed_evidence_query() -> None:
    gov = _gov(
        review_manifest(unavailable_queries=["PO-01"]),
        reviewed_domains=["uc", "portfolio-readiness"],
    )
    assert (gov.assessment, gov.coverage) == ("assessed", "partial")
    assert "missing_source:PO-01" in gov.uncertainty
    assert gov.acquisition_request["missing"] == ("PO-01",)
    assert gov.acquisition_request["command"] == DISCOVERY_COMMAND


def test_partial_governance_from_degraded_manifest_names_failed_discovery_queries() -> (
    None
):
    gov = _gov(
        review_manifest(degraded=True, unavailable_queries=["DQ-01", "DCL-01"]),
        reviewed_domains=["uc", "portfolio-readiness"],
    )
    assert gov.coverage == "partial"
    assert {
        "manifest_degraded",
        "unavailable_query:DCL-01",
        "unavailable_query:DQ-01",
    } <= set(gov.uncertainty)
    assert gov.acquisition_request["missing"] == (
        "DCL-01",
        "DQ-01",
        "manifest_degraded",
    )
    assert "findings_manifest" not in gov.acquisition_request["missing"]
    assert gov.acquisition_request["command"] == DISCOVERY_COMMAND


def test_partial_governance_from_unreviewed_domain_asks_for_review() -> None:
    gov = _gov(review_manifest(), reviewed_domains=["portfolio-readiness"])
    assert gov.coverage == "partial"
    assert "not_reviewed:uc" in gov.uncertainty
    assert gov.acquisition_request["missing"] == ("not_reviewed:uc",)
    assert gov.acquisition_request["command"] == REVIEW_COMMAND


def test_targeted_requests_rewrite_acquisition_commands() -> None:
    from .test_health import health

    cur = rule_coverage(
        review_manifest(unavailable_queries=["PO-01"]),
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
        evidence_ids=(EV,),
        reviewed_domains=["portfolio-readiness"],
    )
    read = targeted_requests(health(list(cur)), _DRIVE)
    for fam in read.families:
        request = fam.acquisition_request
        if request is None:
            continue
        assert "--run-folder F1" in request["command"]
        assert request["placeholders"] == placeholders([request["command"]])
    assert targeted_requests(read, _DRIVE) == read


# ---- B4: failed_runs and failed_run_dbus together -----------------------------


def test_job_failure_rule_with_failed_runs_sets_both() -> None:
    entry = {"rule_id": "job_high_failure_rate", "entity_id": "77", "severity": "high"}
    eid = "job_high_failure_rate::77"
    cur = [
        present(eid, family="reliability"),
        obs(
            family="reliability",
            entity_kind="finding",
            entity_id=eid,
            metric="evidence_dbu_estimate",
            unit="DBU",
            value=786.24,
            method_version="findings_manifest_v2",
        ),
    ]
    plays, _ = plays_for(cur, [], manifest=manifest(entry))
    (play,) = non_acquire(plays)
    # The review cites no failed-run count: the DBU is not failed-run DBU.
    assert (play.exposure["failed_runs"], play.exposure["failed_run_dbus"]) == (
        None,
        None,
    )
    assert play.exposure["exposure_dbus"] == 786.24


# ---- B8: a step change is a run-rate ------------------------------------------


def test_step_change_exposure_is_a_labelled_run_rate() -> None:
    eid = "spend_step_change::ws"
    entry = {
        "composite_key": eid,
        "rule_id": "spend_step_change",
        "entity_id": "ws",
        "severity": "high",
    }
    cur = [
        present(eid, family="consumption_trajectory"),
        obs(
            family="consumption_trajectory",
            entity_kind="finding",
            entity_id=eid,
            metric="evidence_dbu_estimate",
            unit="DBU",
            value=42.0,
            method_version="findings_manifest_v2",
        ),
    ]
    plays, _ = plays_for(cur, [], manifest=manifest(entry))
    (play,) = non_acquire(plays)
    assert dict(play.exposure) == {
        "failed_runs": None,
        "failed_run_dbus": None,
        "exposure_dbus": None,
        "exposure_dbus_per_day": 42.0,
    }
    assert "~42 DBU/day run-rate (list-price estimate)" in play.reason


def test_project_ignores_targets() -> None:
    # project() keeps the run-less commands; targeting is a separate, explicit step.
    cur = job_triplet(100, 8, 8.0)
    read = project(
        cur,
        run(cur, []).findings,
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
    )
    commands = {
        f.acquisition_request["command"] for f in read.families if f.acquisition_request
    }
    assert commands <= {DISCOVERY_COMMAND, REVIEW_COMMAND}
