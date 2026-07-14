# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Unit tests for ModeAwareResponder - adjusts responses based on ONLINE/OFFLINE mode.

Tests cover:
- ONLINE mode: Can fetch additional context
- OFFLINE mode: Provides manual guidance
- HYBRID mode: Partial context with guidance
- Response adaptation based on mode
"""

from __future__ import annotations

import pytest
from starboard.tools.domain.diagnostic.context_extractor import ContextMode
from starboard.tools.domain.diagnostic.mode_aware_responder import (
    ModeAwareResponder,
    ModeAwareResponse,
    OfflineGuidance,
)


@pytest.fixture
def responder() -> ModeAwareResponder:
    """Create ModeAwareResponder instance."""
    return ModeAwareResponder()


# =============================================================================
# ONLINE MODE RESPONSES
# =============================================================================


class TestOnlineModeResponses:
    """Tests for ONLINE mode responses."""

    def test_online_mode_suggests_tool_calls(
        self, responder: ModeAwareResponder
    ) -> None:
        """ONLINE mode suggests using tools to fetch context."""
        response = responder.create_response(
            mode=ContextMode.ONLINE,
            diagnosis="Memory issue detected",
            available_ids={"cluster_id": "1234-567890-abc123"},
        )

        assert response.mode == ContextMode.ONLINE
        assert response.can_fetch_context is True
        assert len(response.suggested_tool_calls) > 0

    def test_online_mode_includes_cluster_tools(
        self, responder: ModeAwareResponder
    ) -> None:
        """ONLINE mode with cluster_id suggests cluster-related tools."""
        response = responder.create_response(
            mode=ContextMode.ONLINE,
            diagnosis="Executor lost",
            available_ids={"cluster_id": "1234-567890-abc123"},
        )

        # Should suggest fetching cluster events
        tool_names = [t["tool"] for t in response.suggested_tool_calls]
        assert any("cluster" in t.lower() for t in tool_names)

    def test_online_mode_includes_job_tools(
        self, responder: ModeAwareResponder
    ) -> None:
        """ONLINE mode with job_id suggests job-related tools."""
        response = responder.create_response(
            mode=ContextMode.ONLINE,
            diagnosis="Job failed",
            available_ids={"job_id": "12345", "run_id": "67890"},
        )

        tool_names = [t["tool"] for t in response.suggested_tool_calls]
        assert any("job" in t.lower() for t in tool_names)

    def test_online_mode_no_manual_guidance(
        self, responder: ModeAwareResponder
    ) -> None:
        """ONLINE mode doesn't need manual guidance."""
        response = responder.create_response(
            mode=ContextMode.ONLINE,
            diagnosis="Test issue",
            available_ids={"cluster_id": "abc123"},
        )

        assert response.offline_guidance is None


# =============================================================================
# OFFLINE MODE RESPONSES
# =============================================================================


class TestOfflineModeResponses:
    """Tests for OFFLINE mode responses."""

    def test_offline_mode_provides_manual_guidance(
        self, responder: ModeAwareResponder
    ) -> None:
        """OFFLINE mode provides manual investigation guidance."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="Memory issue detected",
            available_ids={},
        )

        assert response.mode == ContextMode.OFFLINE
        assert response.can_fetch_context is False
        assert response.offline_guidance is not None

    def test_offline_mode_has_investigation_steps(
        self, responder: ModeAwareResponder
    ) -> None:
        """OFFLINE mode includes step-by-step investigation."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="Shuffle fetch failed",
            available_ids={},
        )

        assert response.offline_guidance is not None
        assert len(response.offline_guidance.investigation_steps) > 0

    def test_offline_mode_has_questions_to_answer(
        self, responder: ModeAwareResponder
    ) -> None:
        """OFFLINE mode includes questions for user."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="Unknown error",
            available_ids={},
        )

        assert response.offline_guidance is not None
        assert len(response.offline_guidance.questions_to_answer) > 0

    def test_offline_mode_has_data_to_collect(
        self, responder: ModeAwareResponder
    ) -> None:
        """OFFLINE mode lists data to collect."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="Performance issue",
            available_ids={},
        )

        assert response.offline_guidance is not None
        assert len(response.offline_guidance.data_to_collect) > 0

    def test_offline_mode_no_tool_calls(self, responder: ModeAwareResponder) -> None:
        """OFFLINE mode doesn't suggest tool calls."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="Test",
            available_ids={},
        )

        assert len(response.suggested_tool_calls) == 0


# =============================================================================
# HYBRID MODE RESPONSES
# =============================================================================


class TestHybridModeResponses:
    """Tests for HYBRID mode responses."""

    def test_hybrid_mode_has_both(self, responder: ModeAwareResponder) -> None:
        """HYBRID mode has both tool suggestions and guidance."""
        response = responder.create_response(
            mode=ContextMode.HYBRID,
            diagnosis="Memory issue",
            available_ids={"cluster_id": "abc123"},  # Has cluster, missing job
        )

        assert response.mode == ContextMode.HYBRID
        # Should have some tool calls for available IDs
        assert response.can_fetch_context is True
        # Should also have guidance for missing context
        assert response.offline_guidance is not None

    def test_hybrid_mode_mentions_partial_context(
        self, responder: ModeAwareResponder
    ) -> None:
        """HYBRID mode mentions partial context availability."""
        response = responder.create_response(
            mode=ContextMode.HYBRID,
            diagnosis="Job failure",
            available_ids={"cluster_id": "abc123"},
        )

        assert response.partial_context_note is not None
        assert (
            "partial" in response.partial_context_note.lower()
            or "some" in response.partial_context_note.lower()
        )


# =============================================================================
# DIAGNOSIS-SPECIFIC GUIDANCE
# =============================================================================


class TestDiagnosisSpecificGuidance:
    """Tests for diagnosis-specific guidance."""

    def test_memory_issue_guidance(self, responder: ModeAwareResponder) -> None:
        """Memory issues get memory-specific guidance."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="OutOfMemoryError",
            available_ids={},
        )

        guidance = response.offline_guidance
        assert guidance is not None
        # Should mention memory-related investigation
        all_text = " ".join(guidance.investigation_steps).lower()
        assert "memory" in all_text or "gc" in all_text or "heap" in all_text

    def test_network_issue_guidance(self, responder: ModeAwareResponder) -> None:
        """Network issues get network-specific guidance."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="Connection timeout",
            available_ids={},
        )

        guidance = response.offline_guidance
        assert guidance is not None
        all_text = " ".join(guidance.investigation_steps).lower()
        assert (
            "network" in all_text or "connection" in all_text or "firewall" in all_text
        )

    def test_permission_issue_guidance(self, responder: ModeAwareResponder) -> None:
        """Permission issues get permission-specific guidance."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="Permission denied",
            available_ids={},
        )

        guidance = response.offline_guidance
        assert guidance is not None
        all_text = " ".join(guidance.investigation_steps).lower()
        assert "permission" in all_text or "access" in all_text or "grant" in all_text


# =============================================================================
# RESPONSE STRUCTURE
# =============================================================================


class TestResponseStructure:
    """Tests for response structure."""

    def test_response_has_mode(self, responder: ModeAwareResponder) -> None:
        """Response includes mode information."""
        response = responder.create_response(
            mode=ContextMode.ONLINE,
            diagnosis="Test",
            available_ids={"cluster_id": "abc"},
        )

        assert isinstance(response, ModeAwareResponse)
        assert response.mode == ContextMode.ONLINE

    def test_response_has_diagnosis(self, responder: ModeAwareResponder) -> None:
        """Response includes original diagnosis."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="Test diagnosis",
            available_ids={},
        )

        assert response.diagnosis == "Test diagnosis"

    def test_guidance_structure(self, responder: ModeAwareResponder) -> None:
        """Guidance has expected structure."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="Test",
            available_ids={},
        )

        guidance = response.offline_guidance
        assert isinstance(guidance, OfflineGuidance)
        assert hasattr(guidance, "investigation_steps")
        assert hasattr(guidance, "questions_to_answer")
        assert hasattr(guidance, "data_to_collect")


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_diagnosis(self, responder: ModeAwareResponder) -> None:
        """Empty diagnosis doesn't crash."""
        response = responder.create_response(
            mode=ContextMode.OFFLINE,
            diagnosis="",
            available_ids={},
        )
        assert isinstance(response, ModeAwareResponse)

    def test_empty_ids_for_online(self, responder: ModeAwareResponder) -> None:
        """ONLINE mode with empty IDs still works."""
        response = responder.create_response(
            mode=ContextMode.ONLINE,
            diagnosis="Test",
            available_ids={},
        )
        # Should still be ONLINE mode but no specific tool suggestions
        assert response.mode == ContextMode.ONLINE

    def test_none_values_in_ids(self, responder: ModeAwareResponder) -> None:
        """IDs with None values are handled."""
        response = responder.create_response(
            mode=ContextMode.ONLINE,
            diagnosis="Test",
            available_ids={"cluster_id": None, "job_id": "123"},
        )
        assert isinstance(response, ModeAwareResponse)
