"""
Tests for specialist context builder.

Coverage targets:
- Building context dictionaries
- Merging shared context with routing decisions
- Preserving all context fields
"""

from unittest.mock import Mock

import pytest
from starboard_server.agents.routing.routing_models import RouteDecision
from starboard_server.agents.routing.specialist_context_builder import (
    SpecialistContextBuilder,
)


class TestSpecialistContextBuilder:
    """Tests for SpecialistContextBuilder class."""

    @pytest.fixture
    def builder(self) -> SpecialistContextBuilder:
        """Create a SpecialistContextBuilder instance."""
        return SpecialistContextBuilder()

    @pytest.fixture
    def mock_shared_context(self) -> Mock:
        """Create a mock SharedAgentContext."""
        mock_context = Mock()
        mock_context.to_dict.return_value = {
            "conversation_id": "conv-123",
            "user_id": "user-456",
            "conversation_history": [],
            "working_memory": {},
            "agent_transitions": [],
            "metadata": {"source": "test"},
        }
        return mock_context

    @pytest.fixture
    def route_decision(self) -> RouteDecision:
        """Create a sample RouteDecision."""
        return RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={"statement_id": "abc123"},
            context={},
            clarification_needed=False,
            reasoning="Statement ID detected",
        )

    def test_build_context_includes_shared_fields(
        self,
        builder: SpecialistContextBuilder,
        mock_shared_context: Mock,
        route_decision: RouteDecision,
    ) -> None:
        """Test that build includes all shared context fields."""
        # Act
        result = builder.build(mock_shared_context, route_decision)

        # Assert
        assert result["conversation_id"] == "conv-123"
        assert result["user_id"] == "user-456"
        assert result["conversation_history"] == []
        assert result["working_memory"] == {}
        assert result["agent_transitions"] == []
        assert result["metadata"] == {"source": "test"}

    def test_build_context_includes_routing_fields(
        self,
        builder: SpecialistContextBuilder,
        mock_shared_context: Mock,
        route_decision: RouteDecision,
    ) -> None:
        """Test that build includes routing-specific fields."""
        # Act
        result = builder.build(mock_shared_context, route_decision)

        # Assert
        assert result["domain"] == "query"
        assert result["extracted_ids"] == {"statement_id": "abc123"}
        assert result["route_reasoning"] == "Statement ID detected"
        assert result["route_confidence"] == 0.9

    def test_build_context_all_fields_present(
        self,
        builder: SpecialistContextBuilder,
        mock_shared_context: Mock,
        route_decision: RouteDecision,
    ) -> None:
        """Test that build returns all expected fields."""
        # Act
        result = builder.build(mock_shared_context, route_decision)

        # Assert - Check all expected keys are present
        expected_keys = {
            "conversation_id",
            "user_id",
            "conversation_history",
            "working_memory",
            "agent_transitions",
            "metadata",
            "domain",
            "extracted_ids",
            "route_reasoning",
            "route_confidence",
        }
        assert set(result.keys()) == expected_keys

    def test_build_context_with_different_domains(
        self, builder: SpecialistContextBuilder, mock_shared_context: Mock
    ) -> None:
        """Test building context for different domain types."""
        # Arrange
        domains = [
            "query",
            "job",
            "uc",
            "cluster",
            "diagnostic",
            "analytics",
            "warehouse",
        ]

        # Act & Assert
        for domain in domains:
            decision = RouteDecision(
                domain=domain,  # type: ignore
                confidence=0.8,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning=f"Testing {domain}",
            )

            result = builder.build(mock_shared_context, decision)
            assert result["domain"] == domain

    def test_build_context_with_multiple_extracted_ids(
        self, builder: SpecialistContextBuilder, mock_shared_context: Mock
    ) -> None:
        """Test building context with multiple extracted IDs."""
        # Arrange
        decision = RouteDecision(
            domain="query",
            confidence=1.0,
            extracted_ids={
                "statement_id": "abc123",
                "job_id": "456",
                "table_name": "users",
            },
            context={},
            clarification_needed=False,
            reasoning="Multiple IDs detected",
        )

        # Act
        result = builder.build(mock_shared_context, decision)

        # Assert
        assert result["extracted_ids"] == {
            "statement_id": "abc123",
            "job_id": "456",
            "table_name": "users",
        }

    def test_build_context_with_empty_extracted_ids(
        self, builder: SpecialistContextBuilder, mock_shared_context: Mock
    ) -> None:
        """Test building context with no extracted IDs."""
        # Arrange
        decision = RouteDecision(
            domain="diagnostic",
            confidence=0.7,
            extracted_ids={},
            context={},
            clarification_needed=True,
            reasoning="No specific IDs found",
        )

        # Act
        result = builder.build(mock_shared_context, decision)

        # Assert
        assert result["extracted_ids"] == {}

    def test_build_context_low_confidence(
        self, builder: SpecialistContextBuilder, mock_shared_context: Mock
    ) -> None:
        """Test building context with low confidence routing."""
        # Arrange
        decision = RouteDecision(
            domain="query",
            confidence=0.5,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Uncertain classification",
        )

        # Act
        result = builder.build(mock_shared_context, decision)

        # Assert
        assert result["route_confidence"] == 0.5
        assert result["route_reasoning"] == "Uncertain classification"

    def test_build_context_with_rich_shared_context(
        self, builder: SpecialistContextBuilder, route_decision: RouteDecision
    ) -> None:
        """Test building context with rich shared context data."""
        # Arrange
        mock_context = Mock()
        mock_context.to_dict.return_value = {
            "conversation_id": "conv-789",
            "user_id": "user-101",
            "conversation_history": [
                {"role": "user", "content": "Previous question"},
                {"role": "assistant", "content": "Previous answer"},
            ],
            "working_memory": {
                "last_query": "SELECT * FROM users",
                "context_tables": ["users", "orders"],
            },
            "agent_transitions": [
                {
                    "from_agent": "router",
                    "to_agent": "query",
                    "timestamp": "2025-11-18T12:00:00Z",
                }
            ],
            "metadata": {"session_start": "2025-11-18T11:00:00Z", "platform": "web"},
        }

        # Act
        result = builder.build(mock_context, route_decision)

        # Assert
        assert len(result["conversation_history"]) == 2
        assert result["working_memory"]["last_query"] == "SELECT * FROM users"
        assert len(result["agent_transitions"]) == 1
        assert result["metadata"]["platform"] == "web"

    def test_build_context_preserves_shared_context_structure(
        self, builder: SpecialistContextBuilder
    ) -> None:
        """Test that shared context structure is preserved exactly."""
        # Arrange
        mock_context = Mock()
        original_dict = {
            "conversation_id": "test",
            "user_id": "user",
            "conversation_history": [],
            "working_memory": {"nested": {"data": "value"}},
            "agent_transitions": [],
            "metadata": {},
        }
        mock_context.to_dict.return_value = original_dict.copy()

        decision = RouteDecision(
            domain="query",
            confidence=0.8,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="Test",
        )

        # Act
        result = builder.build(mock_context, decision)

        # Assert - Original shared context fields should be unchanged
        assert result["working_memory"] == {"nested": {"data": "value"}}
        assert result["conversation_history"] == []

    def test_build_context_calls_to_dict_once(
        self, builder: SpecialistContextBuilder, route_decision: RouteDecision
    ) -> None:
        """Test that to_dict is called exactly once on shared context."""
        # Arrange
        mock_context = Mock()
        mock_context.to_dict.return_value = {
            "conversation_id": "test",
            "user_id": "user",
            "conversation_history": [],
            "working_memory": {},
            "agent_transitions": [],
            "metadata": {},
        }

        # Act
        builder.build(mock_context, route_decision)

        # Assert
        mock_context.to_dict.assert_called_once()


class TestSpecialistContextBuilderIntegration:
    """Integration tests for context building."""

    def test_build_context_for_query_specialist(self) -> None:
        """Test building complete context for query specialist."""
        # Arrange
        builder = SpecialistContextBuilder()

        mock_context = Mock()
        mock_context.to_dict.return_value = {
            "conversation_id": "conv-query",
            "user_id": "user-query",
            "conversation_history": [
                {"role": "user", "content": "Optimize statement_id:abc123"}
            ],
            "working_memory": {},
            "agent_transitions": [],
            "metadata": {},
        }

        decision = RouteDecision(
            domain="query",
            confidence=1.0,
            extracted_ids={"statement_id": "abc123"},
            context={},
            clarification_needed=False,
            reasoning="Statement ID abc123 detected",
        )

        # Act
        result = builder.build(mock_context, decision)

        # Assert
        assert result["domain"] == "query"
        assert result["extracted_ids"]["statement_id"] == "abc123"
        assert result["route_confidence"] == 1.0
        assert "abc123" in result["route_reasoning"]

    def test_build_context_for_diagnostic_specialist(self) -> None:
        """Test building complete context for diagnostic specialist."""
        # Arrange
        builder = SpecialistContextBuilder()

        mock_context = Mock()
        mock_context.to_dict.return_value = {
            "conversation_id": "conv-diag",
            "user_id": "user-diag",
            "conversation_history": [
                {"role": "user", "content": "Why is my query slow?"}
            ],
            "working_memory": {},
            "agent_transitions": [],
            "metadata": {},
        }

        decision = RouteDecision(
            domain="diagnostic",
            confidence=0.7,
            extracted_ids={},
            context={},
            clarification_needed=True,
            reasoning="Diagnostic keywords detected",
        )

        # Act
        result = builder.build(mock_context, decision)

        # Assert
        assert result["domain"] == "diagnostic"
        assert result["extracted_ids"] == {}
        assert result["route_confidence"] == 0.7
        assert result["route_reasoning"] == "Diagnostic keywords detected"
