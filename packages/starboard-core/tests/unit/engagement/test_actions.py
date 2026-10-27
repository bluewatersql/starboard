# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the Action lifecycle (WP3-7, D3-13)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from starboard_core.engagement.actions import (
    InvalidTransition,
    observe_outcomes,
    propose,
    propose_from_case,
    transition,
)
from starboard_core.engagement.cases import open_case, revise
from starboard_core.engagement.concerns import evaluate
from starboard_core.engagement.health import project
from starboard_core.engagement.history import finding_states
from starboard_core.engagement.plays import candidates
from starboard_core.engagement.records import (
    Action,
    FindingRecord,
    action_id,
    case_action_id,
    episode_id,
    play_id,
)

from .test_concerns import (
    CUR,
    INTERVAL,
    NOW,
    PRIOR,
    PRIOR_INTERVAL,
    job_triplet,
    prior,
    run,
    selection_for,
)

pytestmark = pytest.mark.unit

AT_PRIOR = "2026-09-23T00:00:00+00:00"


def _prior_run() -> tuple[Any, Any]:
    p_cur = job_triplet(100, 8, 8.0, maker=prior)
    result = evaluate(
        p_cur, selection_for(p_cur, [], run_id=PRIOR), [], run_id=PRIOR, baselines=[]
    )
    health = project(
        p_cur,
        result.findings,
        run_id=PRIOR,
        account_key="acme",
        workspace_id="123",
        interval=PRIOR_INTERVAL,
    )
    plays = candidates(
        result.findings, health, p_cur, run_id=PRIOR, interval=PRIOR_INTERVAL
    )
    return p_cur, result, plays


def proposed() -> Action:
    _, _, plays = _prior_run()
    (action,) = propose(plays, (), run_id=PRIOR, at=AT_PRIOR)
    return action


def current_findings(
    runs: Any, failed: Any, rate: Any
) -> tuple[tuple[FindingRecord, ...], Any]:
    p_cur, p_res, _ = _prior_run()
    cur = job_triplet(runs, failed, rate)
    c_res = run(cur, p_cur, p_res.findings)
    sel = selection_for([*cur, *c_res.flags], [*p_cur, *p_res.flags])
    return finding_states(p_res.findings, sel, c_res.findings), sel


def outcome(action: Action, runs: Any, failed: Any, rate: Any) -> Action:
    findings, sel = current_findings(runs, failed, rate)
    (out,) = observe_outcomes([action], findings, sel)
    return out


def step(action: Action, kind: str, **kw: Any) -> Action:
    kw.setdefault("recorded_by", "operator")
    return transition(action, kind, run_id=PRIOR, at=AT_PRIOR, **kw)


# ---- propose -----------------------------------------------------------------


def test_propose_one_pending_action_per_finding_play() -> None:
    _, result, plays = _prior_run()
    (action,) = propose(plays, (), run_id=PRIOR, at=AT_PRIOR)
    play = next(p for p in plays if p.finding_ids)
    fid = result.findings[0].finding_id
    assert action.action_id == action_id(fid, play.play_code, PRIOR)
    assert (action.finding_id, action.play_id, action.owner_role) == (
        fid,
        play.play_id,
        "job_owner",
    )
    assert (action.proposal_state, action.acceptance_state, action.execution_state) == (
        "proposed",
        "pending",
        "not_started",
    )
    assert (action.outcome_state, action.attribution) == (
        "not_observed",
        "not_established",
    )
    assert [(e.seq, e.kind, e.recorded_by) for e in action.events] == [
        (1, "proposed", "rule")
    ]
    assert action.next_step == play.reason


def test_acquisition_plays_get_no_action() -> None:
    _, _, plays = _prior_run()
    acquire = [p for p in plays if not p.finding_ids]
    assert acquire and propose(acquire, (), run_id=PRIOR, at=AT_PRIOR) == ()


def test_open_action_for_same_finding_and_play_is_kept() -> None:
    _, _, plays = _prior_run()
    existing = step(proposed(), "accepted")
    (kept,) = propose(plays, [existing], run_id=CUR, at=NOW)
    assert kept == existing


@pytest.mark.parametrize("closing", ["rejected", "withdrawn"])
def test_closed_action_allows_a_new_proposal(closing: str) -> None:
    _, _, plays = _prior_run()
    closed = step(proposed(), closing)
    (fresh,) = propose(plays, [closed], run_id=CUR, at=NOW)
    assert fresh.action_id != closed.action_id and fresh.acceptance_state == "pending"


def current_plays(runs: Any, failed: Any, rate: Any) -> tuple[Any, Any]:
    """The current run's findings and plays (the prior run's finding re-measured)."""
    p_cur, p_res, _ = _prior_run()
    cur = job_triplet(runs, failed, rate)
    c_res = run(cur, p_cur, p_res.findings)
    observations = [*cur, *c_res.flags]
    sel = selection_for(observations, [*p_cur, *p_res.flags])
    findings = finding_states(p_res.findings, sel, c_res.findings)
    health = project(
        observations,
        findings,
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
    )
    plays = candidates(findings, health, observations, run_id=CUR, interval=INTERVAL)
    return findings, plays


def test_open_action_of_a_superseded_play_is_withdrawn_by_rule() -> None:
    findings, plays = current_plays(100, 9, 9.0)
    (finding,) = findings
    other = {"job_reliability_session", "job_reliability_investigation"} - {
        plays[0].play_code
    }
    stale = replace(
        step(proposed(), "accepted"),
        play_id=play_id(other.pop(), finding.finding_id),
    )
    fresh, withdrawn = propose(plays, [stale], run_id=CUR, at=NOW, findings=findings)
    assert fresh.acceptance_state == "pending" and fresh.play_id != stale.play_id
    assert withdrawn.action_id == stale.action_id
    assert (withdrawn.proposal_state, withdrawn.run_id) == ("withdrawn", CUR)
    last = withdrawn.events[-1]
    assert (last.seq, last.kind, last.recorded_by, last.run_id) == (
        len(stale.events) + 1,
        "withdrawn",
        "rule",
        CUR,
    )
    assert last.note is not None and last.note.startswith("superseded")
    # An executed action is never withdrawn.
    done = replace(
        step(step(proposed(), "accepted"), "executed", executed_at="2026-09-22"),
        play_id=stale.play_id,
    )
    (only,) = propose(plays, [done], run_id=CUR, at=NOW, findings=findings)
    assert only.action_id != done.action_id


def _case_action(finding: FindingRecord, run_id: str = PRIOR) -> Action:
    case, _ = open_case(
        account_key="acme",
        workspace_id="123",
        origin="finding",
        origin_ref=finding.finding_id,
        question="why does it fail?",
        run_id=run_id,
        finding=finding,
    )
    case, _ = revise(
        case,
        finding,
        run_id=run_id,
        observations=(),
        evidence_ids=["ev_" + "a" * 24],
        gaps=(),
    )
    return propose_from_case(
        case,
        next_step="raise the cluster's driver memory",
        owner_role="job_owner",
        owner_label=None,
        verify_method="vt-job-run-states over the next 14 days",
        run_id=run_id,
        at=AT_PRIOR,
    )


def test_propose_from_case_is_a_host_case_origin_action() -> None:
    _, result, _ = _prior_run()
    finding = result.findings[0]
    action = _case_action(finding)
    assert (action.play_id, action.case_id is not None) == (None, True)
    assert action.action_id == case_action_id(
        action.case_id, finding.finding_id, "raise the cluster's driver memory"
    )
    assert action.action_id == _case_action(finding).action_id  # deterministic
    assert (action.acceptance_state, action.verify_method) == (
        "pending",
        "vt-job-run-states over the next 14 days",
    )
    (event,) = action.events
    assert (event.kind, event.recorded_by, event.evidence_ids) == (
        "proposed",
        "host",
        ("ev_" + "a" * 24,),
    )
    assert Action.from_dict(action.to_dict()) == action


def test_rule_proposals_never_withdraw_a_case_origin_action() -> None:
    findings, plays = current_plays(100, 9, 9.0)
    (finding,) = findings
    case_action = step(_case_action(finding), "accepted")
    out = propose(plays, [case_action], run_id=CUR, at=NOW, findings=findings)
    assert case_action.action_id not in {a.action_id for a in out}
    assert all(a.proposal_state == "proposed" for a in out)


def test_executed_and_observed_action_is_not_re_proposed_in_its_episode() -> None:
    findings, plays = current_plays(100, 9, 9.0)
    executed = step(step(proposed(), "accepted"), "executed", executed_at="2026-09-22")
    (observed,) = observe_outcomes([executed], findings, selection_for([], []))
    assert observed.outcome_state == "unchanged"
    (kept,) = propose(plays, [observed], run_id=CUR, at=NOW, findings=findings)
    assert kept == observed


def test_a_new_episode_gets_a_new_action_and_withdraws_the_old_one() -> None:
    findings, plays = current_plays(100, 9, 9.0)
    (finding,) = findings
    reopened = replace(
        finding,
        episode_started_run_id=CUR,
        episode_id=episode_id(finding.finding_id, CUR),
    )
    old = step(proposed(), "accepted")
    fresh, withdrawn = propose(plays, [old], run_id=CUR, at=NOW, findings=[reopened])
    assert fresh.action_id == action_id(finding.finding_id, plays[0].play_code, CUR)
    assert fresh.acceptance_state == "pending"
    assert (withdrawn.action_id, withdrawn.proposal_state) == (
        old.action_id,
        "withdrawn",
    )
    assert withdrawn.events[-1].recorded_by == "rule"
    # The same action in the current episode is kept (the pre-episode key).
    (kept,) = propose(plays, [old], run_id=CUR, at=NOW, findings=findings)
    assert kept == old


# ---- transitions (D3-13) -------------------------------------------------------

_KINDS = ("accepted", "rejected", "executed", "withdrawn")
_TABLE: dict[str, set[str]] = {
    "pending": {"accepted", "rejected", "withdrawn"},
    "accepted": {"executed", "withdrawn"},
    "rejected": set(),
    "executed": set(),
    "withdrawn": set(),
}


def _in_state(name: str) -> Action:
    action = proposed()
    if name == "pending":
        return action
    if name == "executed":
        return step(step(action, "accepted"), "executed", executed_at="2026-09-24")
    if name == "withdrawn":
        return step(action, "withdrawn")
    return step(action, name)


@pytest.mark.parametrize("start", sorted(_TABLE))
@pytest.mark.parametrize("kind", _KINDS)
def test_transition_table(start: str, kind: str) -> None:
    action = _in_state(start)
    if kind in _TABLE[start]:
        out = step(
            action, kind, executed_at="2026-09-24" if kind == "executed" else None
        )
        assert (
            out.events[-1].kind == kind and out.events[-1].seq == len(action.events) + 1
        )
        assert out.events[:-1] == action.events
    else:
        with pytest.raises(InvalidTransition) as err:
            step(action, kind)
        assert err.value.code == "INVALID_TRANSITION"


def test_transition_fields() -> None:
    accepted = step(proposed(), "accepted", note="customer agreed")
    assert (
        accepted.acceptance_state == "accepted"
        and accepted.events[-1].note == "customer agreed"
    )
    executed = step(accepted, "executed", executed_at="2026-09-24")
    assert (executed.execution_state, executed.executed_at) == (
        "executed",
        "2026-09-24",
    )
    assert executed.acceptance_state == "accepted"
    assert step(proposed(), "rejected").acceptance_state == "rejected"
    assert step(proposed(), "withdrawn").proposal_state == "withdrawn"


def test_execute_defaults_executed_at_to_event_time() -> None:
    out = step(step(proposed(), "accepted"), "executed")
    assert out.executed_at == AT_PRIOR


@pytest.mark.parametrize(
    ("kind", "by"),
    [("outcome_observed", "operator"), ("proposed", "operator"), ("accepted", "rule")],
)
def test_outcomes_and_rule_acceptance_are_not_transitions(kind: str, by: str) -> None:
    with pytest.raises(InvalidTransition):
        step(proposed(), kind, recorded_by=by)


# ---- outcomes (measurement only) -------------------------------------------------


def test_recovery_with_pending_acceptance_is_improved_not_established() -> None:
    out = outcome(proposed(), 100, 1, 1.0)
    assert (out.outcome_state, out.attribution) == ("improved", "not_established")
    assert (out.acceptance_state, out.execution_state) == ("pending", "not_started")
    assert (out.verification_window_start, out.verification_window_end) == INTERVAL
    assert out.outcome_observation_ids
    last = out.events[-1]
    assert (last.kind, last.recorded_by, last.run_id) == (
        "outcome_observed",
        "rule",
        CUR,
    )
    assert out.run_id == CUR


def test_unknown_current_gives_unknown_outcome() -> None:
    out = outcome(proposed(), None, None, None)
    assert out.outcome_state == "unknown" and out.attribution == "not_established"


def test_low_volume_with_open_finding_is_unknown_not_recovered() -> None:
    """30 runs / 20 failed cannot re-test the open finding: never ``improved``."""
    (finding,), _ = current_findings(30, 20, 66.7)
    assert (finding.state, finding.severity) == ("unknown_current", None)
    assert finding.last_confirmed_severity == "watch"
    out = outcome(proposed(), 30, 20, 66.7)
    assert out.outcome_state == "unknown" and out.attribution == "not_established"


def test_enough_runs_with_few_failures_is_a_genuine_recovery() -> None:
    (finding,), _ = current_findings(60, 1, 1.7)
    assert (finding.state, finding.severity) == ("recovered", "none")
    assert outcome(proposed(), 60, 1, 1.7).outcome_state == "improved"


def test_recovered_without_cited_measurements_is_not_improved() -> None:
    (finding,), sel = current_findings(60, 1, 1.7)
    latest = replace(finding.revisions[-1], observation_ids=())
    bare = replace(finding, revisions=(*finding.revisions[:-1], latest))
    (out,) = observe_outcomes([proposed()], [bare], sel)
    assert out.outcome_state == "unknown"


def test_same_severity_unchanged_higher_worsened() -> None:
    assert outcome(proposed(), 100, 9, 9.0).outcome_state == "unchanged"
    assert outcome(proposed(), 100, 30, 30.0).outcome_state == "worsened"


def test_executed_before_window_and_improved_is_consistent_with_action() -> None:
    executed = step(step(proposed(), "accepted"), "executed", executed_at="2026-09-22")
    out = outcome(executed, 100, 1, 1.0)
    assert (out.outcome_state, out.attribution) == (
        "improved",
        "consistent_with_action",
    )
    assert out.acceptance_state == "accepted" and out.execution_state == "executed"


def test_executed_inside_window_is_not_established() -> None:
    executed = step(step(proposed(), "accepted"), "executed", executed_at="2026-09-30")
    assert outcome(executed, 100, 1, 1.0).attribution == "not_established"


def test_action_proposed_this_run_or_withdrawn_is_not_observed() -> None:
    findings, sel = current_findings(100, 1, 1.0)
    fresh = replace(proposed(), events=(replace(proposed().events[0], run_id=CUR),))
    withdrawn = step(proposed(), "withdrawn")
    assert observe_outcomes([fresh, withdrawn], findings, sel) == (
        fresh,
        withdrawn,
    )


def test_unrelated_finding_leaves_action_untouched() -> None:
    action = proposed()
    assert observe_outcomes([action], (), selection_for([], [])) == (action,)


def test_no_state_named_caused() -> None:
    executed = step(step(proposed(), "accepted"), "executed", executed_at="2026-09-22")
    text = str(outcome(executed, 100, 1, 1.0).to_dict())
    assert "caused" not in text
