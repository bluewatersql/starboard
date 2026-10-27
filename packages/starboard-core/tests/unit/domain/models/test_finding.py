# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the shared review ``Finding`` model + scorer (Phase-1 D3).

The ``Finding`` model is the kernel-tier output contract shared by the seed
rules and (later) the Phase-3 Workload Review flow. It must be pure pydantic
and stay kernel-clean (no databricks-sdk / openai / fastapi / mcp).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from starboard_core.domain.models.finding import (
    Bucket,
    Confidence,
    Effort,
    Finding,
    Location,
    Severity,
    bucket_for_score,
    dedupe_findings,
    score,
    score_and_bucket,
)

_CORE_DIR = Path(__file__).parents[4]


def _minimal_finding(**overrides: object) -> Finding:
    kwargs: dict[str, object] = {
        "id": "select_star_projection",
        "severity": Severity.HIGH,
        "category": "query",
        "summary": "SELECT * pulls every column",
        "rationale": "Wide projections read and shuffle unused columns.",
        "current_state": "SELECT * FROM sales",
        "suggested_fix": "SELECT order_id, amount FROM sales",
        "impact": 4,
        "effort": Effort.S,
    }
    kwargs.update(overrides)
    return Finding(**kwargs)  # type: ignore[arg-type]


@pytest.mark.unit
class TestFindingValidation:
    """The Finding model validates required fields and rejects bad enums."""

    def test_minimal_finding_validates(self) -> None:
        f = _minimal_finding()
        assert f.severity is Severity.HIGH
        assert f.effort is Effort.S
        assert f.impact == 4
        # confidence defaults to MEDIUM
        assert f.confidence is Confidence.MEDIUM
        # source is nullable and defaults to None (governance: no go/ links)
        assert f.source is None

    def test_missing_required_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Finding(  # type: ignore[call-arg]
                id="x",
                severity=Severity.LOW,
                category="query",
                # summary missing
                rationale="r",
                current_state="c",
                suggested_fix="s",
                impact=1,
                effort=Effort.XS,
            )

    def test_bad_severity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _minimal_finding(severity="urgent")

    def test_bad_effort_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _minimal_finding(effort="XXL")

    def test_impact_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _minimal_finding(impact=0)
        with pytest.raises(ValidationError):
            _minimal_finding(impact=6)

    def test_bad_good_aliases_accepted(self) -> None:
        # Harvested schema exposes current_state/bad and suggested_fix/good
        # as alias pairs (Isaac /review bad/good tables).
        f = Finding(  # type: ignore[call-arg]
            id="a",
            severity=Severity.MEDIUM,
            category="query",
            summary="s",
            rationale="r",
            bad="SELECT *",
            good="SELECT a, b",
            impact=3,
            effort=Effort.M,
        )
        assert f.current_state == "SELECT *"
        assert f.suggested_fix == "SELECT a, b"

    def test_location_optional_and_structured(self) -> None:
        f = _minimal_finding(
            location=Location(file="etl.sql", line=12, table="main.sales")
        )
        assert f.location is not None
        assert f.location.file == "etl.sql"
        assert f.location.table == "main.sales"
        # location is optional
        assert _minimal_finding().location is None


@pytest.mark.unit
class TestScorer:
    """score = (severity_weight x impact) / effort_points; then bucketed."""

    def test_severity_weights_and_effort_points(self) -> None:
        # Critical=4, High=3, Medium=2, Low=1 ; XS=1,S=2,M=3,L=4,XL=5
        # (4 * 5) / 1 = 20.0
        assert score(Severity.CRITICAL, 5, Effort.XS) == pytest.approx(20.0)
        # (1 * 1) / 5 = 0.2
        assert score(Severity.LOW, 1, Effort.XL) == pytest.approx(0.2)
        # (3 * 4) / 2 = 6.0
        assert score(Severity.HIGH, 4, Effort.S) == pytest.approx(6.0)

    @pytest.mark.parametrize(
        ("severity", "impact", "effort", "expected"),
        [
            # >= 20 -> Fix Immediately
            (Severity.CRITICAL, 5, Effort.XS, Bucket.FIX_IMMEDIATELY),
            # (4*5)/1 = 20 exactly -> Fix Immediately (inclusive)
            (Severity.CRITICAL, 4, Effort.XS, Bucket.THIS_SPRINT),  # 16 -> This Sprint
            # >= 10 -> This Sprint : (3*4)/1 = 12
            (Severity.HIGH, 4, Effort.XS, Bucket.THIS_SPRINT),
            # exactly 10 -> This Sprint : (2*5)/1 = 10
            (Severity.MEDIUM, 5, Effort.XS, Bucket.THIS_SPRINT),
            # >= 4 -> Backlog : (3*4)/2 = 6
            (Severity.HIGH, 4, Effort.S, Bucket.BACKLOG),
            # exactly 4 -> Backlog : (2*4)/2 = 4
            (Severity.MEDIUM, 4, Effort.S, Bucket.BACKLOG),
            # < 4 -> Nice to Have : (1*1)/5 = 0.2
            (Severity.LOW, 1, Effort.XL, Bucket.NICE_TO_HAVE),
        ],
    )
    def test_bucketing(
        self,
        severity: Severity,
        impact: int,
        effort: Effort,
        expected: Bucket,
    ) -> None:
        assert score_and_bucket(severity, impact, effort)[1] is expected

    def test_bucket_for_score_thresholds(self) -> None:
        assert bucket_for_score(20.0) is Bucket.FIX_IMMEDIATELY
        assert bucket_for_score(19.99) is Bucket.THIS_SPRINT
        assert bucket_for_score(10.0) is Bucket.THIS_SPRINT
        assert bucket_for_score(9.99) is Bucket.BACKLOG
        assert bucket_for_score(4.0) is Bucket.BACKLOG
        assert bucket_for_score(3.99) is Bucket.NICE_TO_HAVE

    def test_finding_score_and_bucket_properties(self) -> None:
        f = _minimal_finding(severity=Severity.HIGH, impact=4, effort=Effort.S)
        assert f.score == pytest.approx(6.0)
        assert f.bucket is Bucket.BACKLOG


@pytest.mark.unit
class TestDedup:
    """dedupe_findings merges same-location findings, keeping highest severity."""

    def test_dedupe_keeps_highest_severity_per_location(self) -> None:
        loc = Location(file="etl.sql", line=10)
        low = _minimal_finding(id="a", severity=Severity.LOW, location=loc)
        high = _minimal_finding(id="b", severity=Severity.CRITICAL, location=loc)
        other = _minimal_finding(
            id="c", severity=Severity.MEDIUM, location=Location(file="other.sql")
        )
        result = dedupe_findings([low, high, other])
        assert len(result) == 2
        by_loc = {(f.location.file, f.location.line): f for f in result if f.location}
        assert by_loc[("etl.sql", 10)].severity is Severity.CRITICAL

    def test_dedupe_preserves_findings_without_location(self) -> None:
        a = _minimal_finding(id="a")
        b = _minimal_finding(id="b")
        # No location -> not merged together (dedup only merges shared locations)
        result = dedupe_findings([a, b])
        assert len(result) == 2


@pytest.mark.unit
class TestKernelBoundary:
    """Finding imports with no databricks-sdk (kernel boundary)."""

    def test_finding_imports_without_databricks_sdk(self) -> None:
        body = """
import importlib
import sys

importlib.import_module("starboard_core.domain.models.finding")
leaked = sorted(m for m in sys.modules if m == "databricks" or m.startswith("databricks."))
assert not leaked, f"databricks imported: {leaked}"
print("OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", body],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout
