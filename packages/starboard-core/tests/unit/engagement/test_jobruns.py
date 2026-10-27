# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for sliced job-run reconstruction and F-12 aggregate combining (D3-18)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from starboard_core.engagement.jobruns import (
    CANCELLED_STATE,
    F12_CAP,
    FAILED_STATES,
    METHOD_VERSION,
    AggregateSlice,
    JobReliability,
    Reconstruction,
    RunSlice,
    combine_job_aggregates,
    reconstruct_runs,
    slice_from_verify,
)

WS = "123"
START = "2026-09-01"
END = "2026-09-30"
TODAY = date(2026, 10, 5)


def run(
    run_id: str,
    state: str | None,
    last_end: str,
    *,
    job_id: str = "42",
    first_start: str | None = None,
) -> dict[str, Any]:
    return {
        "workspace_id": WS,
        "job_id": job_id,
        "run_id": run_id,
        "result_state": state,
        "first_period_start": first_start or last_end,
        "last_period_end": last_end,
        "trigger_type": "PERIODIC",
    }


def slc(
    rows: list[dict[str, Any]],
    *,
    start: str = START,
    end: str = END,
    job_ids: tuple[str, ...] = ("42",),
    source_kind: str = "customer_workspace",
    evidence_id: str = "ev_a",
    limit_reached: bool = False,
) -> RunSlice:
    return RunSlice(
        source_kind=source_kind,
        window_start=start,
        window_end=end,
        job_ids=job_ids,
        evidence_id=evidence_id,
        rows=tuple(rows),
        limit_reached=limit_reached,
        workspace_id=WS,
    )


def recon(slices: list[RunSlice], **kw: Any) -> Reconstruction:
    return reconstruct_runs(
        slices,
        interval_start=kw.pop("interval_start", START),
        interval_end=kw.pop("interval_end", END),
        today=kw.pop("today", TODAY),
        **kw,
    )


def only(r: Reconstruction, job_id: str = "42") -> JobReliability:
    (job,) = [j for j in r.jobs if j.job_id == job_id]
    return job


# ---- constants ---------------------------------------------------------------


def test_failed_states_and_method_version() -> None:
    assert FAILED_STATES == ("FAILED", "ERROR", "TIMED_OUT", "TIMEDOUT")
    assert CANCELLED_STATE == "CANCELLED"
    assert CANCELLED_STATE not in FAILED_STATES
    assert METHOD_VERSION == "job_reliability_v1"
    assert F12_CAP == 25


def test_facts_module_uses_the_kernel_constant() -> None:
    from starboard_core.engagement import jobruns
    from starboard_x.discovery import _facts

    assert _facts.FAILED_STATES is jobruns.FAILED_STATES


# ---- per-run collapse ----------------------------------------------------------


def test_run_spanning_two_slices_counts_once() -> None:
    # Periods span the slice boundary; verify places the run only in the slice of
    # its last period, so the first slice does not carry it.
    first = slc([], start="2026-09-01", end="2026-09-15", evidence_id="ev_1")
    second = slc(
        [
            run(
                "r1",
                "SUCCESS",
                "2026-09-16T01:00:00",
                first_start="2026-09-15T23:00:00",
            )
        ],
        start="2026-09-16",
        end="2026-09-30",
        evidence_id="ev_2",
    )
    job = only(recon([first, second]))
    assert job.runs == 1
    assert job.failed_runs == 0
    assert job.coverage == "complete"
    assert job.uncertainty == ()
    assert job.source_windows == (
        ("2026-09-01", "2026-09-15"),
        ("2026-09-16", "2026-09-30"),
    )
    assert job.evidence_ids == ("ev_1", "ev_2")


def test_repaired_run_counts_by_final_state() -> None:
    # The verify CTE already collapses periods by MAX_BY(result_state, period_end_time);
    # a repaired run arrives as one SUCCESS row and counts once.
    job = only(recon([slc([run("r1", "SUCCESS", "2026-09-10T05:00:00")])]))
    assert (job.runs, job.failed_runs) == (1, 0)


def test_in_flight_runs_are_excluded_and_counted() -> None:
    r = recon(
        [
            slc(
                [
                    run("r1", "FAILED", "2026-09-10T05:00:00"),
                    run("r2", None, "2026-09-29T05:00:00"),
                ]
            )
        ]
    )
    assert r.in_flight == 1
    job = only(r)
    assert (job.runs, job.failed_runs) == (1, 1)
    assert job.failure_rate_pct == 100.0


def test_run_ending_today_is_excluded() -> None:
    r = recon(
        [
            slc(
                [
                    run("r1", "SUCCESS", "2026-09-29T05:00:00"),
                    run("r2", "FAILED", "2026-09-30T05:00:00"),
                ]
            )
        ],
        today=date(2026, 9, 30),
    )
    assert only(r).runs == 1
    assert only(r).failed_runs == 0


def test_run_ending_on_interval_end_plus_one_is_excluded() -> None:
    r = recon(
        [
            slc(
                [
                    run("r1", "FAILED", "2026-09-30T23:59:59"),
                    run("r2", "FAILED", "2026-10-01T00:00:00"),
                ]
            )
        ]
    )
    assert only(r).runs == 1


def test_timed_out_variants_count_as_failed_cancelled_separate() -> None:
    job = only(
        recon(
            [
                slc(
                    [
                        run("r1", "TIMEDOUT", "2026-09-02T01:00:00"),
                        run("r2", "TIMED_OUT", "2026-09-03T01:00:00"),
                        run("r3", "ERROR", "2026-09-04T01:00:00"),
                        run("r4", "FAILED", "2026-09-05T01:00:00"),
                        run("r5", "CANCELLED", "2026-09-06T01:00:00"),
                        run("r6", "SUCCESS", "2026-09-07T01:00:00"),
                        run("r7", "SUCCESS", "2026-09-08T01:00:00"),
                        run("r8", "SUCCESS", "2026-09-09T01:00:00"),
                    ]
                )
            ]
        )
    )
    assert job.runs == 8
    assert job.failed_runs == 4
    assert job.cancelled_runs == 1
    assert job.failure_rate_pct == 50.0


# ---- coverage ------------------------------------------------------------------


def test_tiling_slices_give_complete() -> None:
    job = only(
        recon(
            [
                slc([], start="2026-09-01", end="2026-09-10", evidence_id="a"),
                slc([], start="2026-09-11", end="2026-09-20", evidence_id="b"),
                slc([], start="2026-09-21", end="2026-09-30", evidence_id="c"),
            ]
        )
    )
    assert job.coverage == "complete"
    assert job.runs == 0
    assert job.failure_rate_pct is None


def test_gap_gives_partial_slice() -> None:
    job = only(
        recon(
            [
                slc([], start="2026-09-01", end="2026-09-10", evidence_id="a"),
                slc([], start="2026-09-12", end="2026-09-30", evidence_id="b"),
            ]
        )
    )
    assert job.coverage == "partial"
    assert job.uncertainty == ("partial_slice",)


def test_limit_reached_gives_partial_with_code() -> None:
    job = only(
        recon([slc([run("r1", "FAILED", "2026-09-10T05:00:00")], limit_reached=True)])
    )
    assert job.coverage == "partial"
    assert "verify_limit_reached" in job.uncertainty
    assert job.runs == 1  # a lower bound, still reported


def test_no_slice_gives_unknown() -> None:
    r = recon([], expected_jobs=((WS, "42"),))
    job = only(r)
    assert job.coverage == "unknown"
    assert job.runs is None
    assert job.failed_runs is None
    assert job.failure_rate_pct is None
    assert recon([]).jobs == ()


def test_slice_for_other_job_does_not_cover_expected_job() -> None:
    r = recon([slc([], job_ids=("7",))], expected_jobs=((WS, "42"),))
    assert only(r, "42").coverage == "unknown"
    assert only(r, "7").coverage == "complete"


# ---- duplicates, supersession, conflicts -----------------------------------------


def test_identical_mirrored_slice_adds_duplicates_only() -> None:
    rows = [
        run("r1", "FAILED", "2026-09-10T05:00:00"),
        run("r2", "SUCCESS", "2026-09-11T05:00:00"),
    ]
    alone = only(recon([slc(rows)]))
    both = recon(
        [
            slc(rows, evidence_id="ev_c"),
            slc(rows, source_kind="internal_mirror", evidence_id="ev_m"),
        ]
    )
    job = only(both)
    assert (job.runs, job.failed_runs) == (alone.runs, alone.failed_runs) == (2, 1)
    assert job.duplicate_rows == 2
    assert both.duplicate_rows == 2
    assert job.evidence_ids == ("ev_c", "ev_m")
    assert job.coverage == "complete"


def test_later_last_period_end_supersedes() -> None:
    early = slc([run("r1", "FAILED", "2026-09-10T05:00:00")], evidence_id="a")
    late = slc([run("r1", "SUCCESS", "2026-09-10T09:00:00")], evidence_id="b")
    r = recon([early, late])
    job = only(r)
    assert (job.runs, job.failed_runs) == (1, 0)
    assert job.superseded_rows == 1
    assert r.superseded_rows == 1


def test_same_end_different_state_drops_job_with_conflict() -> None:
    a = slc(
        [
            run("r1", "FAILED", "2026-09-10T05:00:00"),
            run("r2", "SUCCESS", "2026-09-12T05:00:00"),
        ],
        evidence_id="a",
    )
    b = slc([run("r1", "SUCCESS", "2026-09-10T05:00:00")], evidence_id="b")
    r = recon([a, b])
    job = only(r)
    assert job.coverage == "unknown"
    assert job.uncertainty == ("source_conflict",)
    assert job.runs is None and job.failed_runs is None
    assert job.conflicts == ("r1",)
    assert r.conflicts == ((WS, "42", "r1"),)


def test_output_has_no_workspace_rollup() -> None:
    r = recon(
        [
            slc(
                [
                    run("r1", "FAILED", "2026-09-10T05:00:00", job_id="42"),
                    run("r2", "SUCCESS", "2026-09-10T05:00:00", job_id="43"),
                ],
                job_ids=("42", "43"),
            )
        ]
    )
    assert {j.job_id for j in r.jobs} == {"42", "43"}
    assert all(j.job_id for j in r.jobs)
    field_names = set(Reconstruction.__dataclass_fields__)
    assert field_names == {
        "jobs",
        "in_flight",
        "duplicate_rows",
        "superseded_rows",
        "conflicts",
    }


def test_matches_documented_f06_counts() -> None:
    # Synthetic per-run rows whose F-06 counts are 10 runs / 3 failed / 1 cancelled.
    rows = [run(f"r{i}", "SUCCESS", f"2026-09-{i + 1:02d}T01:00:00") for i in range(6)]
    rows += [
        run("f1", "FAILED", "2026-09-20T01:00:00"),
        run("f2", "TIMEDOUT", "2026-09-21T01:00:00"),
        run("f3", "ERROR", "2026-09-22T01:00:00"),
        run("c1", "CANCELLED", "2026-09-23T01:00:00"),
    ]
    job = only(recon([slc(rows)]))
    assert (job.runs, job.failed_runs, job.cancelled_runs) == (10, 3, 1)
    assert job.failure_rate_pct == 30.0


# ---- slice_from_verify -------------------------------------------------------------


def _verify_payload(*, limit_reached: bool, arrays: bool = False) -> dict[str, Any]:
    rows: list[Any] = [run("r1", "FAILED", "2026-09-10T05:00:00")]
    data: dict[str, Any] = {
        "row_count": 1,
        "limit_reached": limit_reached,
        "verify": {
            "vt_id": "vt-job-run-states",
            "params": {"ws": WS, "start": START, "end": END, "job_ids": "'42', '43'"},
            "source": "public",
        },
    }
    if arrays:
        cols = list(rows[0])
        data["columns"] = cols
        data["rows"] = [[r[c] for c in cols] for r in rows]
    else:
        data["rows"] = rows
    return {"ok": True, "domain": "query", "command": "sql", "data": data, "meta": {}}


@pytest.mark.parametrize("arrays", [False, True])
def test_slice_from_verify_reads_rows_and_limit(arrays: bool) -> None:
    s = slice_from_verify(
        _verify_payload(limit_reached=True, arrays=arrays),
        source_kind="customer_workspace",
        evidence_id="ev_v",
    )
    assert s.limit_reached is True
    assert s.window_start == START and s.window_end == END
    assert s.job_ids == ("42", "43")
    assert s.workspace_id == WS
    assert s.evidence_id == "ev_v"
    assert s.rows[0]["run_id"] == "r1"
    job = only(recon([s]))
    assert job.coverage == "partial"
    assert job.uncertainty == ("verify_limit_reached",)


def test_slice_from_verify_rejects_non_job_filtered_payload() -> None:
    payload = _verify_payload(limit_reached=False)
    del payload["data"]["verify"]["params"]["job_ids"]
    with pytest.raises(ValueError, match="job_ids"):
        slice_from_verify(payload, source_kind="customer_workspace", evidence_id="e")


def test_run_slice_requires_job_ids() -> None:
    with pytest.raises(ValueError, match="job_ids"):
        slc([], job_ids=())


# ---- combine_job_aggregates ----------------------------------------------------------


def agg_row(job_id: str, runs: int, failed: int, cancelled: int = 0) -> dict[str, Any]:
    return {
        "workspace_id": WS,
        "job_id": job_id,
        "runs": runs,
        "failed_runs": failed,
        "cancelled_runs": cancelled,
    }


def agg(
    rows: list[dict[str, Any]],
    *,
    start: str = START,
    end: str = END,
    source_kind: str = "customer_workspace",
    evidence_id: str = "ev_f",
) -> AggregateSlice:
    return AggregateSlice(
        source_kind=source_kind,
        window_start=start,
        window_end=end,
        evidence_id=evidence_id,
        rows=tuple(rows),
        method_version=METHOD_VERSION,
    )


def test_aggregate_rows_carry_per_job_cap() -> None:
    r = combine_job_aggregates(
        [agg([agg_row("42", 20, 5, 1), agg_row("43", 10, 0)])],
        interval_start=START,
        interval_end=END,
    )
    job = only(r)
    assert (job.runs, job.failed_runs, job.cancelled_runs) == (20, 5, 1)
    assert job.failure_rate_pct == 25.0
    assert job.coverage == "partial"
    assert job.uncertainty == ("per_job_cap_25",)
    assert all("per_job_cap_25" in j.uncertainty for j in r.jobs)
    assert all(j.coverage != "complete" for j in r.jobs)


def test_aggregate_overlap_raises() -> None:
    with pytest.raises(ValueError, match="interval_overlap"):
        combine_job_aggregates(
            [
                agg([agg_row("42", 1, 0)], start="2026-09-01", end="2026-09-15"),
                agg([agg_row("42", 1, 0)], start="2026-09-15", end="2026-09-30"),
            ],
            interval_start=START,
            interval_end=END,
        )


def test_aggregate_identical_windows_dedupe() -> None:
    r = combine_job_aggregates(
        [
            agg([agg_row("42", 20, 5)], evidence_id="ev_c"),
            agg(
                [agg_row("42", 20, 5)],
                source_kind="internal_mirror",
                evidence_id="ev_m",
            ),
        ],
        interval_start=START,
        interval_end=END,
    )
    job = only(r)
    assert (job.runs, job.failed_runs) == (20, 5)
    assert job.duplicate_rows == 1
    assert job.evidence_ids == ("ev_c", "ev_m")


def test_aggregate_identical_window_conflict_is_unknown() -> None:
    r = combine_job_aggregates(
        [
            agg([agg_row("42", 20, 5)], evidence_id="ev_c"),
            agg(
                [agg_row("42", 20, 6)],
                source_kind="internal_mirror",
                evidence_id="ev_m",
            ),
        ],
        interval_start=START,
        interval_end=END,
    )
    job = only(r)
    assert job.coverage == "unknown"
    assert job.runs is None
    assert "source_conflict" in job.uncertainty


def test_aggregate_disjoint_windows_sum() -> None:
    r = combine_job_aggregates(
        [
            agg(
                [agg_row("42", 10, 2)],
                start="2026-09-01",
                end="2026-09-15",
                evidence_id="a",
            ),
            agg(
                [agg_row("42", 10, 3)],
                start="2026-09-16",
                end="2026-09-30",
                evidence_id="b",
            ),
        ],
        interval_start=START,
        interval_end=END,
    )
    job = only(r)
    assert (job.runs, job.failed_runs) == (20, 5)
    assert job.uncertainty == ("per_job_cap_25",)
