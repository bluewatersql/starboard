# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Cases: open and revise an investigation (``Case v1``, spec §B6, D3-5, D3-12).

- A case opened on a finding revises that same finding (same ``finding_id`` and
  ``episode_id``) with one ``investigated`` revision per :func:`revise`, even
  when the case lives in a different run folder.
- A standalone case (a ``job:`` / ``query:`` / ``pipeline:`` / ``run:`` clue or
  a ``drive:`` object) creates its own ``case:<target kind>`` finding. A job,
  query or pipeline clue names that entity (the one a health finding on it
  carries); a ``run:`` clue or a Drive object names the workspace.
- Case observations carry ``method_version="acquisition_v1"``: they never make
  a health family assessed and are never baselines (a method mismatch).
- Starboard writes ``cause_confidence="unassessed"``; only the host raises it,
  and ``supported`` needs a ``supported`` hypothesis citing evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from starboard_core.engagement.health import ACQUISITION_METHOD
from starboard_core.engagement.records import (
    CLUE_KINDS,
    UNCLASSIFIED,
    Case,
    FindingRecord,
    FindingRevision,
    Observation,
    case_id,
    concern_key,
    episode_id,
    finding_id,
)

__all__ = ["CASE_RULE_ID", "open_case", "revise"]

CASE_RULE_ID = "case_v1"
_RULE_VERSION = 1
_ENTITY_CLUES = ("job", "query", "pipeline")


def _target(origin: str, origin_ref: str) -> tuple[str, str]:
    if origin == "drive_object":
        return "drive_object", origin_ref.removeprefix("drive:")
    kind, _, ident = origin_ref.partition(":")
    if origin == "clue" and (kind not in CLUE_KINDS or not ident):
        clues = ", ".join(f"{k}:<id>" for k in CLUE_KINDS)
        raise ValueError(f"a clue must be one of {clues}, got {origin_ref!r}")
    return kind, ident


def _case_finding(
    *,
    account_key: str,
    workspace_id: str,
    target_kind: str,
    target_id: str,
    entity: tuple[str, str] | None,
    error_signature: str | None,
    case: str,
    run_id: str,
) -> FindingRecord:
    if entity is None:
        entity = (
            (target_kind, target_id)
            if target_kind in _ENTITY_CLUES
            else ("workspace", workspace_id)
        )
    discriminator = f"sig:{error_signature}" if error_signature else "-"
    code = f"case:{target_kind}"
    key = concern_key(
        account_key, workspace_id, entity[0], entity[1], code, discriminator
    )
    fid = finding_id(key)
    revision = FindingRevision(
        revision=1,
        run_id=run_id,
        reason="detected",
        severity="watch",
        symptom_confidence="unverified",
        cause_confidence="unassessed",
        case_id=case,
    )
    return FindingRecord(
        finding_id=fid,
        finding_key=key,
        concern_code=code,
        family=UNCLASSIFIED,
        account_key=account_key,
        workspace_id=workspace_id,
        entity_kind=entity[0],
        entity_id=entity[1],
        episode_id=episode_id(fid, run_id),
        episode_started_run_id=run_id,
        state="watch",
        severity="watch",
        last_confirmed_severity=None,
        symptom_confidence="unverified",
        cause_confidence="unassessed",
        rule_id=CASE_RULE_ID,
        rule_version=_RULE_VERSION,
        revision=1,
        revisions=(revision,),
        observation_ids=(),
        run_id=run_id,
        case_ids=(case,),
    )


def open_case(
    *,
    account_key: str,
    workspace_id: str,
    origin: str,
    origin_ref: str,
    question: str,
    run_id: str,
    finding: FindingRecord | None = None,
    finding_entity: tuple[str, str] | None = None,
    error_signature: str | None = None,
) -> tuple[Case, FindingRecord | None]:
    """Open a case; a standalone case also creates its ``case:<kind>`` finding.

    Args:
        account_key / workspace_id: Scope of the case.
        origin: ``finding``, ``clue`` or ``drive_object``.
        origin_ref: The finding ID, a clue (``job:<id>``, ``query:<id>``,
            ``pipeline:<id>``, ``run:<id>``) or ``drive:<id>``.
        question: Host free text (≤ 500 chars; emails/credentials rejected).
        run_id: The run opening the case.
        finding: The origin finding (``origin="finding"`` only, possibly loaded
            from another run folder).
        finding_entity: ``(entity_kind, entity_id)`` of a standalone case's
            finding; defaults to the clue's job/query/pipeline, else the
            workspace.
        error_signature: ``error_signature_v1`` of a run-level failure; becomes
            the ``sig:`` discriminator so unrelated failures stay separate.

    Returns:
        ``(case, created_finding)``; ``created_finding`` is ``None`` for a
        finding-origin case (the finding is revised by :func:`revise`).

    Raises:
        ValueError: On an invalid origin/ref, or a finding that does not match.
    """
    if origin == "finding":
        if finding is None or finding.finding_id != origin_ref:
            raise ValueError("a finding-origin case needs the finding it cites")
        if (finding.account_key, finding.workspace_id) != (account_key, workspace_id):
            raise ValueError(
                "the origin finding belongs to another account or workspace"
            )
        case = Case(
            case_id=case_id(account_key, origin_ref, run_id, question),
            account_key=account_key,
            workspace_id=workspace_id,
            origin=origin,
            origin_ref=origin_ref,
            finding_id=finding.finding_id,
            target_entity_kind=finding.entity_kind,
            target_entity_id=finding.entity_id,
            question=question,
            hypotheses=(),
            evidence_revisions=(),
            state="open",
            opened_run_id=run_id,
            run_id=run_id,
        )
        return case, None
    if finding is not None:
        raise ValueError(f"a {origin} case creates its own finding")
    cid = case_id(account_key, origin_ref, run_id, question)
    target_kind, target_id = _target(origin, origin_ref)
    created = _case_finding(
        account_key=account_key,
        workspace_id=workspace_id,
        target_kind=target_kind,
        target_id=target_id,
        entity=finding_entity,
        error_signature=error_signature,
        case=cid,
        run_id=run_id,
    )
    case = Case(
        case_id=cid,
        account_key=account_key,
        workspace_id=workspace_id,
        origin=origin,
        origin_ref=origin_ref,
        finding_id=created.finding_id,
        target_entity_kind=target_kind,
        target_entity_id=target_id,
        question=question,
        hypotheses=(),
        evidence_revisions=(),
        state="open",
        opened_run_id=run_id,
        run_id=run_id,
    )
    return case, created


def _union(*groups: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(x for g in groups for x in g))


def revise(
    case: Case,
    finding: FindingRecord,
    *,
    run_id: str,
    observations: Sequence[Observation],
    evidence_ids: Sequence[str],
    gaps: Sequence[str],
    hypothesis: Mapping[str, Any] | None = None,
    cause_confidence: str | None = None,
) -> tuple[Case, FindingRecord]:
    """Record one investigation step on the case and its finding.

    Args:
        case: The case being revised.
        finding: The case's finding (latest revision, from any run folder).
        run_id: The run recording the revision.
        observations: Reconstruction/acquisition observations of this step
            (``method_version="acquisition_v1"`` only).
        evidence_ids: Evidence registered by this step.
        gaps: Codes of evidence that could not be acquired (e.g. ``job_run_output``).
        hypothesis: ``{hypothesis_id, statement, status, evidence_ids}``; replaces
            the case hypothesis of the same ID in place, else is appended.
        cause_confidence: Host-set ``hypothesis`` / ``supported``; ``None`` keeps
            the finding's current value.

    Returns:
        ``(case, finding)``: the case with one more evidence revision, and the
        same finding / episode with one more ``investigated`` revision.

    Raises:
        ValueError: A finding other than the case's, a non-acquisition
            observation, or ``supported`` without a supported hypothesis citing
            evidence.
    """
    if finding.finding_id != case.finding_id:
        raise ValueError(
            f"case {case.case_id} revises finding {case.finding_id}, not {finding.finding_id}"
        )
    foreign = [
        o.observation_id for o in observations if o.method_version != ACQUISITION_METHOD
    ]
    if foreign:
        raise ValueError(
            f"case observations must use method_version {ACQUISITION_METHOD!r}: {foreign}"
        )
    hypotheses = list(case.hypotheses)
    if hypothesis is not None:
        hid = hypothesis.get("hypothesis_id")
        slot = next(
            (i for i, h in enumerate(hypotheses) if h["hypothesis_id"] == hid), None
        )
        if slot is None:
            hypotheses.append(dict(hypothesis))
        else:  # a revised hypothesis keeps its position
            hypotheses[slot] = dict(hypothesis)
    cause = cause_confidence or finding.cause_confidence
    if cause == "supported" and not any(
        h["status"] == "supported" and h["evidence_ids"] for h in hypotheses
    ):
        raise ValueError(
            "cause_confidence 'supported' needs a supported hypothesis citing evidence"
        )
    obs_ids = tuple(o.observation_id for o in observations)
    new_case = replace(
        case,
        hypotheses=tuple(hypotheses),
        evidence_revisions=(
            *case.evidence_revisions,
            {
                "revision": len(case.evidence_revisions) + 1,
                "run_id": run_id,
                "evidence_ids": tuple(evidence_ids),
                "observation_ids": obs_ids,
                "gaps": tuple(gaps),
            },
        ),
        run_id=run_id,
    )
    entry = FindingRevision(
        revision=finding.revision + 1,
        run_id=run_id,
        reason="investigated",
        severity=finding.severity,
        symptom_confidence=finding.symptom_confidence,
        cause_confidence=cause,
        observation_ids=obs_ids,
        evidence_ids=tuple(evidence_ids),
        case_id=case.case_id,
    )
    revised = replace(
        finding,
        revision=entry.revision,
        revisions=(*finding.revisions, entry),
        cause_confidence=cause,
        evidence_ids=_union(finding.evidence_ids, evidence_ids),
        case_ids=_union(finding.case_ids, (case.case_id,)),
        run_id=run_id,
    )
    return new_case, revised
