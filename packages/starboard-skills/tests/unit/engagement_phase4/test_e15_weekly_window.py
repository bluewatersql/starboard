"""E15 weekly cadence: two ``health_check`` runs 7 days apart (arch H1(a)).

``starboard --discover --lookback-days 7`` renders the facts pack (F-01..F-12)
over a 7-day window, and ``build_facts`` reports ``window.days`` from F-01's
server-side bounds. ``engagement analyze`` runs without ``--interval-*``, so it
takes the reporting interval from the facts window. The facts, manifest and
rule-coverage families must all carry that one interval. The second run compares
to the first: no ``interval_overlap`` rejection and no false week-over-week
change on identical evidence. As a control, two trailing-30-day windows taken
7 days apart overlap and are not compared.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import pytest
from starboard_core.engagement.observations import FINDINGS_METHOD

from . import _fixtures
from ._support import (
    FACTS,
    MANIFEST,
    Ctx,
    Run,
    commit,
    engagement_ok,
    new_run,
    records,
    write,
)

WEEK1 = ("2026-09-26", "2026-10-02")
WEEK2 = ("2026-10-03", "2026-10-09")
MONTH1 = ("2026-09-03", "2026-10-02")
MONTH2 = ("2026-09-10", "2026-10-09")

FINDING = {
    "id": "W-IDLE::wh-1",
    "composite_key": "W-IDLE::wh-1",
    "rule_id": "W-IDLE",
    "entity_id": "wh-1",
    "category": "warehouse",
    "severity": "medium",
    "score": 1.0,
    "evidence_dbu_estimate": 12.0,
}
FACTS_METHOD = "family_observations_v1"
RULE_COVERAGE_METRICS = {"rules_evaluated", "active_rule_findings"}


def _facts(window: tuple[str, str]) -> dict[str, Any]:
    return _fixtures.facts(window, f06=(120, 3, 0), f12=[(_fixtures.JOB, 25, 1, 0)])


def _run(ctx: Ctx, window: tuple[str, str], days: int) -> tuple[Run, dict[str, Any]]:
    """A ``health_check`` run on ``window``, analyzed without ``--interval-*``."""
    run = new_run(ctx, task="health_check")
    review = {
        **_fixtures.review_manifest(window[1]),
        "lookback_days": days,
        "findings": [FINDING],
    }
    write(ctx, run, {FACTS: _facts(window), MANIFEST: review})
    data = engagement_ok(
        ctx, run, "analyze", *run.flags(), "--manifest", MANIFEST, "--facts", FACTS
    )
    commit(ctx, run)
    return run, data


def _intervals(observations: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(o["interval_start"], o["interval_end"]) for o in observations}


@pytest.mark.parametrize("lookback, window", [(7, WEEK1), (30, MONTH1)])
def test_facts_window_comes_from_the_rendered_pack(
    lookback: int, window: tuple[str, str]
) -> None:
    """The real F-01 render at ``--lookback-days`` bounds the window ``build_facts``
    reports, so analyze's interval is the pack's, not a modelled one."""
    from starboard.discovery.executor import make_render
    from starboard.discovery.query_packs.facts import F_01_SQL

    sql = make_render(lookback, 50)(F_01_SQL)
    lower = re.search(
        r"DATEADD\(DAY, -(\d+), CURRENT_DATE\(\)\)\s+AS window_start", sql
    )
    upper = re.search(r"DATEADD\(DAY, -(\d+), CURRENT_DATE\(\)\)\s+AS window_end", sql)
    assert lower and upper, sql
    assert f"usage_date >= DATEADD(DAY, -{lookback}, CURRENT_DATE())" in sql
    assert "usage_date < CURRENT_DATE()" in sql
    # Evaluate the rendered bounds as the warehouse would on the day after the window.
    today = date.fromisoformat(window[1]) + timedelta(days=1)
    served = (
        (today - timedelta(days=int(lower.group(1)))).isoformat(),
        (today - timedelta(days=int(upper.group(1)))).isoformat(),
    )
    assert served == window
    assert _facts(served)["window"] == {
        "start": window[0],
        "end": window[1],
        "days": lookback,
        "label": f"trailing {lookback} full days (excludes today)",
    }


def test_weekly_runs_compare_week_over_week(ctx: Ctx) -> None:
    first, d1 = _run(ctx, WEEK1, 7)
    second, d2 = _run(ctx, WEEK2, 7)
    assert d1["interval"] == {"start": WEEK1[0], "end": WEEK1[1]}
    assert d2["interval"] == {"start": WEEK2[0], "end": WEEK2[1]}
    r1, r2 = records(ctx, first), records(ctx, second)

    for recs, week in ((r1, WEEK1), (r2, WEEK2)):
        obs = recs.observations
        methods = {o["method_version"] for o in obs}
        assert {FACTS_METHOD, FINDINGS_METHOD} <= methods, methods
        assert {o["metric"] for o in obs} >= RULE_COVERAGE_METRICS
        assert _intervals(obs) == {week}

    recs_ids = {o["observation_id"] for o in r1.observations}
    assert recs_ids
    sel = r2.baselines
    reasons = {r["reason"] for r in sel["rejected"]}
    assert "interval_overlap" not in reasons, reasons
    comparisons = {e["comparison"] for e in sel["selected"]}
    assert comparisons <= {"continuing", "no_prior_measurement"}, comparisons
    compared = [e for e in sel["selected"] if e["comparison"] == "continuing"]
    assert compared and all(e["baseline_observation_id"] in recs_ids for e in compared)
    present = next(o for o in r2.observations if o["method_version"] == FINDINGS_METHOD)
    assert any(
        e["current_observation_id"] == present["observation_id"] for e in compared
    )

    assert d2["comparisons"].get("new", 0) == d2["comparisons"].get("recovered", 0) == 0
    for change in r2.changes:
        assert (
            change["baseline_interval_start"],
            change["baseline_interval_end"],
        ) == WEEK1
        assert (
            change["current_interval_start"],
            change["current_interval_end"],
        ) == WEEK2
        assert change["current_value"] == change["baseline_value"], change["change_id"]


def test_trailing_month_windows_seven_days_apart_are_not_compared(ctx: Ctx) -> None:
    _run(ctx, MONTH1, 30)
    second, data = _run(ctx, MONTH2, 30)
    sel = records(ctx, second).baselines
    assert "interval_overlap" in {r["reason"] for r in sel["rejected"]}
    assert "continuing" not in {e["comparison"] for e in sel["selected"]}
    assert data["comparisons"].get("not_comparable", 0) > 0
