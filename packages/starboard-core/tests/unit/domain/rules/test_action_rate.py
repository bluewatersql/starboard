# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the Action-Rate re-scan loop (Phase-3 D1c / D-3.3).

Proves the pure snapshot + resolved-rate delta: a snapshot captures a review's
finding ids; a later review's delta reports which prior findings resolved, which
persist, and which are new, with a correct resolved rate. Read-only — the
computation never touches a workspace.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.finding import Effort, Finding, Severity
from starboard_core.domain.models.review import ReviewFinding, WorkloadReview
from starboard_core.domain.rules.action_rate import (
    ReviewSnapshot,
    compute_action_rate,
)


def _review(*ids: str, workspace: str | None = "acme") -> WorkloadReview:
    findings = tuple(
        ReviewFinding(
            finding=Finding(
                id=fid,
                severity=Severity.HIGH,
                category="jobs",
                summary=fid,
                rationale="r",
                current_state="bad",
                suggested_fix="good",
                impact=3,
                effort=Effort.S,
            )
        )
        for fid in ids
    )
    return WorkloadReview(
        workspace=workspace,
        requested_domains=("jobs",),
        findings=findings,
    )


@pytest.mark.unit
class TestReviewSnapshot:
    def test_from_review_captures_sorted_unique_ids(self) -> None:
        snap = ReviewSnapshot.from_review(
            _review("b", "a", "a"), created_at="2026-01-01T00:00:00Z"
        )
        assert snap.finding_ids == ("a", "b")
        assert snap.finding_count == 2
        assert snap.workspace == "acme"
        assert snap.requested_domains == ("jobs",)
        assert snap.created_at == "2026-01-01T00:00:00Z"

    def test_snapshot_roundtrips_through_json(self) -> None:
        snap = ReviewSnapshot.from_review(_review("x", "y"))
        restored = ReviewSnapshot.model_validate(snap.model_dump(mode="json"))
        assert restored.finding_ids == ("x", "y")


@pytest.mark.unit
class TestActionRateDelta:
    def test_resolved_rate_and_partitions(self) -> None:
        prior = ReviewSnapshot.from_review(_review("a", "b", "c", "d"))
        # b, d resolved; a, c persist; e is new.
        current = _review("a", "c", "e")
        delta = compute_action_rate(prior, current)
        assert delta.prior_count == 4
        assert delta.current_count == 3
        assert delta.resolved_ids == ("b", "d")
        assert delta.persisting_ids == ("a", "c")
        assert delta.new_ids == ("e",)
        assert delta.resolved_count == 2
        assert delta.resolved_rate == 0.5

    def test_all_resolved_is_full_rate(self) -> None:
        prior = ReviewSnapshot.from_review(_review("a", "b"))
        delta = compute_action_rate(prior, _review())
        assert delta.resolved_rate == 1.0
        assert delta.resolved_ids == ("a", "b")

    def test_empty_prior_is_zero_rate_not_error(self) -> None:
        prior = ReviewSnapshot.from_review(_review())
        delta = compute_action_rate(prior, _review("a"))
        assert delta.prior_count == 0
        assert delta.resolved_rate == 0.0
        assert delta.new_ids == ("a",)

    def test_none_resolved_when_all_persist(self) -> None:
        prior = ReviewSnapshot.from_review(_review("a", "b"))
        delta = compute_action_rate(prior, _review("a", "b"))
        assert delta.resolved_rate == 0.0
        assert delta.persisting_ids == ("a", "b")
