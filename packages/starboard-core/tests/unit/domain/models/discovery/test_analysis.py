# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for discovery analysis Pydantic models.

Tests cover:
- Evidence, LikelyCause, Remediation construction and defaults
- DiscoveryFinding validation (required fields, literals)
- DataCoverage defaults
- DomainAnalysis score bounds and grade values
- DomainAnalysis string-to-list coercion for LLM output resilience
"""

import pytest
from pydantic import ValidationError
from starboard_core.domain.models.discovery.analysis import (
    DataCoverage,
    DiscoveryFinding,
    DomainAnalysis,
    Evidence,
    LikelyCause,
    Remediation,
    _coerce_str_to_list,
)


class TestEvidence:
    def test_minimal(self):
        e = Evidence(source_query_id="C-B01", excerpt="Total DBUs: 12,340")
        assert e.metric_name is None
        assert e.metric_value is None

    def test_with_metrics(self):
        e = Evidence(
            source_query_id="C-B01",
            excerpt="Total DBUs: 12,340",
            metric_name="dbus_consumed",
            metric_value="12340",
        )
        assert e.metric_name == "dbus_consumed"


class TestLikelyCause:
    def test_defaults(self):
        c = LikelyCause(description="Over-provisioned cluster")
        assert c.is_hypothesis is False
        assert c.how_to_confirm is None

    def test_hypothesis(self):
        c = LikelyCause(
            description="Skew in partition keys",
            is_hypothesis=True,
            how_to_confirm="Check partition column distribution",
        )
        assert c.is_hypothesis is True


class TestRemediation:
    def test_defaults(self):
        r = Remediation()
        assert r.immediate == []
        assert r.medium_term == []
        assert r.long_term == []

    def test_with_actions(self):
        r = Remediation(
            immediate=["Enable auto-scaling"],
            medium_term=["Right-size clusters"],
            long_term=["Migrate to serverless"],
        )
        assert len(r.immediate) == 1
        assert len(r.long_term) == 1


class TestDiscoveryFinding:
    def test_valid_finding(self):
        f = DiscoveryFinding(
            finding_id="F-001",
            title="Over-provisioned interactive cluster",
            priority="HIGH",
            impact="HIGH",
            effort="LOW",
            confidence="HIGH",
            finding_type="COST_OPTIMIZATION",
            domain="compute",
            description="Cluster xyz has 20% utilization.",
        )
        assert f.finding_id == "F-001"
        assert f.evidence == []
        assert f.expected_outcome == ""

    def test_invalid_priority(self):
        with pytest.raises(ValidationError):
            DiscoveryFinding(
                finding_id="F-001",
                title="Test",
                priority="URGENT",  # type: ignore[arg-type]
                impact="HIGH",
                effort="LOW",
                confidence="HIGH",
                finding_type="PERFORMANCE",
                domain="test",
                description="Test",
            )

    def test_invalid_finding_type(self):
        with pytest.raises(ValidationError):
            DiscoveryFinding(
                finding_id="F-001",
                title="Test",
                priority="HIGH",
                impact="HIGH",
                effort="LOW",
                confidence="HIGH",
                finding_type="UNKNOWN",  # type: ignore[arg-type]
                domain="test",
                description="Test",
            )

    def test_serialization_roundtrip(self):
        f = DiscoveryFinding(
            finding_id="F-002",
            title="High job failure rate",
            priority="CRITICAL",
            impact="HIGH",
            effort="MEDIUM",
            confidence="HIGH",
            finding_type="RELIABILITY",
            domain="jobs",
            description="45% failure rate in last 30 days.",
            evidence=[
                Evidence(
                    source_query_id="C-J01",
                    excerpt="failure_rate: 0.45",
                    metric_name="failure_rate",
                    metric_value="0.45",
                )
            ],
            likely_causes=[
                LikelyCause(
                    description="Unstable dependencies",
                    is_hypothesis=True,
                )
            ],
            remediation=Remediation(immediate=["Add retry logic"]),
            expected_outcome="Reduce failure rate to <5%",
        )
        data = f.model_dump()
        reconstructed = DiscoveryFinding.model_validate(data)
        assert reconstructed == f


class TestDataCoverage:
    def test_defaults(self):
        dc = DataCoverage()
        assert dc.queries_executed == 0
        assert dc.time_range_start is None
        assert dc.gaps == []


class TestDomainAnalysis:
    def test_valid_analysis(self):
        da = DomainAnalysis(
            domain="compute",
            grade="B",
            score=78.5,
            summary="Generally well-configured clusters.",
        )
        assert da.grade == "B"
        assert da.findings == []

    def test_score_out_of_range(self):
        with pytest.raises(ValidationError):
            DomainAnalysis(
                domain="test",
                grade="A",
                score=101.0,
                summary="Test",
            )

    def test_negative_score(self):
        with pytest.raises(ValidationError):
            DomainAnalysis(
                domain="test",
                grade="F",
                score=-1.0,
                summary="Test",
            )

    def test_invalid_grade(self):
        with pytest.raises(ValidationError):
            DomainAnalysis(
                domain="test",
                grade="E",  # type: ignore[arg-type]
                score=50.0,
                summary="Test",
            )

    def test_observations_coerced_from_bullet_string(self):
        da = DomainAnalysis(
            domain="jobs",
            grade="C",
            score=62.0,
            summary="Test",
            observations="\n- 27 active jobs processing telecom data\n- Coverage gaps (C-J01, C-J03)\n",  # type: ignore[arg-type]
        )
        assert da.observations == [
            "27 active jobs processing telecom data",
            "Coverage gaps (C-J01, C-J03)",
        ]

    def test_patterns_coerced_from_bullet_string(self):
        da = DomainAnalysis(
            domain="jobs",
            grade="C",
            score=62.0,
            summary="Test",
            patterns="\n- High-frequency, low-latency patterns\n- CDR/fraud detection\n",  # type: ignore[arg-type]
        )
        assert da.patterns == [
            "High-frequency, low-latency patterns",
            "CDR/fraud detection",
        ]

    def test_recommended_actions_coerced_from_bullet_string(self):
        da = DomainAnalysis(
            domain="jobs",
            grade="C",
            score=62.0,
            summary="Test",
            recommended_actions="- Enable auto-scaling\n- Right-size clusters",  # type: ignore[arg-type]
        )
        assert da.recommended_actions == [
            "Enable auto-scaling",
            "Right-size clusters",
        ]

    def test_list_inputs_pass_through_unchanged(self):
        da = DomainAnalysis(
            domain="jobs",
            grade="B",
            score=80.0,
            summary="Test",
            observations=["obs1", "obs2"],
            patterns=["pat1"],
            recommended_actions=["act1"],
        )
        assert da.observations == ["obs1", "obs2"]
        assert da.patterns == ["pat1"]
        assert da.recommended_actions == ["act1"]


class TestCoerceStrToList:
    def test_list_passthrough(self):
        assert _coerce_str_to_list(["a", "b"]) == ["a", "b"]

    def test_dash_bullets(self):
        assert _coerce_str_to_list("\n- alpha\n- beta\n") == ["alpha", "beta"]

    def test_asterisk_bullets(self):
        assert _coerce_str_to_list("* one\n* two") == ["one", "two"]

    def test_unicode_bullet(self):
        assert _coerce_str_to_list("• foo\n• bar") == ["foo", "bar"]

    def test_empty_string(self):
        assert _coerce_str_to_list("") == []

    def test_single_item_no_bullet(self):
        assert _coerce_str_to_list("just a plain string") == ["just a plain string"]

    def test_none_passthrough(self):
        assert _coerce_str_to_list(None) is None

    def test_int_passthrough(self):
        assert _coerce_str_to_list(42) == 42
