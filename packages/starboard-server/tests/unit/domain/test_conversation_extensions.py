"""Unit tests for conversation pattern domain models."""

import pytest
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    AgentResponse,
    IntentClassification,
    NextStepOption,
    OptionSelection,
    # Phase 2: Conversation Extension
    UserIntentType,
)


class TestNextStepOption:
    """Test NextStepOption domain model."""

    def test_create_tool_call_option(self):
        """Test creating a tool call option."""
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Optimize query",
            description="Rewrite for better performance",
            action_type=ActionType.TOOL_CALL,
            target_agent=None,
            tool_name="optimize_query",
            parameters={"query_id": "123"},
        )

        assert option.id == "opt1"
        assert option.number == 1
        assert option.title == "Optimize query"
        assert option.action_type == ActionType.TOOL_CALL
        assert option.tool_name == "optimize_query"
        assert option.target_agent is None
        assert option.parameters["query_id"] == "123"

    def test_create_route_option(self):
        """Test creating a routing option."""
        option = NextStepOption(
            id="opt2",
            number=2,
            title="Analyze performance",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={"warehouse_id": "prod"},
        )

        assert option.action_type == ActionType.ROUTE
        assert option.target_agent == "performance_analyzer"
        assert option.tool_name is None

    def test_option_immutability(self):
        """Test that option is immutable (frozen dataclass)."""
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Test",
            description=None,
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters=None,
        )

        with pytest.raises(AttributeError):
            option.title = "New title"  # Should fail - frozen

    def test_option_number_valid_range(self):
        """Test option numbers are in valid range."""
        # Valid numbers 1-9
        for n in range(1, 10):
            option = NextStepOption(
                id=f"opt{n}",
                number=n,
                title=f"Option {n}",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            )
            assert 1 <= option.number <= 9

    def test_to_dict(self):
        """Test serialization to dict."""
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Test option",
            description="Test description",
            action_type=ActionType.TOOL_CALL,
            target_agent=None,
            tool_name="test_tool",
            parameters={"key": "value"},
        )

        result = option.to_dict()

        assert result["id"] == "opt1"
        assert result["number"] == 1
        assert result["title"] == "Test option"
        assert result["action_type"] == "tool_call"
        assert result["tool_name"] == "test_tool"
        assert result["parameters"] == {"key": "value"}

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "id": "opt1",
            "number": 1,
            "title": "Test option",
            "description": None,
            "action_type": "route",
            "target_agent": "test_agent",
            "tool_name": None,
            "parameters": None,
        }

        option = NextStepOption.from_dict(data)

        assert option.id == "opt1"
        assert option.number == 1
        assert option.action_type == ActionType.ROUTE
        assert option.target_agent == "test_agent"


class TestAgentResponse:
    """Test AgentResponse domain model."""

    def test_create_response_without_options(self):
        """Test creating response without next steps."""
        response = AgentResponse(
            content="Query analyzed successfully",
            next_steps=None,
            conversation_id="conv-123",
            message_id="msg-456",
            agent_name="query_optimizer",
            metadata={"token_count": 100},
        )

        assert response.content == "Query analyzed successfully"
        assert response.next_steps is None
        assert response.conversation_id == "conv-123"
        assert response.agent_name == "query_optimizer"
        assert response.metadata["token_count"] == 100

    def test_create_response_with_options(self):
        """Test creating response with next steps."""
        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Option 1",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
            NextStepOption(
                id="opt2",
                number=2,
                title="Option 2",
                description=None,
                action_type=ActionType.ROUTE,
                target_agent="other_agent",
                tool_name=None,
                parameters=None,
            ),
        )

        response = AgentResponse(
            content="Here are your options:",
            next_steps=options,
            conversation_id="conv-123",
            message_id="msg-456",
            agent_name="test_agent",
            metadata={},
        )

        assert len(response.next_steps) == 2
        assert response.next_steps[0].number == 1
        assert response.next_steps[1].number == 2

    def test_response_immutability(self):
        """Test that response is immutable."""
        response = AgentResponse(
            content="Test",
            next_steps=None,
            conversation_id="conv-123",
            message_id="msg-456",
            agent_name="test_agent",
            metadata={},
        )

        with pytest.raises(AttributeError):
            response.content = "New content"  # Should fail - frozen

    def test_to_dict(self):
        """Test serialization to dict."""
        options = (
            NextStepOption(
                id="opt1",
                number=1,
                title="Test",
                description=None,
                action_type=ActionType.CONTINUE,
                target_agent=None,
                tool_name=None,
                parameters=None,
            ),
        )

        response = AgentResponse(
            content="Test response",
            next_steps=options,
            conversation_id="conv-123",
            message_id="msg-456",
            agent_name="test_agent",
            metadata={"key": "value"},
        )

        result = response.to_dict()

        assert result["content"] == "Test response"
        assert len(result["next_steps"]) == 1
        assert result["conversation_id"] == "conv-123"
        assert result["metadata"]["key"] == "value"


class TestOptionSelection:
    """Test OptionSelection domain model."""

    def test_create_option_selection(self):
        """Test creating an option selection result."""
        option = NextStepOption(
            id="opt1",
            number=1,
            title="Test",
            description=None,
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters=None,
        )

        selection = OptionSelection(
            selection_type="option",
            selected_option=option,
            original_input="1",
            confidence=1.0,
        )

        assert selection.selection_type == "option"
        assert selection.selected_option.number == 1
        assert selection.original_input == "1"
        assert selection.confidence == 1.0

    def test_create_free_text_selection(self):
        """Test creating a free text selection result."""
        selection = OptionSelection(
            selection_type="free_text",
            selected_option=None,
            original_input="Tell me about costs",
            confidence=1.0,
        )

        assert selection.selection_type == "free_text"
        assert selection.selected_option is None
        assert selection.original_input == "Tell me about costs"

    def test_confidence_range(self):
        """Test confidence is in valid range."""
        selection = OptionSelection(
            selection_type="option",
            selected_option=None,
            original_input="test",
            confidence=0.75,
        )

        assert 0.0 <= selection.confidence <= 1.0

    def test_selection_immutability(self):
        """Test that selection is immutable."""
        selection = OptionSelection(
            selection_type="free_text",
            selected_option=None,
            original_input="test",
            confidence=1.0,
        )

        with pytest.raises(AttributeError):
            selection.confidence = 0.5  # Should fail - frozen


class TestActionType:
    """Test ActionType enum."""

    def test_action_type_values(self):
        """Test all action type values."""
        assert ActionType.CONTINUE.value == "continue"
        assert ActionType.ROUTE.value == "route"
        assert ActionType.TOOL_CALL.value == "tool_call"

    def test_action_type_from_string(self):
        """Test creating ActionType from string."""
        assert ActionType("continue") == ActionType.CONTINUE
        assert ActionType("route") == ActionType.ROUTE
        assert ActionType("tool_call") == ActionType.TOOL_CALL

    def test_invalid_action_type(self):
        """Test invalid action type raises error."""
        with pytest.raises(ValueError):
            ActionType("invalid")


# ==============================================================================
# Phase 2: Conversation Extension Pattern Tests
# ==============================================================================


class TestUserIntentType:
    """Test UserIntentType enum for Phase 2: Conversation Extension."""

    def test_user_intent_type_values(self):
        """Test all UserIntentType enum values."""
        assert UserIntentType.EXTENSION.value == "extension"
        assert UserIntentType.REFINEMENT.value == "refinement"
        assert UserIntentType.CLARIFICATION.value == "clarification"
        assert UserIntentType.NEW_QUERY.value == "new_query"
        assert UserIntentType.FEEDBACK.value == "feedback"

    def test_user_intent_type_from_string(self):
        """Test creating UserIntentType from string."""
        assert UserIntentType("extension") == UserIntentType.EXTENSION
        assert UserIntentType("refinement") == UserIntentType.REFINEMENT
        assert UserIntentType("clarification") == UserIntentType.CLARIFICATION
        assert UserIntentType("new_query") == UserIntentType.NEW_QUERY
        assert UserIntentType("feedback") == UserIntentType.FEEDBACK

    def test_invalid_user_intent_type(self):
        """Test invalid intent type raises error."""
        with pytest.raises(ValueError):
            UserIntentType("invalid")


class TestIntentClassification:
    """Test IntentClassification model for Phase 2: Conversation Extension."""

    def test_create_extension_intent(self):
        """Test creating an EXTENSION intent classification."""
        classification = IntentClassification(
            intent_type=UserIntentType.EXTENSION,
            confidence=0.92,
            reasoning="User is adding time-based constraints to existing query analysis",
            extracted_entities={"timeframe": "morning", "metric": "performance"},
        )

        assert classification.intent_type == UserIntentType.EXTENSION
        assert classification.confidence == 0.92
        assert "time-based constraints" in classification.reasoning
        assert classification.extracted_entities["timeframe"] == "morning"
        assert classification.extracted_entities["metric"] == "performance"

    def test_create_new_query_intent(self):
        """Test creating a NEW_QUERY intent classification."""
        classification = IntentClassification(
            intent_type=UserIntentType.NEW_QUERY,
            confidence=0.98,
            reasoning="Topic completely different from previous conversation",
            extracted_entities={},
        )

        assert classification.intent_type == UserIntentType.NEW_QUERY
        assert classification.confidence == 0.98
        assert classification.extracted_entities == {}

    def test_create_refinement_intent(self):
        """Test creating a REFINEMENT intent classification."""
        classification = IntentClassification(
            intent_type=UserIntentType.REFINEMENT,
            confidence=0.85,
            reasoning="User correcting previous assumption about warehouse",
            extracted_entities={"corrected_warehouse": "prod_dw"},
        )

        assert classification.intent_type == UserIntentType.REFINEMENT
        assert classification.confidence == 0.85
        assert "correcting" in classification.reasoning

    def test_create_clarification_intent(self):
        """Test creating a CLARIFICATION intent classification."""
        classification = IntentClassification(
            intent_type=UserIntentType.CLARIFICATION,
            confidence=1.0,
            reasoning="User answering agent's direct question",
            extracted_entities={"answer": "yes", "confirmed": True},
        )

        assert classification.intent_type == UserIntentType.CLARIFICATION
        assert classification.confidence == 1.0

    def test_create_feedback_intent(self):
        """Test creating a FEEDBACK intent classification."""
        classification = IntentClassification(
            intent_type=UserIntentType.FEEDBACK,
            confidence=0.95,
            reasoning="User expressing satisfaction with recommendation",
            extracted_entities={"sentiment": "positive"},
        )

        assert classification.intent_type == UserIntentType.FEEDBACK
        assert classification.confidence == 0.95

    def test_intent_classification_immutability(self):
        """Test that IntentClassification is immutable."""
        classification = IntentClassification(
            intent_type=UserIntentType.EXTENSION,
            confidence=0.9,
            reasoning="Test",
            extracted_entities={},
        )

        with pytest.raises(Exception):  # Frozen dataclass
            classification.confidence = 0.5  # type: ignore

    def test_serialization_round_trip(self):
        """Test serializing and deserializing IntentClassification."""
        original = IntentClassification(
            intent_type=UserIntentType.EXTENSION,
            confidence=0.87,
            reasoning="Adding constraints to query analysis",
            extracted_entities={
                "timeframe": "morning",
                "constraint": "slow_performance",
                "threshold_ms": 5000,
            },
        )

        # Serialize
        data = original.to_dict()

        # Verify serialized format
        assert data["intent_type"] == "extension"
        assert data["confidence"] == 0.87
        assert data["reasoning"] == "Adding constraints to query analysis"
        assert data["extracted_entities"]["timeframe"] == "morning"
        assert data["extracted_entities"]["threshold_ms"] == 5000

        # Deserialize
        restored = IntentClassification.from_dict(data)

        # Verify round-trip
        assert restored.intent_type == original.intent_type
        assert restored.confidence == original.confidence
        assert restored.reasoning == original.reasoning
        assert restored.extracted_entities == original.extracted_entities

    def test_confidence_bounds(self):
        """Test confidence is between 0.0 and 1.0."""
        # Valid confidence values
        valid = IntentClassification(
            intent_type=UserIntentType.EXTENSION,
            confidence=0.75,
            reasoning="Test",
            extracted_entities={},
        )
        assert 0.0 <= valid.confidence <= 1.0

        # Edge cases
        edge_low = IntentClassification(
            intent_type=UserIntentType.EXTENSION,
            confidence=0.0,
            reasoning="Test",
            extracted_entities={},
        )
        assert edge_low.confidence == 0.0

        edge_high = IntentClassification(
            intent_type=UserIntentType.EXTENSION,
            confidence=1.0,
            reasoning="Test",
            extracted_entities={},
        )
        assert edge_high.confidence == 1.0

    def test_empty_extracted_entities(self):
        """Test IntentClassification with no extracted entities."""
        classification = IntentClassification(
            intent_type=UserIntentType.NEW_QUERY,
            confidence=0.99,
            reasoning="Completely new topic",
            extracted_entities={},
        )

        assert classification.extracted_entities == {}

        # Should serialize/deserialize correctly
        data = classification.to_dict()
        restored = IntentClassification.from_dict(data)
        assert restored.extracted_entities == {}

    def test_complex_extracted_entities(self):
        """Test IntentClassification with complex nested entities."""
        classification = IntentClassification(
            intent_type=UserIntentType.EXTENSION,
            confidence=0.88,
            reasoning="Multi-dimensional constraint addition",
            extracted_entities={
                "temporal": {
                    "start_time": "08:00",
                    "end_time": "10:00",
                    "timezone": "UTC",
                },
                "filters": ["warehouse_id:prod", "status:running"],
                "threshold": 5000,
                "enabled": True,
            },
        )

        # Verify nested structure
        assert classification.extracted_entities["temporal"]["start_time"] == "08:00"
        assert len(classification.extracted_entities["filters"]) == 2
        assert classification.extracted_entities["enabled"] is True

        # Verify serialization handles nested structures
        data = classification.to_dict()
        restored = IntentClassification.from_dict(data)
        assert restored.extracted_entities == classification.extracted_entities
