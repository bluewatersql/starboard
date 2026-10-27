"""E7: no current evidence for job 42 is ``unknown_current``, never recovered (D3-13)."""

from __future__ import annotations

from . import _j42
from ._support import (
    Ctx,
    baseline_run,
    current_run,
    family,
    finding,
    job_obs,
    records,
    recovery_run,
)


def test_missing_current_is_unknown(
    mode, capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, mode)
    baseline_run(ctx)
    cur = records(ctx, current_run(ctx))
    fid = _j42.finding_id_j42()
    detected = finding(cur, fid)
    proposed = next(a for a in cur.actions if a["finding_id"] == fid)

    recs = records(ctx, recovery_run(ctx, measured=False))
    stale = finding(recs, fid)
    assert stale["state"] == "unknown_current"
    assert stale["severity"] is None
    assert stale["last_confirmed_severity"] == "serious"
    assert stale["episode_id"] == detected["episode_id"]
    assert stale["revisions"][-1]["reason"] == "unknown_current"

    action = next(a for a in recs.actions if a["action_id"] == proposed["action_id"])
    assert action["outcome_state"] == "unknown"
    assert action["attribution"] == "not_established"

    rate = job_obs(recs, "job_failure_rate_pct")
    assert rate["state"] == "unknown"
    assert rate["value"] is None

    # D3-6: family severity counts only active/watch findings (else ``none``,
    # never a "healthy"/recovered label); the read cites the unknown per-job
    # value and lists no recovered finding.
    rel = family(recs, "reliability")
    assert rel["severity"] == "none"
    assert rate["observation_id"] in rel["observation_ids"]
    assert fid not in rel["finding_ids"]
    assert fid not in [
        f["finding_id"] for f in recs.findings if f["state"] == "recovered"
    ]
