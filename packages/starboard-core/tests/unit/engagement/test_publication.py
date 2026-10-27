# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the report audience gate and publication state machine (P2-G7)."""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement.policy import SourceMode
from starboard_core.engagement.publication import (
    allowed_audiences,
    approval_matches,
    audience_gate,
    can_approve,
    can_deliver,
    publication_state,
    revision_state,
    undelivered_reports,
)
from starboard_core.engagement.records import (
    Approval,
    DeliveryReceipt,
    EvidenceRef,
    Observation,
    ReportRevision,
    StorageRef,
    evidence_id,
    observation_id,
)

RID = "20261007_12345678-1234-4234-8234-123456789abc"
MD5 = "0" * 32
MD5_B = "1" * 32


def ref(path: str = "deliverables/report.md", md5: str = MD5) -> StorageRef:
    return StorageRef(
        path=path,
        object_id="obj-" + path.replace("/", "-"),
        revision="r1",
        md5=md5,
        size=10,
        mime_type="text/markdown",
    )


def ev(path: str, source_kind: str = "customer_workspace") -> EvidenceRef:
    r = ref(path)
    audience = (
        "internal_only" if source_kind.startswith("internal_") else "customer_shareable"
    )
    return EvidenceRef(
        evidence_id=evidence_id(RID, path, MD5),
        run_id=RID,
        storage_ref=r,
        source_kind=source_kind,
        scope_workspace_ids=("123",),
        producer="discovery",
        row_count=1,
        truncated=False,
        acquired_at="2026-10-08T09:00:00+00:00",
        audience_class=audience,
        method_version="v1",
    )


def ob(
    entity_id: str,
    source_kind: str = "customer_workspace",
    evidence_ids: tuple[str, ...] = (),
) -> Observation:
    audience = (
        "internal_only" if source_kind.startswith("internal_") else "customer_shareable"
    )
    key = (
        "acme",
        "123",
        "other",
        "job",
        entity_id,
        "dbus",
        "2026-10-01",
        "2026-10-31",
        "v1",
    )
    return Observation(
        observation_id=observation_id(key),
        run_id=RID,
        account_key="acme",
        workspace_id="123",
        family="other",
        entity_kind="job",
        entity_id=entity_id,
        metric="dbus",
        value=1.0,
        unit="DBU",
        grain="interval",
        method_version="v1",
        interval_start="2026-10-01",
        interval_end="2026-10-31",
        as_of="2026-11-01T00:00:00+00:00",
        coverage="complete",
        coverage_fraction=None,
        state="measured",
        unknown_reason=None,
        evidence_ids=evidence_ids,
        source_kind=source_kind,
        audience_class=audience,
    )


def rev(**over: Any) -> ReportRevision:
    base: dict[str, Any] = {
        "report_id": "cost-review",
        "revision": 1,
        "audience": "customer",
        "object_ref": ref(),
        "cited_evidence_ids": (),
        "cited_observation_ids": (),
        "derived_from": None,
        "state": "ready",
        "blocked_reasons": (),
        "created_at": "2026-10-08T10:00:00+00:00",
    }
    base.update(over)
    return ReportRevision(**base)


def approval(**over: Any) -> Approval:
    base: dict[str, Any] = {
        "approval_id": "apr_1",
        "report_id": "cost-review",
        "revision": 1,
        "object_md5": MD5,
        "approver_principal_id": "user-1",
        "approved_at": "2026-10-08T11:00:00+00:00",
    }
    base.update(over)
    return Approval(**base)


def receipt(**over: Any) -> DeliveryReceipt:
    base: dict[str, Any] = {
        "receipt_id": "rcp_1",
        "report_id": "cost-review",
        "revision": 1,
        "object_md5": MD5,
        "channel": "google_doc",
        "destination_id": "dest",
        "delivered_object_id": "doc-1",
        "delivered_revision": None,
        "verified": True,
        "delivered_at": "2026-10-08T12:00:00+00:00",
    }
    base.update(over)
    return DeliveryReceipt(**base)


# ---- audience_gate -------------------------------------------------------------


def gate(
    r: ReportRevision,
    evidence: Any,
    observations: Any,
    *,
    source_mode: SourceMode = SourceMode.CUSTOMER_WORKSPACE,
    source_revision: ReportRevision | None = None,
) -> tuple[str, tuple[str, ...]]:
    return audience_gate(
        r,
        evidence,
        observations,
        source_mode=source_mode,
        source_revision=source_revision,
    )


CUST = ev("raw/customer.json")
INTERNAL = ev("raw/mirror.json", "internal_mirror")
EVIDENCE = {CUST.evidence_id: CUST, INTERNAL.evidence_id: INTERNAL}


def test_customer_report_with_shareable_citations_is_ready() -> None:
    o = ob("j1", evidence_ids=(CUST.evidence_id,))
    r = rev(
        cited_evidence_ids=(CUST.evidence_id,),
        cited_observation_ids=(o.observation_id,),
    )
    assert gate(r, EVIDENCE, {o.observation_id: o}) == ("ready", ())


def test_customer_report_citing_internal_evidence_is_blocked() -> None:
    r = rev(cited_evidence_ids=(CUST.evidence_id, INTERNAL.evidence_id))
    assert gate(r, EVIDENCE, {}) == (
        "blocked_audience",
        (f"internal_only_evidence:{INTERNAL.evidence_id}",),
    )


def test_customer_report_citing_internal_observation_is_blocked() -> None:
    o = ob("j1", "internal_telemetry", evidence_ids=(INTERNAL.evidence_id,))
    r = rev(cited_observation_ids=(o.observation_id,))
    state, reasons = gate(r, EVIDENCE, {o.observation_id: o})
    assert state == "blocked_audience"
    assert reasons == (
        f"internal_only_observation:{o.observation_id}",
        f"internal_only_evidence:{INTERNAL.evidence_id}",
    )


def test_unknown_citations_fail_closed() -> None:
    o = ob("j2", evidence_ids=("ev_" + "f" * 24,))
    r = rev(
        cited_evidence_ids=("ev_" + "e" * 24,),
        cited_observation_ids=(o.observation_id, "obs_x"),
    )
    state, reasons = gate(r, EVIDENCE, {o.observation_id: o})
    assert state == "blocked_audience"
    assert reasons == (
        "unknown_evidence:ev_" + "e" * 24,
        "unknown_evidence:ev_" + "f" * 24,
        "unknown_observation:obs_x",
    )


def test_derivative_must_cite_only_shareable() -> None:
    r = rev(
        derived_from="internal-review@2", cited_evidence_ids=(INTERNAL.evidence_id,)
    )
    assert gate(r, EVIDENCE, {})[0] == "blocked_audience"


def test_internal_audience_is_never_blocked() -> None:
    r = rev(
        audience="internal", cited_evidence_ids=(INTERNAL.evidence_id, "ev_unknown")
    )
    assert gate(r, EVIDENCE, {}) == ("ready", ())


def test_reasons_are_deduplicated() -> None:
    r = rev(cited_evidence_ids=(INTERNAL.evidence_id, INTERNAL.evidence_id))
    assert gate(r, EVIDENCE, {})[1] == (
        f"internal_only_evidence:{INTERNAL.evidence_id}",
    )


# ---- source-mode-aware gate (D4-6) ---------------------------------------------

SOURCE = rev(report_id="internal-review", revision=2, audience="internal")


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (SourceMode.INTERNAL_ONLY, ("internal",)),
        (SourceMode.HYBRID, ("internal", "customer")),
        (SourceMode.CUSTOMER_WORKSPACE, ("internal", "customer")),
        (SourceMode.UNKNOWN, ("internal", "customer")),
    ],
)
def test_allowed_audiences(mode: SourceMode, expected: tuple[str, ...]) -> None:
    assert allowed_audiences(mode) == expected


def test_audience_gate_run_context_is_keyword_only_and_required() -> None:
    r = rev()
    with pytest.raises(TypeError):
        audience_gate(r, EVIDENCE, {})  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        audience_gate(r, EVIDENCE, {}, SourceMode.HYBRID, None)  # type: ignore[misc]


def test_customer_on_internal_only_run_is_blocked_first() -> None:
    r = rev(cited_evidence_ids=(INTERNAL.evidence_id,))
    assert gate(r, EVIDENCE, {}, source_mode=SourceMode.INTERNAL_ONLY) == (
        "blocked_audience",
        ("internal_only_run", f"internal_only_evidence:{INTERNAL.evidence_id}"),
    )


def test_customer_on_internal_only_run_is_blocked_even_when_shareable() -> None:
    r = rev(cited_evidence_ids=(CUST.evidence_id,), derived_from="internal-review@2")
    assert gate(
        r,
        EVIDENCE,
        {},
        source_mode=SourceMode.INTERNAL_ONLY,
        source_revision=SOURCE,
    ) == ("blocked_audience", ("internal_only_run",))


def test_hybrid_customer_without_derivative_is_blocked() -> None:
    r = rev(cited_evidence_ids=(CUST.evidence_id, INTERNAL.evidence_id))
    assert gate(r, EVIDENCE, {}, source_mode=SourceMode.HYBRID) == (
        "blocked_audience",
        ("derivative_required", f"internal_only_evidence:{INTERNAL.evidence_id}"),
    )


def test_hybrid_customer_derived_from_a_customer_source_is_blocked() -> None:
    src = rev(report_id="customer-a", revision=1, audience="customer")
    r = rev(cited_evidence_ids=(CUST.evidence_id,), derived_from="customer-a@1")
    assert gate(
        r, EVIDENCE, {}, source_mode=SourceMode.HYBRID, source_revision=src
    ) == ("blocked_audience", ("derivative_source_not_internal",))


@pytest.mark.parametrize(
    "source",
    [
        None,  # unresolved
        rev(report_id="internal-review", revision=3, audience="internal"),  # wrong rev
        rev(report_id="other", revision=2, audience="internal"),  # wrong report
    ],
)
def test_hybrid_unresolved_or_mismatched_source_fails_closed(
    source: ReportRevision | None,
) -> None:
    r = rev(cited_evidence_ids=(CUST.evidence_id,), derived_from="internal-review@2")
    assert gate(
        r, EVIDENCE, {}, source_mode=SourceMode.HYBRID, source_revision=source
    ) == ("blocked_audience", ("derivative_source_not_internal",))


def test_hybrid_internal_derivative_with_shareable_evidence_is_ready() -> None:
    o = ob("j1", evidence_ids=(CUST.evidence_id,))
    r = rev(
        cited_evidence_ids=(CUST.evidence_id,),
        cited_observation_ids=(o.observation_id,),
        derived_from="internal-review@2",
    )
    assert gate(
        r,
        EVIDENCE,
        {o.observation_id: o},
        source_mode=SourceMode.HYBRID,
        source_revision=SOURCE,
    ) == ("ready", ())


def test_hybrid_internal_derivative_still_checks_evidence() -> None:
    r = rev(
        cited_evidence_ids=(INTERNAL.evidence_id,), derived_from="internal-review@2"
    )
    assert gate(
        r, EVIDENCE, {}, source_mode=SourceMode.HYBRID, source_revision=SOURCE
    ) == ("blocked_audience", (f"internal_only_evidence:{INTERNAL.evidence_id}",))


def test_unknown_source_mode_needs_a_derivative_like_hybrid() -> None:
    r = rev(cited_evidence_ids=(CUST.evidence_id,))
    assert gate(r, EVIDENCE, {}, source_mode=SourceMode.UNKNOWN) == (
        "blocked_audience",
        ("derivative_required",),
    )


def test_customer_workspace_needs_no_derivative() -> None:
    r = rev(cited_evidence_ids=(CUST.evidence_id,))
    assert gate(r, EVIDENCE, {}, source_mode=SourceMode.CUSTOMER_WORKSPACE) == (
        "ready",
        (),
    )


@pytest.mark.parametrize("mode", list(SourceMode))
def test_internal_revision_is_ready_on_every_run(mode: SourceMode) -> None:
    r = rev(audience="internal", cited_evidence_ids=(INTERNAL.evidence_id,))
    assert gate(r, EVIDENCE, {}, source_mode=mode) == ("ready", ())


# ---- approval ------------------------------------------------------------------


def test_unattended_approve_refused() -> None:
    assert can_approve(rev(), unattended=False) is True
    assert can_approve(rev(), unattended=True) is False


@pytest.mark.parametrize(
    "r",
    [
        rev(state="draft"),
        rev(state="blocked_audience", blocked_reasons=("internal_only_evidence:x",)),
    ],
)
def test_only_ready_revisions_can_be_approved(r: ReportRevision) -> None:
    assert can_approve(r, unattended=False) is False


def test_approval_md5_mismatch() -> None:
    r = rev()
    assert approval_matches(r, approval()) is True
    assert approval_matches(r, approval(object_md5=MD5_B)) is False
    assert approval_matches(r, approval(revision=2)) is False
    assert approval_matches(r, approval(report_id="other")) is False
    # A changed object (new md5) needs a new revision and a new approval.
    changed = rev(revision=2, object_ref=ref(md5=MD5_B))
    assert revision_state(changed, [approval()], []) == "ready"
    assert can_deliver(changed, [approval()]) is False


def test_customer_deliver_requires_approval_internal_does_not() -> None:
    assert can_deliver(rev(), []) is False
    assert can_deliver(rev(), [approval()]) is True
    assert can_deliver(rev(audience="internal"), []) is True
    assert can_deliver(rev(state="draft", audience="internal"), []) is False


# ---- revision_state ------------------------------------------------------------


def test_revision_state_progression() -> None:
    r = rev()
    assert revision_state(r, [], []) == "ready"
    assert revision_state(r, [approval()], []) == "approved"
    failed = receipt(verified=False)
    assert revision_state(r, [approval()], [failed]) == "pending_delivery"
    assert (
        revision_state(r, [approval()], [failed, receipt(receipt_id="rcp_2")])
        == "delivered"
    )


def test_customer_receipt_without_approval_does_not_deliver() -> None:
    assert revision_state(rev(), [], [receipt()]) == "ready"


def test_slack_receipt_never_delivers() -> None:
    slack = receipt(channel="slack", verified=False)
    assert revision_state(rev(), [approval()], [slack]) == "pending_delivery"


def test_receipt_md5_must_match() -> None:
    assert (
        revision_state(rev(), [approval()], [receipt(object_md5=MD5_B)]) == "approved"
    )


def test_draft_and_blocked_are_terminal_for_derivation() -> None:
    blocked = rev(state="blocked_audience", blocked_reasons=("x",))
    assert revision_state(blocked, [approval()], [receipt()]) == "blocked_audience"
    assert revision_state(rev(state="draft"), [], []) == "draft"


def test_internal_revision_delivers_without_approval() -> None:
    r = rev(audience="internal")
    assert revision_state(r, [], [receipt()]) == "delivered"


# ---- publication_state ---------------------------------------------------------


def test_publication_skipped_without_customer_reports() -> None:
    assert publication_state([], [], []) == "skipped"
    assert publication_state([rev(audience="internal")], [], []) == "skipped"


def test_failed_delivery_is_pending() -> None:
    assert (
        publication_state([rev()], [approval()], [receipt(verified=False)]) == "pending"
    )
    assert publication_state([rev()], [approval()], []) == "pending"


def test_receipt_makes_publication_complete() -> None:
    assert publication_state([rev()], [approval()], [receipt()]) == "complete"


def test_publication_uses_latest_revision_per_report() -> None:
    r1 = rev()
    r2 = rev(revision=2, object_ref=ref(md5=MD5_B))
    # r1 delivered, but r2 supersedes it and is not delivered yet.
    assert publication_state([r1, r2], [approval()], [receipt()]) == "pending"
    a2 = approval(approval_id="apr_2", revision=2, object_md5=MD5_B)
    rc2 = receipt(receipt_id="rcp_2", revision=2, object_md5=MD5_B)
    assert publication_state([r2, r1], [approval(), a2], [receipt(), rc2]) == "complete"


def test_publication_needs_every_customer_report() -> None:
    other = rev(report_id="exec-summary")
    assert publication_state([rev(), other], [approval()], [receipt()]) == "pending"


def test_blocked_customer_report_keeps_publication_pending() -> None:
    blocked = rev(state="blocked_audience", blocked_reasons=("x",))
    assert publication_state([blocked], [], []) == "pending"


def _entry(rid: str, rev: int, audience: str, state: str) -> dict[str, Any]:
    return {"report_id": rid, "revision": rev, "audience": audience, "state": state}


def test_undelivered_reports_uses_latest_customer_revision() -> None:
    assert undelivered_reports(
        [_entry("r", 1, "customer", "ready"), _entry("r", 2, "customer", "delivered")]
    ) == []
    assert undelivered_reports(
        [_entry("i", 1, "internal", "ready"), _entry("c", 1, "customer", "delivered")]
    ) == []
    late = _entry("r", 2, "customer", "approved")
    assert undelivered_reports([late, _entry("r", 1, "customer", "delivered")]) == [late]
