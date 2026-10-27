"""``run check`` gates its items by the run's workflow profile (phase-4 spec §B2–§B4).

The profile is the descriptor's ``intent`` (``profile_source: "descriptor"``); only a
local run dir with no ``analysis/run-authorization.json`` falls back to
``action_plan`` (``"default"``). Items outside the profile are not run and are
listed in ``skipped_by_profile``. The positive paths of the record-backed items
(``health_present``, ``plays_present``, ``health_report``, ``case_linked``) are
driven end to end by the phase-4 exit tests.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_skills.helpers import contract
from starboard_skills.helpers.contract import ArgError
from starboard_skills.helpers.run import cmd_check

from .conftest import commit_manifest, make_drive_run
from .test_run_check import _make_run

DESCRIPTOR = "analysis/run-authorization.json"
DEFAULT_WARNING = "no run authorization: using the action_plan checklist"
TODAY = frozenset({*(str(n) for n in range(1, 17)), "health_read"})
#: Profile items that are only checked with --internal (skipped_not_internal otherwise).
INTERNAL_ONLY = frozenset({"12", "16"})
NEW = frozenset(
    {
        "health_present",
        "plays_present",
        "health_report",
        "case_linked",
        "focused_report",
        "review_json",
    }
)


def _ids(entries: Any) -> set[str]:
    return {
        str(e["item"] if isinstance(e, dict) else e).split(":", 1)[0]
        for e in entries or ()
    }


def _descriptor(rd: Path, intent: str) -> None:
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import AccountRef, RunAuthorization

    auth = RunAuthorization(
        engagement_id=f"acme/{intent}/ws-123",
        run_id="20261001_12345678-1234-4234-8234-123456789abc",
        intent=intent,
        task="ws-123",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={"workspace_ids": ["123"]},
        authorized_scope={"account_key": "acme", "workspace_ids": ["123"]},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=SourceMode.CUSTOMER_WORKSPACE,
        storage_policy=StoragePolicy.LOCAL,
        audience="operator",
        methodology_version="m1",
        drive=None,
    )
    (rd / "analysis").mkdir(parents=True, exist_ok=True)
    (rd / DESCRIPTOR).write_text(json.dumps(auth.to_dict()))


def _check(rd: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    args = SimpleNamespace(run_dir=str(rd), internal=False, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    return int(exc.value.code or 0), json.loads(capsys.readouterr().out)["data"]


def _run(tmp_path: Path, intent: str | None) -> Path:
    rd = _make_run(tmp_path)
    if intent is not None:
        _descriptor(rd, intent)
    return rd


# --------------------------------------------------------------------------- #
# Profile source
# --------------------------------------------------------------------------- #
def test_tasks_are_the_workflow_profiles() -> None:
    from starboard_core.engagement.profiles import WORKFLOW_PROFILES
    from starboard_skills.helpers.engagement._envelope import TASKS

    assert set(TASKS) == set(WORKFLOW_PROFILES)


def test_no_descriptor_uses_the_action_plan_default(tmp_path, capsys) -> None:
    code, data = _check(_run(tmp_path, None), capsys)
    assert code == 0
    assert data["profile"] == "action_plan"
    assert data["profile_source"] == "default"
    assert DEFAULT_WARNING in data["warnings"]
    assert _ids(data["passed"]) == TODAY - INTERNAL_ONLY
    assert _ids(data["skipped_not_internal"]) == INTERNAL_ONLY
    assert set(data["skipped_by_profile"]) == NEW


def test_an_action_plan_descriptor_runs_todays_items(tmp_path, capsys) -> None:
    code, data = _check(_run(tmp_path, "action_plan"), capsys)
    assert code == 0
    assert (data["profile"], data["profile_source"]) == ("action_plan", "descriptor")
    assert DEFAULT_WARNING not in data["warnings"]
    assert _ids(data["passed"]) == TODAY - INTERNAL_ONLY
    assert _ids(data["skipped_not_internal"]) == INTERNAL_ONLY


def test_a_discovery_run_skips_everything_else(tmp_path, capsys) -> None:
    code, data = _check(_run(tmp_path, "discovery"), capsys)
    assert code == 0, data["failed"]
    assert _ids(data["passed"]) == {"1", "2", "3", "4"}
    assert _ids(data["skipped_not_internal"]) == INTERNAL_ONLY
    skipped = data["skipped_by_profile"]
    assert "5:analysis/verify/ .sql/.json pairs (min count)" in skipped
    assert "14:backlog carries or cuts every fired catalog trigger" in skipped
    assert _ids(skipped) == (TODAY | NEW) - {"1", "2", "3", "4", "12", "16"}
    assert not set(skipped) & set(data["passed"])
    assert data["summary"]["total"] == 4


def test_a_skipped_item_is_never_run(tmp_path, capsys) -> None:
    rd = _run(tmp_path, "discovery")
    (rd / "analysis" / "backlog.json").write_text("{not json")
    (rd / "analysis" / "action-plan.md").unlink()
    code, data = _check(rd, capsys)
    assert code == 0, data["failed"]
    assert data["failed"] == []


@pytest.mark.parametrize(
    ("how", "reason"),
    [
        ("bad_json", "run authorization unreadable:"),
        ("wrong_version", "run authorization unreadable:"),
        ("not_object", "run authorization unreadable:"),
        ("unknown_intent", "run authorization intent bogus is not a workflow profile"),
    ],
)
def test_a_bad_descriptor_is_an_arg_error(tmp_path, how: str, reason: str) -> None:
    rd = _run(tmp_path, "health_check")
    path = rd / DESCRIPTOR
    doc = json.loads(path.read_text())
    if how == "bad_json":
        path.write_text("{not json")
    elif how == "not_object":
        path.write_text("[]")
    elif how == "wrong_version":
        path.write_text(json.dumps({**doc, "schema_version": 999}))
    else:
        path.write_text(json.dumps({**doc, "intent": "bogus"}))
    with pytest.raises(ArgError) as exc:
        cmd_check(SimpleNamespace(run_dir=str(rd), internal=False, format="json"))
    assert reason in str(exc.value)
    assert exc.value.exit_code == 4


# --------------------------------------------------------------------------- #
# Profile items (failing paths)
# --------------------------------------------------------------------------- #
def test_a_health_check_run_needs_health_plays_and_a_report(tmp_path, capsys) -> None:
    code, data = _check(_run(tmp_path, "health_check"), capsys)
    assert code == 1
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    assert set(failed) == {"health_present", "plays_present", "health_report"}
    assert "analysis/health.json" in failed["health_present"]
    assert "analysis/plays.json" in failed["plays_present"]
    # The backlog/notebook/verify items are not run.
    assert {"5", "6", "9", "10", "11", "14"} <= _ids(data["skipped_by_profile"])


def test_unparseable_health_and_empty_plays_fail(tmp_path, capsys) -> None:
    rd = _run(tmp_path, "health_check")
    (rd / "analysis" / "health.json").write_text(json.dumps({"verdict": "health_read"}))
    (rd / "analysis" / "plays.json").write_text("[]")
    (rd / "deliverables" / "health-read.md").write_text("# Health read\n")
    _code, data = _check(rd, capsys)
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    assert "not a valid HealthRead" in failed["health_present"]
    assert "no play" in failed["plays_present"]
    assert "not a valid HealthRead" in failed["health_report"]


def test_a_troubleshooting_run_needs_a_linked_case_and_its_report(
    tmp_path, capsys
) -> None:
    code, data = _check(_run(tmp_path, "troubleshooting"), capsys)
    assert code == 1
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    assert set(failed) == {"case_linked", "focused_report"}
    assert "analysis/cases.json" in failed["case_linked"]
    assert "deliverables/case-report.md" in failed["focused_report"]
    assert _ids(data["passed"]) == {"1"}
    assert _ids(data["skipped_not_internal"]) == INTERNAL_ONLY


def test_a_case_report_needs_an_unknowns_heading(tmp_path, capsys) -> None:
    rd = _run(tmp_path, "troubleshooting")
    report = rd / "deliverables" / "case-report.md"
    report.write_text("# Case report\n\n## Cause\n\nunassessed\n")
    _code, data = _check(rd, capsys)
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    assert "Unknowns" in failed["focused_report"]

    report.write_text("# Case report\n\n## Unknowns\n\n- none\n")
    _code, data = _check(rd, capsys)
    assert "focused_report" in _ids(data["passed"])


def test_an_empty_case_report_fails(tmp_path, capsys) -> None:
    rd = _run(tmp_path, "troubleshooting")
    (rd / "deliverables" / "case-report.md").write_text("  \n")
    _code, data = _check(rd, capsys)
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    assert "empty" in failed["focused_report"]


def test_a_review_run_needs_review_json_findings(tmp_path, capsys) -> None:
    rd = _run(tmp_path, "review")
    code, data = _check(rd, capsys)
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    assert code == 1 and set(failed) == {"review_json"}
    assert "analysis/review.json" in failed["review_json"]

    (rd / "analysis" / "review.json").write_text(json.dumps({"data": {}}))
    _code, data = _check(rd, capsys)
    assert (
        "data.findings"
        in {f["item"]: f["reason"] for f in data["failed"]}["review_json"]
    )

    (rd / "analysis" / "review.json").write_text(json.dumps({"data": {"findings": []}}))
    code, data = _check(rd, capsys)
    assert code == 0, data["failed"]
    assert _ids(data["passed"]) == {"1", "13", "15", "review_json"}
    assert _ids(data["skipped_not_internal"]) == INTERNAL_ONLY


# --------------------------------------------------------------------------- #
# Drive: the descriptor picks the profile, R3 checks the manifest agrees
# --------------------------------------------------------------------------- #
def _drive_check(
    run: Any, capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, Any]]:
    args = SimpleNamespace(
        run_dir=None,
        run_folder=run.folder_id,
        internal=False,
        out=None,
        stdout=True,
        format="json",
    )
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    return int(exc.value.code or 0), json.loads(capsys.readouterr().out)["data"]


def _r3(data: dict[str, Any]) -> str | None:
    """R3's failure reason, or ``None`` when R3 passed."""
    for entry in data["failed"]:
        if entry["item"].startswith("R3"):
            return str(entry["reason"])
    assert any(p.startswith("R3") for p in data["passed"]), data["passed"]
    return None


@pytest.mark.parametrize("manifest_profile", ["discovery", None])
def test_r3_fails_when_the_manifest_disagrees(
    monkeypatch, capsys, manifest_profile: str | None
) -> None:
    run = make_drive_run(intent="review")
    monkeypatch.setattr(contract, "_load_storage", lambda: run.store)
    commit_manifest(run)
    _code, before = _drive_check(run, capsys)
    assert (before["profile"], before["profile_source"]) == ("review", "descriptor")
    assert before["remote"]["workflow_profile"] == "review"
    assert _r3(before) is None

    commit_manifest(run, workflow_profile=manifest_profile)
    code, after = _drive_check(run, capsys)
    reason = _r3(after)
    assert reason is not None and "profile" in reason
    assert "start a new run" in reason
    assert code == 1
    assert after["profile"] == "review"
    assert after["skipped_by_profile"] == before["skipped_by_profile"]
    assert not [w for w in after["warnings"] if "no profile-specific gates" in w]


def test_r3_still_fails_on_a_failed_stage(monkeypatch, capsys) -> None:
    run = make_drive_run(intent="review")
    monkeypatch.setattr(contract, "_load_storage", lambda: run.store)
    commit_manifest(
        run,
        states={
            "capture": "complete",
            "analysis": "failed",
            "check": "pending",
            "publication": "pending",
        },
    )
    _code, data = _drive_check(run, capsys)
    reason = _r3(data)
    assert reason is not None and "failed stage" in reason


def test_drive_health_report_needs_a_registered_revision(monkeypatch, capsys) -> None:
    run = make_drive_run(intent="health_check")
    monkeypatch.setattr(contract, "_load_storage", lambda: run.store)
    commit_manifest(run)
    _code, data = _drive_check(run, capsys)
    assert data["profile"] == "health_check"
    failed = {f["item"]: f["reason"] for f in data["failed"]}
    assert "health_report" in failed


def test_the_fixture_manifest_records_the_descriptor_profile() -> None:
    from starboard_core.engagement.commit import latest_manifest

    run = make_drive_run(intent="troubleshooting")
    commit_manifest(run)
    latest = latest_manifest(run.store, run.folder_id)
    assert latest is not None
    assert latest[0].workflow_profile == "troubleshooting"
    assert dataclasses.replace(latest[0]).workflow_profile == "troubleshooting"
