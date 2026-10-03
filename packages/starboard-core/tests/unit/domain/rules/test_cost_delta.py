# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the run-over-run cost comparison engine (recurrence loop).

Proves the pure ``findings-manifest`` per-run record and the ``CostDelta``
classification (newly-expensive / regressed / improved / persisting), keyed on
``composite_key = rule_id + "::" + entity_id`` with per-entry DBU deltas. Pure
and read-only — the computation never touches a workspace.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.finding import (
    Effort,
    Finding,
    Location,
    Severity,
)
from starboard_core.domain.models.review import (
    EvidenceRef,
    ReviewFinding,
    WorkloadReview,
)
from starboard_core.domain.rules.action_rate import (
    MANIFEST_VERSION,
    CostDelta,
    FindingsManifest,
    compute_cost_delta,
    extract_evidence_dbu,
)


def _finding(
    *,
    rule_id: str,
    entity: str,
    severity: Severity = Severity.HIGH,
    dbu: float | None = None,
    entity_type: str = "warehouse",
) -> ReviewFinding:
    """Build a ReviewFinding mirroring the evaluator's id/location construction."""
    fid = f"{rule_id}::{entity}"
    row: dict = {"warehouse_id": entity}
    if dbu is not None:
        row["total_dbus"] = dbu
    return ReviewFinding(
        finding=Finding(
            id=fid,
            severity=severity,
            category="warehouse",
            summary=rule_id,
            rationale="r",
            current_state="bad",
            suggested_fix="good",
            impact=3,
            effort=Effort.S,
            rule_id=rule_id,
            location=Location(entity=entity, entity_type=entity_type),
        ),
        evidence=(EvidenceRef(query_id="W-W02", row_index=0, row=row),),
    )


def _review(*findings: ReviewFinding, workspace: str = "acme") -> WorkloadReview:
    return WorkloadReview(
        workspace=workspace,
        requested_domains=("warehouse",),
        findings=tuple(findings),
    )


def _manifest(
    *findings: ReviewFinding,
    run_date: str = "2026-09-18",
    products_dbu: dict[str, float] | None = None,
) -> FindingsManifest:
    return FindingsManifest.from_review(
        _review(*findings),
        run_date=run_date,
        lookback_days=30,
        products_dbu=products_dbu,
    )


# --- extract_evidence_dbu -------------------------------------------------- #
@pytest.mark.unit
class TestExtractEvidenceDbu:
    def test_reads_absolute_dbu_columns(self) -> None:
        assert extract_evidence_dbu({"total_dbus": 42600}) == 42600.0
        assert extract_evidence_dbu({"dbus": 51.0}) == 51.0
        assert extract_evidence_dbu({"dbus_consumed": 700}) == 700.0
        assert extract_evidence_dbu({"recoverable_dbus": 88}) == 88.0

    def test_ignores_percentage_and_unknown_columns(self) -> None:
        # wasted_dbu_pct / auto_stop_waste_pct are percentages, not DBU.
        assert extract_evidence_dbu({"wasted_dbu_pct": 40.0}) is None
        assert extract_evidence_dbu({"auto_stop_waste_pct": 80.0}) is None
        assert extract_evidence_dbu({"shuffle_gb": 12.0}) is None
        assert extract_evidence_dbu({}) is None

    def test_string_numbers_coerce(self) -> None:
        assert extract_evidence_dbu({"total_dbus": "1234.5"}) == 1234.5

    def test_priority_prefers_explicit_estimate(self) -> None:
        row = {"evidence_dbu_estimate": 10, "total_dbus": 999}
        assert extract_evidence_dbu(row) == 10.0


# --- FindingsManifest.from_review ------------------------------------------ #
@pytest.mark.unit
class TestFindingsManifest:
    def test_captures_per_finding_record(self) -> None:
        m = _manifest(
            _finding(rule_id="warehouse_auto_stop_disabled", entity="wh-1", dbu=42600),
        )
        assert m.snapshot_version == MANIFEST_VERSION
        assert m.run_date == "2026-09-18"
        assert m.workspace == "acme"
        assert m.lookback_days == 30
        assert len(m.findings) == 1
        rec = m.findings[0]
        assert rec.rule_id == "warehouse_auto_stop_disabled"
        assert rec.entity_id == "wh-1"
        assert rec.severity == "high"
        assert rec.evidence_dbu_estimate == 42600.0
        assert rec.query_id == "W-W02"
        assert rec.score == pytest.approx(4.5)  # (3*3)/2

    def test_composite_key_is_rule_plus_entity(self) -> None:
        rec = _manifest(
            _finding(rule_id="r1", entity="e1"),
        ).findings[0]
        assert rec.composite_key == "r1::e1"
        # equals finding.id for rule-produced findings
        assert rec.composite_key == rec.id

    def test_composite_key_falls_back_to_id_without_rule_id(self) -> None:
        rf = ReviewFinding(
            finding=Finding(
                id="opaque-hash-123",
                severity=Severity.MEDIUM,
                category="jobs",
                summary="s",
                rationale="r",
                current_state="bad",
                suggested_fix="good",
                impact=2,
                effort=Effort.S,
            )
        )
        rec = _manifest(rf).findings[0]
        assert rec.composite_key == "opaque-hash-123"

    def test_null_dbu_when_no_dbu_column(self) -> None:
        rec = _manifest(
            _finding(rule_id="r1", entity="e1", dbu=None),
        ).findings[0]
        assert rec.evidence_dbu_estimate is None

    def test_roundtrips_through_json(self) -> None:
        m = _manifest(
            _finding(rule_id="r1", entity="e1", dbu=100),
            products_dbu={"VECTOR_SEARCH": 1655165.0},
        )
        restored = FindingsManifest.model_validate(m.model_dump(mode="json"))
        assert restored.findings[0].composite_key == "r1::e1"
        assert restored.products_dbu["VECTOR_SEARCH"] == 1655165.0


# --- compute_cost_delta ---------------------------------------------------- #
@pytest.mark.unit
class TestCostDeltaClassification:
    def test_newly_expensive_above_threshold(self) -> None:
        prev = _manifest()
        curr = _manifest(_finding(rule_id="r", entity="e", dbu=8200))
        delta = compute_cost_delta(prev, curr)
        assert [e.composite_key for e in delta.newly_expensive] == ["r::e"]
        assert delta.newly_expensive[0].current_dbu == 8200.0
        assert not delta.new_low_cost

    def test_appeared_below_threshold_is_new_low_cost(self) -> None:
        prev = _manifest()
        curr = _manifest(_finding(rule_id="r", entity="e", dbu=100))
        delta = compute_cost_delta(prev, curr)
        assert not delta.newly_expensive
        assert [e.composite_key for e in delta.new_low_cost] == ["r::e"]

    def test_appeared_null_dbu_is_new_low_cost(self) -> None:
        prev = _manifest()
        curr = _manifest(_finding(rule_id="r", entity="e", dbu=None))
        delta = compute_cost_delta(prev, curr)
        assert not delta.newly_expensive
        assert [e.composite_key for e in delta.new_low_cost] == ["r::e"]

    def test_regressed_on_dbu_increase(self) -> None:
        prev = _manifest(_finding(rule_id="r", entity="e", dbu=12400))
        curr = _manifest(_finding(rule_id="r", entity="e", dbu=18200))
        delta = compute_cost_delta(prev, curr)
        assert [e.composite_key for e in delta.regressed] == ["r::e"]
        entry = delta.regressed[0]
        assert entry.prior_dbu == 12400.0
        assert entry.current_dbu == 18200.0
        assert entry.dbu_delta == pytest.approx(5800.0)
        assert entry.dbu_delta_pct == pytest.approx(0.4677, abs=1e-3)

    def test_regressed_on_severity_worsening(self) -> None:
        prev = _manifest(
            _finding(rule_id="r", entity="e", dbu=1000, severity=Severity.MEDIUM)
        )
        curr = _manifest(
            _finding(rule_id="r", entity="e", dbu=1000, severity=Severity.CRITICAL)
        )
        delta = compute_cost_delta(prev, curr)
        assert [e.composite_key for e in delta.regressed] == ["r::e"]
        assert delta.regressed[0].severity_changed == "worsened"

    def test_improved_on_resolution(self) -> None:
        prev = _manifest(_finding(rule_id="r", entity="e", dbu=191346))
        curr = _manifest()
        delta = compute_cost_delta(prev, curr)
        assert [e.composite_key for e in delta.improved] == ["r::e"]
        entry = delta.improved[0]
        assert entry.prior_dbu == 191346.0
        assert entry.current_dbu is None

    def test_improved_on_cost_reduction(self) -> None:
        prev = _manifest(_finding(rule_id="r", entity="e", dbu=10000))
        curr = _manifest(_finding(rule_id="r", entity="e", dbu=5000))
        delta = compute_cost_delta(prev, curr)
        assert [e.composite_key for e in delta.improved] == ["r::e"]

    def test_persisting_within_threshold(self) -> None:
        prev = _manifest(_finding(rule_id="r", entity="e", dbu=10000))
        curr = _manifest(_finding(rule_id="r", entity="e", dbu=10500))
        delta = compute_cost_delta(prev, curr)
        assert [e.composite_key for e in delta.persisting] == ["r::e"]
        assert not delta.regressed
        assert not delta.improved

    def test_null_dbu_classifies_on_severity_only(self) -> None:
        # Same severity, no DBU on either side → persisting with a note.
        prev = _manifest(_finding(rule_id="r", entity="e", dbu=None))
        curr = _manifest(_finding(rule_id="r", entity="e", dbu=None))
        delta = compute_cost_delta(prev, curr)
        assert [e.composite_key for e in delta.persisting] == ["r::e"]
        assert delta.persisting[0].note is not None

    def test_null_dbu_severity_improvement_is_improved(self) -> None:
        prev = _manifest(
            _finding(rule_id="r", entity="e", dbu=None, severity=Severity.CRITICAL)
        )
        curr = _manifest(
            _finding(rule_id="r", entity="e", dbu=None, severity=Severity.LOW)
        )
        delta = compute_cost_delta(prev, curr)
        assert [e.composite_key for e in delta.improved] == ["r::e"]
        assert delta.improved[0].severity_changed == "improved"

    def test_empty_prior_run_all_appear(self) -> None:
        prev = _manifest()
        curr = _manifest(
            _finding(rule_id="r", entity="big", dbu=9000),
            _finding(rule_id="r", entity="small", dbu=10),
        )
        delta = compute_cost_delta(prev, curr)
        assert delta.prior_count == 0
        assert delta.current_count == 2
        assert [e.composite_key for e in delta.newly_expensive] == ["r::big"]
        assert [e.composite_key for e in delta.new_low_cost] == ["r::small"]
        assert not delta.regressed
        assert not delta.improved
        assert not delta.persisting

    def test_reappeared_item_classifies_as_newly_expensive(self) -> None:
        # At the two-manifest level, a finding absent from prev but present in
        # curr (having resolved in an earlier run) reads as newly-expensive.
        prev = _manifest(_finding(rule_id="r", entity="other", dbu=100))
        curr = _manifest(_finding(rule_id="r", entity="back", dbu=7000))
        delta = compute_cost_delta(prev, curr)
        assert [e.composite_key for e in delta.newly_expensive] == ["r::back"]
        assert [e.composite_key for e in delta.improved] == ["r::other"]

    def test_products_dbu_delta(self) -> None:
        prev = _manifest(products_dbu={"VS": 100.0, "MS": 50.0})
        curr = _manifest(products_dbu={"VS": 120.0, "JOBS": 10.0})
        delta = compute_cost_delta(prev, curr)
        assert delta.products_dbu_delta["VS"] == pytest.approx(20.0)
        assert delta.products_dbu_delta["MS"] == pytest.approx(-50.0)
        assert delta.products_dbu_delta["JOBS"] == pytest.approx(10.0)

    def test_summary_counts_and_json_roundtrip(self) -> None:
        prev = _manifest(
            _finding(rule_id="r", entity="stay", dbu=10000),
            _finding(rule_id="r", entity="gone", dbu=5000),
        )
        curr = _manifest(
            _finding(rule_id="r", entity="stay", dbu=10200),
            _finding(rule_id="r", entity="new", dbu=9000),
        )
        delta = compute_cost_delta(prev, curr)
        assert delta.newly_expensive_count == 1
        assert delta.improved_count == 1
        assert delta.persisting_count == 1
        restored = CostDelta.model_validate(delta.model_dump(mode="json"))
        assert restored.newly_expensive_count == 1
