"""E17: one finding across health_check/ and troubleshooting/ folders (D3-4, D3-12, D3-25)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from . import _j42
from ._support import (
    QUESTION,
    Ctx,
    analyze,
    baseline_run,
    clean,
    commit,
    current_run,
    engagement_ok,
    fake_run_output,
    finding,
    helper,
    job_obs,
    new_run,
    read_json,
    records,
    recovery_run,
    ticket_flags,
    verify_slice,
    write_inputs,
    ws_obs,
)

MODE = "drive_backed"
CASES = "analysis/cases.json"
FINDINGS = "analysis/findings.json"
RUN_OUTPUT = "raw/job-run-output-9001.json"
RATE = "job_failure_rate_pct"


def _ticket_run(ctx: Ctx):
    return new_run(
        ctx,
        task="troubleshooting",
        task_name="job-42-failures",
        route_flags=ticket_flags(ctx.store, ctx.tmp_path),
    )


def _findings(ctx: Ctx, run) -> SimpleNamespace:
    return SimpleNamespace(findings=read_json(ctx, run, FINDINGS))


def test_ticket_case_revises_the_health_finding(
    monkeypatch, capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, MODE)
    fid = _j42.finding_id_j42()
    baseline_run(ctx)
    health = current_run(ctx)
    detected = finding(records(ctx, health), fid)
    assert detected["revision"] == 1
    action = next(a for a in records(ctx, health).actions if a["finding_id"] == fid)

    ticket = _ticket_run(ctx)
    assert ticket.rf and ticket.rf != health.rf
    engagement_ok(
        ctx,
        ticket,
        "case",
        "open",
        *ticket.flags(),
        "--finding-id",
        fid,
        "--question",
        QUESTION,
    )
    case = next(c for c in read_json(ctx, ticket, CASES) if c["finding_id"] == fid)
    fake_run_output(monkeypatch, run_id=9001, trace=_j42.TRACE_OOM)
    before = sandbox.snapshot()
    code, _env, raw = helper(
        capsys,
        "job",
        "run-output",
        "--run-id",
        "9001",
        "--run-folder",
        ticket.rf,
        "--out",
        RUN_OUTPUT,
    )
    assert code == 0, raw
    clean(sandbox, before, raw)
    engagement_ok(
        ctx,
        ticket,
        "case",
        "revise",
        *ticket.flags(),
        "--case-id",
        case["case_id"],
        "--evidence",
        RUN_OUTPUT,
    )
    commit(ctx, ticket)

    revised = finding(_findings(ctx, ticket), fid)
    assert revised["finding_id"] == detected["finding_id"]
    assert revised["episode_id"] == detected["episode_id"]
    assert revised["revision"] == 2
    assert revised["revisions"][-1]["reason"] == "investigated"
    assert case["case_id"] in revised["case_ids"]

    # The next health run picks the troubleshooting copy (highest revision wins).
    later = recovery_run(ctx)
    recs = records(ctx, later)
    carried = finding(recs, fid)
    assert carried["episode_id"] == detected["episode_id"]
    assert carried["revision"] == 3
    assert [r["reason"] for r in carried["revisions"]][:2] == [
        "detected",
        "investigated",
    ]
    assert case["case_id"] in carried["case_ids"]
    assert action["action_id"] in carried["action_ids"]
    assert [a["action_id"] for a in recs.actions if a["finding_id"] == fid] == [
        action["action_id"]
    ]


def test_standalone_case_is_a_possible_link(
    capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, MODE)
    baseline_run(ctx)
    ticket = _ticket_run(ctx)
    engagement_ok(
        ctx,
        ticket,
        "case",
        "open",
        *ticket.flags(),
        "--clue",
        f"job:{_j42.JOB}",
        "--question",
        QUESTION,
    )
    case = next(c for c in read_json(ctx, ticket, CASES) if c["origin"] != "finding")
    case_finding = finding(_findings(ctx, ticket), case["finding_id"])
    assert case_finding["concern_code"] == "case:job"
    assert (case_finding["entity_kind"], case_finding["entity_id"]) == ("job", _j42.JOB)
    commit(ctx, ticket)

    health = current_run(ctx)
    j42 = finding(records(ctx, health), _j42.finding_id_j42())
    assert j42["concern_code"] == "job_failure_rise"
    assert case["finding_id"] in j42["possible_links"]
    assert j42["finding_id"] != case["finding_id"]


def _corrupt_tree(store, folder_id: str) -> int:
    count = 0
    for obj in store.list_children(folder_id):
        if obj.is_folder:
            count += _corrupt_tree(store, obj.id)
        else:
            store.corrupt_object(obj.id)
            count += 1
    return count


def test_unreadable_registry_degrades_to_history_unavailable(
    capsys, store, sandbox, seams, tmp_path
) -> None:
    from starboard_core.engagement.registry import ensure_registry

    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, MODE)
    baseline_run(ctx)
    handles = ensure_registry(store, _j42.ACCOUNT)
    assert (
        sum(
            _corrupt_tree(store, h.registrations_folder_id)
            + _corrupt_tree(store, h.index_folder_id)
            for h in handles
        )
        >= 1
    )

    run = current_run(ctx, commit_it=False)  # analyze exits 0 (asserted by the helper)
    recs = records(ctx, run)
    rate = job_obs(recs, RATE)
    entries = [*recs.baselines["selected"], *recs.baselines["unavailable"]]
    mine = [
        e for e in entries if e.get("current_observation_id") == rate["observation_id"]
    ]
    assert [e["comparison"] for e in mine] == ["history_unavailable"]
    assert all(e.get("comparison") != "continuing" for e in entries)
    assert all(c["comparison"] != "continuing" for c in recs.changes)
    assert "continuing" not in json.dumps([recs.changes, recs.baselines])
    j42 = finding(recs, _j42.finding_id_j42())
    assert j42["revision"] == 1


def test_late_upload_of_an_older_interval_is_not_the_baseline(
    capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, MODE)
    base = baseline_run(ctx)
    base_ids = {
        o["observation_id"] for o in read_json(ctx, base, "analysis/observations.json")
    }

    late = new_run(ctx)
    write_inputs(
        ctx, late, facts=_j42.late_older_facts(), review=_j42.review_manifest()
    )
    rel = verify_slice(
        ctx, late, _j42.LATE_OLDER, _j42.late_older_rows(), suffix="late"
    )
    analyze(ctx, late, _j42.LATE_OLDER, verify=(rel,))
    commit(ctx, late)
    late_ids = {
        o["observation_id"] for o in read_json(ctx, late, "analysis/observations.json")
    }
    assert late_ids and not late_ids & base_ids

    cur = records(ctx, current_run(ctx, commit_it=False))
    for obs in (job_obs(cur, RATE), ws_obs(cur, RATE)):
        picked = [
            s
            for s in cur.baselines["selected"]
            if s["current_observation_id"] == obs["observation_id"]
        ]
        assert len(picked) == 1, obs["entity_kind"]
        assert picked[0]["baseline_observation_id"] in base_ids
        assert picked[0]["comparison"] == "continuing"
    assert all(
        s["baseline_observation_id"] not in late_ids for s in cur.baselines["selected"]
    )
