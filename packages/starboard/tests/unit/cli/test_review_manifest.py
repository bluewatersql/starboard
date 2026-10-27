# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``starboard review`` findings-manifest CLI helpers.

Covers the recurrence-loop wiring in ``review_command``: writing a v2
findings-manifest from a review, and the version-discriminating ``--since``
loader that returns a v1 snapshot or a v2 manifest. All local-file only —
read-only w.r.t. the customer workspace.
"""

from __future__ import annotations

import json

import pytest
from starboard.cli.cli.review_command import _load_since, _write_manifest
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
    FindingsManifest,
    ReviewSnapshot,
)


def _review() -> WorkloadReview:
    finding = ReviewFinding(
        finding=Finding(
            id="warehouse_auto_stop_disabled::wh-1",
            severity=Severity.HIGH,
            category="warehouse",
            summary="auto-stop disabled",
            rationale="r",
            current_state="bad",
            suggested_fix="good",
            impact=3,
            effort=Effort.S,
            rule_id="warehouse_auto_stop_disabled",
            location=Location(entity="wh-1", entity_type="warehouse"),
        ),
        evidence=(
            EvidenceRef(query_id="W-W02", row_index=0, row={"total_dbus": 42600}),
        ),
    )
    return WorkloadReview(
        workspace="e2-demo-field-eng",
        requested_domains=("warehouse",),
        findings=(finding,),
    )


@pytest.mark.unit
class TestReviewManifestCli:
    def test_write_manifest_produces_v2_record(self, tmp_path) -> None:
        path = tmp_path / "findings-manifest.json"
        _write_manifest(
            _review(), str(path), lookback_days=30, workspace="e2-demo-field-eng"
        )
        payload = json.loads(path.read_text())
        assert payload["snapshot_version"] == "2.0"
        assert payload["lookback_days"] == 30
        assert payload["workspace"] == "e2-demo-field-eng"
        rec = payload["findings"][0]
        assert rec["composite_key"] == "warehouse_auto_stop_disabled::wh-1"
        assert rec["entity_id"] == "wh-1"
        assert rec["evidence_dbu_estimate"] == 42600.0

    def test_load_since_returns_manifest_for_v2(self, tmp_path) -> None:
        path = tmp_path / "manifest.json"
        _write_manifest(_review(), str(path), lookback_days=30, workspace="ws")
        loaded = _load_since(str(path))
        assert isinstance(loaded, FindingsManifest)
        assert loaded.findings[0].composite_key == (
            "warehouse_auto_stop_disabled::wh-1"
        )

    def test_load_since_returns_snapshot_for_v1(self, tmp_path) -> None:
        path = tmp_path / "snapshot.json"
        snap = ReviewSnapshot.from_review(_review())
        path.write_text(json.dumps(snap.model_dump(mode="json")))
        loaded = _load_since(str(path))
        assert isinstance(loaded, ReviewSnapshot)
        assert loaded.finding_ids == ("warehouse_auto_stop_disabled::wh-1",)
