"""E7 Scenario 7: audience and follow-up (``drive_backed``, ``hybrid_drive``; §H.7, B6, D4-6).

* A customer report on an ``internal_only`` run is ``blocked_audience``
  (``internal_only_run``).
* On a hybrid run a customer report needs ``--derived-from`` an internal
  revision (``derivative_required`` / ``derivative_source_not_internal``); a
  dangling or self ``--derived-from`` is ``REPORT_REFUSED`` (exit 2) and writes
  nothing.
* An approved derivative is delivered only with a verified non-Slack receipt of
  its exact MD5; approval of rev 1 does not cover rev 2; a Slack receipt and a
  pending approval are not delivery.
* Next run: lost coverage is ``unknown_current`` (never ``recovered``); an
  observed improvement with no executed action is not adoption (D3-13).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from . import _fixtures
from ._support import (
    Ctx,
    Run,
    baseline_run,
    commit,
    current_run,
    destination,
    eng,
    engagement_ok,
    error_code,
    finding,
    host_put,
    manifest,
    md5,
    new_run,
    record_evidence,
    records,
    recovery_run,
    report,
    revision_flags,
    run_record,
    run_sink,
)

DRIVE = pytest.mark.parametrize("mode", ["drive_backed"])
HYBRID = pytest.mark.parametrize("mode", ["hybrid_drive"])
BOTH = pytest.mark.parametrize("mode", ["drive_backed", "hybrid_drive"])

INTERNAL = "deliverables/internal-report.md"
INTERNAL_BODY = "# Job 42 failures\n\nFailure rate 1% -> 8% after 2026-09-22.\n"
CUSTOMER = "deliverables/customer-report.md"
BODY_1 = "# Job 42 reliability\n\nFailures rose after the 2026-09-22 change.\n"
BODY_2 = "# Job 42 reliability\n\nFailures rose after the change; fix applied.\n"


def _put(ctx: Ctx, run: Run, rel: str, text: str) -> None:
    host_put(ctx, run, rel, text)
    commit(ctx, run)


def _registered(
    ctx: Ctx, run: Run, report_id: str, rel: str, audience: str, *extra: str
) -> dict[str, Any]:
    code, env, raw = report(ctx, run, report_id, rel, audience, *extra)
    assert code == 0, raw
    data: dict[str, Any] = env["data"]
    return data


def _report_objects(ctx: Ctx, run: Run) -> list[str]:
    assert run.rf
    return [p for p in run_sink(ctx.store, run.rf).list("") if p.startswith("reports/")]


def _hybrid(ctx: Ctx) -> tuple[Run, str]:
    """A routed hybrid run with ``internal-report@1`` and a shareable citation."""
    run = new_run(ctx, task="health_check")
    _put(ctx, run, INTERNAL, INTERNAL_BODY)
    internal = _registered(ctx, run, "internal-report", INTERNAL, "internal")
    assert internal["revision"] == 1
    cited = record_evidence(ctx, run, "capture/rows.json")
    _put(ctx, run, CUSTOMER, BODY_1)
    return run, cited


def _derivative(ctx: Ctx, run: Run, cited: str, report_id: str, source: str) -> Any:
    return _registered(
        ctx,
        run,
        report_id,
        CUSTOMER,
        "customer",
        "--cite-evidence",
        cited,
        "--derived-from",
        source,
    )


@DRIVE
def test_a_customer_report_on_an_internal_only_run_is_blocked(ctx: Ctx) -> None:
    run = new_run(
        ctx, task="troubleshooting", task_name="job-42", source_mode="internal_only"
    )
    cited = record_evidence(ctx, run, "capture/rows.json")
    _put(ctx, run, CUSTOMER, BODY_1)
    data = _registered(
        ctx, run, "customer-report", CUSTOMER, "customer", "--cite-evidence", cited
    )
    assert data["state"] == "blocked_audience"
    assert "internal_only_run" in data["blocked_reasons"]
    assert data.get("allowed_audiences") == ["internal"]
    assert "customer_eligible" not in data

    dest = destination(ctx.store)
    flags = revision_flags(run, "customer-report", data["revision"])
    code, env, raw = eng(ctx.capsys, "deliver", *flags, "--destination-folder-id", dest)
    assert code == 2 and error_code(env) == "DELIVERY_REFUSED", raw
    assert ctx.store.list_children(dest) == []


@DRIVE
def test_a_customer_workspace_run_needs_no_derivative(ctx: Ctx) -> None:
    run = new_run(ctx, task="health_check")
    cited = record_evidence(ctx, run, "capture/rows.json")
    _put(ctx, run, CUSTOMER, BODY_1)
    data = _registered(
        ctx, run, "customer-report", CUSTOMER, "customer", "--cite-evidence", cited
    )
    assert data["state"] == "ready", data
    assert data.get("allowed_audiences") == ["internal", "customer"]
    assert "customer_eligible" not in data


@HYBRID
def test_a_hybrid_customer_report_needs_an_internal_derivative(ctx: Ctx) -> None:
    run, cited = _hybrid(ctx)
    plain = _registered(
        ctx, run, "customer-report", CUSTOMER, "customer", "--cite-evidence", cited
    )
    assert plain["state"] == "blocked_audience"
    assert "derivative_required" in plain["blocked_reasons"]

    first = _derivative(ctx, run, cited, "customer-a", "internal-report@1")
    assert first["state"] == "ready", first
    rederived = _derivative(ctx, run, cited, "customer-b", "customer-a@1")
    assert rederived["state"] == "blocked_audience"
    assert "derivative_source_not_internal" in rederived["blocked_reasons"]


@HYBRID
@pytest.mark.parametrize("source", ["internal-report@9", "customer-report@1"])
def test_a_dangling_or_self_derived_from_is_refused(ctx: Ctx, source: str) -> None:
    run, cited = _hybrid(ctx)
    if source.startswith("customer-report@"):
        held = _derivative(ctx, run, cited, "customer-report", "internal-report@1")
        assert held["revision"] == 1
        _put(ctx, run, CUSTOMER, BODY_2)
    reports, objects = _report_objects(ctx, run), ctx.store.object_count
    code, env, raw = report(
        ctx,
        run,
        "customer-report",
        CUSTOMER,
        "customer",
        "--cite-evidence",
        cited,
        "--derived-from",
        source,
    )
    assert code == 2, raw
    assert error_code(env) == "REPORT_REFUSED"
    assert _report_objects(ctx, run) == reports
    assert ctx.store.object_count == objects


@HYBRID
def test_an_approved_derivative_is_delivered_for_its_exact_revision(
    ctx: Ctx,
) -> None:
    from starboard_core.engagement.records import DeliveryReceipt

    run, cited = _hybrid(ctx)
    assert run.rf
    rev1 = _derivative(ctx, run, cited, "customer-report", "internal-report@1")
    assert rev1["state"] == "ready" and rev1["revision"] == 1
    assert "customer_eligible" not in rev1
    assert "internal-report" in json.dumps(rev1.get("derived_from_revision"))

    flags1 = revision_flags(run, "customer-report", 1)
    engagement_ok(ctx, run, "approve", *flags1)
    dest = destination(ctx.store)
    delivered = engagement_ok(
        ctx, run, "deliver", *flags1, "--destination-folder-id", dest
    )
    assert delivered["state"] == "delivered"
    receipt = run_record(ctx.store, run.rf, DeliveryReceipt, delivered["receipt_id"])
    assert receipt.verified is True and receipt.channel != "slack"
    assert receipt.object_md5 == md5(BODY_1)

    # A new body is a new revision: rev 1's approval does not cover it.
    _put(ctx, run, CUSTOMER, BODY_2)
    rev2 = _derivative(ctx, run, cited, "customer-report", "internal-report@1")
    assert rev2["revision"] == 2 and rev2["state"] == "ready"
    flags2 = revision_flags(run, "customer-report", 2)
    code, env, raw = eng(
        ctx.capsys, "deliver", *flags2, "--destination-folder-id", dest
    )
    assert code == 2 and error_code(env) == "DELIVERY_REFUSED", raw
    status = engagement_ok(ctx, run, "status", "--run-folder", run.rf)
    assert status["states"]["publication"] == "pending"  # pending approval

    # A Slack receipt is never delivery.
    engagement_ok(ctx, run, "approve", *flags2)
    slack = engagement_ok(
        ctx,
        run,
        "receipt",
        *flags2,
        "--channel",
        "slack",
        "--external-object-id",
        "p123",
        "--destination-id",
        "C0123",
    )
    assert slack["verified"] is False
    assert slack["state"] != "delivered"
    assert manifest(ctx.store, run.rf).states["publication"] == "pending"


@BOTH
def test_lost_coverage_is_unknown_current_not_recovered(ctx: Ctx) -> None:
    baseline_run(ctx, task="health_check")
    cur = records(ctx, current_run(ctx, task="health_check"))
    fid = _fixtures.finding_id_j42()
    detected = finding(cur, fid)
    proposed = next(a for a in cur.actions if a["finding_id"] == fid)

    run = recovery_run(ctx, measured=False, task="health_check")
    assert run.rf
    assert manifest(ctx.store, run.rf).workflow_profile == "health_check"
    recs = records(ctx, run)
    stale = finding(recs, fid)
    assert stale["state"] == "unknown_current"
    assert stale["episode_id"] == detected["episode_id"]
    assert fid not in [
        f["finding_id"] for f in recs.findings if f["state"] == "recovered"
    ]
    action = next(a for a in recs.actions if a["action_id"] == proposed["action_id"])
    assert action["outcome_state"] == "unknown"


@BOTH
def test_improvement_without_an_executed_action_is_not_adoption(ctx: Ctx) -> None:
    baseline_run(ctx, task="health_check")
    cur = records(ctx, current_run(ctx, task="health_check"))
    fid = _fixtures.finding_id_j42()
    proposed = next(a for a in cur.actions if a["finding_id"] == fid)

    run = recovery_run(ctx, task="health_check")
    assert run.rf
    assert manifest(ctx.store, run.rf).workflow_profile == "health_check"
    recs = records(ctx, run)
    assert finding(recs, fid)["state"] == "recovered"
    action = next(a for a in recs.actions if a["action_id"] == proposed["action_id"])
    assert action["outcome_state"] == "improved"
    assert action["execution_state"] == "not_started"
    assert action["attribution"] == "not_established"
