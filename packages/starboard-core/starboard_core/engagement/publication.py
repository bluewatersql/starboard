# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Report audience gate and publication state machine.

Pure functions, no I/O. States: ``draft -> ready -> (blocked_audience |
approved) -> pending_delivery -> delivered``.

- A ``customer`` revision citing any ``internal_only`` evidence or observation,
  or any citation that cannot be resolved, is ``blocked_audience`` (fail
  closed, D-14).
- The run's source mode also gates ``customer`` revisions (D4-6): never on an
  ``internal_only`` run; on a ``hybrid`` (or ``unknown``) run only as a
  derivative of an exact ``internal`` revision.
- An approval binds ``(report_id, revision, object_md5)``; unattended runs
  cannot approve. Who may approve is policy, not code (D-21).
- Only a verified, non-Slack receipt delivers (D-22). ``customer`` delivery also
  needs a matching approval; ``internal`` revisions do not.
- Run-level publication is ``complete`` iff the latest revision of every report
  that requires delivery is delivered; ``skipped`` when there is none.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Literal

from starboard_core.engagement.policy import SourceMode
from starboard_core.engagement.records import (
    Approval,
    DeliveryReceipt,
    EvidenceRef,
    Observation,
    ReportRevision,
)

__all__ = [
    "allowed_audiences",
    "approval_matches",
    "audience_gate",
    "can_approve",
    "can_deliver",
    "publication_state",
    "receipt_delivers",
    "revision_state",
    "undelivered_reports",
]

_SHAREABLE = "customer_shareable"
_UNDERIVABLE = frozenset({"draft", "blocked_audience"})


_DERIVATIVE_MODES = frozenset({SourceMode.HYBRID, SourceMode.UNKNOWN})


def allowed_audiences(source_mode: SourceMode) -> tuple[str, ...]:
    """The report audiences a run of ``source_mode`` may register as deliverable.

    ``internal_only`` runs allow only ``internal``. Every other mode allows
    ``customer`` too (on ``hybrid``/``unknown`` only as a derivative of an
    ``internal`` revision; see :func:`audience_gate`).
    """
    if SourceMode(source_mode) is SourceMode.INTERNAL_ONLY:
        return ("internal",)
    return ("internal", "customer")


def _source_reason(
    revision: ReportRevision,
    source_mode: SourceMode,
    source_revision: ReportRevision | None,
) -> str | None:
    """The run-context reason a ``customer`` revision is blocked, if any."""
    mode = SourceMode(source_mode)
    if mode is SourceMode.INTERNAL_ONLY:
        return "internal_only_run"
    if mode not in _DERIVATIVE_MODES:
        return None
    if revision.derived_from is None:
        return "derivative_required"
    if (
        source_revision is None
        or f"{source_revision.report_id}@{source_revision.revision}"
        != revision.derived_from
        or source_revision.report_id == revision.report_id
        or source_revision.audience != "internal"
    ):
        return "derivative_source_not_internal"
    return None


def audience_gate(
    revision: ReportRevision,
    evidence: Mapping[str, EvidenceRef],
    observations: Mapping[str, Observation],
    *,
    source_mode: SourceMode,
    source_revision: ReportRevision | None,
) -> tuple[str, tuple[str, ...]]:
    """Return ``(state, blocked_reasons)`` for ``revision``.

    ``internal`` revisions are always ``("ready", ())``. For ``customer``
    revisions the run context is checked first, giving at most one leading
    reason:

    - ``internal_only_run``: the run's ``source_mode`` is ``internal_only``;
    - ``derivative_required``: a ``hybrid`` (or ``unknown``) run and
      ``revision.derived_from`` is ``None``;
    - ``derivative_source_not_internal``: a ``hybrid`` (or ``unknown``) run and
      ``source_revision`` is missing, is not the exact revision named by
      ``derived_from``, is the same report, or is not ``audience == "internal"``
      (fail closed).

    ``customer_workspace`` runs need no derivative. Then every cited evidence
    ID, every cited observation, and every evidence ID those observations rest
    on must resolve and be ``customer_shareable``. Those reasons are
    ``internal_only_evidence:<id>``, ``unknown_evidence:<id>``,
    ``internal_only_observation:<id>`` and ``unknown_observation:<id>``, in
    citation order, deduplicated.
    """
    if revision.audience != "customer":
        return ("ready", ())
    reasons: list[str] = []
    lead = _source_reason(revision, source_mode, source_revision)
    if lead is not None:
        reasons.append(lead)

    def add(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    def check_evidence(eid: str) -> None:
        ref = evidence.get(eid)
        if ref is None:
            add(f"unknown_evidence:{eid}")
        elif ref.audience_class != _SHAREABLE:
            add(f"internal_only_evidence:{eid}")

    for eid in revision.cited_evidence_ids:
        check_evidence(eid)
    for oid in revision.cited_observation_ids:
        obs = observations.get(oid)
        if obs is None:
            add(f"unknown_observation:{oid}")
            continue
        if obs.audience_class != _SHAREABLE:
            add(f"internal_only_observation:{oid}")
        for eid in obs.evidence_ids:
            check_evidence(eid)
    if reasons:
        return ("blocked_audience", tuple(reasons))
    return ("ready", ())


def can_approve(revision: ReportRevision, *, unattended: bool) -> bool:
    """Only an attended operator may approve, and only a ``ready`` revision."""
    return not unattended and revision.state == "ready"


def approval_matches(revision: ReportRevision, approval: Approval) -> bool:
    """True when ``approval`` binds this exact revision and object MD5."""
    return (
        approval.report_id == revision.report_id
        and approval.revision == revision.revision
        and approval.object_md5 == revision.object_ref.md5
    )


def _receipt_for(revision: ReportRevision, receipt: DeliveryReceipt) -> bool:
    return (
        receipt.report_id == revision.report_id
        and receipt.revision == revision.revision
        and receipt.object_md5 == revision.object_ref.md5
    )


def receipt_delivers(revision: ReportRevision, receipt: DeliveryReceipt) -> bool:
    """True for a verified, non-Slack receipt of this exact revision (D-22)."""
    return (
        _receipt_for(revision, receipt)
        and receipt.verified
        and receipt.channel != "slack"
    )


def can_deliver(revision: ReportRevision, approvals: Iterable[Approval]) -> bool:
    """``customer`` needs a matching approval; ``internal`` needs none.

    ``draft`` and ``blocked_audience`` revisions are never deliverable.
    """
    if revision.state in _UNDERIVABLE:
        return False
    if revision.audience != "customer":
        return True
    return any(approval_matches(revision, a) for a in approvals)


def revision_state(
    revision: ReportRevision,
    approvals: Iterable[Approval],
    receipts: Iterable[DeliveryReceipt],
) -> str:
    """Derive the current state of one revision from approvals and receipts."""
    if revision.state in _UNDERIVABLE:
        return revision.state
    approved = any(approval_matches(revision, a) for a in approvals)
    if revision.audience == "customer" and not approved:
        return "ready"
    mine = [r for r in receipts if _receipt_for(revision, r)]
    if any(receipt_delivers(revision, r) for r in mine):
        return "delivered"
    if mine:
        return "pending_delivery"
    return "approved" if approved else "ready"


def publication_state(
    revisions: Sequence[ReportRevision],
    approvals: Sequence[Approval],
    receipts: Sequence[DeliveryReceipt],
) -> Literal["pending", "complete", "skipped"]:
    """Run-level publication state over the latest revision of each report."""
    due = [r for r in _latest(revisions, lambda r: (r.report_id, r.revision)) if r.requires_delivery]
    if not due:
        return "skipped"
    if all(revision_state(r, approvals, receipts) == "delivered" for r in due):
        return "complete"
    return "pending"


def _latest[T](items: Iterable[T], key: Callable[[T], tuple[str, int]]) -> list[T]:
    """The highest-revision item per report ID, in first-seen report order."""
    latest: dict[str, tuple[int, T]] = {}
    for item in items:
        report_id, revision = key(item)
        held = latest.get(report_id)
        if held is None or revision > held[0]:
            latest[report_id] = (revision, item)
    return [item for _, item in latest.values()]


def undelivered_reports(entries: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The manifest ``reports`` entries that still block run-level publication.

    Same rule as :func:`publication_state`, over the manifest's
    ``{report_id, revision, audience, state}`` summaries: only the latest
    revision of each report counts, and only ``customer`` reports require
    delivery (the internal run folder is itself the internal delivery).
    """
    latest = _latest(entries, lambda e: (str(e["report_id"]), int(e["revision"])))
    return [e for e in latest if e["audience"] == "customer" and e["state"] != "delivered"]
