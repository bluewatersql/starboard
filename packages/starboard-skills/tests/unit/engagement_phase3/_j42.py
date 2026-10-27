"""The synthetic J-42 fixture (spec §H): job ``42`` in workspace ``123``.

Windows (inclusive dates):

* baseline 2026-08-09..2026-09-07: job 42 fails 1 of 100 runs;
* current 2026-09-08..2026-10-07, verified as two job-filtered slices
  s1 = 09-08..09-22 and s2 = 09-23..10-07: job 42 fails 8 of 100 runs;
* recovery 2026-10-08..2026-11-06 (30 days, like every other window: a different
  window length is `window_mismatch`): job 42 fails 1 of 100 runs again, all on 10-08.

``TODAY`` (2026-10-08) is the injected reconstruction clock: a run whose last period
ends on it is excluded as possibly incomplete.

The current slices hold the edge cases of D3-18:

* ``r2000``: periods on both sides of the s1/s2 boundary; s1 sees a preliminary
  ``FAILED`` (a repaired run), s2 its final ``SUCCESS``: counts once, as a success;
* ``r2001``: s1 sees it running (no state), s2 sees it ``FAILED``: counts once, failed;
* ``r3000``: still in flight (no final state): excluded;
* ``r3001``: last period ends on ``TODAY``: excluded.

The failed runs cycle through every ``FAILED_STATES`` literal.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

ACCOUNT = "001ABC"
WS = "123"
JOB = "42"
TODAY = date(2026, 10, 8)

BASELINE = ("2026-08-09", "2026-09-07")
CURRENT = ("2026-09-08", "2026-10-07")
S1 = ("2026-09-08", "2026-09-22")
S2 = ("2026-09-23", "2026-10-07")
RECOVERY = ("2026-10-08", "2026-11-06")
#: An interval older than the baseline, uploaded after it (E17 late upload).
LATE_OLDER = ("2026-07-10", "2026-08-08")

RUN_COLUMNS = (
    "workspace_id",
    "job_id",
    "run_id",
    "result_state",
    "trigger_type",
    "first_period_start",
    "last_period_end",
)
FAILED_CYCLE = ("FAILED", "ERROR", "TIMED_OUT", "TIMEDOUT")
#: Governance evidence queries of the seed rules (portfolio_readiness + uc packs).
GOVERNANCE_QUERIES = ("C-B01", "C-J01", "PO-01")

TRACE_OOM = (
    "org.apache.spark.SparkException: Job aborted.\n"
    "Caused by: java.lang.OutOfMemoryError: Java heap space\n"
    "\tat org.apache.spark.sql.execution.Exchange.doExecute(Exchange.scala:91)\n"
)
TRACE_TABLE = (
    "pyspark.errors.exceptions.captured.AnalysisException: [TABLE_OR_VIEW_NOT_FOUND] "
    "The table or view `main`.`sales`.`orders` cannot be found.\n"
    "\tat org.apache.spark.sql.catalyst.analysis.CheckAnalysis.failAnalysis(CheckAnalysis.scala:52)\n"
)


def run_row(run_id: int, state: str | None, first: str, last: str) -> dict[str, Any]:
    """One ``vt-job-run-states`` row (one run of job 42)."""
    return {
        "workspace_id": WS,
        "job_id": JOB,
        "run_id": str(run_id),
        "result_state": state,
        "trigger_type": "PERIODIC",
        "first_period_start": first,
        "last_period_end": last,
    }


def _day(start: str, offset: int) -> date:
    return date.fromisoformat(start) + timedelta(days=offset)


def _runs(
    first_id: int, window: tuple[str, str], states: list[str]
) -> list[dict[str, Any]]:
    """Runs spread over ``window`` (each ends at 02:00, started at 01:00)."""
    days = (date.fromisoformat(window[1]) - date.fromisoformat(window[0])).days + 1
    rows = []
    for i, state in enumerate(states):
        day = _day(window[0], i % days).isoformat()
        rows.append(run_row(first_id + i, state, f"{day}T01:00:00", f"{day}T02:00:00"))
    return rows


def _states(success: int, failed: int, cancelled: int) -> list[str]:
    out = ["SUCCESS"] * success
    out += [FAILED_CYCLE[i % len(FAILED_CYCLE)] for i in range(failed)]
    out += ["CANCELLED"] * cancelled
    return out


# --------------------------------------------------------------------------- #
# Verify slices
# --------------------------------------------------------------------------- #
def baseline_rows() -> list[dict[str, Any]]:
    """Baseline: 99 SUCCESS + 1 FAILED."""
    return _runs(100, BASELINE, _states(99, 1, 0))


def s1_rows() -> list[dict[str, Any]]:
    """s1: 45 SUCCESS + 4 failed + 1 CANCELLED, plus the preliminary r2000/r2001 rows."""
    return [
        *_runs(1000, S1, _states(45, 4, 1)),
        run_row(2000, "FAILED", "2026-09-22T22:00:00", "2026-09-22T23:30:00"),
        run_row(2001, None, "2026-09-22T19:00:00", "2026-09-22T20:00:00"),
    ]


def s2_rows() -> list[dict[str, Any]]:
    """s2: 44 SUCCESS + 3 failed + 1 CANCELLED, plus r2000/r2001 final and r3000/r3001."""
    return [
        *_runs(1100, S2, _states(44, 3, 1)),
        run_row(2000, "SUCCESS", "2026-09-22T22:00:00", "2026-09-23T00:30:00"),
        run_row(2001, "FAILED", "2026-09-22T19:00:00", "2026-09-23T03:00:00"),
        run_row(3000, None, "2026-10-06T22:00:00", "2026-10-06T23:00:00"),
        run_row(3001, "FAILED", "2026-10-07T23:00:00", "2026-10-08T01:00:00"),
    ]


def conflicting_copy() -> list[dict[str, Any]]:
    """s2 with one changed final state at the same ``last_period_end`` (a conflict)."""
    rows = s2_rows()
    first_success = next(
        i for i, r in enumerate(rows) if r["result_state"] == "SUCCESS"
    )
    rows[first_success] = {**rows[first_success], "result_state": "FAILED"}
    return rows


def superseding_copy() -> list[dict[str, Any]]:
    """s2 where one run has a later ``last_period_end`` (and a final state)."""
    rows = s2_rows()
    first_success = next(
        i for i, r in enumerate(rows) if r["result_state"] == "SUCCESS"
    )
    row = rows[first_success]
    rows[first_success] = {
        **row,
        "last_period_end": row["last_period_end"][:11] + "03:30:00",
    }
    return rows


def recovery_rows() -> list[dict[str, Any]]:
    """Recovery day: 99 SUCCESS + 1 FAILED, all ending on 10-08."""
    return _runs(5000, (RECOVERY[0], RECOVERY[0]), _states(99, 1, 0))


def late_older_rows() -> list[dict[str, Any]]:
    """The late-uploaded older interval: 98 SUCCESS + 2 FAILED."""
    return _runs(7000, LATE_OLDER, _states(98, 2, 0))


# --------------------------------------------------------------------------- #
# Discovery facts and the review manifest
# --------------------------------------------------------------------------- #
def _q(query_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "status": "succeeded",
        "error": None,
        "rows": rows,
        "truncated": False,
    }


def facts(
    window: tuple[str, str],
    *,
    f06: tuple[int, int, int] | None,
    f12: list[tuple[str, int, int, int]] | None,
) -> dict[str, Any]:
    """``data.facts`` for ``window`` (``build_facts`` over synthetic F-xx rows)."""
    from starboard_x.discovery._facts import build_facts

    start, end = window
    queries = [
        _q(
            "F-01",
            [
                {
                    "workspace_id": WS,
                    "billing_origin_product": p,
                    "usage_unit": "DBU",
                    "window_start": start,
                    "window_end": end,
                    "usage_quantity": v,
                }
                for p, v in (("JOBS", 600), ("SQL", 300), ("DLT", 100))
            ],
        ),
        _q(
            "F-04",
            [
                {
                    "workspace_id": WS,
                    "job_id": str(i),
                    "job_name": f"job-{i}",
                    "dbus": 100 - i,
                    "job_rank": i,
                }
                for i in range(1, 13)
            ],
        ),
        _q(
            "F-07",
            [
                {
                    "workspace_id": WS,
                    "billing_origin_product": "JOBS",
                    "performance_target": "PERFORMANCE_OPTIMIZED",
                    "dbus": 300,
                },
                {
                    "workspace_id": WS,
                    "billing_origin_product": "DLT",
                    "performance_target": "STANDARD",
                    "dbus": 100,
                },
            ],
        ),
    ]
    if f06 is not None:
        runs, failed, cancelled = f06
        queries.append(
            _q(
                "F-06",
                [
                    {
                        "workspace_id": WS,
                        "runs": runs,
                        "failed_runs": failed,
                        "cancelled_runs": cancelled,
                        "window_start": start,
                        "window_end": end,
                    }
                ],
            )
        )
    if f12 is not None:
        queries.append(
            _q(
                "F-12",
                [
                    {
                        "workspace_id": WS,
                        "job_id": job,
                        "runs": runs,
                        "failed_runs": failed,
                        "cancelled_runs": cancelled,
                        "window_start": start,
                        "window_end": end,
                    }
                    for job, runs, failed, cancelled in f12
                ],
            )
        )
    out = build_facts(queries, today=date.fromisoformat(end) + timedelta(days=1))
    out["window"] = {**out["window"], "start": start, "end": end}
    return out


def baseline_facts() -> dict[str, Any]:
    return facts(BASELINE, f06=(480, 6, 0), f12=[(JOB, 100, 1, 0)])


def current_facts() -> dict[str, Any]:
    return facts(CURRENT, f06=(500, 12, 0), f12=[(JOB, 100, 8, 2)])


def recovery_facts(*, per_job: bool = True) -> dict[str, Any]:
    """Recovery facts; ``per_job=False`` drops F-12 (the E7 missing-current input)."""
    return facts(RECOVERY, f06=(500, 5, 0), f12=[(JOB, 100, 1, 0)] if per_job else None)


def late_older_facts() -> dict[str, Any]:
    return facts(LATE_OLDER, f06=(470, 7, 0), f12=[(JOB, 100, 2, 0)])


def empty_facts(window: tuple[str, str] = CURRENT) -> dict[str, Any]:
    """Facts with every source unavailable (the E8 all-unknown input)."""
    from starboard_x.discovery._facts import build_facts

    out = build_facts([], today=date.fromisoformat(window[1]) + timedelta(days=1))
    out["window"] = {**out["window"], "start": window[0], "end": window[1]}
    return out


def review_manifest(run_date: str = "2026-10-08") -> dict[str, Any]:
    """A clean review manifest whose governance evidence queries were unavailable."""
    return {
        "snapshot_version": "2.0",
        "run_date": run_date,
        "workspace": "acme-prod",
        "workspace_id": WS,
        "lookback_days": 30,
        "findings": [],
        "degraded": False,
        "unavailable_queries": list(GOVERNANCE_QUERIES),
    }


def degraded_manifest(run_date: str = "2026-10-08") -> dict[str, Any]:
    """Every rule's evidence query and every review domain unavailable."""
    from starboard_core.domain.rules.registry import RuleRegistry

    reg = RuleRegistry.from_seed()
    queries = sorted({r.evidence_query for r in reg.rules if r.evidence_query})
    return {
        **review_manifest(run_date),
        "degraded": True,
        "unavailable_queries": queries,
        "unavailable_domains": list(reg.domains),
    }


def finding_id_j42() -> str:
    """The expected J-42 finding id (``job_failure_rise`` on job 42)."""
    from starboard_core.engagement.records import concern_key, finding_id

    return finding_id(concern_key(ACCOUNT, WS, "job", JOB, "job_failure_rise"))
