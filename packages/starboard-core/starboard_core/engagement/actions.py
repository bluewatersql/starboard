# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Action lifecycle (``Action v1``, spec §B7, D3-13).

- :func:`propose` turns a run's finding plays into ``pending`` actions recorded
  by ``rule`` (at most one per play; an open action for the same finding,
  episode and play is kept, never duplicated; an open action another play or
  a new episode supersedes is withdrawn by ``rule``).
- :func:`propose_from_case` records the host's next step on a case's finding
  as a ``pending`` action (``case_id`` origin, no play). Rule proposals never
  supersede or withdraw a case-origin action.
- :func:`transition` applies a host/operator event: ``accepted`` / ``rejected``
  from ``pending``; ``executed`` only after ``accepted``; ``withdrawn`` before
  execution. Anything else raises :class:`InvalidTransition`.
- :func:`observe_outcomes` sets outcomes from measurement only: the finding's
  current revision against its severity when the action was proposed.
  Measurement never moves acceptance or execution, and attribution is
  ``consistent_with_action`` only when the action was executed before the
  verification window and the outcome is ``improved``. No field says "caused".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from starboard_core.engagement.health import severity_rank
from starboard_core.engagement.records import (
    FREE_TEXT_MAX,
    Action,
    ActionEvent,
    BaselineSelection,
    Case,
    FindingRecord,
    Play,
    action_id,
    case_action_id,
)

__all__ = [
    "InvalidTransition",
    "observe_outcomes",
    "propose",
    "propose_from_case",
    "transition",
]

_HOST_RECORDERS = ("host", "operator")


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class InvalidTransition(ValueError):
    """The requested action event is not allowed from the action's state (D3-13)."""

    code = "INVALID_TRANSITION"


def _is_open(action: Action) -> bool:
    return action.proposal_state == "proposed" and action.acceptance_state != "rejected"


def _latest(actions: Sequence[Action]) -> dict[str, Action]:
    """One copy per ``action_id``: the one with the most events (ties: first given)."""
    out: dict[str, Action] = {}
    for a in actions:
        held = out.get(a.action_id)
        if held is None or len(a.events) > len(held.events):
            out[a.action_id] = a
    return out


def _episode_runs(finding: FindingRecord) -> frozenset[str]:
    """The runs of the finding's current episode (its start run onwards)."""
    runs = [r.run_id for r in finding.revisions]
    started = finding.episode_started_run_id
    return frozenset(runs[runs.index(started) :] if started in runs else runs)


def _episode_of(action: Action, findings: Mapping[str, FindingRecord]) -> str | None:
    """The episode an action was proposed in: the finding's current episode, an
    ended one (``""``, never matched) or ``None`` when the finding is not given."""
    finding = findings.get(action.finding_id)
    if finding is None:
        return None
    current = action.events[0].run_id in _episode_runs(finding)
    return finding.episode_id if current else ""


def _superseded(action: Action, by: Play, run_id: str, at: str) -> Action:
    """``action`` withdrawn by ``rule``: another play now stands for its finding."""
    note = f"superseded by {by.play_code} ({by.play_id})"[:FREE_TEXT_MAX]
    return replace(
        action,
        proposal_state="withdrawn",
        events=_event(action, "withdrawn", run_id, at, "rule", note),
        run_id=run_id,
    )


def propose(
    plays: Sequence[Play],
    prior_actions: Sequence[Action],
    *,
    run_id: str,
    at: str,
    findings: Sequence[FindingRecord] = (),
) -> tuple[Action, ...]:
    """The open action of each finding play: the existing one, else a new proposal.

    Args:
        plays: The run's ``play_rules_v1`` candidates; plays citing no finding
            (``acquire_family_evidence``) get no action.
        prior_actions: Actions from prior runs (any copies, any order).
        run_id: The current run (the proposing run of new actions).
        at: ISO-8601 time of the ``proposed`` / ``withdrawn`` events.
        findings: The run's findings; they place each action in an episode
            (D3-13). Without them every action counts as the current episode.

    Returns:
        In play order, one action per finding play: the kept action of the same
        ``finding_id`` + episode + ``play_id`` (unchanged; an executed one is
        kept too, so it is never re-proposed in its episode) or a new
        ``pending`` action. Then each superseded open play action — not executed,
        and its finding now has a candidate play with another ``play_id`` or a
        new episode — with a ``withdrawn`` event recorded by ``rule``. Other
        closed prior actions are not returned.
    """
    by_fid = {f.finding_id: f for f in findings}
    open_by_key: dict[tuple[str, str | None, str | None], Action] = {}
    for a in _latest(prior_actions).values():
        # A case-origin action is the host's: no play stands for it or supersedes it.
        if _is_open(a) and a.case_id is None:
            key = (a.finding_id, _episode_of(a, by_fid), a.play_id)
            open_by_key.setdefault(key, a)
    out: list[Action] = []
    seen: set[str] = set()
    standing: dict[str, Play] = {}
    for play in plays:
        if not play.finding_ids or play.play_id in seen:
            continue
        seen.add(play.play_id)
        fid = play.finding_ids[0]
        standing.setdefault(fid, play)
        finding = by_fid.get(fid)
        episode = finding.episode_id if finding is not None else None
        kept = open_by_key.pop((fid, episode, play.play_id), None)
        if kept is not None:
            out.append(kept)
            continue
        out.append(
            Action(
                action_id=action_id(fid, play.play_code, run_id),
                finding_id=fid,
                play_id=play.play_id,
                case_id=None,
                owner_role=play.owner_role,
                owner_label=play.owner_label,
                next_step=play.reason[:FREE_TEXT_MAX],
                proposal_state="proposed",
                acceptance_state="pending",
                execution_state="not_started",
                executed_at=None,
                verification_window_start=None,
                verification_window_end=None,
                outcome_state="not_observed",
                outcome_observation_ids=(),
                attribution="not_established",
                events=(
                    ActionEvent(
                        seq=1, kind="proposed", run_id=run_id, at=at, recorded_by="rule"
                    ),
                ),
                run_id=run_id,
            )
        )
    for (fid, episode, _), a in open_by_key.items():
        by = standing.get(fid)
        if by is not None and episode is not None and a.execution_state != "executed":
            out.append(_superseded(a, by, run_id, at))
    return tuple(out)


def propose_from_case(
    case: Case,
    *,
    next_step: str,
    owner_role: str,
    owner_label: str | None,
    verify_method: str | None,
    run_id: str,
    at: str,
    note: str | None = None,
) -> Action:
    """The host's ``pending`` action on ``case``'s finding (``case_id`` origin).

    The ID is deterministic in the case, its finding and the next step, so
    re-proposing the same step names the same action. The ``proposed`` event
    (``host``) cites every evidence ID the case's revisions recorded.
    """
    cited = tuple(
        dict.fromkeys(e for r in case.evidence_revisions for e in r["evidence_ids"])
    )
    return Action(
        action_id=case_action_id(case.case_id, case.finding_id, next_step),
        finding_id=case.finding_id,
        play_id=None,
        case_id=case.case_id,
        owner_role=owner_role,
        owner_label=owner_label,
        next_step=next_step,
        proposal_state="proposed",
        acceptance_state="pending",
        execution_state="not_started",
        executed_at=None,
        verification_window_start=None,
        verification_window_end=None,
        outcome_state="not_observed",
        outcome_observation_ids=(),
        attribution="not_established",
        events=(
            ActionEvent(
                seq=1,
                kind="proposed",
                run_id=run_id,
                at=at,
                recorded_by="host",
                evidence_ids=cited,
                note=note,
            ),
        ),
        run_id=run_id,
        verify_method=verify_method,
    )


def _event(
    action: Action, kind: str, run_id: str, at: str, recorded_by: str, note: str | None
) -> tuple[ActionEvent, ...]:
    event = ActionEvent(
        seq=len(action.events) + 1,
        kind=kind,
        run_id=run_id,
        at=at,
        recorded_by=recorded_by,
        note=note,
    )
    return (*action.events, event)


def transition(
    action: Action,
    kind: str,
    *,
    run_id: str,
    at: str,
    recorded_by: str,
    executed_at: str | None = None,
    note: str | None = None,
) -> Action:
    """Apply one host/operator event to ``action``.

    Args:
        action: The current action record.
        kind: ``accepted``, ``rejected``, ``executed`` or ``withdrawn``.
        run_id: The run recording the event (becomes the action's ``run_id``).
        at: ISO-8601 event time.
        recorded_by: ``host`` or ``operator`` (a rule never accepts or executes).
        executed_at: When the change was made (``executed`` only); defaults to ``at``.
        note: Optional host free text.

    Raises:
        InvalidTransition: The event is not allowed from the action's state.
    """
    if recorded_by not in _HOST_RECORDERS:
        raise InvalidTransition(f"{kind!r} must be recorded by host or operator")
    withdrawn = action.proposal_state == "withdrawn"
    executed = action.execution_state == "executed"
    pending = action.acceptance_state == "pending"
    changes: dict[str, Any]
    if kind in ("accepted", "rejected") and not withdrawn and pending:
        changes = {"acceptance_state": kind}
    elif (
        kind == "executed"
        and not withdrawn
        and not executed
        and (action.acceptance_state == "accepted")
    ):
        changes = {"execution_state": "executed", "executed_at": executed_at or at}
    elif (
        kind == "withdrawn"
        and not withdrawn
        and not executed
        and (action.acceptance_state != "rejected")
    ):
        changes = {"proposal_state": "withdrawn"}
    else:
        raise InvalidTransition(
            f"cannot record {kind!r} on action {action.action_id} (proposal "
            f"{action.proposal_state}, acceptance {action.acceptance_state}, execution "
            f"{action.execution_state})"
        )
    return replace(
        action,
        events=_event(action, kind, run_id, at, recorded_by, note),
        run_id=run_id,
        **changes,
    )


def _reference_severity(finding: FindingRecord, proposed_run: str) -> str | None:
    """The finding's severity in the run that proposed the action."""
    earlier = finding.revisions[:-1]
    for rev in reversed(earlier):
        if rev.run_id == proposed_run:
            return rev.severity
    return earlier[-1].severity if earlier else None


def _outcome(finding: FindingRecord, reference: str | None) -> str:
    if finding.state == "unknown_current" or finding.severity is None:
        return "unknown"
    if finding.state == "recovered":
        # Improved only on a re-measured clear: the recovery revision must cite
        # the current measurements that show it (never an absence of data).
        latest = finding.revisions[-1]
        measured = latest.reason == "recovered" and bool(latest.observation_ids)
        return "improved" if measured else "unknown"
    if reference is None:
        return "unknown"
    now, then = severity_rank(finding.severity), severity_rank(reference)
    if now < then:
        return "improved"
    return "unchanged" if now == then else "worsened"


def observe_outcomes(
    actions: Sequence[Action],
    findings: Sequence[FindingRecord],
    selection: BaselineSelection,
) -> tuple[Action, ...]:
    """Record the measured outcome of each action whose finding this run re-evaluated.

    Args:
        actions: Current actions (any state).
        findings: The run's findings after ``finding_states``.
        selection: The run's baseline selection; its ``run_id`` and
            ``computed_at`` stamp the ``outcome_observed`` event and its
            ``reporting_interval`` is the default verification window.

    Returns:
        ``actions`` in order. An action is unchanged when it is withdrawn, was
        proposed in this run, or its finding was not re-evaluated in this run.
        Otherwise it gains an ``outcome_observed`` event (``rule``) with the
        outcome: ``recovered`` or a lower severity is ``improved``; missing
        current evidence is ``unknown`` (never ``improved``); the same severity
        is ``unchanged``; a higher one ``worsened``.
    """
    run_id = selection.run_id
    by_id = {f.finding_id: f for f in findings if f.revisions[-1].run_id == run_id}
    out: list[Action] = []
    for action in actions:
        finding = by_id.get(action.finding_id)
        proposed_run = action.events[0].run_id
        if (
            finding is None
            or action.proposal_state == "withdrawn"
            or proposed_run == run_id
        ):
            out.append(action)
            continue
        state = _outcome(finding, _reference_severity(finding, proposed_run))
        start = action.verification_window_start or selection.reporting_interval[0]
        end = action.verification_window_end or selection.reporting_interval[1]
        consistent = (
            action.execution_state == "executed"
            and action.executed_at is not None
            and _ts(action.executed_at) < _ts(start)
            and state == "improved"
        )
        out.append(
            replace(
                action,
                verification_window_start=start,
                verification_window_end=end,
                outcome_state=state,
                outcome_observation_ids=finding.revisions[-1].observation_ids,
                attribution="consistent_with_action"
                if consistent
                else "not_established",
                events=_event(
                    action,
                    "outcome_observed",
                    run_id,
                    selection.computed_at,
                    "rule",
                    None,
                ),
                run_id=run_id,
            )
        )
    return tuple(out)
