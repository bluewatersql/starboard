"""E5 Scenario 5: focused failure, customer plus internal (``hybrid_drive``; §H.5).

* ``engagement source-options`` requires a choice on an overlay install, and
  ``hybrid`` is ``drive_required`` with workspace auth.
* A ``verify-identity`` mismatch stops the customer leg (exit 5).
* Targeted ``job run-output`` / ``job code`` evidence enriches the existing
  health finding (same ``finding_id``, next revision).
* An internal report is delivered with a verified receipt; a forced upload
  failure leaves a resumable ``publication_pending`` run and no local file.
* **No customer profile** (D4-14): the hybrid preflight is not routed without
  ``verify-identity`` (usage exit 2, no local file); a new ``internal_only``
  troubleshooting run carries the gap line in its case report ``Unknowns`` and
  passes ``run check``; a report without an ``Unknowns`` heading fails
  ``focused_report``.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from . import _fixtures
from ._support import (
    CASE_REPORT,
    NO_CUSTOMER_GAP,
    QUESTION,
    WS,
    Ctx,
    FakeWorkspace,
    Run,
    autospec_client,
    case_report,
    clean,
    commit,
    current_run,
    destination,
    eng,
    engagement_ok,
    error_code,
    error_text,
    failed_ids,
    finding,
    helper,
    host_put,
    ids,
    manifest,
    md5,
    new_run,
    ok,
    preflight_argv,
    readme,
    record_evidence,
    records,
    report,
    revision_flags,
    run_check,
    run_record,
    run_sink,
    verify_slice,
)

pytestmark = pytest.mark.parametrize("mode", ["hybrid_drive"])

RUN_OUTPUT = "raw/job-run-output-9001.json"
JOB_CODE = "raw/job-code-42.json"
INTERNAL = "deliverables/internal-report.md"
INTERNAL_BODY = "# Job 42 failures\n\nFailure rate 1% -> 8% after 2026-09-22.\n"
CUSTOMER = "deliverables/customer-report.md"
CUSTOMER_BODY = "# Job 42 reliability\n\nFailures rose after the 2026-09-22 change.\n"
TROUBLE_README = "not applicable: troubleshooting run"
TRACE = "java.lang.OutOfMemoryError: Java heap space\n\tat ingest.scala:42\n"


def _options(ctx: Ctx) -> dict[str, dict[str, Any]]:
    data = ok(ctx.capsys, "source-options", "--task", "troubleshooting")
    assert data["overlay_enabled"] is True
    assert data["choice_required"] is True
    return {o["source_mode"]: o for o in data["options"]}


def _profiled(ctx: Ctx, run: Run, profile: str) -> None:
    """D4-1: the route records the task profile on the run's first manifest."""
    assert run.rf
    assert manifest(ctx.store, run.rf).workflow_profile == profile


def _fake_jobs(monkeypatch: pytest.MonkeyPatch) -> Any:
    """An autospec client answering ``job run-output`` and ``job code`` for job 42."""
    from databricks.sdk.service.jobs import (
        Job,
        JobSettings,
        NotebookTask,
        RunLifeCycleState,
        RunOutput,
        RunResultState,
        RunState,
        RunTask,
        Task,
    )
    from databricks.sdk.service.jobs import Run as SdkRun
    from databricks.sdk.service.workspace import ExportResponse

    failed = RunState(
        life_cycle_state=RunLifeCycleState.TERMINATED,
        result_state=RunResultState.FAILED,
        state_message="failed",
    )
    w = autospec_client("jobs", "workspace")
    w.jobs.get_run.return_value = SdkRun(
        run_id=9001,
        job_id=42,
        state=failed,
        tasks=[RunTask(task_key="ingest", run_id=9002, state=failed)],
    )
    w.jobs.get_run_output.return_value = RunOutput(
        error="task failed",
        error_trace=TRACE,
        logs="driver log\n",
        metadata=SdkRun(run_id=9002, state=failed),
    )
    w.jobs.get.return_value = Job(
        job_id=42,
        settings=JobSettings(
            name="j42",
            tasks=[
                Task(
                    task_key="ingest",
                    notebook_task=NotebookTask(notebook_path="/Shared/j42/ingest"),
                )
            ],
        ),
    )
    w.workspace.export.return_value = ExportResponse(
        content=base64.b64encode(b"df = spark.read.table('t')\n").decode(),
        file_type="py",
    )
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def _acquire(ctx: Ctx, run: Run, *argv: str) -> None:
    assert run.rf
    before = ctx.sandbox.snapshot()
    code, _env, raw = helper(ctx.capsys, *argv, "--run-folder", run.rf)
    assert code == 0, raw
    clean(ctx.sandbox, before, raw)


def _health_run(ctx: Ctx) -> Run:
    run = current_run(ctx, task="health_check")
    _profiled(ctx, run, "health_check")
    return run


def _internal_report(ctx: Ctx, run: Run) -> dict[str, Any]:
    host_put(ctx, run, INTERNAL, INTERNAL_BODY)
    commit(ctx, run)
    code, env, raw = report(ctx, run, "internal-report", INTERNAL, "internal")
    assert code == 0, raw
    data = env["data"]
    assert data["state"] == "ready"
    assert data.get("allowed_audiences") == ["internal", "customer"]
    assert "derived_from_revision" in data and data["derived_from_revision"] is None
    return data


def test_source_options_require_a_choice_and_hybrid_needs_drive(ctx: Ctx) -> None:
    before = ctx.sandbox.snapshot()
    objects = ctx.store.object_count
    options = _options(ctx)
    assert list(options) == ["internal_only", "customer_workspace", "hybrid"]
    assert options["hybrid"]["storage_policy"] == "drive_required"
    assert options["hybrid"]["storage_choices"] == ["drive"]
    assert options["hybrid"]["needs_workspace_auth"] is True
    assert options["internal_only"]["needs_workspace_auth"] is False
    assert ctx.store.object_count == objects
    assert ctx.sandbox.snapshot() == before


def test_identity_mismatch_stops_the_customer_leg(ctx: Ctx) -> None:
    pre = ok(
        ctx.capsys,
        *preflight_argv(
            ctx, task="troubleshooting", task_name="job-42", source_mode="hybrid"
        ),
    )
    ctx.seams.client = FakeWorkspace(workspace_id="999")
    code, env, raw = eng(
        ctx.capsys,
        "verify-identity",
        "--run-id",
        pre["run_id"],
        "--profile",
        "acme",
        "--expected-workspace-id",
        WS,
    )
    assert code == 5, raw
    assert error_code(env) == "IDENTITY_MISMATCH"
    code, env, raw = eng(ctx.capsys, "route", "--run-id", pre["run_id"])
    assert code == 5, raw


def test_targeted_acquisition_enriches_the_health_finding(
    ctx: Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = current_run(ctx, task="health_check", commit_it=False)
    _profiled(ctx, run, "health_check")
    fid = _fixtures.finding_id_j42()
    detected = finding(records(ctx, run), fid)
    case = engagement_ok(
        ctx,
        run,
        "case",
        "open",
        *run.flags(),
        "--finding-id",
        fid,
        "--question",
        QUESTION,
    )
    assert case["finding_id"] == fid

    _fake_jobs(monkeypatch)
    _acquire(ctx, run, "job", "run-output", "--run-id", "9001", "--out", RUN_OUTPUT)
    _acquire(ctx, run, "job", "code", "--job-id", "42", "--out", JOB_CODE)
    revised = engagement_ok(
        ctx,
        run,
        "case",
        "revise",
        *run.flags(),
        "--case-id",
        case["case_id"],
        "--evidence",
        RUN_OUTPUT,
        "--evidence",
        JOB_CODE,
    )
    assert revised["finding_id"] == fid
    enriched = finding(records(ctx, run), fid)
    assert enriched["finding_id"] == detected["finding_id"]
    assert enriched["episode_id"] == detected["episode_id"]
    assert enriched["revision"] == detected["revision"] + 1
    latest = next(
        c for c in records(ctx, run).cases if c["case_id"] == case["case_id"]
    )["evidence_revisions"][-1]
    assert len(latest["evidence_ids"]) >= 2


def test_internal_report_is_delivered_with_a_verified_receipt(ctx: Ctx) -> None:
    from starboard_core.engagement.records import DeliveryReceipt

    run = _health_run(ctx)
    rev = _internal_report(ctx, run)
    flags = revision_flags(run, "internal-report", rev["revision"])
    dest = destination(ctx.store)
    delivered = engagement_ok(
        ctx, run, "deliver", *flags, "--destination-folder-id", dest
    )
    assert delivered["state"] == "delivered"
    assert run.rf
    receipt = run_record(ctx.store, run.rf, DeliveryReceipt, delivered["receipt_id"])
    assert receipt.verified is True and receipt.channel != "slack"
    assert receipt.object_md5 == md5(INTERNAL_BODY)
    (copy,) = ctx.store.list_children(dest)
    assert copy.md5 == md5(INTERNAL_BODY)


def test_forced_upload_failure_leaves_a_resumable_pending_run(ctx: Ctx) -> None:
    """A customer derivative of the internal report (the delivery that is due)."""
    run = _health_run(ctx)
    source = _internal_report(ctx, run)
    assert run.rf
    cited = record_evidence(ctx, run, "capture/rows.json")
    host_put(ctx, run, CUSTOMER, CUSTOMER_BODY)
    commit(ctx, run)
    code, env, raw = report(
        ctx,
        run,
        "customer-report",
        CUSTOMER,
        "customer",
        "--cite-evidence",
        cited,
        "--derived-from",
        f"internal-report@{source['revision']}",
    )
    assert code == 0, raw
    assert env["data"]["state"] == "ready", raw
    flags = revision_flags(run, "customer-report", env["data"]["revision"])
    engagement_ok(ctx, run, "approve", *flags)
    dest = destination(ctx.store)
    before = ctx.sandbox.snapshot()
    ctx.store.fail_put_after = 0
    code, env, raw = eng(ctx.capsys, "deliver", *flags, "--destination-folder-id", dest)
    ctx.store.fail_put_after = None
    assert code == 4, raw
    assert env["data"]["run_status"] == "publication_pending"
    assert env["data"]["resume"]["stage"] == "publication"
    assert manifest(ctx.store, run.rf).states["publication"] == "pending"
    assert manifest(ctx.store, run.rf).receipts == ()
    assert ctx.sandbox.snapshot() == before

    retried = engagement_ok(
        ctx, run, "deliver", *flags, "--destination-folder-id", dest
    )
    assert retried["state"] == "delivered"
    assert manifest(ctx.store, run.rf).states["publication"] == "complete"
    assert ctx.sandbox.snapshot() == before


def test_hybrid_without_a_customer_profile_is_not_routed(ctx: Ctx) -> None:
    assert _options(ctx)["hybrid"]["needs_workspace_auth"] is True
    before = ctx.sandbox.snapshot()
    pre = ok(
        ctx.capsys,
        *preflight_argv(
            ctx, task="troubleshooting", task_name="job-42", source_mode="hybrid"
        ),
    )
    code, env, raw = eng(ctx.capsys, "route", "--run-id", pre["run_id"])
    assert code == 2, raw
    assert "verify-identity" in error_text(env, raw)
    assert ctx.sandbox.snapshot() == before


def _no_profile_case(ctx: Ctx, *, unknowns: bool) -> Run:
    """D4-14: the operator has no customer profile -> a new internal-only run.

    D4-15: the run names its workspace at preflight (``new_run``), so the
    standalone ``case open`` runs first and the Drive slice passes the scope.
    """
    run = new_run(
        ctx,
        task="troubleshooting",
        task_name="job-42",
        source_mode="internal_only",
    )
    _profiled(ctx, run, "troubleshooting")
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
    rel = verify_slice(ctx, run, _fixtures.S2, _fixtures.s2_rows(), suffix="s2")
    engagement_ok(
        ctx,
        run,
        "case",
        "revise",
        *run.flags(),
        "--case-id",
        opened["case_id"],
        "--verify",
        rel,
    )
    body = case_report([opened["case_id"]], gaps=(NO_CUSTOMER_GAP,), unknowns=unknowns)
    host_put(ctx, run, CASE_REPORT, body)
    readme(ctx, run, delivery=f"- {CASE_REPORT}", recur=TROUBLE_README)
    commit(ctx, run)
    return run


def test_internal_only_fallback_records_the_customer_gap_and_passes(
    ctx: Ctx,
) -> None:
    before = ctx.sandbox.snapshot()
    run = _no_profile_case(ctx, unknowns=True)
    assert run.source_mode == "internal_only"
    assert run.rf
    text = run_sink(ctx.store, run.rf).get_bytes(CASE_REPORT).decode()
    unknowns = text.split("## Unknowns", 1)[1]
    assert NO_CUSTOMER_GAP in unknowns
    code, data, raw = run_check(ctx, run)
    assert data.get("profile") == "troubleshooting", raw[:2000]
    assert {"case_linked", "focused_report"} <= ids(data.get("passed"))
    assert failed_ids(data) == set(), raw[:2000]
    assert code == 0
    assert ctx.sandbox.snapshot() == before


def test_a_case_report_without_unknowns_fails_focused_report(ctx: Ctx) -> None:
    run = _no_profile_case(ctx, unknowns=False)
    code, data, raw = run_check(ctx, run)
    assert data.get("profile") == "troubleshooting", raw[:2000]
    assert "focused_report" in failed_ids(data)
    assert code == 1
