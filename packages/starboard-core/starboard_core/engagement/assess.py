# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""The single run pipeline (D3-25): current inputs + prior records → one assessment.

:func:`assess_run` is the only function that sets finding states, revisions,
episodes, action outcomes and proposals. It composes, in order:

``families`` / ``observations`` producers → ``dedupe.merge`` →
``history.select_baselines`` → ``concerns.evaluate`` → ``history.finding_states``
→ case links (``possible_links``) → ``changes.build`` → ``health.project`` →
``plays.candidates`` → ``actions.observe_outcomes`` / ``actions.propose``.

Pure: no I/O and no clock read. Every timestamp is ``<today>T00:00:00+00:00``.
Records written by the current run are never treated as prior. Cases are carried
unchanged (``cases.open_case`` / ``cases.revise`` own their revisions).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from starboard_core.engagement.actions import observe_outcomes, propose
from starboard_core.engagement.changes import ChangeContext, build
from starboard_core.engagement.concerns import evaluate
from starboard_core.engagement.dedupe import merge
from starboard_core.engagement.evidence import SOURCE_KIND_ORDER
from starboard_core.engagement.families import (
    RUN_LEVEL_KEY_PREFIX,
    from_facts,
    from_reliability,
    rule_coverage,
)
from starboard_core.engagement.health import (
    RunTarget,
    health_eligible,
    project,
    targeted_requests,
)
from starboard_core.engagement.history import (
    finding_states,
    select_baselines,
    selection_reason,
)
from starboard_core.engagement.jobruns import FAILED_STATES, RunSlice, reconstruct_runs
from starboard_core.engagement.observations import from_findings_manifest
from starboard_core.engagement.plays import PlayContext, candidates
from starboard_core.engagement.prior import PriorRecords
from starboard_core.engagement.records import (
    Action,
    BaselineSelection,
    Case,
    ChangeInput,
    FindingRecord,
    HealthRead,
    Observation,
    Play,
)

__all__ = ["CurrentInputs", "RunAssessment", "assess_run"]

_CASE_PREFIX = "case:"
_JOB_RISE = "job_failure_rise"
_SETTLED = frozenset({"recovered", "historical"})


@dataclass(frozen=True)
class CurrentInputs:
    """What the current run measured.

    Attributes:
        facts: The discovery ``facts`` dict (``families.from_facts``), if any.
        manifest: The findings-manifest 2.0 dict (rule findings and coverage).
        verify_slices: Job-filtered ``vt-job-run-states`` slices (run-level reliability).
        case_evidence: Case acquisition observations (``acquisition_v1``); kept in
            the run's observations, never a baseline or a health input.
        observations: Further observations already built (e.g. F-12 aggregates).
        evidence_ids: Evidence IDs cited by the facts / manifest observations.
        source_kind: Source of the facts / manifest observations.
    """

    facts: Mapping[str, Any] | None = None
    manifest: Mapping[str, Any] | None = None
    verify_slices: Sequence[RunSlice] = ()
    case_evidence: Sequence[Observation] = ()
    observations: Sequence[Observation] = ()
    evidence_ids: Sequence[str] = ()
    source_kind: str = "customer_workspace"


@dataclass(frozen=True)
class RunAssessment:
    """The seven §B record sets of one run plus its baseline selection.

    Attributes:
        observations: Merged current observations, then the concern flags.
        findings: Findings after ``finding_states`` (case findings excluded),
            with case links and the IDs of their actions.
        health: The six-family health read.
        plays: Ordered play candidates.
        changes: ChangeInputs of continuing / new / recovered comparisons.
        cases: Prior cases, unchanged.
        actions: Proposed and kept open actions (play order), the open actions
            they supersede (withdrawn by ``rule``), then the other actions
            whose outcome this run observed.
        baseline_selection: The selection over ``observations``.
    """

    observations: tuple[Observation, ...]
    findings: tuple[FindingRecord, ...]
    health: HealthRead
    plays: tuple[Play, ...]
    changes: tuple[ChangeInput, ...]
    cases: tuple[Case, ...]
    actions: tuple[Action, ...]
    baseline_selection: BaselineSelection


def _is_case(finding: FindingRecord) -> bool:
    return finding.concern_code.startswith(_CASE_PREFIX)


def _union(first: Sequence[str], second: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _stamp(today: date | str) -> tuple[str, str]:
    day = (
        today.isoformat()
        if isinstance(today, date)
        else date.fromisoformat(today).isoformat()
    )
    return day, f"{day}T00:00:00+00:00"


def _current_observations(
    current: CurrentInputs,
    prior: Sequence[Observation],
    slices: Sequence[RunSlice],
    *,
    run_id: str,
    account_key: str,
    workspace_id: str,
    interval: tuple[str, str],
    today: str,
    expected_jobs: Sequence[tuple[str, str]] = (),
) -> list[Observation]:
    scope: dict[str, Any] = {
        "run_id": run_id,
        "account_key": account_key,
        "workspace_id": workspace_id,
        "source_kind": current.source_kind,
        "evidence_ids": tuple(current.evidence_ids),
    }
    built: list[Observation] = []
    if current.facts is not None:
        built += from_facts(current.facts, **scope)
    if current.manifest is not None:
        built += from_findings_manifest(
            current.manifest, interval=interval, prior=prior, **scope
        )
        built += rule_coverage(current.manifest, interval=interval, **scope)
    if slices or expected_jobs:
        recon = reconstruct_runs(
            slices,
            interval_start=interval[0],
            interval_end=interval[1],
            today=today,
            expected_jobs=expected_jobs,
        )
        built += from_reliability(
            recon,
            run_id=run_id,
            account_key=account_key,
            source_kind=min(
                (s.source_kind for s in slices), key=SOURCE_KIND_ORDER.index
            )
            if slices
            else current.source_kind,
            interval=interval,
        )
    built += current.observations
    built += current.case_evidence
    return [
        o
        for o in built
        if o.account_key == account_key and o.workspace_id == workspace_id
    ]


def _open_job_rises(
    findings: Sequence[FindingRecord], account_key: str, workspace_id: str
) -> tuple[tuple[str, str], ...]:
    """``(workspace_id, job_id)`` of each open prior per-job rise in this scope.

    Each such job is reconstructed even without a covering slice, so missing
    current evidence is an explicit ``unknown`` observation (spec E7), never an
    absence that a flag could read as recovered.
    """
    latest: dict[str, FindingRecord] = {}
    for f in findings:
        if f.finding_id not in latest or f.revision > latest[f.finding_id].revision:
            latest[f.finding_id] = f
    return tuple(
        sorted(
            {
                (workspace_id, f.entity_id)
                for f in latest.values()
                if f.concern_code == _JOB_RISE
                and f.entity_kind == "job"
                and f.state not in _SETTLED
                and (f.account_key, f.workspace_id) == (account_key, workspace_id)
            }
        )
    )


def _source_windows(
    observations: Sequence[Observation], slices: Sequence[RunSlice]
) -> dict[str, tuple[tuple[str, str, str], ...]]:
    """Run-level job observation → the ``(start, end, source_kind)`` slices covering it."""
    out: dict[str, tuple[tuple[str, str, str], ...]] = {}
    for o in observations:
        if o.entity_kind != "job" or not (o.dedupe_key or "").startswith(
            RUN_LEVEL_KEY_PREFIX
        ):
            continue
        windows = sorted(
            {
                (s.window_start, s.window_end, s.source_kind)
                for s in slices
                if o.entity_id in s.job_ids and s.workspace_id in (None, o.workspace_id)
            }
        )
        if windows:
            out[o.observation_id] = tuple(windows)
    return out


def _latest_failed_runs(
    slices: Sequence[RunSlice], workspace_id: str
) -> dict[str, str]:
    """``job_id`` → the failed run with the latest ``last_period_end``."""
    latest: dict[str, tuple[str, str]] = {}
    for s in slices:
        for row in s.rows:
            if str(row.get("workspace_id") or s.workspace_id or "") != workspace_id:
                continue
            if str(row.get("result_state") or "").upper() not in FAILED_STATES:
                continue
            job, run = str(row.get("job_id") or ""), str(row.get("run_id") or "")
            if not job or not run:
                continue
            rank = (str(row.get("last_period_end") or ""), run)
            if job not in latest or rank > latest[job]:
                latest[job] = rank
    return {job: rank[1] for job, rank in sorted(latest.items())}


def _link_cases(
    findings: Sequence[FindingRecord], case_findings: Sequence[FindingRecord]
) -> tuple[FindingRecord, ...]:
    """Link each finding to the standalone case findings on the same entity."""
    out: list[FindingRecord] = []
    for f in findings:
        links = [
            c.finding_id
            for c in case_findings
            if (c.entity_kind, c.entity_id) == (f.entity_kind, f.entity_id)
        ]
        out.append(
            replace(f, possible_links=_union(f.possible_links, links)) if links else f
        )
    return tuple(out)


def assess_run(
    prior: PriorRecords,
    current: CurrentInputs,
    *,
    run_id: str,
    account_key: str,
    workspace_id: str,
    interval: tuple[str, str],
    today: date | str,
    task: str | None = None,
    target: RunTarget | None = None,
) -> RunAssessment:
    """Assess one run of one account workspace against its prior records.

    Args:
        prior: ``prior.load_prior`` / ``load_prior_local`` output for the workspace.
        current: What this run measured.
        run_id: The current run.
        account_key / workspace_id: Scope; current observations outside it are dropped.
        interval: The reporting interval ``(start, end)``.
        today: The run date (reconstruction cut-off and every timestamp).
        task: The run's task (``RunAuthorization.intent``): with
            ``current.source_kind`` it picks the plays' ``next_commands`` forms.
        target: Where the run's printed commands read and write (run folder or
            run dir, warehouse, profile); ``internal`` follows
            ``current.source_kind``. Default: run-less forms.

    Raises:
        ValueError: An input the producers reject (e.g. a manifest that is not 2.0,
            facts without a window).
    """
    day, at = _stamp(today)
    slices = tuple(current.verify_slices)
    cands = [
        c
        for c in prior.observations
        if c.observation.run_id != run_id and health_eligible(c.observation)
    ]
    baselines = [c.observation for c in cands]
    gaps = [u for u in prior.unavailable if "observations" in u.records]
    prior_findings = [f for f in prior.findings if f.run_id != run_id]
    prior_actions = [a for a in prior.actions if a.run_id != run_id]

    merged = merge(
        _current_observations(
            current,
            baselines,
            slices,
            run_id=run_id,
            account_key=account_key,
            workspace_id=workspace_id,
            interval=interval,
            today=day,
            expected_jobs=_open_job_rises(prior_findings, account_key, workspace_id),
        )
    )

    def select(observations: Sequence[Observation]) -> BaselineSelection:
        return select_baselines(
            [o for o in observations if health_eligible(o)],
            cands,
            reporting_interval=interval,
            unavailable=gaps,
            run_id=run_id,
            computed_at=at,
        )

    concern = evaluate(
        merged.observations,
        select(merged.observations),
        prior_findings,
        run_id=run_id,
        baselines=baselines,
        manifest=current.manifest,
    )
    observations = (*merged.observations, *concern.flags)
    selection = select(observations)

    case_findings = [
        f
        for f in prior_findings
        if _is_case(f)
        and (f.account_key, f.workspace_id) == (account_key, workspace_id)
    ]
    findings = _link_cases(
        finding_states(
            [f for f in prior_findings if not _is_case(f)], selection, concern.findings
        ),
        case_findings,
    )

    facts = current.facts or {}
    step = facts.get("step_change")
    changes = build(
        observations,
        selection,
        context=ChangeContext(
            baselines=baselines,
            superseded=merged.superseded,
            config_changes=tuple(facts.get("recent_config_changes") or ()),
            step_change=step if isinstance(step, Mapping) else None,
            actions=prior_actions,
            findings=findings,
            source_windows=_source_windows(merged.observations, slices),
        ),
    )
    health = project(
        observations,
        findings,
        changes,
        run_id=run_id,
        account_key=account_key,
        workspace_id=workspace_id,
        interval=interval,
    )
    run_target = replace(
        target or RunTarget(), internal=current.source_kind == "internal_mirror"
    )
    health = targeted_requests(health, run_target)
    plays = candidates(
        findings,
        health,
        observations,
        run_id=run_id,
        interval=interval,
        changes=changes,
        review_severities=concern.review_severities,
        latest_failed_runs=_latest_failed_runs(slices, workspace_id),
        context=PlayContext(task=task, target=run_target),
    )

    # No key has a prior baseline: nothing measured an action's outcome.
    observed = (
        tuple(prior_actions)
        if selection_reason(selection) is not None
        else observe_outcomes(prior_actions, findings, selection)
    )
    proposed = propose(plays, observed, run_id=run_id, at=at, findings=findings)
    kept = {a.action_id for a in proposed}
    actions = (
        *proposed,
        *(a for a in observed if a.run_id == run_id and a.action_id not in kept),
    )
    action_ids: dict[str, list[str]] = {}
    for a in actions:
        action_ids.setdefault(a.finding_id, []).append(a.action_id)
    findings = tuple(
        replace(f, action_ids=_union(f.action_ids, action_ids[f.finding_id]))
        if f.finding_id in action_ids
        else f
        for f in findings
    )

    return RunAssessment(
        observations=observations,
        findings=findings,
        health=health,
        plays=plays,
        changes=changes,
        cases=tuple(prior.cases),
        actions=actions,
        baseline_selection=selection,
    )
