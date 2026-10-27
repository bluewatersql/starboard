"""Host-recorded investigation and actions: ``engagement case|action|play``.

* ``case open`` opens a case on a finding (this run's or a prior run's, any run
  folder of the account), or a standalone case on a clue (``job:42``) / Drive
  object, which creates its ``case:<kind>`` finding.
* ``case revise`` records one investigation step: run-level reliability rebuilt
  from ``--verify`` slices (``acquisition_v1`` observations), the evidence IDs of
  ``--evidence`` artifacts, the gaps, an optional hypothesis and cause
  confidence. The case's ``finding_id`` is fixed at ``case open`` and never
  changes; a cited job run-output only reports its ``error_signature``.
* ``case show`` prints one case and its finding (read-only).
* ``action propose`` records the host's next step on a case's finding as a
  ``pending`` case-origin action (after the cause; no play), linked from the
  finding's ``action_ids``.
* ``action accept|reject|execute|withdraw`` applies one host event to an action.
* ``play rank`` records the host's rank of one play, with its reason.

Every write goes through the run sink (``analysis/{cases,findings,observations,
actions,plays}.json``); free text that carries an email or a credential is
refused (exit 2) without being echoed.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from starboard_skills.helpers.contract import ArgError, NotFoundError
from starboard_skills.helpers.engagement import _envelope
from starboard_skills.helpers.engagement._envelope import (
    ACTIONS_PATH,
    CASES_PATH,
    FINDINGS_PATH,
    OBSERVATIONS_PATH,
    PLAYS_PATH,
    Refusal,
    _ctx,
)
from starboard_skills.helpers.engagement.analysis_cmds import (
    OpenRun,
    _merge,
    _slices,
    action_index,
    effective_order,
    open_run,
)

ACTION_EVENTS = {
    "accept": "accepted",
    "reject": "rejected",
    "execute": "executed",
    "withdraw": "withdrawn",
}
#: The kernel's ``OwnerRole`` values (``records.OwnerRole``).
OWNER_ROLES = (
    "job_owner",
    "warehouse_owner",
    "pipeline_owner",
    "platform_admin",
    "operator",
    "account_team",
)
HYPOTHESIS_STATES = ("untested", "supported", "refuted")
VERIFY_ONLY_JOB_RUN_STATES = (
    "`case revise --verify` takes only vt-job-run-states verify results (job run "
    "reliability); cite any other verify result (warehouse, query, pipeline, ...) "
    "with --evidence <path>"
)
CAUSE_CONFIDENCE = ("hypothesis", "supported")
_RUN_OUTPUT_GAP = "job_run_output"


def _latest(items: Sequence[Any], key: str, value: str) -> Any | None:
    """The highest-revision item whose ``key`` is ``value`` (``None`` when absent)."""
    found = [i for i in items if getattr(i, key) == value]
    return max(found, key=lambda i: getattr(i, "revision", 0)) if found else None


def _lookup(run: OpenRun, kind: str, rel: str, key: str, value: str) -> Any:
    """``value`` from this run's records, else the account's prior records."""
    item = _latest(run.records(kind, rel), key, value)
    if item is None:
        item = _latest(getattr(run.prior(None), kind), key, value)
    if item is None:
        raise NotFoundError(
            f"no {kind[:-1]} {value!r} in this run or the account's prior runs"
        )
    return item


def _save(run: OpenRun, kind: str, rel: str, items: Sequence[Any], key: str) -> None:
    run.put(rel, [i.to_dict() for i in _merge(run.records(kind, rel), items, key)])


def _summary(case: Any, finding: Any) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "case_state": case.state,
        "origin": case.origin,
        "finding_id": finding.finding_id,
        "finding_key": finding.finding_key,
        "episode_id": finding.episode_id,
        # The finding's latest revision across the account's runs, and the run
        # that wrote it (a case on a prior run's finding continues its revisions).
        "finding_revision": finding.revision,
        "finding_revision_run_id": finding.run_id,
        "cause_confidence": finding.cause_confidence,
        "evidence_revisions": len(case.evidence_revisions),
        "hypotheses": [
            {
                "hypothesis_id": h["hypothesis_id"],
                "statement": h["statement"],
                "status": h["status"],
                "evidence_ids": list(h["evidence_ids"]),
            }
            for h in case.hypotheses
        ],
    }


# --------------------------------------------------------------------------- #
# case open
# --------------------------------------------------------------------------- #
def cmd_case_open(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.engagement.cases import open_case  # lazy – kernel dep

    origins = [
        (name, value)
        for name, value in (
            ("finding", args.finding_id),
            ("clue", args.clue),
            ("drive_object", args.drive_object),
        )
        if value
    ]
    if len(origins) != 1:
        raise ArgError("pass exactly one of --finding-id, --clue or --drive-object")
    origin, ref = origins[0]
    with open_run(args) as run:
        _ctx(args)["stage"] = "analysis"
        if origin == "finding":
            finding = _lookup(run, "findings", FINDINGS_PATH, "finding_id", ref)
            case, created = open_case(
                account_key=run.account_key,
                workspace_id=finding.workspace_id,
                origin=origin,
                origin_ref=ref,
                question=args.question,
                run_id=run.run_id,
                finding=finding,
            )
        else:
            case, created = open_case(
                account_key=run.account_key,
                workspace_id=run.workspace(),
                origin=origin,
                origin_ref=ref,
                question=args.question,
                run_id=run.run_id,
            )
            finding = created
        mine = _latest(run.records("cases", CASES_PATH), "case_id", case.case_id)
        if mine is not None and mine.run_id == run.run_id:
            # The same origin and question in the same run names the same case.
            case, created = mine, None
            finding = _lookup(
                run, "findings", FINDINGS_PATH, "finding_id", case.finding_id
            )
        outputs = [CASES_PATH]
        if created is not None:
            held = _latest(
                run.records("findings", FINDINGS_PATH), "finding_id", created.finding_id
            )
            if held is not None:
                # Another case of this run already holds the finding: link both.
                created = replace(
                    held, case_ids=tuple(dict.fromkeys((*held.case_ids, case.case_id)))
                )
                finding = created
            _save(run, "findings", FINDINGS_PATH, [created], "finding_id")
            outputs.append(FINDINGS_PATH)
        _save(run, "cases", CASES_PATH, [case], "case_id")
        return run.result({**_summary(case, finding), "outputs": outputs})


# --------------------------------------------------------------------------- #
# case revise
# --------------------------------------------------------------------------- #
def _acquired(run: OpenRun, rels: Sequence[str], index: dict[str, Any]) -> list[Any]:
    """``acquisition_v1`` per-job reliability rebuilt from ``--verify`` slices."""
    from starboard_core.engagement.evidence import SOURCE_KIND_ORDER  # lazy – kernel
    from starboard_core.engagement.families import (  # lazy – kernel dep
        from_reliability,
    )
    from starboard_core.engagement.health import ACQUISITION_METHOD
    from starboard_core.engagement.jobruns import reconstruct_runs
    from starboard_core.engagement.records import (
        _OBSERVATION_KEY_FIELDS,
        observation_id,
    )

    if not rels:
        return []
    try:
        slices = _slices(run, rels, index)
    except ArgError as exc:
        if "is not in the run" in exc.message:
            raise
        raise ArgError(f"{exc.message}. {VERIFY_ONLY_JOB_RUN_STATES}") from exc
    start = min(s.window_start for s in slices)[:10]
    end = max(s.window_end for s in slices)[:10]
    today = date.fromisoformat(end) + timedelta(days=1)
    recon = reconstruct_runs(
        slices, interval_start=start, interval_end=end, today=today
    )
    built = from_reliability(
        recon,
        run_id=run.run_id,
        account_key=run.account_key,
        # The most restrictive slice source governs audience (as in assess_run).
        source_kind=min((s.source_kind for s in slices), key=SOURCE_KIND_ORDER.index),
        interval=(start, end),
    )
    out = []
    for o in built:
        fields = {**{n: getattr(o, n) for n in _OBSERVATION_KEY_FIELDS}}
        fields["method_version"] = ACQUISITION_METHOD
        key = tuple(fields[n] for n in _OBSERVATION_KEY_FIELDS)
        oid = observation_id(key)
        out.append(replace(o, method_version=ACQUISITION_METHOD, observation_id=oid))
    return out


def _run_output_signature(payload: Any) -> str | None:
    """``error_signature_v1`` of a ``job run-output`` payload (``None`` otherwise)."""
    from starboard_core.engagement.concerns import (  # lazy – kernel dep
        error_signature,
        strip_ansi,
    )

    doc = payload.get("data", payload) if isinstance(payload, dict) else None
    if not isinstance(doc, dict) or not ({"error_trace", "logs"} & set(doc)):
        return None
    text = doc.get("error_trace") or doc.get("error")
    if not text:
        return error_signature(None)
    from starboard_x.diagnostic.evidence_extractor import EvidenceWindowExtractor

    text = strip_ansi(str(text))
    primary = EvidenceWindowExtractor().extract(text).primary_evidence
    category = primary.evidence_type.value if primary is not None else None
    return error_signature(text, category=category)


def _hypothesis_evidence(
    explicit: Sequence[str] | None,
    registered: Sequence[str],
    case: Any,
    finding: Any,
    index: dict[str, Any],
) -> list[str]:
    """``--hypothesis-evidence`` IDs (each known to the run) plus this step's IDs.

    Evidence this step registers always joins the list: its IDs are unknown until
    the call prints them, so it cannot be named in ``--hypothesis-evidence``.
    Known IDs: the run's evidence index, this step's, and the case's and its
    finding's earlier citations (a local run has no index).

    Raises:
        ArgError: An explicit ID the run does not know.
    """
    if not explicit:
        return list(dict.fromkeys(registered))
    known = {str(ref.evidence_id) for ref in index.values()}
    known.update(registered, finding.evidence_ids)
    known.update(e for r in case.evidence_revisions for e in r["evidence_ids"])
    unknown = [e for e in explicit if e not in known]
    if unknown:
        raise ArgError(
            f"--hypothesis-evidence {', '.join(unknown)} is not evidence of this run "
            "(evidence/index.json or an earlier step); pass the evidence_ids a "
            "`case revise` printed"
        )
    return list(dict.fromkeys([*explicit, *registered]))


def _stored_hypothesis(
    case: Any, hypothesis_id: str | None, statement: str | None
) -> dict[str, Any] | None:
    """The case's hypothesis ``hypothesis_id`` (``None`` when a new one is stated).

    Raises:
        ArgError: ``--hypothesis-id`` names no hypothesis of the case and no
            ``--hypothesis`` statement was given to add it.
    """
    if not hypothesis_id:
        return None
    found = next(
        (dict(h) for h in case.hypotheses if h["hypothesis_id"] == hypothesis_id), None
    )
    if found is None and not statement:
        known = ", ".join(h["hypothesis_id"] for h in case.hypotheses) or "none"
        raise ArgError(
            f"--hypothesis-id {hypothesis_id!r} is not a hypothesis of case "
            f"{case.case_id} (known: {known}); pass --hypothesis to add it"
        )
    return found


def cmd_case_revise(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.engagement.cases import revise  # lazy – kernel dep

    if args.hypothesis_status and not (args.hypothesis or args.hypothesis_id):
        raise ArgError(
            "--hypothesis-status needs --hypothesis-id (an existing hypothesis) or "
            "--hypothesis (a new statement)"
        )
    with open_run(args) as run:
        _ctx(args)["stage"] = "analysis"
        case = _lookup(run, "cases", CASES_PATH, "case_id", args.case_id)
        finding = _lookup(run, "findings", FINDINGS_PATH, "finding_id", case.finding_id)
        index = run.evidence()
        observations = _acquired(run, args.verify or (), index)
        evidence_ids = [o for obs in observations for o in obs.evidence_ids]
        signatures: list[str] = []
        for rel in args.evidence or ():
            data = run.read(rel)
            evidence_ids.append(run.evidence_id(rel, data, index))
            try:
                sig = _run_output_signature(json.loads(data))
            except ValueError:
                sig = None
            if sig:
                signatures.append(sig)
        # A job case's revision without the gap cited its run output; once cited,
        # later steps (a hypothesis, more slices) leave no gap behind.
        cited_output = signatures or any(
            _RUN_OUTPUT_GAP not in r["gaps"] for r in case.evidence_revisions
        )
        gaps = (
            [_RUN_OUTPUT_GAP]
            if case.target_entity_kind == "job" and not cited_output
            else []
        )
        hypothesis = None
        if args.hypothesis or args.hypothesis_id:
            stored = _stored_hypothesis(case, args.hypothesis_id, args.hypothesis)
            cited = _hypothesis_evidence(
                args.hypothesis_evidence, evidence_ids, case, finding, index
            )
            if stored is not None:
                # A restatement or status step keeps the statement, status and
                # position it does not name; the stored evidence list is kept
                # unless --hypothesis-evidence replaces it, and evidence this
                # step registered joins it.
                kept = [] if args.hypothesis_evidence else stored["evidence_ids"]
                hypothesis = {
                    **stored,
                    "statement": args.hypothesis or stored["statement"],
                    "status": args.hypothesis_status or stored["status"],
                    "evidence_ids": tuple(dict.fromkeys([*kept, *cited])),
                }
            else:
                hypothesis = {
                    "hypothesis_id": args.hypothesis_id
                    or f"h{len(case.hypotheses) + 1}",
                    "statement": args.hypothesis,
                    "status": args.hypothesis_status or "untested",
                    # Default: the evidence this step registered.
                    "evidence_ids": tuple(cited),
                }
        case, finding = revise(
            case,
            finding,
            run_id=run.run_id,
            observations=observations,
            evidence_ids=list(dict.fromkeys(evidence_ids)),
            gaps=gaps,
            hypothesis=hypothesis,
            cause_confidence=args.cause_confidence,
        )
        if observations:
            _save(
                run, "observations", OBSERVATIONS_PATH, observations, "observation_id"
            )
        _save(run, "findings", FINDINGS_PATH, [finding], "finding_id")
        _save(run, "cases", CASES_PATH, [case], "case_id")
        return run.result(
            {
                **_summary(case, finding),
                "observations_added": len(observations),
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
                # error_signature_v1 of a cited job run-output (informational; the
                # case's finding_id never changes after `case open`).
                "error_signature": signatures[0] if signatures else None,
                "gaps": gaps,
                "outputs": [CASES_PATH, FINDINGS_PATH]
                + ([OBSERVATIONS_PATH] if observations else []),
            }
        )


def _evidence_paths(run: OpenRun, case: Any, finding: Any) -> dict[str, str | None]:
    """``evidence_id -> run-relative path`` for every evidence ID the case cites.

    Indexed IDs come from the run's evidence index; the others are matched to
    this run's artifacts by their deterministic ID (``run_id``, path, md5). A
    Drive run's listing carries the md5, so nothing is downloaded. ``None``: not
    an artifact of this run (a prior run's evidence, or a removed file).
    """
    import hashlib

    from starboard_core.engagement.records import evidence_id  # lazy – kernel dep

    wanted = list(
        dict.fromkeys(
            [
                *(e for r in case.evidence_revisions for e in r["evidence_ids"]),
                *(e for h in case.hypotheses for e in h["evidence_ids"]),
                *finding.evidence_ids,
            ]
        )
    )
    if not wanted:
        return {}
    paths = {str(ref.evidence_id): rel for rel, ref in run.evidence().items()}
    if any(e not in paths for e in wanted):
        listed = getattr(run._sink, "artifacts", None)
        md5s: dict[str, str] = {}
        if callable(listed):  # Drive: md5s from the listing
            md5s = {rel: obj.md5 for rel, obj in listed().items() if obj.md5}
        else:  # a local run dir: hash the files in place
            for rel in run.listing(""):
                try:
                    md5s[rel] = hashlib.md5(run.read(rel)).hexdigest()  # noqa: S324
                except ArgError:
                    continue
        for rel, md5 in sorted(md5s.items()):
            paths.setdefault(evidence_id(run.run_id, rel, md5), rel)
    return {e: paths.get(e) for e in wanted}


def _evidence_runs(case: Any, finding: Any) -> dict[str, str]:
    """``evidence_id -> run_id`` of the first revision that cited it.

    The case's own revisions come first, then the finding's chain (which can
    hold another run's citations), then the finding's current run.
    """
    runs: dict[str, str] = {}
    for r in case.evidence_revisions:
        for e in r["evidence_ids"]:
            runs.setdefault(e, r["run_id"])
    for rev in finding.revisions:
        for e in rev.evidence_ids:
            runs.setdefault(e, rev.run_id)
    for e in finding.evidence_ids:
        runs.setdefault(e, finding.run_id)
    return runs


def cmd_case_show(args: argparse.Namespace) -> dict[str, Any]:
    with open_run(args) as run:
        case = _lookup(run, "cases", CASES_PATH, "case_id", args.case_id)
        finding = _lookup(run, "findings", FINDINGS_PATH, "finding_id", case.finding_id)
        paths = _evidence_paths(run, case, finding)
        cited_in = _evidence_runs(case, finding)
        return run.result(
            {
                **_summary(case, finding),
                "target": [case.target_entity_kind, case.target_entity_id],
                "evidence_paths": paths,
                # A null path is no artifact of this run: the run that cited it.
                "evidence_from_run": {
                    e: cited_in[e]
                    for e, rel in paths.items()
                    if rel is None and e in cited_in
                },
                "evidence": [
                    {
                        "revision": r["revision"],
                        "run_id": r["run_id"],
                        "evidence_ids": list(r["evidence_ids"]),
                        "gaps": list(r["gaps"]),
                    }
                    for r in case.evidence_revisions
                ],
            }
        )


# --------------------------------------------------------------------------- #
# action / play
# --------------------------------------------------------------------------- #
def cmd_action_propose(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.engagement.actions import propose_from_case  # lazy – kernel

    with open_run(args) as run:
        _ctx(args)["stage"] = "analysis"
        case = _lookup(run, "cases", CASES_PATH, "case_id", args.case_id)
        finding = _latest(
            run.records("findings", FINDINGS_PATH), "finding_id", case.finding_id
        )
        if finding is None:
            raise Refusal(
                "CASE_NOT_REVISED",
                f"case {case.case_id}'s finding {case.finding_id} is not in this run; "
                "record the cause with `engagement case revise` first",
            )
        action = propose_from_case(
            case,
            next_step=args.next_step,
            owner_role=args.owner_role,
            owner_label=args.owner_label,
            verify_method=args.verify_method,
            run_id=run.run_id,
            at=_envelope._now(),
            note=args.note,
        )
        held = _latest(
            run.records("actions", ACTIONS_PATH), "action_id", action.action_id
        )
        created = held is None
        if held is not None:
            # The same next step on the same case names the same action.
            action = held
        else:
            _save(run, "actions", ACTIONS_PATH, [action], "action_id")
        linked = replace(
            finding,
            action_ids=tuple(dict.fromkeys((*finding.action_ids, action.action_id))),
        )
        _save(run, "findings", FINDINGS_PATH, [linked], "finding_id")
        return run.result(
            {
                "action_id": action.action_id,
                "case_id": case.case_id,
                "finding_id": action.finding_id,
                "created": created,
                "event": "proposed",
                "proposal_state": action.proposal_state,
                "acceptance_state": action.acceptance_state,
                "execution_state": action.execution_state,
                "outputs": [ACTIONS_PATH, FINDINGS_PATH],
            }
        )


def _already(action: Any, kind: str) -> bool:
    """Whether ``action`` is already in the state the event ``kind`` leads to."""
    state = {
        "accepted": action.acceptance_state,
        "rejected": action.acceptance_state,
        "executed": action.execution_state,
        "withdrawn": action.proposal_state,
    }[kind]
    return bool(state == kind)


def _action_cmd(verb: str) -> Any:
    kind = ACTION_EVENTS[verb]

    def cmd(args: argparse.Namespace) -> dict[str, Any]:
        from starboard_core.engagement.actions import (  # lazy – kernel dep
            InvalidTransition,
            transition,
        )

        with open_run(args) as run:
            _ctx(args)["stage"] = "analysis"
            action = _lookup(run, "actions", ACTIONS_PATH, "action_id", args.action_id)
            if _already(action, kind):
                # The same event again is a no-op: nothing is written.
                return run.result(
                    {
                        "action_id": action.action_id,
                        "finding_id": action.finding_id,
                        "event": kind,
                        "already": kind,
                        "proposal_state": action.proposal_state,
                        "acceptance_state": action.acceptance_state,
                        "execution_state": action.execution_state,
                        "executed_at": action.executed_at,
                        "outputs": [],
                    }
                )
            try:
                moved = transition(
                    action,
                    kind,
                    run_id=run.run_id,
                    at=_envelope._now(),
                    recorded_by="host",
                    executed_at=args.executed_at,
                    note=args.note,
                )
            except InvalidTransition as exc:
                raise Refusal("INVALID_TRANSITION", str(exc)) from exc
            _save(run, "actions", ACTIONS_PATH, [moved], "action_id")
            return run.result(
                {
                    "action_id": moved.action_id,
                    "finding_id": moved.finding_id,
                    "event": kind,
                    "already": None,
                    "proposal_state": moved.proposal_state,
                    "acceptance_state": moved.acceptance_state,
                    "execution_state": moved.execution_state,
                    "executed_at": moved.executed_at,
                    "outputs": [ACTIONS_PATH],
                }
            )

    cmd.__name__ = f"cmd_action_{verb}"
    return cmd


cmd_action_accept = _action_cmd("accept")
cmd_action_reject = _action_cmd("reject")
cmd_action_execute = _action_cmd("execute")
cmd_action_withdraw = _action_cmd("withdraw")


def cmd_play_rank(args: argparse.Namespace) -> dict[str, Any]:
    if args.rank < 1:
        raise ArgError("--rank must be 1 or more")
    with open_run(args) as run:
        _ctx(args)["stage"] = "analysis"
        play = _latest(run.records("plays", PLAYS_PATH), "play_id", args.play_id)
        if play is None:
            raise NotFoundError(
                f"no play {args.play_id!r} in this run; run `engagement analyze` first"
            )
        ranked = replace(play, host_rank=args.rank, host_reorder_reason=args.reason)
        ranked = type(play).from_dict(ranked.to_dict())  # the record's own checks
        _save(run, "plays", PLAYS_PATH, [ranked], "play_id")
        # The same order analyze's top_plays use, over every play of the run.
        effective = {
            p.play_id: rank
            for rank, p in effective_order(run.records("plays", PLAYS_PATH))
        }
        return run.result(
            {
                "play_id": ranked.play_id,
                "host_rank": ranked.host_rank,
                "effective_rank": effective.get(ranked.play_id),
                "action_id": action_index(
                    run.records("actions", ACTIONS_PATH), run.run_id
                ).get(ranked.play_id),
                "outputs": [PLAYS_PATH],
            }
        )
