"""E6: recovery is measured, never adoption; ``analyze`` and ``run recur`` agree (D3-13, D3-25)."""

from __future__ import annotations

import pytest

from . import _j42
from ._support import (
    Ctx,
    Run,
    analyze,
    baseline_run,
    clean,
    commit,
    current_run,
    finding,
    helper,
    job_obs,
    new_run,
    records,
    verify_slice,
    write_inputs,
)


def _recur(ctx: Ctx, run: Run) -> None:
    if run.drive:
        assert run.rf
        argv = ["run", "recur", "--run-folder", run.rf]
    else:
        assert run.run_dir and run.case_root
        argv = [
            "run",
            "recur",
            str(run.run_dir),
            "--workspace-root",
            str(run.case_root),
        ]
    before = ctx.sandbox.snapshot()
    code, _env, raw = helper(ctx.capsys, *argv)
    assert code == 0, raw
    if run.drive:
        clean(ctx.sandbox, before, raw)


@pytest.mark.parametrize("verb", ["analyze", "recur"])
def test_recovery_without_adoption(
    verb, mode, capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, mode)
    baseline_run(ctx)
    cur = records(ctx, current_run(ctx))
    fid = _j42.finding_id_j42()
    detected = finding(cur, fid)
    proposed = next(a for a in cur.actions if a["finding_id"] == fid)

    run = new_run(ctx)
    write_inputs(ctx, run, facts=_j42.recovery_facts(), review=_j42.review_manifest())
    rel = verify_slice(ctx, run, _j42.RECOVERY, _j42.recovery_rows(), suffix="next")
    if verb == "analyze":
        analyze(ctx, run, _j42.RECOVERY, verify=(rel,))
    else:
        _recur(ctx, run)
    commit(ctx, run)
    recs = records(ctx, run)

    rate = job_obs(recs, "job_failure_rate_pct")
    assert rate["state"] == "measured" and rate["value"] == 1.0

    recovered = finding(recs, fid)
    assert recovered["state"] == "recovered"
    assert recovered["episode_id"] == detected["episode_id"]
    assert recovered["revisions"][-1]["reason"] == "recovered"
    assert recovered["last_confirmed_severity"] == "serious"

    action = next(a for a in recs.actions if a["action_id"] == proposed["action_id"])
    assert action["outcome_state"] == "improved"
    assert action["acceptance_state"] == "pending"
    assert action["execution_state"] == "not_started"
    assert action["attribution"] == "not_established"
    assert rate["observation_id"] in action["outcome_observation_ids"]

    changes = [c for c in recs.changes if c["observation_id"] == rate["observation_id"]]
    assert len(changes) == 1
    assert changes[0]["causality"] == "not_assessed"
    assert changes[0]["delta"] == -7.0 and changes[0]["delta_unit"] == "pp"
