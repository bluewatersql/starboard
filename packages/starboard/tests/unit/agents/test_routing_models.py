# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for routing models (Phase 1).

Tests the routing_models module, including RouteDecision and
AgentTransition dataclasses, plus helper functions.
"""

from datetime import UTC, datetime, timedelta

import pytest
from starboard.agents.routing.routing_models import (
    AgentTransition,
    RouteDecision,
    create_diagnostic_decision,
    create_job_decision,
    create_query_decision,
)


class TestRouteDecision:
    """Tests for RouteDecision dataclass."""

    def test_route_decision_creation(self):
        """Should create RouteDecision with all fields."""
        decision = RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={"statement_id": "abc123"},
            context={"user_id": "user1"},
            clarification_needed=False,
            reasoning="Statement ID detected",
        )

        assert decision.domain == "query"
        assert decision.confidence == 0.9
        assert decision.extracted_ids == {"statement_id": "abc123"}
        assert decision.context == {"user_id": "user1"}
        assert decision.clarification_needed is False
        assert decision.reasoning == "Statement ID detected"

    def test_route_decision_immutable(self):
        """RouteDecision should be immutable (frozen)."""
        decision = RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )

        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            decision.domain = "job"  # type: ignore

    def test_route_decision_validates_confidence(self):
        """Should validate confidence is between 0.0 and 1.0."""
        # Valid confidences
        RouteDecision(
            domain="query",
            confidence=0.0,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )
        RouteDecision(
            domain="query",
            confidence=1.0,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )

        # Invalid confidences
        with pytest.raises(ValueError, match="Confidence must be between"):
            RouteDecision(
                domain="query",
                confidence=-0.1,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning="Test",
            )

        with pytest.raises(ValueError, match="Confidence must be between"):
            RouteDecision(
                domain="query",
                confidence=1.1,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning="Test",
            )

    def test_route_decision_validates_domain(self):
        """Should validate domain is one of the valid domains."""
        # Valid domains (note: "uc" replaces deprecated "table" domain, "cluster" replaces "cluster")
        valid_domains = [
            "query",
            "job",
            "uc",
            "cluster",
            "diagnostic",
            "analytics",
            "warehouse",
        ]
        for domain in valid_domains:
            RouteDecision(
                domain=domain,  # type: ignore
                confidence=0.9,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning="Test",
            )

        # Invalid domain
        with pytest.raises(ValueError, match="Invalid domain"):
            RouteDecision(
                domain="invalid",  # type: ignore
                confidence=0.9,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning="Test",
            )

    def test_should_route_high_confidence_no_clarification(self):
        """should_route() should return True for high confidence, no clarification."""
        decision = RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )
        assert decision.should_route() is True

    def test_should_route_threshold_confidence(self):
        """should_route() should return True at exactly 0.7 confidence."""
        decision = RouteDecision(
            domain="query",
            confidence=0.7,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )
        assert decision.should_route() is True

    def test_should_route_low_confidence(self):
        """should_route() should return False for low confidence."""
        decision = RouteDecision(
            domain="query",
            confidence=0.6,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )
        assert decision.should_route() is False

    def test_should_route_clarification_needed(self):
        """should_route() should return False if clarification needed."""
        decision = RouteDecision(
            domain="diagnostic",
            confidence=0.9,  # High confidence
            extracted_ids={},
            context={},
            clarification_needed=True,  # But needs clarification
            reasoning="Test",
        )
        assert decision.should_route() is False

    def test_should_route_high_confidence_with_clarification(self):
        """should_route() should return False even with high confidence if clarification needed."""
        decision = RouteDecision(
            domain="diagnostic",
            confidence=1.0,  # Perfect confidence
            extracted_ids={},
            context={},
            clarification_needed=True,
            reasoning="Test",
        )
        assert decision.should_route() is False


class TestAgentTransition:
    """Tests for AgentTransition dataclass."""

    def test_agent_transition_creation(self):
        """Should create AgentTransition with all fields."""
        now = datetime.now(UTC)
        transition = AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=now,
            reason="Statement ID detected",
            context_passed={"statement_id": "abc123"},
        )

        assert transition.from_agent == "router"
        assert transition.to_agent == "query"
        assert transition.timestamp == now
        assert transition.reason == "Statement ID detected"
        assert transition.context_passed == {"statement_id": "abc123"}

    def test_agent_transition_immutable(self):
        """AgentTransition should be immutable (frozen)."""
        transition = AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=datetime.now(UTC),
            reason="Test",
            context_passed={},
        )

        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            transition.from_agent = "diagnostic"  # type: ignore

    def test_agent_transition_validates_from_agent(self):
        """Should validate from_agent is not empty."""
        with pytest.raises(ValueError, match="from_agent cannot be empty"):
            AgentTransition(
                from_agent="",
                to_agent="query",
                timestamp=datetime.now(UTC),
                reason="Test",
                context_passed={},
            )

    def test_agent_transition_validates_to_agent(self):
        """Should validate to_agent is not empty."""
        with pytest.raises(ValueError, match="to_agent cannot be empty"):
            AgentTransition(
                from_agent="router",
                to_agent="",
                timestamp=datetime.now(UTC),
                reason="Test",
                context_passed={},
            )

    def test_agent_transition_validates_no_self_transition(self):
        """Should prevent transition to same agent."""
        with pytest.raises(ValueError, match="Cannot transition to same agent"):
            AgentTransition(
                from_agent="query",
                to_agent="query",
                timestamp=datetime.now(UTC),
                reason="Test",
                context_passed={},
            )

    def test_agent_transition_validates_timestamp_not_future(self):
        """Should prevent timestamps in the future."""
        future_time = datetime.now(UTC) + timedelta(hours=1)

        with pytest.raises(ValueError, match="Timestamp cannot be in the future"):
            AgentTransition(
                from_agent="router",
                to_agent="query",
                timestamp=future_time,
                reason="Test",
                context_passed={},
            )

    def test_agent_transition_allows_current_time(self):
        """Should allow current time (within 5 sec tolerance)."""
        now = datetime.now(UTC)
        transition = AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=now,
            reason="Test",
            context_passed={},
        )
        assert transition.timestamp == now


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_create_query_decision_defaults(self):
        """create_query_decision() should use sensible defaults."""
        decision = create_query_decision(extracted_ids={"statement_id": "abc123"})

        assert decision.domain == "query"
        assert decision.confidence == 1.0
        assert decision.extracted_ids == {"statement_id": "abc123"}
        assert decision.context == {}
        assert decision.clarification_needed is False
        assert "Statement ID or SQL" in decision.reasoning

    def test_create_query_decision_custom_confidence(self):
        """create_query_decision() should allow custom confidence."""
        decision = create_query_decision(
            extracted_ids={},
            confidence=0.9,
            reasoning="SQL detected",
        )

        assert decision.domain == "query"
        assert decision.confidence == 0.9
        assert decision.reasoning == "SQL detected"

    def test_create_job_decision_defaults(self):
        """create_job_decision() should use sensible defaults."""
        decision = create_job_decision(extracted_ids={"job_id": "456"})

        assert decision.domain == "job"
        assert decision.confidence == 1.0
        assert decision.extracted_ids == {"job_id": "456"}
        assert decision.context == {}
        assert decision.clarification_needed is False
        assert "Job ID" in decision.reasoning

    def test_create_job_decision_custom_confidence(self):
        """create_job_decision() should allow custom confidence."""
        decision = create_job_decision(
            extracted_ids={},
            confidence=0.8,
            reasoning="Job keyword detected",
        )

        assert decision.domain == "job"
        assert decision.confidence == 0.8
        assert decision.reasoning == "Job keyword detected"

    def test_create_diagnostic_decision_defaults(self):
        """create_diagnostic_decision() should use sensible defaults."""
        decision = create_diagnostic_decision(extracted_ids={})

        assert decision.domain == "diagnostic"
        assert decision.confidence == 0.7
        assert decision.extracted_ids == {}
        assert decision.context == {}
        assert decision.clarification_needed is True  # Default for diagnostic
        assert "Diagnostic keywords" in decision.reasoning

    def test_create_diagnostic_decision_custom_clarification(self):
        """create_diagnostic_decision() should allow custom clarification flag."""
        decision = create_diagnostic_decision(
            extracted_ids={},
            clarification_needed=False,
            reasoning="Clear diagnostic request",
        )

        assert decision.domain == "diagnostic"
        assert decision.clarification_needed is False
        assert decision.reasoning == "Clear diagnostic request"

    def test_helper_functions_create_valid_decisions(self):
        """All helper functions should create valid RouteDecision objects."""
        helpers = [
            create_query_decision({}),
            create_job_decision({}),
            create_diagnostic_decision({}),
        ]

        for decision in helpers:
            # All should pass validation
            assert 0.0 <= decision.confidence <= 1.0
            assert decision.domain in [
                "query",
                "job",
                "uc",
                "cluster",
                "diagnostic",
                "analytics",
            ]
            assert isinstance(decision.extracted_ids, dict)
            assert isinstance(decision.context, dict)
            assert isinstance(decision.clarification_needed, bool)
            assert isinstance(decision.reasoning, str)
