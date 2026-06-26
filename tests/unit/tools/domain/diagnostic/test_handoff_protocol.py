# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for diagnostic handoff protocol."""

import pytest
from starboard_server.tools.domain.diagnostic.handoff_protocol import (
    HandoffProtocol,
    HandoffResult,
)
from starboard_server.tools.domain.diagnostic.models import (
    DiagnosticFingerprint,
    ExplorationSummary,
    PrimarySymptom,
)


class TestHandoffResult:
    """Tests for HandoffResult dataclass."""

    def test_create_handoff_result(self) -> None:
        """Should create a valid handoff result."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.OOM,
            likely_root_causes=["heap exhausted"],
            extracted_context={"cluster_id": "0123-456789-abc"},
        )
        result = HandoffResult(
            target_agent="cluster",
            fingerprint=fingerprint,
            handoff_message="Memory issue detected, handing off to cluster agent.",
            exploration_context="Analyzed stack trace, found java.lang.OutOfMemoryError",
        )
        assert result.target_agent == "cluster"
        assert result.fingerprint.primary_symptom == PrimarySymptom.OOM

    def test_handoff_result_to_dict(self) -> None:
        """Should serialize to dictionary for agent communication."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.SHUFFLE_FAILURE,
            likely_root_causes=["network issue"],
        )
        result = HandoffResult(
            target_agent="job",
            fingerprint=fingerprint,
            handoff_message="Shuffle failure detected.",
        )
        data = result.to_dict()
        assert data["target_agent"] == "job"
        assert data["fingerprint"]["primary_symptom"] == "shuffle_failure"
        assert "handoff_message" in data


class TestHandoffProtocol:
    """Tests for HandoffProtocol class."""

    @pytest.fixture
    def protocol(self) -> HandoffProtocol:
        """Create a HandoffProtocol instance."""
        return HandoffProtocol()

    def test_should_handoff_high_confidence(self, protocol: HandoffProtocol) -> None:
        """Should recommend handoff when confidence is high and target differs."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.OOM,
            likely_root_causes=["heap exhausted"],
            exploration_summary=ExplorationSummary(
                steps_completed=4,
                final_confidence=0.85,
                strategies_used=["detect_type", "match_patterns"],
            ),
        )
        should_handoff = protocol.should_handoff(fingerprint)
        assert should_handoff is True

    def test_should_not_handoff_low_confidence(self, protocol: HandoffProtocol) -> None:
        """Should not recommend handoff when confidence is too low."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.OOM,
            likely_root_causes=["unclear"],
            exploration_summary=ExplorationSummary(
                steps_completed=2,
                final_confidence=0.35,  # Below threshold
                strategies_used=["detect_type"],
            ),
        )
        should_handoff = protocol.should_handoff(fingerprint)
        assert should_handoff is False

    def test_should_not_handoff_unknown_symptom(
        self, protocol: HandoffProtocol
    ) -> None:
        """Should not handoff if symptom is unknown (stays with diagnostic)."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.UNKNOWN,
            likely_root_causes=["undetermined"],
            exploration_summary=ExplorationSummary(
                steps_completed=4,
                final_confidence=0.9,
                strategies_used=["detect_type", "match_patterns"],
            ),
        )
        should_handoff = protocol.should_handoff(fingerprint)
        assert should_handoff is False  # Unknown stays with diagnostic

    def test_create_handoff_for_cluster(self, protocol: HandoffProtocol) -> None:
        """Should create proper handoff for cluster-related issues."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.OOM,
            likely_root_causes=["Java heap space exhausted", "GC overhead"],
            extracted_context={"cluster_id": "0123-456789-abc", "job_id": "12345"},
            evidence_snippets=["java.lang.OutOfMemoryError: Java heap space"],
            exploration_summary=ExplorationSummary(
                steps_completed=4,
                final_confidence=0.88,
                strategies_used=["detect_type", "extract_evidence", "match_patterns"],
                patterns_matched=["java_heap_space"],
            ),
        )
        result = protocol.create_handoff(fingerprint)
        assert result.target_agent == "cluster"
        assert "memory" in result.handoff_message.lower()
        assert result.fingerprint == fingerprint

    def test_create_handoff_for_job(self, protocol: HandoffProtocol) -> None:
        """Should create proper handoff for job-related issues."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.DATA_SKEW,
            likely_root_causes=["uneven data distribution"],
            exploration_summary=ExplorationSummary(
                steps_completed=3,
                final_confidence=0.75,
                strategies_used=["detect_type", "match_patterns"],
            ),
        )
        result = protocol.create_handoff(fingerprint)
        assert result.target_agent == "job"
        assert (
            "skew" in result.handoff_message.lower()
            or "job" in result.handoff_message.lower()
        )

    def test_create_handoff_for_uc(self, protocol: HandoffProtocol) -> None:
        """Should create proper handoff for UC permission issues."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.PERMISSION,
            likely_root_causes=["missing grant on table"],
            extracted_context={"table": "catalog.schema.table"},
            exploration_summary=ExplorationSummary(
                steps_completed=3,
                final_confidence=0.92,
                strategies_used=["detect_type", "extract_ids", "match_patterns"],
            ),
        )
        result = protocol.create_handoff(fingerprint)
        assert result.target_agent == "uc"
        assert "permission" in result.handoff_message.lower()

    def test_create_handoff_for_query(self, protocol: HandoffProtocol) -> None:
        """Should create proper handoff for query issues."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.PARSE_ERROR,
            likely_root_causes=["syntax error in SQL"],
            exploration_summary=ExplorationSummary(
                steps_completed=2,
                final_confidence=0.80,
                strategies_used=["detect_type", "match_patterns"],
            ),
        )
        result = protocol.create_handoff(fingerprint)
        assert result.target_agent == "query"

    def test_handoff_includes_exploration_context(
        self, protocol: HandoffProtocol
    ) -> None:
        """Handoff should include summary of exploration for receiving agent."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.EXECUTOR_LOST,
            likely_root_causes=["GC overhead", "memory pressure"],
            evidence_snippets=[
                "Lost executor 3",
                "GC overhead limit exceeded",
            ],
            exploration_summary=ExplorationSummary(
                steps_completed=5,
                final_confidence=0.85,
                strategies_used=["detect_type", "extract_evidence", "match_patterns"],
                patterns_matched=["executor_lost", "gc_overhead"],
                tool_calls_made=["get_run_output"],
            ),
        )
        result = protocol.create_handoff(fingerprint)
        # Exploration context should summarize what was found
        assert result.exploration_context is not None
        assert (
            "5" in result.exploration_context
            or "steps" in result.exploration_context.lower()
        )

    def test_handoff_respects_recommended_override(
        self, protocol: HandoffProtocol
    ) -> None:
        """Explicit recommended_handoff should override symptom-based target."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=PrimarySymptom.OOM,  # Would normally go to cluster
            likely_root_causes=["query memory issue"],
            recommended_handoff="query",  # Override
            exploration_summary=ExplorationSummary(
                steps_completed=3,
                final_confidence=0.80,
                strategies_used=["detect_type"],
            ),
        )
        result = protocol.create_handoff(fingerprint)
        assert result.target_agent == "query"  # Respects override


class TestHandoffMessages:
    """Tests for handoff message generation."""

    @pytest.fixture
    def protocol(self) -> HandoffProtocol:
        return HandoffProtocol()

    @pytest.mark.parametrize(
        "symptom,expected_keywords",
        [
            (PrimarySymptom.OOM, ["memory", "heap"]),
            (PrimarySymptom.EXECUTOR_LOST, ["executor", "lost"]),
            (PrimarySymptom.PERMISSION, ["permission", "access"]),
            (PrimarySymptom.SHUFFLE_FAILURE, ["shuffle"]),
            (PrimarySymptom.DATA_SKEW, ["skew", "partition"]),
            (PrimarySymptom.TIMEOUT, ["timeout"]),
        ],
    )
    def test_handoff_message_contains_relevant_keywords(
        self,
        protocol: HandoffProtocol,
        symptom: PrimarySymptom,
        expected_keywords: list[str],
    ) -> None:
        """Handoff message should contain symptom-relevant keywords."""
        fingerprint = DiagnosticFingerprint(
            primary_symptom=symptom,
            likely_root_causes=["test cause"],
            exploration_summary=ExplorationSummary(
                steps_completed=2,
                final_confidence=0.75,
                strategies_used=["detect_type"],
            ),
        )
        result = protocol.create_handoff(fingerprint)
        message_lower = result.handoff_message.lower()
        assert any(kw in message_lower for kw in expected_keywords), (
            f"Message '{result.handoff_message}' should contain one of {expected_keywords}"
        )
