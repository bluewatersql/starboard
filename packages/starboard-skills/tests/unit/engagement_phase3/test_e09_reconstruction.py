"""E9: per-run reconstruction with an injected ``today``; one failure set everywhere (D3-18, D3-23)."""

from __future__ import annotations

import re
from pathlib import Path

from . import _j42

VERIFY_SQL = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "starboard"
    / "starboard-engagement"
    / "references"
    / "verify-sql.md"
)
_IN_LIST_RE = re.compile(r"IN \(((?:'[A-Z_]+'(?:, )?)+)\)")


def _slice(window, rows, evidence_id, *, limit_reached=False):
    from starboard_core.engagement.jobruns import RunSlice

    return RunSlice(
        "customer_workspace",
        window[0],
        window[1],
        (_j42.JOB,),
        evidence_id,
        rows,
        limit_reached=limit_reached,
    )


def _job(*slices):
    from starboard_core.engagement.jobruns import reconstruct_runs

    rec = reconstruct_runs(
        slices,
        interval_start=_j42.CURRENT[0],
        interval_end=_j42.CURRENT[1],
        today=_j42.TODAY,
    )
    jobs = [j for j in rec.jobs if j.job_id == _j42.JOB]
    assert len(jobs) == 1, rec.jobs
    return rec, jobs[0]


def _row(rows, run_id):
    return next(r for r in rows if r["run_id"] == str(run_id))


def test_boundary_repaired_in_flight_and_today_runs() -> None:
    rec, job = _job(
        _slice(_j42.S1, _j42.s1_rows(), "ev-s1"),
        _slice(_j42.S2, _j42.s2_rows(), "ev-s2"),
    )
    # r2000: preliminary FAILED in s1, final SUCCESS in s2 -> one success.
    # r2001: running in s1, FAILED in s2 -> one failure.
    # r3000: no terminal state -> in flight; r3001: ends on today -> excluded.
    assert (job.runs, job.failed_runs, job.cancelled_runs) == (100, 8, 2)
    assert job.failure_rate_pct == 8.0
    assert job.coverage == "complete"
    assert job.uncertainty == ()
    assert job.superseded_rows == 2
    assert rec.in_flight >= 1
    assert [tuple(w[:2]) for w in job.source_windows] == [_j42.S1, _j42.S2]

    # Without r2000's final row the repaired run would count as a failure.
    s2_partial = [r for r in _j42.s2_rows() if r["run_id"] != "2000"]
    _, unrepaired = _job(
        _slice(_j42.S1, _j42.s1_rows(), "ev-s1"), _slice(_j42.S2, s2_partial, "ev-s2")
    )
    assert unrepaired.failed_runs == 9 and unrepaired.runs == 100


def test_today_is_injected_not_read() -> None:
    from starboard_core.engagement.jobruns import reconstruct_runs

    rows = [*_j42.s2_rows()]
    assert _row(rows, 3001)["last_period_end"].startswith(_j42.TODAY.isoformat())
    slices = (_slice(_j42.S1, _j42.s1_rows(), "ev-s1"), _slice(_j42.S2, rows, "ev-s2"))
    later = reconstruct_runs(
        slices,
        interval_start=_j42.CURRENT[0],
        interval_end="2026-10-08",
        today=_j42.TODAY.replace(day=9),
    )
    job = next(j for j in later.jobs if j.job_id == _j42.JOB)
    # With a later clock and interval, r3001 (FAILED, ending 10-08) now counts.
    assert (job.runs, job.failed_runs) == (101, 9)


def test_limit_reached_is_partial() -> None:
    from starboard_core.engagement.jobruns import UNCERTAINTY_VERIFY_LIMIT

    _, job = _job(
        _slice(_j42.S1, _j42.s1_rows(), "ev-s1", limit_reached=True),
        _slice(_j42.S2, _j42.s2_rows(), "ev-s2"),
    )
    assert job.coverage == "partial"
    assert UNCERTAINTY_VERIFY_LIMIT in job.uncertainty


def test_gap_is_partial() -> None:
    _, job = _job(_slice(_j42.S2, _j42.s2_rows(), "ev-s2"))
    assert job.coverage == "partial"


def test_shared_run_summary_cte() -> None:
    from starboard.discovery.query_packs import facts

    def cte(sql: str) -> str:
        start = sql.index("run_summary AS (")
        depth = 0
        for i, ch in enumerate(sql[start:], start):
            depth += ch == "("
            depth -= ch == ")"
            if ch == ")" and depth == 0:
                return sql[start : i + 1]
        raise AssertionError("unterminated run_summary CTE")

    assert cte(facts.F_06_SQL) == cte(facts.F_12_SQL) == facts.RUN_SUMMARY_CTE
    by_id = {q.query_id: q for q in facts.FACTS_PACK.queries}
    assert by_id["F-06"].sql_template == facts.F_06_SQL
    assert by_id["F-12"].sql_template == facts.F_12_SQL


def _section(text: str, template: str) -> str:
    start = text.index(f"### {template}:")
    end = text.find("\n### ", start + 1)
    return text[start : end if end > 0 else None]


def _literal_sets(text: str) -> set[tuple[str, ...]]:
    return {
        tuple(s.strip("'") for s in m.group(1).split(", "))
        for m in _IN_LIST_RE.finditer(text)
        if "'FAILED'" in m.group(1)
    }


def test_one_failure_set_everywhere() -> None:
    from starboard.discovery.query_packs import facts
    from starboard_core.engagement.jobruns import FAILED_STATES

    expected = {tuple(FAILED_STATES)}
    assert _literal_sets(facts.F_06_SQL) == expected
    assert _literal_sets(facts.F_12_SQL) == expected

    text = VERIFY_SQL.read_text()
    assert _literal_sets(_section(text, "vt-job-runs")) == expected
    states = _section(text, "vt-job-run-states")
    prose = re.search(r"failed = `([A-Z_, ]+)`", states)
    assert prose is not None
    assert tuple(s.strip() for s in prose.group(1).split(",")) == tuple(FAILED_STATES)
    assert "LIMIT" not in states.split("```sql", 1)[1].split("```", 1)[0]


def test_reconstruction_equals_documented_counts() -> None:
    _, job = _job(
        _slice(_j42.S1, _j42.s1_rows(), "ev-s1"),
        _slice(_j42.S2, _j42.s2_rows(), "ev-s2"),
    )
    by_job = _j42.current_facts()["job_reliability_by_job"]
    documented = next(j for j in by_job["jobs"] if str(j["job_id"]) == _j42.JOB)
    assert (job.runs, job.failed_runs, job.cancelled_runs) == (
        documented["runs"],
        documented["failed_runs"],
        documented["cancelled_runs"],
    )
    assert job.failure_rate_pct == documented["failure_rate_pct"]
