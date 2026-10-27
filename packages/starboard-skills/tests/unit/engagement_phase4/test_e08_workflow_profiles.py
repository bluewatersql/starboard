"""E8 Workflow profiles (spec §H.8, B1–B4, D4-1…D4-3, D4-13).

* ``profile_for_task`` is the identity on ``TASKS`` (``None`` -> ``action_plan``).
* The route records the profile on the first manifest and later revisions
  carry it; ``run check`` always takes the profile from the descriptor
  (``profile_source: "descriptor"``), never from the manifest.
* A local run dir with no descriptor gets ``action_plan`` (``default``), a
  warning and today's golden item set; a corrupt or unknown-intent descriptor
  is exit 4 on ``run check`` and ``run recur``.
* ``health_report`` cannot pass on Drive without a registered report revision.
* R3 fails on a tampered or ``None`` manifest profile, which never changes the
  item set; the "no profile-specific gates" warning is gone.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest

from ..test_run_check import _make_run
from . import _fixtures
from ._support import (
    HEALTH_READ,
    MANIFEST,
    Ctx,
    Run,
    all_warnings,
    commit,
    current_run,
    failed_ids,
    health_body,
    helper,
    host_put,
    ids,
    manifest,
    new_run,
    read_json,
    readme,
    report,
    run_check,
    run_recur,
    write,
)

LOCAL = pytest.mark.parametrize("mode", ["public_local", "internal_local"])
DRIVE = pytest.mark.parametrize("mode", ["drive_backed", "hybrid_drive"])

GOLDEN = Path(__file__).parent.parent / "golden_helpers" / "run_check.json"
DESCRIPTOR = "analysis/run-authorization.json"
TODAY = frozenset({*(str(n) for n in range(1, 17)), "health_read"})
NEW_IDS = frozenset(
    {
        "health_present",
        "plays_present",
        "health_report",
        "case_linked",
        "focused_report",
        "review_json",
    }
)
PROFILE_TABLE = {
    "action_plan": TODAY,
    "discovery": frozenset({"1", "2", "3", "4", "12", "16"}),
    "review": frozenset({"1", "12", "13", "15", "16", "review_json"}),
    "health_check": frozenset(
        {
            "1",
            "2",
            "12",
            "13",
            "15",
            "16",
            "health_read",
            "health_present",
            "plays_present",
            "health_report",
        }
    ),
    "troubleshooting": frozenset({"1", "12", "16", "case_linked", "focused_report"}),
}
PROFILE_KEYS = ("profile", "profile_source", "skipped_by_profile")
DEFAULT_WARNING = "no run authorization: using the action_plan checklist"
NO_GATES = "no profile-specific gates"
TASK_SOURCES = {
    "public_local": "customer_workspace",
    "internal_local": "internal_only",
    "drive_backed": "customer_workspace",
    "hybrid_drive": "hybrid",
}


def _source(mode: str, task: str) -> str:
    del task
    return TASK_SOURCES[mode]


def _expect(fn: Any, *args: Any, error: type[Exception] = ValueError) -> None:
    """``fn(*args)`` raises ``error`` (an AssertionError when it does not)."""
    try:
        fn(*args)
    except error:
        return
    raise AssertionError(f"{getattr(fn, '__name__', fn)}{args!r} did not raise")


# --------------------------------------------------------------------------- #
# B1 kernel module
# --------------------------------------------------------------------------- #
def test_profile_for_task_is_the_identity_on_tasks() -> None:
    from starboard_core.engagement.profiles import (
        CHECK_IDS,
        PROFILE_CHECKS,
        WORKFLOW_PROFILES,
        profile_for_task,
        required_checks,
    )
    from starboard_skills.helpers.engagement._envelope import TASKS

    assert set(TASKS) == set(WORKFLOW_PROFILES)
    for task in TASKS:
        assert profile_for_task(task) == task
    assert profile_for_task(None) == "action_plan"
    _expect(profile_for_task, "bogus")
    _expect(required_checks, "bogus")

    assert len(CHECK_IDS) == len(set(CHECK_IDS)) == 23
    assert set(CHECK_IDS) == TODAY | NEW_IDS
    assert set(PROFILE_CHECKS) == set(WORKFLOW_PROFILES)
    for profile, items in PROFILE_TABLE.items():
        assert required_checks(profile) == items, profile
        assert frozenset(PROFILE_CHECKS[profile]) == items


def test_run_manifest_rejects_an_unknown_workflow_profile() -> None:
    from starboard_core.engagement.records import RunManifest

    fields = {f.name for f in dataclasses.fields(RunManifest)}
    assert "workflow_profile" in fields
    _expect(_manifest_with_profile, "bogus")
    for profile in PROFILE_TABLE:
        assert _manifest_with_profile(profile).workflow_profile == profile


def _manifest_with_profile(profile: str) -> Any:
    """A minimal valid revision-1 ``RunManifest`` with ``profile``."""
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import (
        MANIFEST_STATE_KEYS,
        RunManifest,
        StorageRef,
    )

    return RunManifest(
        engagement_id="001ABC/workspace/ws-123",
        run_id="20261001_12345678-1234-4234-8234-123456789abc",
        revision=1,
        previous_object_id=None,
        task="health_check",
        task_name="ws-123",
        source_mode=SourceMode.CUSTOMER_WORKSPACE,
        storage_policy=StoragePolicy.DRIVE_REQUIRED,
        descriptor_ref=StorageRef(
            path="run-authorization.json",
            object_id="obj-1",
            revision="rev-1",
            md5="0" * 32,
            size=2,
            mime_type="application/json",
        ),
        refs=(),
        states=dict.fromkeys(MANIFEST_STATE_KEYS, "pending"),
        committed_at="2026-10-01T00:00:00+00:00",
        workflow_profile=profile,
    )


# --------------------------------------------------------------------------- #
# D4-1 the route records the profile; run check reads the descriptor
# --------------------------------------------------------------------------- #
@DRIVE
@pytest.mark.parametrize(
    "task", ["health_check", "troubleshooting", "discovery", "action_plan", "review"]
)
def test_the_route_records_the_profile_and_commits_carry_it(
    ctx: Ctx, task: str
) -> None:
    run = new_run(
        ctx, task=task, task_name=f"t-{task}", source_mode=_source(ctx.mode, task)
    )
    assert run.rf
    first = manifest(ctx.store, run.rf)
    assert first.workflow_profile == task
    readme(ctx, run)
    commit(ctx, run)
    later = manifest(ctx.store, run.rf)
    assert later.revision > first.revision
    assert later.workflow_profile == task

    _code, data, raw = run_check(ctx, run)
    assert data.get("profile") == task, raw[:2000]
    assert data.get("profile_source") == "descriptor"
    assert data.get("remote", {}).get("workflow_profile") == task
    _items_partition(data, task)


@LOCAL
@pytest.mark.parametrize("task", ["health_check", "troubleshooting", "action_plan"])
def test_a_local_run_takes_its_profile_from_the_descriptor(ctx: Ctx, task: str) -> None:
    run = new_run(
        ctx, task=task, task_name=f"t-{task}", source_mode=_source(ctx.mode, task)
    )
    assert run.run_dir and (run.run_dir / DESCRIPTOR).is_file()
    _code, data, raw = run_check(ctx, run)
    assert data.get("profile") == task, raw[:2000]
    assert data.get("profile_source") == "descriptor"
    assert DEFAULT_WARNING not in all_warnings(data)
    _items_partition(data, task)


def _items_partition(data: dict[str, Any], profile: str) -> None:
    """Profile items are run (passed or failed) or, for 12/16 without ``--internal``,
    listed in ``skipped_not_internal``; the rest are only listed as skipped."""
    ran = ids(data.get("passed")) | failed_ids(data)
    ran = {i for i in ran if not i.startswith("R")}
    not_internal = ids(data.get("skipped_not_internal"))
    assert not_internal <= {"12", "16"} and not ran & not_internal
    skipped = ids(data.get("skipped_by_profile"))
    assert ran | not_internal == set(PROFILE_TABLE[profile]), sorted(ran)
    assert skipped == (TODAY | NEW_IDS) - PROFILE_TABLE[profile]
    assert not ran & skipped


# --------------------------------------------------------------------------- #
# D4-2 no descriptor -> action_plan; descriptor errors -> exit 4
# --------------------------------------------------------------------------- #
def _golden_stdout() -> dict[str, Any]:
    golden = json.loads(GOLDEN.read_text())
    doc: dict[str, Any] = json.loads(golden["stdout"])
    return doc


def _normalised(raw: str, tmp: Path) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(raw.replace(str(tmp), "<TMP>"))
    return doc


def _check_golden_run(capsys: Any, tmp: Path) -> tuple[int, dict[str, Any], str]:
    rd = _make_run(tmp)
    return helper(
        capsys,
        "run",
        "check",
        str(rd),
        "--out",
        str(rd / "analysis" / "run-check.json"),
    )


def test_a_run_dir_without_a_descriptor_uses_the_action_plan_default(
    public: None, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, env, raw = _check_golden_run(capsys, tmp_path)
    assert not (tmp_path / "run" / DESCRIPTOR).exists()
    data = env.get("data") or {}
    assert code == 0, raw[:2000]
    assert data.get("profile") == "action_plan"
    assert data.get("profile_source") == "default"
    assert DEFAULT_WARNING in all_warnings(data)
    golden = _golden_stdout()["data"]
    assert data["passed"] == golden["passed"]
    assert ids(data.get("skipped_by_profile")) == NEW_IDS


def _public_descriptor(rd: Path, intent: str) -> None:
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import AccountRef, RunAuthorization

    auth = RunAuthorization(
        engagement_id="001ABC/workspace/ws-123",
        run_id="20261001_12345678-1234-4234-8234-123456789abc",
        intent=intent,
        task="workspace",
        account=AccountRef(id="001ABC", display_name="Acme", verifier="operator"),
        requested_scope={"workspace_ids": ["123"]},
        authorized_scope={"account_key": "001ABC", "workspace_ids": ["123"]},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=SourceMode.CUSTOMER_WORKSPACE,
        storage_policy=StoragePolicy.LOCAL,
        audience="customer",
        methodology_version="m1",
        drive=None,
    )
    (rd / DESCRIPTOR).write_text(json.dumps(auth.to_dict()))


def test_an_action_plan_run_matches_today_plus_the_profile_keys(
    public: None, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    rd = _make_run(tmp_path)
    _public_descriptor(rd, "action_plan")
    code, _env, raw = helper(
        capsys,
        "run",
        "check",
        str(rd),
        "--out",
        str(rd / "analysis" / "run-check.json"),
    )
    assert code == 0, raw[:2000]
    doc = _normalised(raw, tmp_path)
    data = doc["data"]
    assert data.get("profile") == "action_plan"
    assert data.get("profile_source") == "descriptor"
    assert ids(data.get("skipped_by_profile")) == NEW_IDS
    for key in PROFILE_KEYS:
        data.pop(key, None)
    data["warnings"] = [
        w
        for w in data["warnings"]
        if not w.startswith("run dir name is not its run id")
    ]
    assert doc == _golden_stdout()


def _corrupt(run_dir: Path, how: str) -> str:
    path = run_dir / DESCRIPTOR
    assert path.is_file(), f"{DESCRIPTOR} was not written"
    if how == "bad_json":
        path.write_text("{not json")
        return "run authorization unreadable:"
    if how == "wrong_version":
        doc = json.loads(path.read_text())
        doc["schema_version"] = 999
        path.write_text(json.dumps(doc))
        return "run authorization unreadable:"
    doc = json.loads(path.read_text())
    doc["intent"] = "bogus"
    path.write_text(json.dumps(doc))
    return "run authorization intent bogus is not a workflow profile"


@LOCAL
@pytest.mark.parametrize("how", ["bad_json", "wrong_version", "unknown_intent"])
def test_a_bad_descriptor_is_exit_4_on_check_and_recur(ctx: Ctx, how: str) -> None:
    run = new_run(ctx, task="health_check")
    assert run.run_dir
    write(ctx, run, {MANIFEST: _fixtures.review_manifest()})  # recur would run
    reason = _corrupt(run.run_dir, how)

    code, data, raw = run_check(ctx, run)
    assert code == 4, raw[:2000]
    assert reason in raw
    assert data.get("profile") != "action_plan"

    code, _data, raw = run_recur(ctx, run, baseline=True)
    assert code == 4, raw[:2000]
    assert reason in raw


# --------------------------------------------------------------------------- #
# D4-13 health_report on Drive needs a registered report revision
# --------------------------------------------------------------------------- #
def _health_run_without_report(ctx: Ctx, *, extra: dict[str, str] | None = None) -> Run:
    run = current_run(ctx, task="health_check", commit_it=False)
    health = read_json(ctx, run, "analysis/health.json")
    host_put(ctx, run, HEALTH_READ, health_body(health))
    for rel, text in (extra or {}).items():
        host_put(ctx, run, rel, text)
    readme(ctx, run)
    commit(ctx, run)
    return run


@DRIVE
def test_health_report_fails_on_drive_without_a_report_revision(ctx: Ctx) -> None:
    run = _health_run_without_report(ctx)
    code, data, raw = run_check(ctx, run)
    assert data.get("profile") == "health_check", raw[:2000]
    assert {"health_present", "plays_present"} <= ids(data.get("passed"))
    assert "health_report" in failed_ids(data)
    assert code == 1

    code, env, raw = report(ctx, run, "health-read", HEALTH_READ, "internal")
    assert code == 0, raw
    _code, data, raw = run_check(ctx, run)
    assert "health_report" in ids(data.get("passed")), raw[:2000]


EXEC_SUMMARY = "deliverables/exec-summary.md"


def _unknown_families(ctx: Ctx, run: Run) -> list[str]:
    health = read_json(ctx, run, "analysis/health.json")
    return [f["family"] for f in health["families"] if f.get("assessment") == "unknown"]


@DRIVE
def test_health_report_reads_the_health_read_report_not_the_latest(ctx: Ctx) -> None:
    """A later report of another id (no ``Unknowns``) leaves ``health_report`` passing."""
    run = _health_run_without_report(
        ctx, extra={EXEC_SUMMARY: "# Executive summary\n\nSpend is flat.\n"}
    )
    assert _unknown_families(ctx, run), "the read must name an unknown family"
    code, _env, raw = report(ctx, run, "health-read", HEALTH_READ, "internal")
    assert code == 0, raw
    code, _env, raw = report(ctx, run, "exec-summary", EXEC_SUMMARY, "internal")
    assert code == 0, raw
    _code, data, raw = run_check(ctx, run)
    assert {"health_report", "health_read"} <= ids(data.get("passed")), raw[:2000]


@DRIVE
def test_health_report_fails_with_only_another_report_registered(ctx: Ctx) -> None:
    run = _health_run_without_report(ctx, extra={EXEC_SUMMARY: "# Executive summary\n"})
    code, _env, raw = report(ctx, run, "exec-summary", EXEC_SUMMARY, "internal")
    assert code == 0, raw
    code, data, raw = run_check(ctx, run)
    assert "health_report" in failed_ids(data), raw[:2000]
    reason = next(f["reason"] for f in data["failed"] if f["item"] == "health_report")
    assert "health-read" in reason
    assert code == 1


# --------------------------------------------------------------------------- #
# B4 R3 checks the manifest agrees with the descriptor
# --------------------------------------------------------------------------- #
def _retag(ctx: Ctx, run: Run, profile: str | None) -> None:
    """Append a manifest revision whose ``workflow_profile`` is ``profile``."""
    from starboard_core.engagement.commit import append_manifest

    assert run.rf
    latest = manifest(ctx.store, run.rf)

    def build(n: int, previous: str | None) -> Any:
        return dataclasses.replace(
            latest, revision=n, previous_object_id=previous, workflow_profile=profile
        )

    append_manifest(ctx.store, run.rf, build)


def _r3(data: dict[str, Any]) -> tuple[bool, str]:
    for entry in data.get("failed") or ():
        if isinstance(entry, dict) and str(entry.get("item", "")).startswith("R3"):
            return False, str(entry.get("reason", ""))
    passed = [str(p) for p in data.get("passed") or ()]
    assert any(p.startswith("R3") for p in passed), passed
    return True, ""


@DRIVE
@pytest.mark.parametrize("tampered", ["review", None])
def test_r3_fails_on_a_tampered_manifest_profile(
    ctx: Ctx, tampered: str | None
) -> None:
    run = _health_run_without_report(ctx)
    report(ctx, run, "health-read", HEALTH_READ, "internal")
    _code, before, raw = run_check(ctx, run)
    assert before.get("profile") == "health_check", raw[:2000]
    assert _r3(before)[0] is True
    assert not [w for w in all_warnings(before) if NO_GATES in w]

    _retag(ctx, run, tampered)
    code, after, raw = run_check(ctx, run)
    passed, reason = _r3(after)
    assert passed is False, raw[:2000]
    assert re.search(r"profile", reason)
    assert code == 1
    assert after.get("profile") == "health_check"
    assert after.get("profile_source") == "descriptor"
    assert ids(after.get("skipped_by_profile")) == ids(before.get("skipped_by_profile"))
    assert not [w for w in all_warnings(after) if NO_GATES in w]
