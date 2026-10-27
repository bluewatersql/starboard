"""E5: a case opened on the J-42 finding revises that same finding (D3-12)."""

from __future__ import annotations

from . import _j42
from ._support import (
    QUESTION,
    Ctx,
    baseline_run,
    clean,
    current_run,
    engagement_ok,
    fake_run_output,
    finding,
    helper,
    records,
)

RUN_OUTPUT = "raw/job-run-output-9001.json"
S2_VERIFY = "analysis/verify/vt-job-run-states-s2.json"


def test_case_revises_the_same_finding(
    mode, monkeypatch, capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, mode)
    baseline_run(ctx)
    run = current_run(ctx, commit_it=False)
    fid = _j42.finding_id_j42()
    detected = finding(records(ctx, run), fid)
    assert detected["revision"] == 1

    engagement_ok(
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
    cases = [c for c in records(ctx, run).cases if c["finding_id"] == fid]
    assert len(cases) == 1
    case = cases[0]
    assert case["origin"] == "finding" and case["origin_ref"] == fid
    assert (case["target_entity_kind"], case["target_entity_id"]) == ("job", _j42.JOB)
    assert case["question"] == QUESTION

    revise = [
        "case",
        "revise",
        *run.flags(),
        "--case-id",
        case["case_id"],
        "--verify",
        S2_VERIFY,
    ]
    if run.drive:
        assert run.rf
        fake_run_output(monkeypatch, run_id=9001, trace=_j42.TRACE_OOM)
        before = sandbox.snapshot()
        code, _env, raw = helper(
            capsys,
            "job",
            "run-output",
            "--run-id",
            "9001",
            "--run-folder",
            run.rf,
            "--out",
            RUN_OUTPUT,
        )
        assert code == 0, raw
        clean(sandbox, before, raw)
        revise += ["--evidence", RUN_OUTPUT]
    engagement_ok(ctx, run, *revise)

    recs = records(ctx, run)
    revised = finding(recs, fid)
    assert revised["finding_id"] == detected["finding_id"]
    assert revised["episode_id"] == detected["episode_id"]
    assert revised["revision"] == 2
    assert revised["revisions"][-1]["reason"] == "investigated"
    assert revised["revisions"][-1]["case_id"] == case["case_id"]
    assert revised["cause_confidence"] == "unassessed"
    assert case["case_id"] in revised["case_ids"]

    case = next(c for c in recs.cases if c["case_id"] == case["case_id"])
    assert all(h["status"] == "untested" for h in case["hypotheses"])
    assert case["evidence_revisions"]
    latest = case["evidence_revisions"][-1]
    if run.drive:
        assert latest["evidence_ids"]
    else:
        # No run-output was acquired on the internal-only path: the gap is recorded.
        assert latest["gaps"]
