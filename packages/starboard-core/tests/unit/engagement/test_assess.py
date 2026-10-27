# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the single run pipeline ``assess_run`` (WP3-10, D3-25)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest
from starboard_core.engagement import assess as assess_mod
from starboard_core.engagement import history
from starboard_core.engagement.assess import CurrentInputs, RunAssessment, assess_run
from starboard_core.engagement.cases import open_case, revise
from starboard_core.engagement.history import Candidate
from starboard_core.engagement.jobruns import RunSlice
from starboard_core.engagement.prior import PriorRecords, Unavailable
from starboard_core.engagement.records import (
    FindingRecord,
    concern_key,
    finding_id,
    registration_id,
)

pytestmark = pytest.mark.unit

ACCOUNT = "AR-000000001"
WS = "123"
JOB = "42"
BASE_RUN = "20260908_12345678-1234-4234-8234-123456789abc"
J42_RUN = "20261008_12345678-1234-4234-8234-123456789abc"
NEXT_RUN = "20261107_12345678-1234-4234-8234-123456789abc"
RECOVERY_RUN = "20261009_12345678-1234-4234-8234-123456789abc"
CASE_RUN = "20261001_22345678-1234-4234-8234-123456789abc"
TROUBLE_RUN = "20261008_32345678-1234-4234-8234-123456789abc"
LATE_RUN = "20261002_42345678-1234-4234-8234-123456789abc"

BASELINE = ("2026-08-09", "2026-09-07")
CURRENT = ("2026-09-08", "2026-10-07")
S1 = ("2026-09-08", "2026-09-22")
S2 = ("2026-09-23", "2026-10-07")
NEXT = ("2026-10-08", "2026-11-06")
# Same 30-day window length as CURRENT: other lengths are window_mismatch.
RECOVERY = ("2026-10-08", "2026-11-06")
LATE_OLDER = ("2026-07-10", "2026-08-08")

EV_BASE = "ev_" + "1" * 24
EV_S1 = "ev_" + "2" * 24
EV_S2 = "ev_" + "3" * 24
EV_NEXT = "ev_" + "4" * 24
EV_LATE = "ev_" + "5" * 24
FID = finding_id(concern_key(ACCOUNT, WS, "job", JOB, "job_failure_rise"))


# ---- fixtures ------------------------------------------------------------------------


def rows(first: int, window: tuple[str, str], success: int, failed: int) -> list[Any]:
    """``vt-job-run-states`` rows for job 42 spread over ``window``."""
    start = datetime.fromisoformat(window[0])
    days = (datetime.fromisoformat(window[1]) - start).days + 1
    out = []
    for i, state in enumerate(["SUCCESS"] * success + ["FAILED"] * failed):
        day = (start.date().toordinal() + i % days, i)
        stamp = datetime.fromordinal(day[0]).date().isoformat()
        out.append(
            {
                "workspace_id": WS,
                "job_id": JOB,
                "run_id": str(first + i),
                "result_state": state,
                "first_period_start": f"{stamp}T01:00:00",
                "last_period_end": f"{stamp}T02:00:00",
            }
        )
    return out


def slice_of(
    window: tuple[str, str],
    data: list[Any],
    evidence: str,
    source_kind: str = "customer_workspace",
) -> RunSlice:
    return RunSlice(
        source_kind=source_kind,
        window_start=window[0],
        window_end=window[1],
        job_ids=(JOB,),
        evidence_id=evidence,
        rows=tuple(data),
        workspace_id=WS,
    )


def inputs(*slices: RunSlice, **over: Any) -> CurrentInputs:
    base: dict[str, Any] = {
        "facts": None,
        "manifest": None,
        "verify_slices": slices,
        "case_evidence": (),
        "observations": (),
    }
    base.update(over)
    return CurrentInputs(**base)


def assess(
    prior: PriorRecords,
    current: CurrentInputs,
    run_id: str,
    interval: tuple[str, str],
    today: str,
) -> RunAssessment:
    return assess_run(
        prior,
        current,
        run_id=run_id,
        account_key=ACCOUNT,
        workspace_id=WS,
        interval=interval,
        today=today,
    )


def as_prior(
    *runs: RunAssessment,
    findings: tuple[FindingRecord, ...] = (),
    cases: tuple[Any, ...] = (),
    unavailable: tuple[Unavailable, ...] = (),
) -> PriorRecords:
    """What ``load_prior`` returns for ``runs``: latest finding / action copy each."""
    by_key: dict[str, FindingRecord] = {}
    for f in (*(f for r in runs for f in r.findings), *findings):
        held = by_key.get(f.finding_key)
        if held is None or f.revision >= held.revision:
            by_key[f.finding_key] = f
    actions: dict[str, Any] = {}
    for a in (a for r in runs for a in r.actions):
        if a.action_id not in actions or len(a.events) >= len(
            actions[a.action_id].events
        ):
            actions[a.action_id] = a
    return PriorRecords(
        observations=tuple(
            Candidate(o, 1, registration_id(r.baseline_selection.run_id))
            for r in runs
            for o in r.observations
        ),
        findings=tuple(by_key.values()),
        cases=(*(c for r in runs for c in r.cases), *cases),
        actions=tuple(actions.values()),
        unavailable=unavailable,
    )


def baseline_run() -> RunAssessment:
    return assess(
        PriorRecords(),
        inputs(slice_of(BASELINE, rows(100, BASELINE, 99, 1), EV_BASE)),
        BASE_RUN,
        BASELINE,
        "2026-09-08",
    )


def j42_inputs() -> CurrentInputs:
    return inputs(
        slice_of(S1, rows(1000, S1, 46, 4), EV_S1),
        slice_of(S2, rows(1100, S2, 46, 4), EV_S2),
    )


def j42_run(prior: PriorRecords | None = None) -> RunAssessment:
    if prior is None:
        prior = as_prior(baseline_run())
    return assess(prior, j42_inputs(), J42_RUN, CURRENT, "2026-10-08")


def rate_change(result: RunAssessment) -> Any:
    (change,) = [c for c in result.changes if c.metric == "job_failure_rate_pct"]
    return change


def non_acquire(result: RunAssessment) -> list[Any]:
    return [p for p in result.plays if p.play_code != "acquire_family_evidence"]


# ---- J-42 (E2 / E4) -------------------------------------------------------------------


def test_j42_gives_serious_finding_change_health_play_and_action() -> None:
    base = baseline_run()
    assert base.findings == () and base.actions == ()
    result = j42_run(as_prior(base))

    (finding,) = result.findings
    assert finding.finding_id == FID
    assert (finding.state, finding.severity, finding.revision) == (
        "active",
        "serious",
        1,
    )
    assert finding.symptom_confidence == "confirmed"

    change = rate_change(result)
    assert (change.baseline_value, change.current_value) == (1.0, 8.0)
    assert change.delta == pytest.approx(7.0) and change.delta_unit == "pp"
    assert {(s[:10], e[:10]) for s, e, _ in change.source_windows} == {S1, S2}
    assert {k for _, _, k in change.source_windows} == {"customer_workspace"}

    (entry,) = [
        e
        for e in result.baseline_selection.selected
        if e["current_observation_id"] == change.observation_id
    ]
    (base_rate,) = [
        o
        for o in base.observations
        if o.observation_id == entry["baseline_observation_id"]
    ]
    assert base_rate.run_id == BASE_RUN and entry["comparison"] == "continuing"

    rel = next(f for f in result.health.families if f.family == "reliability")
    # Run-level slices alone lack the required F-06 workspace metrics.
    assert (rel.assessment, rel.coverage, rel.severity) == (
        "assessed",
        "partial",
        "serious",
    )
    assert result.health.verdict == "health_read"

    (play,) = non_acquire(result)
    assert play.play_code == "job_reliability_session"
    assert "1.0% → 8.0% (+7.0 pp)" in play.reason

    (action,) = result.actions
    assert (action.finding_id, action.play_id) == (FID, play.play_id)
    assert (action.proposal_state, action.acceptance_state) == ("proposed", "pending")
    assert action.events[0].recorded_by == "rule"
    assert finding.action_ids == (action.action_id,)


def test_facts_and_slices_together_give_complete_reliability() -> None:
    facts = {
        "window": {"start": CURRENT[0], "end": CURRENT[1]},
        "job_reliability": {
            "runs": 100,
            "failed_runs": 8,
            "cancelled_runs": 0,
            "failure_rate_pct": 8.0,
        },
    }
    result = assess(
        as_prior(baseline_run()),
        replace(j42_inputs(), facts=facts, evidence_ids=(EV_S1,)),
        J42_RUN,
        CURRENT,
        "2026-10-08",
    )
    rel = next(f for f in result.health.families if f.family == "reliability")
    assert (rel.coverage, rel.severity) == ("complete", "serious")
    assert FID in {f.finding_id for f in result.findings}


def test_flags_are_part_of_the_run_observations() -> None:
    result = j42_run()
    flags = [o for o in result.observations if o.metric == "job_failure_concern"]
    assert len(flags) == 1 and flags[0].value == 1.0
    assert {o.run_id for o in result.observations} == {J42_RUN}


def test_superseded_f12_aggregate_is_a_co_movement() -> None:
    from starboard_core.engagement.dedupe import job_aggregate_dedupe_key

    result = j42_run()
    rate = next(o for o in result.observations if o.metric == "job_failure_rate_pct")
    aggregate = replace(
        rate,
        value=9.0,
        dedupe_key=job_aggregate_dedupe_key(WS, JOB, *CURRENT, rate.method_version),
    )
    again = assess(
        as_prior(baseline_run()),
        replace(j42_inputs(), observations=(aggregate,)),
        J42_RUN,
        CURRENT,
        "2026-10-08",
    )
    rate_obs = next(
        o for o in again.observations if o.observation_id == rate.observation_id
    )
    assert rate_obs.value == 8.0
    assert any(
        m.get("observation_id") == rate.observation_id
        for m in rate_change(again).co_movements
    )


# ---- recovery and missing current (E6 / E7 / E8) ---------------------------------------


def test_recovery_gives_recovered_improved_not_established() -> None:
    base = baseline_run()
    j42 = j42_run(as_prior(base))
    result = assess(
        as_prior(base, j42),
        inputs(slice_of(RECOVERY, rows(5000, RECOVERY, 99, 1), EV_NEXT)),
        RECOVERY_RUN,
        RECOVERY,
        "2026-11-07",
    )
    (finding,) = result.findings
    assert (finding.finding_id, finding.state, finding.severity) == (
        FID,
        "recovered",
        "none",
    )
    (action,) = result.actions
    assert action.action_id == j42.actions[0].action_id
    assert (action.outcome_state, action.acceptance_state, action.attribution) == (
        "improved",
        "pending",
        "not_established",
    )
    assert action.events[-1].kind == "outcome_observed"
    change = rate_change(result)
    assert change.observation_id in action.outcome_observation_ids
    assert (change.baseline_value, change.current_value) == (8.0, 1.0)
    assert change.causality == "not_assessed"
    assert non_acquire(result) == []


def test_missing_current_gives_unknown_current_and_unknown_outcome() -> None:
    base = baseline_run()
    j42 = j42_run(as_prior(base))
    result = assess(as_prior(base, j42), inputs(), RECOVERY_RUN, RECOVERY, "2026-10-09")
    (finding,) = result.findings
    assert (finding.state, finding.severity, finding.last_confirmed_severity) == (
        "unknown_current",
        None,
        "serious",
    )
    (action,) = result.actions
    assert action.outcome_state == "unknown"
    # Spec E7: the open job's per-job metric is an explicit unknown, not absent.
    key = ("job", JOB, "job_failure_rate_pct")
    (rate,) = [
        o for o in result.observations if (o.entity_kind, o.entity_id, o.metric) == key
    ]
    assert (rate.state, rate.value) == ("unknown", None)
    assert rate.unknown_reason == "missing_source:vt-job-run-states"
    assert result.health.verdict == "insufficient_evidence"


def test_overlapping_recur_observes_no_action_outcome() -> None:
    j42 = j42_run()
    overlap = ("2026-09-20", "2026-10-19")
    result = assess(
        as_prior(j42),
        inputs(slice_of(overlap, rows(2000, overlap, 92, 8), EV_NEXT)),
        NEXT_RUN,
        overlap,
        "2026-10-20",
    )
    selection = result.baseline_selection
    assert not any(e["baseline_observation_id"] for e in selection.selected)
    assert history.selection_reason(selection) == "interval_overlap"
    (carried,) = [a for a in result.actions if a.action_id == j42.actions[0].action_id]
    assert carried.outcome_state == "not_observed"
    assert "outcome_observed" not in [e.kind for e in carried.events]


def test_no_inputs_give_insufficient_evidence() -> None:
    result = assess(PriorRecords(), inputs(), J42_RUN, CURRENT, "2026-10-08")
    assert result.health.verdict == "insufficient_evidence"
    assert result.health.assessed_count == 0
    assert result.findings == () and result.actions == () and result.changes == ()


# ---- cross-folder continuity (E17) ------------------------------------------------------


def test_case_revision_is_carried_and_superseded_action_withdrawn() -> None:
    base = baseline_run()
    j42 = j42_run(as_prior(base))
    (finding,) = j42.findings
    case, _ = open_case(
        account_key=ACCOUNT,
        workspace_id=WS,
        origin="finding",
        origin_ref=finding.finding_id,
        question="why did job 42 start failing?",
        run_id=TROUBLE_RUN,
        finding=finding,
    )
    case, revised = revise(
        case, finding, run_id=TROUBLE_RUN, observations=(), evidence_ids=(), gaps=()
    )
    assert revised.revision == 2

    result = assess(
        as_prior(base, j42, findings=(revised,), cases=(case,)),
        inputs(slice_of(NEXT, rows(6000, NEXT, 91, 9), EV_NEXT)),
        NEXT_RUN,
        NEXT,
        "2026-11-07",
    )
    (again,) = result.findings
    assert (again.finding_id, again.episode_id) == (FID, finding.episode_id)
    assert again.revision == 3
    assert again.revisions[1].reason == "investigated"
    assert case.case_id in again.case_ids
    carried = next(a for a in result.actions if a.action_id == j42.actions[0].action_id)
    # The watch read now calls for an investigation: the session action's outcome
    # is measured, then the rule withdraws it as superseded (same episode).
    assert [e.kind for e in carried.events[-2:]] == ["outcome_observed", "withdrawn"]
    assert carried.events[-1].recorded_by == "rule"
    (fresh,) = [a for a in result.actions if a.proposal_state == "proposed"]
    assert fresh.play_id != carried.play_id and fresh.finding_id == FID
    assert result.cases == (case,)


def test_standalone_case_finding_is_linked_not_carried() -> None:
    base = baseline_run()
    case, created = open_case(
        account_key=ACCOUNT,
        workspace_id=WS,
        origin="clue",
        origin_ref=f"job:{JOB}",
        question="nightly load fails",
        run_id=CASE_RUN,
    )
    assert created is not None and created.concern_code == "case:job"
    result = j42_run(as_prior(base, findings=(created,), cases=(case,)))
    (finding,) = result.findings
    assert finding.finding_id == FID
    assert finding.possible_links == (created.finding_id,)
    assert result.cases == (case,)


def test_unreadable_registry_gives_history_unavailable_not_continuing() -> None:
    gone = Unavailable(registration=None, object_id="registry-folder", reason="gone")
    result = j42_run(PriorRecords(unavailable=(gone,)))
    comparisons = {e["comparison"] for e in result.baseline_selection.selected}
    assert "continuing" not in comparisons
    rate = rate_change_absent(result)
    assert rate == "history_unavailable"
    assert (
        result.baseline_selection.unavailable[0]["registration_id"] == "registry-folder"
    )
    (finding,) = result.findings
    assert finding.severity == "watch" and finding.revision == 1


def rate_change_absent(result: RunAssessment) -> str:
    assert [c for c in result.changes if c.metric == "job_failure_rate_pct"] == []
    rate = next(o for o in result.observations if o.metric == "job_failure_rate_pct")
    (entry,) = [
        e
        for e in result.baseline_selection.selected
        if e["current_observation_id"] == rate.observation_id
    ]
    return str(entry["comparison"])


def test_imported_local_unavailable_records_do_not_hide_baselines() -> None:
    base = baseline_run()
    imp = Unavailable(
        registration=None,
        object_id="reg_imp_" + "c" * 24,
        reason="imported_local carries observations only",
        records=("findings", "cases", "actions"),
    )
    result = j42_run(replace(as_prior(base), unavailable=(imp,)))
    assert rate_change(result).baseline_value == 1.0
    assert result.baseline_selection.unavailable == ()


def test_late_upload_of_an_older_interval_is_not_the_baseline() -> None:
    base = baseline_run()
    late = assess(
        PriorRecords(),
        inputs(slice_of(LATE_OLDER, rows(7000, LATE_OLDER, 98, 2), EV_LATE)),
        LATE_RUN,
        LATE_OLDER,
        "2026-08-09",
    )
    late = replace(
        late,
        observations=tuple(
            replace(o, as_of="2026-10-01T00:00:00+00:00") for o in late.observations
        ),
    )
    result = j42_run(as_prior(base, late))
    change = rate_change(result)
    assert change.baseline_value == 1.0
    assert change.baseline_interval_start == BASELINE[0]


# ---- determinism ------------------------------------------------------------------------


class _NoClock(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> Any:
        raise AssertionError("assess_run must not read the clock")


def test_deterministic_for_fixed_today_without_reading_the_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = as_prior(baseline_run())
    monkeypatch.setattr(history, "datetime", _NoClock)
    if hasattr(assess_mod, "datetime"):
        monkeypatch.setattr(assess_mod, "datetime", _NoClock)
    first = j42_run(prior)
    second = j42_run(prior)
    assert first == second
    assert first.baseline_selection.computed_at == "2026-10-08T00:00:00+00:00"
    assert first.actions[0].events[0].at == "2026-10-08T00:00:00+00:00"


def test_records_from_the_current_run_are_never_prior() -> None:
    first = j42_run()
    again = j42_run(as_prior(baseline_run(), first))
    assert again == first
