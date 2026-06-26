# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for DiagnosticFingerprint schema and handoff protocol."""

from dataclasses import asdict

import pytest
from starboard_server.tools.domain.diagnostic.models import (
    DiagnosticFingerprint,
    ExplorationSummary,
    PrimarySymptom,
)


class TestPrimarySymptom:
    """Tests for PrimarySymptom enum."""

    def test_all_symptom_types_defined(self) -> None:
        """Should have all expected symptom types."""
        expected = {
            "executor_lost",
            "oom",
            "permission",
            "parse_error",
            "timeout",
            "connection_error",
            "serialization_error",
            "data_skew",
            "shuffle_failure",
            "driver_crash",
            "unknown",
        }
        actual = {s.value for s in PrimarySymptom}
        assert expected.issubset(actual)

    def test_symptom_from_string(self) -> None:
        """Should be able to create symptom from string."""
        symptom = PrimarySymptom("oom")
        assert symptom == PrimarySymptom.OOM


class TestExplorationSummary:
    """Tests for ExplorationSummary dataclass."""

    def test_create_minimal_summary(self) -> None:
        """Should create summary with required fields only."""
        summary = ExplorationSummary(
            steps_completed=3,
            final_confidence=0.85,
            strategies_used=["detect_type", "extract_evidence", "match_patterns"],
        )
        assert summary.steps_completed == 3
        assert summary.final_confidence == 0.85
        assert len(summary.strategies_used) == 3

    def test_create_full_summary(self) -> None:
        """Should create summary with all optional fields."""
        summary = ExplorationSummary(
            steps_completed=5,
            final_confidence=0.92,
            strategies_used=["detect_type", "extract_evidence", "match_patterns"],
            patterns_matched=["java_heap_space", "gc_overhead"],
            tool_calls_made=["get_run_output", "get_cluster_events"],
            total_duration_ms=1250,
        )
        assert summary.patterns_matched == ["java_heap_space", "gc_overhead"]
        assert summary.tool_calls_made == ["get_run_output", "get_cluster_events"]
        assert summary.total_duration_ms == 1250

    def test_summary_is_serializable(self) -> None:
        """Summary should be JSON-serializable via asdict."""
        summary = ExplorationSummary(
            steps_completed=3,
            final_confidence=0.75,
            strategies_used=["detect_type"],
        )
        data = asdict(summary)
        assert data["steps_completed"] == 3
        assert data["final_confidence"] == 0.75


class TestDiagnosticFingerprint:
    """Tests for DiagnosticFingerprint dataclass."""

    def test_create_minimal_fingerprint(self) -> None:
        """Should create fingerprint with required fields."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.OOM,
            likely_root_causes=["heap exhausted", "memory leak"],
        )
        assert fingerprint.primary_symptom == PrimarySymptom.OOM
        assert len(fingerprint.likely_root_causes) == 2
        assert fingerprint.extracted_context == {}
        assert fingerprint.evidence_snippets == []

    def test_create_full_fingerprint(self) -> None:
        """Should create fingerprint with all fields populated."""
        summary = ExplorationSummary(
            steps_completed=4,
            final_confidence=0.88,
            strategies_used=["detect_type", "extract_evidence"],
        )
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.EXECUTOR_LOST,
            likely_root_causes=["GC overhead", "data skew"],
            extracted_context={
                "job_id": "12345",
                "cluster_id": "0123-456789-abc",
                "run_id": "67890",
            },
            evidence_snippets=[
                "java.lang.OutOfMemoryError: GC overhead limit exceeded",
                "Lost executor 3 (already removed)",
            ],
            exploration_summary=summary,
            recommended_handoff="cluster",
        )
        assert fingerprint.extracted_context["job_id"] == "12345"
        assert len(fingerprint.evidence_snippets) == 2
        assert fingerprint.exploration_summary is not None
        assert fingerprint.recommended_handoff == "cluster"

    def test_fingerprint_is_serializable(self) -> None:
        """Fingerprint should be JSON-serializable via to_dict."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.PERMISSION,
            likely_root_causes=["missing grant"],
            extracted_context={"table": "catalog.schema.table"},
        )
        # Use to_dict() which properly serializes enums
        data = fingerprint.to_dict()
        assert data["primary_symptom"] == "permission"
        assert data["likely_root_causes"] == ["missing grant"]
        assert data["extracted_context"]["table"] == "catalog.schema.table"

    def test_fingerprint_to_dict_method(self) -> None:
        """Should have explicit to_dict method for handoff."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.SHUFFLE_FAILURE,
            likely_root_causes=["network issues"],
        )
        data = fingerprint.to_dict()
        assert isinstance(data, dict)
        assert data["primary_symptom"] == "shuffle_failure"


class TestHandoffProtocol:
    """Tests for handoff target determination."""

    @pytest.mark.parametrize(
        "symptom,expected_target",
        [
            (PrimarySymptom.OOM, "cluster"),
            (PrimarySymptom.EXECUTOR_LOST, "cluster"),
            (PrimarySymptom.DRIVER_CRASH, "cluster"),
            (PrimarySymptom.DATA_SKEW, "job"),
            (PrimarySymptom.SHUFFLE_FAILURE, "job"),
            (PrimarySymptom.PERMISSION, "uc"),
            (PrimarySymptom.PARSE_ERROR, "query"),
            (PrimarySymptom.TIMEOUT, "warehouse"),
            (PrimarySymptom.CONNECTION_ERROR, "cluster"),
        ],
    )
    def test_symptom_to_handoff_target(
        self, symptom: PrimarySymptom, expected_target: str
    ) -> None:
        """Each symptom should map to appropriate handoff target."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=symptom,
            likely_root_causes=["test cause"],
        )
        assert fingerprint.get_handoff_target() == expected_target

    def test_recommended_handoff_overrides_default(self) -> None:
        """Explicit recommended_handoff should override symptom-based default."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.OOM,
            likely_root_causes=["query memory issue"],
            recommended_handoff="query",  # Override the default "cluster"
        )
        assert fingerprint.get_handoff_target() == "query"

    def test_unknown_symptom_defaults_to_diagnostic(self) -> None:
        """Unknown symptoms should stay with diagnostic agent."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.UNKNOWN,
            likely_root_causes=["unclear"],
        )
        assert fingerprint.get_handoff_target() == "diagnostic"


class TestFingerprintFromExploration:
    """Tests for creating fingerprints from exploration results."""

    def test_create_from_exploration_context(self) -> None:
        """Should be able to create fingerprint from DiagnosticContext."""
        # This tests the factory method pattern
        fingerprint = DiagnosticFingerprint.from_exploration(
            matched_patterns=["java_heap_space"],
            extracted_ids={"job_id": "123", "cluster_id": "abc"},
            evidence_refs=["EV001", "EV002"],
            confidence=0.85,
            steps_completed=4,
            strategies_used=["detect_type", "extract_evidence", "match_patterns"],
        )
        assert fingerprint.primary_symptom == PrimarySymptom.OOM
        assert "java_heap_space" in str(fingerprint.likely_root_causes)
        assert fingerprint.extracted_context["job_id"] == "123"
        assert fingerprint.exploration_summary is not None
        assert fingerprint.exploration_summary.final_confidence == 0.85

    def test_pattern_to_symptom_mapping(self) -> None:
        """Should map known patterns to appropriate symptoms."""
        # OOM patterns -> OOM symptom
        fp1 = DiagnosticFingerprint.from_exploration(
            matched_patterns=["java_heap_space"],
            extracted_ids={},
            evidence_refs=[],
            confidence=0.9,
            steps_completed=2,
            strategies_used=["detect_type"],
        )
        assert fp1.primary_symptom == PrimarySymptom.OOM

        # Permission patterns -> PERMISSION symptom
        fp2 = DiagnosticFingerprint.from_exploration(
            matched_patterns=["uc_permission_denied"],
            extracted_ids={},
            evidence_refs=[],
            confidence=0.9,
            steps_completed=2,
            strategies_used=["detect_type"],
        )
        assert fp2.primary_symptom == PrimarySymptom.PERMISSION

    def test_no_patterns_defaults_to_unknown(self) -> None:
        """Empty patterns should result in UNKNOWN symptom."""
        fingerprint = DiagnosticFingerprint.from_exploration(
            matched_patterns=[],
            extracted_ids={},
            evidence_refs=[],
            confidence=0.3,
            steps_completed=1,
            strategies_used=["detect_type"],
        )
        assert fingerprint.primary_symptom == PrimarySymptom.UNKNOWN
