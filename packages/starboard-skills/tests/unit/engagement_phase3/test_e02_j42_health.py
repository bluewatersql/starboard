"""E2: J-42 health in both modes: 1/100 baseline -> 8/100 current, one serious finding."""

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
    ws_obs,
)


def _change(recs, observation_id: str) -> dict:
    matches = [c for c in recs.changes if c["observation_id"] == observation_id]
    assert len(matches) == 1, recs.changes
    return matches[0]


def test_j42_health(mode, capsys, store, sandbox, seams, tmp_path) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, mode)
    base = records(ctx, baseline_run(ctx))
    base_rate = job_obs(base, "job_failure_rate_pct")
    assert base_rate["value"] == 1.0 and base_rate["unit"] == "pct"

    cur_run = current_run(ctx)
    cur = records(ctx, cur_run)

    # Per-job reliability from the s1 + s2 reconstruction (the boundary run counts once).
    rate = job_obs(cur, "job_failure_rate_pct")
    assert rate["state"] == "measured"
    assert rate["value"] == 8.0 and rate["unit"] == "pct"
    assert rate["coverage"] == "complete"
    assert rate["family"] == "reliability"
    assert job_obs(cur, "job_runs")["value"] == 100
    assert job_obs(cur, "failed_job_runs")["value"] == 8
    assert rate["source_kind"] == (
        "customer_workspace" if mode == "drive_backed" else "internal_mirror"
    )

    # Workspace reliability comes from F-06, not from the job-filtered slices.
    assert ws_obs(cur, "job_runs")["value"] == 500
    assert ws_obs(cur, "failed_job_runs")["value"] == 12
    assert ws_obs(cur, "job_failure_rate_pct")["value"] == 2.4

    # The change input: +7.0 pp over the selected baseline, both slices cited.
    change = _change(cur, rate["observation_id"])
    assert change["baseline_value"] == 1.0 and change["current_value"] == 8.0
    assert change["delta"] == 7.0 and change["delta_unit"] == "pp"
    # B5: each source window is (start, end, source_kind).
    assert [tuple(w) for w in change["source_windows"]] == [
        (*_j42.S1, rate["source_kind"]),
        (*_j42.S2, rate["source_kind"]),
    ]
    assert change["baseline_observation_id"] == base_rate["observation_id"]

    selected = [
        s
        for s in cur.baselines["selected"]
        if s["current_observation_id"] == rate["observation_id"]
    ]
    assert len(selected) == 1
    assert selected[0]["baseline_observation_id"] == base_rate["observation_id"]
    assert selected[0]["comparison"] == "continuing"

    # One serious J-42 finding; reliability is assessed with complete coverage.
    j42 = finding(cur, _j42.finding_id_j42())
    assert j42["concern_code"] == "job_failure_rise"
    assert j42["entity_kind"] == "job" and j42["entity_id"] == _j42.JOB
    assert j42["severity"] == "serious" and j42["state"] == "active"
    assert j42["revision"] == 1 and j42["revisions"][0]["reason"] == "detected"
    assert rate["observation_id"] in j42["observation_ids"]
    rel = family(cur, "reliability")
    assert rel["assessment"] == "assessed"
    assert rel["coverage"] == "complete"
    assert rel["severity"] == "serious"
    assert j42["finding_id"] in rel["finding_ids"]
