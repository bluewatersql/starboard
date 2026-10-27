"""E10: standalone-case findings (D3-2, D3-14); run 4 fixed the id at ``case open``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from . import _j42
from ._support import (
    Ctx,
    clean,
    engagement_ok,
    fake_run_output,
    finding,
    helper,
    new_run,
    read_json,
)

MODE = "drive_backed"
CASES = "analysis/cases.json"
FINDINGS = "analysis/findings.json"


def _case_on_failed_run(ctx: Ctx, monkeypatch, run, run_id: int, trace: str) -> str:
    assert run.rf
    engagement_ok(
        ctx,
        run,
        "case",
        "open",
        *run.flags(),
        "--clue",
        f"job:{_j42.JOB}",
        "--question",
        f"Why did run {run_id} of job 42 fail?",
    )
    case_id = next(
        c["case_id"]
        for c in read_json(ctx, run, CASES)
        if c["question"].startswith(f"Why did run {run_id} ")
    )
    fake_run_output(monkeypatch, run_id=run_id, trace=trace)
    rel = f"raw/job-run-output-{run_id}.json"
    before = ctx.sandbox.snapshot()
    code, _env, raw = helper(
        ctx.capsys,
        "job",
        "run-output",
        "--run-id",
        str(run_id),
        "--run-folder",
        run.rf,
        "--out",
        rel,
    )
    assert code == 0, raw
    clean(ctx.sandbox, before, raw)
    engagement_ok(
        ctx,
        run,
        "case",
        "revise",
        *run.flags(),
        "--case-id",
        case_id,
        "--evidence",
        rel,
    )
    return case_id


def _case_findings(ctx: Ctx, run, case_ids: list[str]) -> list[dict]:
    by_case = {c["case_id"]: c for c in read_json(ctx, run, CASES)}
    findings = SimpleNamespace(findings=read_json(ctx, run, FINDINGS))
    return [finding(findings, by_case[cid]["finding_id"]) for cid in case_ids]


@pytest.mark.parametrize(
    "traces",
    [(_j42.TRACE_OOM, _j42.TRACE_TABLE), (_j42.TRACE_OOM, _j42.TRACE_OOM)],
    ids=["different-signature", "same-signature"],
)
def test_a_case_finding_id_is_fixed_at_open(
    traces, monkeypatch, capsys, store, sandbox, seams, tmp_path
) -> None:
    """Revising with a run-output never re-keys the case's finding (run-4 C3)."""
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, MODE)
    run = new_run(ctx)
    case_ids = [
        _case_on_failed_run(ctx, monkeypatch, run, 9001 + i, trace)
        for i, trace in enumerate(traces)
    ]
    found = _case_findings(ctx, run, case_ids)
    # Same job, same concern, no signature in the key: one stable finding.
    assert len({f["finding_id"] for f in found}) == 1
    for f in found:
        assert f["concern_code"] == "case:job"
        assert (f["entity_kind"], f["entity_id"]) == ("job", _j42.JOB)
        assert f["finding_key"].rsplit("|", 1)[-1] == "-"
        assert f["cause_confidence"] == "unassessed"
    assert set(found[0]["case_ids"]) == set(case_ids)


def test_signature_family_keys() -> None:
    from starboard_core.engagement.concerns import error_signature
    from starboard_core.engagement.records import concern_key, finding_id

    def fid(trace: str) -> str:
        sig = error_signature(trace, category="spark_error")
        return finding_id(
            concern_key(
                _j42.ACCOUNT, _j42.WS, "job", _j42.JOB, "case:job", f"sig:{sig}"
            )
        )

    assert (
        error_signature(_j42.TRACE_OOM, category="spark_error")
        == "spark_error/sparkexception"
    )
    assert error_signature(None) == "unknown/unknown"
    assert fid(_j42.TRACE_OOM) != fid(_j42.TRACE_TABLE)
    assert fid(_j42.TRACE_OOM) == fid(_j42.TRACE_OOM)
