"""E3: a mirrored copy of a slice never double-counts; conflicts are unknown (D3-18, D3-19)."""

from __future__ import annotations

import pytest

from . import _j42
from ._support import Ctx, baseline_run, current_run, finding, job_obs, records

MODE = "drive_backed"


def _slice(
    source_kind: str, window: tuple[str, str], rows: list[dict], evidence_id: str
):
    from starboard_core.engagement.jobruns import RunSlice

    return RunSlice(source_kind, window[0], window[1], (_j42.JOB,), evidence_id, rows)


def _reconstruct(*slices):
    from starboard_core.engagement.jobruns import reconstruct_runs

    return reconstruct_runs(
        slices,
        interval_start=_j42.CURRENT[0],
        interval_end=_j42.CURRENT[1],
        today=_j42.TODAY,
    )


def _job(reconstruction):
    jobs = [j for j in reconstruction.jobs if j.job_id == _j42.JOB]
    assert len(jobs) == 1, reconstruction.jobs
    return jobs[0]


def _customer_slices():
    return (
        _slice("customer_workspace", _j42.S1, _j42.s1_rows(), "ev-s1"),
        _slice("customer_workspace", _j42.S2, _j42.s2_rows(), "ev-s2"),
    )


def test_mirror_copy_collapses(capsys, store, sandbox, seams, tmp_path) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, MODE)
    # D3-20: ``serious`` needs a rise over an eligible baseline (else ``watch``).
    baseline_run(ctx)
    recs = records(ctx, current_run(ctx, mirror_copy=_j42.s2_rows()))
    assert job_obs(recs, "job_runs")["value"] == 100  # not 148
    assert job_obs(recs, "failed_job_runs")["value"] == 8  # not 11
    rate = job_obs(recs, "job_failure_rate_pct")
    assert rate["value"] == 8.0 and rate["state"] == "measured"

    fid = _j42.finding_id_j42()
    assert finding(recs, fid)["severity"] == "serious"
    plays = [p for p in recs.plays if fid in p["finding_ids"]]
    assert [p["play_code"] for p in plays] == ["job_reliability_session"]
    # Two independent dedupe groups (s1, s2); the mirror copy adds none.
    assert plays[0]["evidence_strength"] == "strong"

    base = _job(_reconstruct(*_customer_slices()))
    mirrored = _job(
        _reconstruct(
            *_customer_slices(),
            _slice("internal_mirror", _j42.S2, _j42.s2_rows(), "ev-s2m"),
        )
    )
    assert (
        (mirrored.runs, mirrored.failed_runs)
        == (base.runs, base.failed_runs)
        == (100, 8)
    )
    assert mirrored.duplicate_rows > 0
    assert mirrored.coverage == "complete"


def test_conflicting_copy_is_unknown_not_serious(
    capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, MODE)
    # With an eligible baseline the unconflicted rise would be serious (E2).
    baseline_run(ctx)
    recs = records(ctx, current_run(ctx, mirror_copy=_j42.conflicting_copy()))
    rate = job_obs(recs, "job_failure_rate_pct")
    assert rate["state"] == "unknown"
    assert rate["unknown_reason"] == "source_conflict"
    fid = _j42.finding_id_j42()
    serious = [
        f
        for f in recs.findings
        if f["finding_id"] == fid and f["severity"] in ("serious", "critical")
    ]
    assert serious == []

    from starboard_core.engagement.jobruns import UNCERTAINTY_SOURCE_CONFLICT

    job = _job(
        _reconstruct(
            *_customer_slices(),
            _slice("internal_mirror", _j42.S2, _j42.conflicting_copy(), "ev-s2m"),
        )
    )
    assert job.runs is None and job.coverage == "unknown"
    assert UNCERTAINTY_SOURCE_CONFLICT in job.uncertainty
    assert job.conflicts


@pytest.mark.parametrize("copy_source", ["internal_mirror", "customer_workspace"])
def test_later_end_supersedes(copy_source: str) -> None:
    base = _job(_reconstruct(*_customer_slices()))
    job = _job(
        _reconstruct(
            *_customer_slices(),
            _slice(copy_source, _j42.S2, _j42.superseding_copy(), "ev-s2x"),
        )
    )
    # The base reconstruction already supersedes the preliminary r2000/r2001 rows;
    # the later-ending copy of one run supersedes exactly one more.
    assert job.superseded_rows == base.superseded_rows + 1
    assert (job.runs, job.failed_runs) == (100, 8)
    assert job.conflicts == ()
