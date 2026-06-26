# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for routing models and helper functions.

Coverage targets:
- RouteDecision dataclass validation and methods
- AgentTransition dataclass validation and methods
- Helper functions for creating routing decisions
"""

from datetime import UTC, datetime, timedelta

import pytest
from starboard_server.agents.routing.routing_models import (
    AgentTransition,
    RouteDecision,
    create_diagnostic_decision,
    create_job_decision,
    create_query_decision,
)


class TestRouteDecision:
    """Tests for RouteDecision dataclass."""

    def test_route_decision_creation(self) -> None:
        """Test creating a valid RouteDecision."""
        # Act
        decision = RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={"statement_id": "abc123"},
            context={},
            clarification_needed=False,
            reasoning="Statement ID detected",
        )

        # Assert
        assert decision.domain == "query"
        assert decision.confidence == 0.9
        assert decision.extracted_ids == {"statement_id": "abc123"}
        assert decision.clarification_needed is False

    def test_route_decision_invalid_confidence_too_low(self) -> None:
        """Test that confidence below 0.0 raises ValueError."""
        # Assert
        with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
            RouteDecision(
                domain="query",
                confidence=-0.1,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning="Test",
            )

    def test_route_decision_invalid_confidence_too_high(self) -> None:
        """Test that confidence above 1.0 raises ValueError."""
        # Assert
        with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
            RouteDecision(
                domain="query",
                confidence=1.5,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning="Test",
            )

    def test_route_decision_invalid_domain(self) -> None:
        """Test that invalid domain raises ValueError."""
        # Assert
        with pytest.raises(ValueError, match="Invalid domain"):
            RouteDecision(
                domain="invalid_domain",  # type: ignore
                confidence=0.9,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning="Test",
            )

    def test_route_decision_all_valid_domains(self) -> None:
        """Test that all valid domains are accepted."""
        # Arrange
        valid_domains = [
            "query",
            "job",
            "uc",
            "cluster",
            "diagnostic",
            "analytics",
            "warehouse",
        ]

        # Act & Assert
        for domain in valid_domains:
            decision = RouteDecision(
                domain=domain,  # type: ignore
                confidence=0.8,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning=f"Testing {domain}",
            )
            assert decision.domain == domain

    def test_should_route_high_confidence(self) -> None:
        """Test that high confidence without clarification returns True."""
        # Arrange
        decision = RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="High confidence",
        )

        # Act & Assert
        assert decision.should_route() is True

    def test_should_route_threshold_confidence(self) -> None:
        """Test that exactly 0.7 confidence returns True."""
        # Arrange
        decision = RouteDecision(
            domain="query",
            confidence=0.7,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Threshold confidence",
        )

        # Act & Assert
        assert decision.should_route() is True

    def test_should_route_low_confidence(self) -> None:
        """Test that low confidence returns False."""
        # Arrange
        decision = RouteDecision(
            domain="query",
            confidence=0.5,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Low confidence",
        )

        # Act & Assert
        assert decision.should_route() is False

    def test_should_route_clarification_needed(self) -> None:
        """Test that clarification needed returns False even with high confidence."""
        # Arrange
        decision = RouteDecision(
            domain="diagnostic",
            confidence=0.9,
            extracted_ids={},
            context={},
            clarification_needed=True,
            reasoning="Need more info",
        )

        # Act & Assert
        assert decision.should_route() is False


class TestAgentTransition:
    """Tests for AgentTransition dataclass."""

    def test_agent_transition_creation(self) -> None:
        """Test creating a valid AgentTransition."""
        # Arrange
        timestamp = datetime.now(UTC)

        # Act
        transition = AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=timestamp,
            reason="Statement ID detected",
            context_passed={"statement_id": "abc123"},
        )

        # Assert
        assert transition.from_agent == "router"
        assert transition.to_agent == "query"
        assert transition.timestamp == timestamp
        assert transition.reason == "Statement ID detected"
        assert transition.context_passed == {"statement_id": "abc123"}

    def test_agent_transition_empty_from_agent(self) -> None:
        """Test that empty from_agent raises ValueError."""
        # Assert
        with pytest.raises(ValueError, match="from_agent cannot be empty"):
            AgentTransition(
                from_agent="",
                to_agent="query",
                timestamp=datetime.now(UTC),
                reason="Test",
                context_passed={},
            )

    def test_agent_transition_empty_to_agent(self) -> None:
        """Test that empty to_agent raises ValueError."""
        # Assert
        with pytest.raises(ValueError, match="to_agent cannot be empty"):
            AgentTransition(
                from_agent="router",
                to_agent="",
                timestamp=datetime.now(UTC),
                reason="Test",
                context_passed={},
            )

    def test_agent_transition_same_agent(self) -> None:
        """Test that transition to same agent raises ValueError."""
        # Assert
        with pytest.raises(ValueError, match="Cannot transition to same agent"):
            AgentTransition(
                from_agent="query",
                to_agent="query",
                timestamp=datetime.now(UTC),
                reason="Test",
                context_passed={},
            )

    def test_agent_transition_future_timestamp(self) -> None:
        """Test that future timestamp raises ValueError."""
        # Arrange
        future_time = datetime.now(UTC) + timedelta(seconds=10)

        # Assert
        with pytest.raises(ValueError, match="Timestamp cannot be in the future"):
            AgentTransition(
                from_agent="router",
                to_agent="query",
                timestamp=future_time,
                reason="Test",
                context_passed={},
            )

    def test_agent_transition_recent_timestamp_allowed(self) -> None:
        """Test that very recent timestamp (within 5 sec tolerance) is allowed."""
        # Arrange - timestamp 3 seconds in the future (within tolerance)
        recent_time = datetime.now(UTC) + timedelta(seconds=3)

        # Act & Assert - should not raise
        transition = AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=recent_time,
            reason="Test",
            context_passed={},
        )
        assert transition.timestamp == recent_time

    def test_agent_transition_naive_datetime(self) -> None:
        """Test AgentTransition with naive datetime."""
        # Arrange
        naive_time = datetime.now(UTC)

        # Act
        transition = AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=naive_time,
            reason="Test",
            context_passed={},
        )

        # Assert
        assert transition.timestamp == naive_time

    def test_agent_transition_to_dict(self) -> None:
        """Test serializing AgentTransition to dictionary."""
        # Arrange
        timestamp = datetime(2025, 11, 18, 12, 0, 0, tzinfo=UTC)
        transition = AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=timestamp,
            reason="Statement ID detected",
            context_passed={"statement_id": "abc123"},
        )

        # Act
        result = transition.to_dict()

        # Assert
        assert result["from_agent"] == "router"
        assert result["to_agent"] == "query"
        assert result["timestamp"] == "2025-11-18T12:00:00+00:00"
        assert result["reason"] == "Statement ID detected"
        assert result["context_passed"] == {"statement_id": "abc123"}

    def test_agent_transition_from_dict(self) -> None:
        """Test deserializing AgentTransition from dictionary."""
        # Arrange
        data = {
            "from_agent": "router",
            "to_agent": "query",
            "timestamp": "2025-11-18T12:00:00+00:00",
            "reason": "Statement ID detected",
            "context_passed": {"statement_id": "abc123"},
        }

        # Act
        transition = AgentTransition.from_dict(data)

        # Assert
        assert transition.from_agent == "router"
        assert transition.to_agent == "query"
        assert transition.reason == "Statement ID detected"
        assert transition.context_passed == {"statement_id": "abc123"}

    def test_agent_transition_round_trip(self) -> None:
        """Test that to_dict and from_dict are inverse operations."""
        # Arrange
        original = AgentTransition(
            from_agent="router",
            to_agent="diagnostic",
            timestamp=datetime(2025, 11, 18, 12, 0, 0, tzinfo=UTC),
            reason="Troubleshooting needed",
            context_passed={"error_code": "500"},
        )

        # Act
        serialized = original.to_dict()
        deserialized = AgentTransition.from_dict(serialized)

        # Assert
        assert deserialized.from_agent == original.from_agent
        assert deserialized.to_agent == original.to_agent
        assert deserialized.reason == original.reason
        assert deserialized.context_passed == original.context_passed


class TestHelperFunctions:
    """Tests for helper functions that create routing decisions."""

    def test_create_query_decision_default(self) -> None:
        """Test creating query decision with defaults."""
        # Arrange
        extracted_ids = {"statement_id": "abc123"}

        # Act
        decision = create_query_decision(extracted_ids)

        # Assert
        assert decision.domain == "query"
        assert decision.confidence == 1.0
        assert decision.extracted_ids == extracted_ids
        assert decision.clarification_needed is False
        assert decision.reasoning == "Statement ID or SQL detected"
        assert decision.should_route() is True

    def test_create_query_decision_custom(self) -> None:
        """Test creating query decision with custom parameters."""
        # Arrange
        extracted_ids = {"statement_id": "xyz789"}

        # Act
        decision = create_query_decision(
            extracted_ids, confidence=0.8, reasoning="Custom SQL detected"
        )

        # Assert
        assert decision.confidence == 0.8
        assert decision.reasoning == "Custom SQL detected"

    def test_create_job_decision_default(self) -> None:
        """Test creating job decision with defaults."""
        # Arrange
        extracted_ids = {"job_id": "456"}

        # Act
        decision = create_job_decision(extracted_ids)

        # Assert
        assert decision.domain == "job"
        assert decision.confidence == 1.0
        assert decision.extracted_ids == extracted_ids
        assert decision.clarification_needed is False
        assert decision.reasoning == "Job ID detected"
        assert decision.should_route() is True

    def test_create_job_decision_custom(self) -> None:
        """Test creating job decision with custom parameters."""
        # Arrange
        extracted_ids = {"job_id": "789"}

        # Act
        decision = create_job_decision(
            extracted_ids, confidence=0.9, reasoning="Job keyword found"
        )

        # Assert
        assert decision.confidence == 0.9
        assert decision.reasoning == "Job keyword found"

    def test_create_diagnostic_decision_default(self) -> None:
        """Test creating diagnostic decision with defaults."""
        # Arrange
        extracted_ids = {}

        # Act
        decision = create_diagnostic_decision(extracted_ids)

        # Assert
        assert decision.domain == "diagnostic"
        assert decision.confidence == 0.7
        assert decision.clarification_needed is True
        assert decision.reasoning == "Diagnostic keywords detected"
        assert decision.should_route() is False  # Due to clarification needed

    def test_create_diagnostic_decision_custom(self) -> None:
        """Test creating diagnostic decision without clarification."""
        # Arrange
        extracted_ids = {}

        # Act
        decision = create_diagnostic_decision(
            extracted_ids,
            confidence=0.9,
            clarification_needed=False,
            reasoning="Clear diagnostic intent",
        )

        # Assert
        assert decision.confidence == 0.9
        assert decision.clarification_needed is False
        assert decision.reasoning == "Clear diagnostic intent"
        assert decision.should_route() is True
