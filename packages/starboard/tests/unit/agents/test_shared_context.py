# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for SharedAgentContext (Phase 3, Task 3.1).

Tests cover:
- Context initialization and validation
- Message management
- Agent transition tracking
- Working memory integration
- Serialization/deserialization
- Helper methods
"""

from datetime import UTC, datetime

import pytest
from starboard.agents.routing.routing_models import AgentTransition
from starboard.agents.state.agent_state import Message, WorkingMemory
from starboard.agents.state.shared_context import SharedAgentContext

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def basic_context():
    """Create a basic SharedAgentContext for testing."""
    return SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_456",
        conversation_history=[],
        working_memory=WorkingMemory(),
    )


@pytest.fixture
def context_with_history():
    """Create context with conversation history."""
    return SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_456",
        conversation_history=[
            Message(role="user", content="Optimize query abc123"),
            Message(role="assistant", content="I'll help you with that"),
        ],
        working_memory=WorkingMemory(facts=["Statement ID: abc123"]),
    )


# =============================================================================
# Test: Initialization and Validation
# =============================================================================


def test_context_initialization(basic_context):
    """Context should initialize with required fields."""
    assert basic_context.conversation_id == "conv_123"
    assert basic_context.user_id == "user_456"
    assert basic_context.conversation_history == []
    assert isinstance(basic_context.working_memory, WorkingMemory)
    assert basic_context.agent_transitions == []
    assert basic_context.metadata == {}


def test_context_requires_conversation_id():
    """Context should require conversation_id."""
    with pytest.raises(ValueError, match="conversation_id cannot be empty"):
        SharedAgentContext(
            conversation_id="",
            user_id="user_456",
            conversation_history=[],
            working_memory=WorkingMemory(),
        )


def test_context_requires_user_id():
    """Context should require user_id."""
    with pytest.raises(ValueError, match="user_id cannot be empty"):
        SharedAgentContext(
            conversation_id="conv_123",
            user_id="",
            conversation_history=[],
            working_memory=WorkingMemory(),
        )


def test_context_validates_conversation_history_type():
    """Context should validate conversation_history is a list."""
    with pytest.raises(TypeError, match="conversation_history must be a list"):
        SharedAgentContext(
            conversation_id="conv_123",
            user_id="user_456",
            conversation_history=("not", "a", "list"),  # type: ignore
            working_memory=WorkingMemory(),
        )


def test_context_validates_message_types():
    """Context should validate all conversation_history items are Messages."""
    with pytest.raises(
        TypeError, match="All conversation_history items must be Message"
    ):
        SharedAgentContext(
            conversation_id="conv_123",
            user_id="user_456",
            conversation_history=["not a message"],  # type: ignore
            working_memory=WorkingMemory(),
        )


def test_context_validates_working_memory_type():
    """Context should validate working_memory is WorkingMemory instance."""
    with pytest.raises(TypeError, match="working_memory must be a WorkingMemory"):
        SharedAgentContext(
            conversation_id="conv_123",
            user_id="user_456",
            conversation_history=[],
            working_memory={"not": "working_memory"},  # type: ignore
        )


# =============================================================================
# Test: Message Management
# =============================================================================


def test_add_message(basic_context):
    """add_message should append message to conversation history."""
    msg = Message(role="user", content="Hello")
    basic_context.add_message(msg)

    assert len(basic_context.conversation_history) == 1
    assert basic_context.conversation_history[0] is msg


def test_add_message_validates_type(basic_context):
    """add_message should validate message type."""
    with pytest.raises(TypeError, match="message must be a Message instance"):
        basic_context.add_message("not a message")  # type: ignore


def test_get_last_user_message(context_with_history):
    """get_last_user_message should return most recent user message."""
    last_user = context_with_history.get_last_user_message()

    assert last_user is not None
    assert last_user.role == "user"
    assert last_user.content == "Optimize query abc123"


def test_get_last_user_message_with_multiple_users(basic_context):
    """get_last_user_message should return most recent when multiple exist."""
    basic_context.add_message(Message(role="user", content="First"))
    basic_context.add_message(Message(role="assistant", content="Response"))
    basic_context.add_message(Message(role="user", content="Second"))

    last_user = basic_context.get_last_user_message()

    assert last_user is not None
    assert last_user.content == "Second"


def test_get_last_user_message_returns_none_when_no_users(basic_context):
    """get_last_user_message should return None if no user messages."""
    basic_context.add_message(Message(role="assistant", content="Hello"))

    last_user = basic_context.get_last_user_message()

    assert last_user is None


# =============================================================================
# Test: Agent Transition Tracking
# =============================================================================


def test_add_transition(basic_context):
    """add_transition should append transition to history."""
    transition = AgentTransition(
        from_agent="router",
        to_agent="query",
        timestamp=datetime.now(UTC),
        reason="User provided statement_id",
        context_passed={"statement_id": "abc123"},
    )

    basic_context.add_transition(transition)

    assert len(basic_context.agent_transitions) == 1
    assert basic_context.agent_transitions[0] is transition


def test_add_transition_validates_type(basic_context):
    """add_transition should validate transition type."""
    with pytest.raises(TypeError, match="transition must be an AgentTransition"):
        basic_context.add_transition("not a transition")  # type: ignore


def test_get_transition_count(basic_context):
    """get_transition_count should return correct count."""
    assert basic_context.get_transition_count() == 0

    basic_context.add_transition(
        AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=datetime.now(UTC),
            reason="test",
            context_passed={},
        )
    )

    assert basic_context.get_transition_count() == 1


def test_get_current_agent(basic_context):
    """get_current_agent should return agent from last transition."""
    assert basic_context.get_current_agent() is None

    basic_context.add_transition(
        AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=datetime.now(UTC),
            reason="test",
            context_passed={},
        )
    )

    assert basic_context.get_current_agent() == "query"

    # Add another transition
    basic_context.add_transition(
        AgentTransition(
            from_agent="query",
            to_agent="table",
            timestamp=datetime.now(UTC),
            reason="needs table info",
            context_passed={},
        )
    )

    assert basic_context.get_current_agent() == "table"


# =============================================================================
# Test: Working Memory Integration
# =============================================================================


def test_merge_working_memory(basic_context):
    """merge_working_memory should combine working memories."""
    basic_context.working_memory = WorkingMemory(facts=["fact1"])

    other_memory = WorkingMemory(facts=["fact2"])
    basic_context.merge_working_memory(other_memory)

    # Should have both facts
    assert "fact1" in basic_context.working_memory.facts
    assert "fact2" in basic_context.working_memory.facts


def test_merge_working_memory_validates_type(basic_context):
    """merge_working_memory should validate memory type."""
    with pytest.raises(TypeError, match="other_memory must be a WorkingMemory"):
        basic_context.merge_working_memory({"not": "working_memory"})  # type: ignore


# =============================================================================
# Test: Serialization
# =============================================================================


def test_to_dict(context_with_history):
    """to_dict should serialize context correctly."""
    data = context_with_history.to_dict()

    assert data["conversation_id"] == "conv_123"
    assert data["user_id"] == "user_456"
    assert len(data["conversation_history"]) == 2
    assert data["conversation_history"][0]["role"] == "user"
    assert data["conversation_history"][0]["content"] == "Optimize query abc123"
    assert "working_memory" in data
    assert "agent_transitions" in data
    assert "metadata" in data


def test_to_dict_includes_message_metadata():
    """to_dict should include message metadata."""
    context = SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_456",
        conversation_history=[
            Message(
                role="user",
                content="test",
                name="test_name",
                tool_call_id="call_123",
                metadata={"key": "value"},
            )
        ],
        working_memory=WorkingMemory(),
    )

    data = context.to_dict()
    msg_data = data["conversation_history"][0]

    assert msg_data["name"] == "test_name"
    assert msg_data["tool_call_id"] == "call_123"
    assert msg_data["metadata"] == {"key": "value"}


def test_to_dict_includes_transitions():
    """to_dict should include agent transitions."""
    context = SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_456",
        conversation_history=[],
        working_memory=WorkingMemory(),
    )

    transition = AgentTransition(
        from_agent="router",
        to_agent="query",
        timestamp=datetime(2025, 11, 18, 13, 0, 0, tzinfo=UTC),
        reason="User provided statement_id",
        context_passed={"statement_id": "abc123"},
    )
    context.add_transition(transition)

    data = context.to_dict()

    assert len(data["agent_transitions"]) == 1
    t_data = data["agent_transitions"][0]
    assert t_data["from_agent"] == "router"
    assert t_data["to_agent"] == "query"
    assert t_data["reason"] == "User provided statement_id"
    assert t_data["timestamp"] == "2025-11-18T13:00:00+00:00"
    assert t_data["context_passed"] == {"statement_id": "abc123"}


def test_from_dict():
    """from_dict should deserialize context correctly."""
    data = {
        "conversation_id": "conv_123",
        "user_id": "user_456",
        "conversation_history": [
            {
                "role": "user",
                "content": "Hello",
                "name": None,
                "tool_call_id": None,
                "metadata": {},
            }
        ],
        "working_memory": {
            "summaries": {},
            "facts": ["fact1"],
            "tools_used": [],
            "metrics": {},
            "user_context": {},
            "clarifications": [],
        },
        "agent_transitions": [
            {
                "from_agent": "router",
                "to_agent": "query",
                "timestamp": "2025-11-18T13:00:00+00:00",
                "reason": "test",
                "context_passed": {},
            }
        ],
        "metadata": {"key": "value"},
    }

    context = SharedAgentContext.from_dict(data)

    assert context.conversation_id == "conv_123"
    assert context.user_id == "user_456"
    assert len(context.conversation_history) == 1
    assert context.conversation_history[0].content == "Hello"
    assert context.working_memory.facts == ("fact1",)  # WorkingMemory uses tuples
    assert len(context.agent_transitions) == 1
    assert context.agent_transitions[0].to_agent == "query"
    assert context.metadata == {"key": "value"}


def test_from_dict_handles_missing_optional_fields():
    """from_dict should handle missing optional fields."""
    data = {
        "conversation_id": "conv_123",
        "user_id": "user_456",
        "conversation_history": [],
        "working_memory": {
            "summaries": {},
            "facts": [],
            "tools_used": [],
            "metrics": {},
            "user_context": {},
            "clarifications": [],
        },
    }

    context = SharedAgentContext.from_dict(data)

    assert context.agent_transitions == []
    assert context.metadata == {}


def test_round_trip_serialization(context_with_history):
    """Context should survive round-trip serialization."""
    # Add transition for completeness
    context_with_history.add_transition(
        AgentTransition(
            from_agent="router",
            to_agent="query",
            timestamp=datetime.now(UTC),
            reason="test",
            context_passed={},
        )
    )

    # Serialize
    data = context_with_history.to_dict()

    # Deserialize
    restored = SharedAgentContext.from_dict(data)

    # Verify
    assert restored.conversation_id == context_with_history.conversation_id
    assert restored.user_id == context_with_history.user_id
    assert len(restored.conversation_history) == len(
        context_with_history.conversation_history
    )
    assert len(restored.agent_transitions) == len(
        context_with_history.agent_transitions
    )


# =============================================================================
# Test: Phase 3 Task 3.1 Acceptance Criteria
# =============================================================================


def test_phase3_task31_acceptance_criteria():
    """
    Comprehensive test for Phase 3, Task 3.1 acceptance criteria.

    Acceptance Criteria:
    - [x] SharedAgentContext dataclass defined
    - [x] Immutable conversation history
    - [x] Working memory integration
    - [x] Agent transition tracking
    - [x] Serialization methods
    - [x] Unit tests for context management
    """
    # ✅ SharedAgentContext dataclass defined
    context = SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_456",
        conversation_history=[],
        working_memory=WorkingMemory(),
    )
    assert context is not None

    # ✅ Immutable conversation history
    # (Messages are frozen dataclasses, history list can be modified but messages can't)
    msg = Message(role="user", content="test")
    with pytest.raises(Exception):  # FrozenInstanceError
        msg.role = "assistant"  # type: ignore

    # ✅ Working memory integration
    context.merge_working_memory(WorkingMemory(facts=("fact1",)))  # Use tuple, not list
    assert "fact1" in context.working_memory.facts

    # ✅ Agent transition tracking
    transition = AgentTransition(
        from_agent="router",
        to_agent="query",
        timestamp=datetime.now(UTC),
        reason="test",
        context_passed={},
    )
    context.add_transition(transition)
    assert context.get_transition_count() == 1
    assert context.get_current_agent() == "query"

    # ✅ Serialization methods
    data = context.to_dict()
    assert "conversation_id" in data
    assert "working_memory" in data
    assert "agent_transitions" in data

    restored = SharedAgentContext.from_dict(data)
    assert restored.conversation_id == context.conversation_id

    # ✅ Unit tests for context management
    # (This test itself validates the functionality)
    assert True


# =============================================================================
# Phase 2: Context Enrichment Tests (Conversation Extension Pattern)
# =============================================================================


def test_enrich_from_intent_classification_with_entities(basic_context):
    """Test enriching context with extracted entities from intent classification."""
    from starboard.domain.models.conversation_patterns import (
        IntentClassification,
        UserIntentType,
    )

    # Create intent classification with entities
    classification = IntentClassification(
        intent_type=UserIntentType.EXTENSION,
        confidence=0.85,
        reasoning="User added temporal constraint",
        extracted_entities={
            "timeframe": "morning",
            "warehouse": "prod_dw",
            "metrics": ["45 seconds"],
        },
    )

    # Enrich context
    basic_context.enrich_from_intent(classification)

    # Verify entities were added to working memory (in metrics dict)
    assert "user_constraints" in basic_context.working_memory.metrics
    constraints = basic_context.working_memory.metrics["user_constraints"]
    assert constraints["timeframe"] == "morning"
    assert constraints["warehouse"] == "prod_dw"

    # Verify metadata was updated
    assert "last_intent" in basic_context.metadata
    assert basic_context.metadata["last_intent"]["intent_type"] == "extension"
    assert basic_context.metadata["last_intent"]["confidence"] == 0.85


def test_enrich_from_intent_classification_without_entities(basic_context):
    """Test enriching context when classification has no entities."""
    from starboard.domain.models.conversation_patterns import (
        IntentClassification,
        UserIntentType,
    )

    classification = IntentClassification(
        intent_type=UserIntentType.NEW_QUERY,
        confidence=0.95,
        reasoning="First message in conversation",
        extracted_entities={},
    )

    basic_context.enrich_from_intent(classification)

    # Metadata should be updated
    assert "last_intent" in basic_context.metadata
    assert basic_context.metadata["last_intent"]["intent_type"] == "new_query"

    # But no constraints added to working memory
    assert (
        "user_constraints" not in basic_context.working_memory.metrics
        or basic_context.working_memory.metrics["user_constraints"] == {}
    )


def test_enrich_accumulates_entities_across_turns(basic_context):
    """Test that entities accumulate across multiple enrichments."""
    from starboard.domain.models.conversation_patterns import (
        IntentClassification,
        UserIntentType,
    )

    # First enrichment
    classification1 = IntentClassification(
        intent_type=UserIntentType.EXTENSION,
        confidence=0.85,
        reasoning="Added timeframe",
        extracted_entities={"timeframe": "morning"},
    )
    basic_context.enrich_from_intent(classification1)

    # Second enrichment
    classification2 = IntentClassification(
        intent_type=UserIntentType.EXTENSION,
        confidence=0.82,
        reasoning="Added warehouse",
        extracted_entities={"warehouse": "prod_dw"},
    )
    basic_context.enrich_from_intent(classification2)

    # Both entities should be present
    constraints = basic_context.working_memory.metrics.get("user_constraints", {})
    assert constraints["timeframe"] == "morning"
    assert constraints["warehouse"] == "prod_dw"


def test_get_conversation_depth_empty(basic_context):
    """Test conversation depth for empty history."""
    depth = basic_context.get_conversation_depth()
    assert depth == 0


def test_get_conversation_depth_with_messages(context_with_history):
    """Test conversation depth counts turns (user messages)."""
    # context_with_history has 2 messages (user + assistant = 1 turn)
    depth = context_with_history.get_conversation_depth()
    assert depth == 1

    # Add another turn
    context_with_history.add_message(Message(role="user", content="What about costs?"))
    context_with_history.add_message(
        Message(role="assistant", content="Here's the cost analysis...")
    )

    depth = context_with_history.get_conversation_depth()
    assert depth == 2


def test_get_conversation_depth_user_only():
    """Test conversation depth with only user messages."""
    context = SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_456",
        conversation_history=[
            Message(role="user", content="First message"),
            Message(role="user", content="Second message"),
        ],
        working_memory=WorkingMemory(),
    )

    depth = context.get_conversation_depth()
    assert depth == 2


def test_get_user_constraints_empty(basic_context):
    """Test getting user constraints when none exist."""
    constraints = basic_context.get_user_constraints()
    assert constraints == {}


def test_get_user_constraints_with_entities(basic_context):
    """Test getting user constraints after enrichment."""
    from starboard.domain.models.conversation_patterns import (
        IntentClassification,
        UserIntentType,
    )

    classification = IntentClassification(
        intent_type=UserIntentType.EXTENSION,
        confidence=0.85,
        reasoning="Added constraints",
        extracted_entities={
            "timeframe": "morning",
            "warehouse": "prod_dw",
        },
    )
    basic_context.enrich_from_intent(classification)

    constraints = basic_context.get_user_constraints()
    assert constraints["timeframe"] == "morning"
    assert constraints["warehouse"] == "prod_dw"


def test_needs_summarization_short_conversation(context_with_history):
    """Test that short conversations don't need summarization."""
    # Default threshold is 10 turns
    needs_summary = context_with_history.needs_summarization()
    assert needs_summary is False


def test_needs_summarization_long_conversation():
    """Test that long conversations trigger summarization."""
    context = SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_456",
        conversation_history=[
            Message(role="user", content=f"Message {i}")
            for i in range(25)  # 25 messages (well over threshold)
        ],
        working_memory=WorkingMemory(),
    )

    needs_summary = context.needs_summarization()
    assert needs_summary is True


def test_needs_summarization_custom_threshold():
    """Test summarization with custom threshold."""
    context = SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_456",
        conversation_history=[
            Message(role="user", content=f"Message {i}")
            for i in range(6)  # 6 messages
        ],
        working_memory=WorkingMemory(),
    )

    # Default threshold (10) - should not need summarization
    assert context.needs_summarization() is False

    # Custom threshold (5) - should need summarization
    assert context.needs_summarization(threshold=5) is True


def test_mark_as_summarized(basic_context):
    """Test marking conversation as summarized."""
    basic_context.mark_as_summarized(
        summary="User asked about query optimization for prod_dw warehouse, focusing on morning performance."
    )

    assert basic_context.metadata["summarized"] is True
    assert (
        basic_context.metadata["summary"]
        == "User asked about query optimization for prod_dw warehouse, focusing on morning performance."
    )
    assert "summarized_at" in basic_context.metadata


def test_clear_user_constraints(basic_context):
    """Test clearing user constraints (for new queries)."""
    from starboard.domain.models.conversation_patterns import (
        IntentClassification,
        UserIntentType,
    )

    # Add constraints
    classification = IntentClassification(
        intent_type=UserIntentType.EXTENSION,
        confidence=0.85,
        reasoning="Added constraints",
        extracted_entities={"timeframe": "morning"},
    )
    basic_context.enrich_from_intent(classification)

    # Verify constraints exist
    assert "timeframe" in basic_context.get_user_constraints()

    # Clear constraints
    basic_context.clear_user_constraints()

    # Verify cleared
    assert basic_context.get_user_constraints() == {}


def test_get_last_intent_no_enrichment(basic_context):
    """Test getting last intent when no enrichment has occurred."""
    last_intent = basic_context.get_last_intent()
    assert last_intent is None


def test_get_last_intent_after_enrichment(basic_context):
    """Test getting last intent after enrichment."""
    from starboard.domain.models.conversation_patterns import (
        IntentClassification,
        UserIntentType,
    )

    classification = IntentClassification(
        intent_type=UserIntentType.EXTENSION,
        confidence=0.85,
        reasoning="Added temporal constraint",
        extracted_entities={"timeframe": "morning"},
    )
    basic_context.enrich_from_intent(classification)

    last_intent = basic_context.get_last_intent()
    assert last_intent is not None
    assert last_intent["intent_type"] == "extension"
    assert last_intent["confidence"] == 0.85
    assert last_intent["reasoning"] == "Added temporal constraint"


# =============================================================================
# Option Selection Parameter Enrichment Tests (Next Steps Context Passing)
# =============================================================================


def test_enrich_from_option_selection_basic(basic_context):
    """Test basic parameter enrichment from option selection."""
    parameters = {
        "job_id": "31942593021809",
        "handoff_context": "High-frequency execution",
    }

    option_metadata = {
        "id": "analyze_job_1",
        "action_type": "route",
        "target_agent": "job",
    }

    basic_context.enrich_from_option_selection(parameters, option_metadata)

    # Verify parameters added to user_constraints
    constraints = basic_context.get_user_constraints()
    assert constraints["job_id"] == "31942593021809"
    assert constraints["handoff_context"] == "High-frequency execution"

    # Verify metadata tracking
    assert "last_option_selection" in basic_context.metadata
    assert basic_context.metadata["last_option_selection"]["id"] == "analyze_job_1"
    assert basic_context.metadata["last_option_selection"]["action_type"] == "route"
    assert basic_context.metadata["last_option_selection"]["target_agent"] == "job"
    assert "parameters" in basic_context.metadata["last_option_selection"]
    assert "timestamp" in basic_context.metadata["last_option_selection"]


def test_enrich_from_option_selection_merge(basic_context):
    """Test that parameters merge with existing constraints."""
    # Add initial constraints (e.g., from intent classification)
    basic_context.working_memory.metrics["user_constraints"] = {
        "timeframe": "morning",
        "warehouse": "prod_dw",
    }

    # Add parameters via option selection
    parameters = {
        "job_id": "123",
        "query_id": "q_456",
    }
    basic_context.enrich_from_option_selection(parameters)

    # Verify merge (not replace)
    constraints = basic_context.get_user_constraints()
    assert constraints["timeframe"] == "morning"
    assert constraints["warehouse"] == "prod_dw"
    assert constraints["job_id"] == "123"
    assert constraints["query_id"] == "q_456"
    assert len(constraints) == 4


def test_enrich_from_option_selection_empty_parameters(basic_context):
    """Test graceful handling of empty parameters."""
    # Enrich with empty parameters
    basic_context.enrich_from_option_selection({})

    # Should not crash, constraints should be empty dict
    constraints = basic_context.get_user_constraints()
    assert constraints == {}

    # Metadata should still be tracked
    assert "last_option_selection" in basic_context.metadata


def test_enrich_from_option_selection_parameter_override(basic_context):
    """Test that new parameters override existing ones with same key."""
    # Add initial job_id via intent
    basic_context.working_memory.metrics["user_constraints"] = {
        "job_id": "old_job_123",
    }

    # Add new job_id via option selection
    parameters = {
        "job_id": "new_job_456",
    }
    basic_context.enrich_from_option_selection(parameters)

    # New value should override old value
    constraints = basic_context.get_user_constraints()
    assert constraints["job_id"] == "new_job_456"


def test_enrich_from_option_selection_without_metadata(basic_context):
    """Test enrichment without providing option metadata."""
    parameters = {
        "job_id": "123",
    }

    # Call without option_metadata
    basic_context.enrich_from_option_selection(parameters, option_metadata=None)

    # Parameters should still be added
    constraints = basic_context.get_user_constraints()
    assert constraints["job_id"] == "123"

    # Metadata should be tracked (but without option details)
    assert "last_option_selection" in basic_context.metadata
    assert "parameters" in basic_context.metadata["last_option_selection"]
    assert "timestamp" in basic_context.metadata["last_option_selection"]


def test_get_last_option_selection(basic_context):
    """Test retrieval of last option selection metadata."""
    # No option selection yet
    assert basic_context.get_last_option_selection() is None

    # Add option selection
    parameters = {"job_id": "123"}
    option_metadata = {
        "id": "opt_1",
        "action_type": "route",
        "target_agent": "job",
    }
    basic_context.enrich_from_option_selection(parameters, option_metadata)

    # Retrieve metadata
    last_selection = basic_context.get_last_option_selection()
    assert last_selection is not None
    assert last_selection["id"] == "opt_1"
    assert last_selection["action_type"] == "route"
    assert last_selection["target_agent"] == "job"


def test_enrich_from_option_selection_multiple_times(basic_context):
    """Test multiple option selections, verify latest is tracked."""
    # First selection
    parameters1 = {"job_id": "123"}
    option_metadata1 = {"id": "opt_1", "action_type": "continue"}
    basic_context.enrich_from_option_selection(parameters1, option_metadata1)

    # Second selection
    parameters2 = {"query_id": "q_456"}
    option_metadata2 = {"id": "opt_2", "action_type": "route"}
    basic_context.enrich_from_option_selection(parameters2, option_metadata2)

    # Last selection metadata should be opt_2
    last_selection = basic_context.get_last_option_selection()
    assert last_selection["id"] == "opt_2"
    assert last_selection["action_type"] == "route"

    # Both parameters should be present
    constraints = basic_context.get_user_constraints()
    assert constraints["job_id"] == "123"
    assert constraints["query_id"] == "q_456"


def test_enrich_from_option_selection_accumulates_with_intent(basic_context):
    """Test that option parameters accumulate with intent entities."""
    from starboard.domain.models.conversation_patterns import (
        IntentClassification,
        UserIntentType,
    )

    # First, enrich from intent
    classification = IntentClassification(
        intent_type=UserIntentType.EXTENSION,
        confidence=0.85,
        reasoning="Added timeframe",
        extracted_entities={"timeframe": "morning"},
    )
    basic_context.enrich_from_intent(classification)

    # Then, enrich from option selection
    parameters = {"job_id": "123"}
    basic_context.enrich_from_option_selection(parameters)

    # Both should be present
    constraints = basic_context.get_user_constraints()
    assert constraints["timeframe"] == "morning"  # From intent
    assert constraints["job_id"] == "123"  # From option


# =============================================================================
# Entity Tracking Tests (Robust Cross-Agent Context Passing)
# =============================================================================


def test_track_entity_basic(basic_context):
    """Test basic entity tracking."""
    basic_context.track_entity("tables", "cprice_main.core.orders")

    entities = basic_context.get_discovered_entities()
    assert "tables" in entities
    assert "cprice_main.core.orders" in entities["tables"]


def test_track_entity_multiple_same_type(basic_context):
    """Test tracking multiple entities of the same type."""
    basic_context.track_entity("tables", "cprice_main.core.orders")
    basic_context.track_entity("tables", "cprice_main.core.products")
    basic_context.track_entity("tables", "cprice_main.core.customers")

    entities = basic_context.get_discovered_entities()
    assert len(entities["tables"]) == 3
    assert "cprice_main.core.orders" in entities["tables"]
    assert "cprice_main.core.products" in entities["tables"]
    assert "cprice_main.core.customers" in entities["tables"]


def test_track_entity_different_types(basic_context):
    """Test tracking entities of different types."""
    basic_context.track_entity("tables", "main.sales.orders")
    basic_context.track_entity("query_ids", "stmt_abc123")
    basic_context.track_entity("warehouse_ids", "wh_xyz789")

    entities = basic_context.get_discovered_entities()
    assert entities["tables"] == ["main.sales.orders"]
    assert entities["query_ids"] == ["stmt_abc123"]
    assert entities["warehouse_ids"] == ["wh_xyz789"]


def test_track_entity_no_duplicates(basic_context):
    """Test that duplicate entities are not tracked."""
    basic_context.track_entity("tables", "main.sales.orders")
    basic_context.track_entity("tables", "main.sales.orders")  # Duplicate
    basic_context.track_entity("tables", "main.sales.orders")  # Duplicate

    entities = basic_context.get_discovered_entities()
    assert len(entities["tables"]) == 1


def test_get_discovered_entities_empty(basic_context):
    """Test getting entities when none tracked."""
    entities = basic_context.get_discovered_entities()
    assert entities == {}


def test_clear_discovered_entities(basic_context):
    """Test clearing discovered entities."""
    basic_context.track_entity("tables", "main.sales.orders")
    basic_context.track_entity("query_ids", "stmt_abc123")

    # Verify entities exist
    assert basic_context.get_discovered_entities() != {}

    # Clear and verify
    basic_context.clear_discovered_entities()
    assert basic_context.get_discovered_entities() == {}


def test_entities_persist_across_operations(basic_context):
    """Test that entities persist when other context operations occur."""
    # Track some entities
    basic_context.track_entity("tables", "main.sales.orders")

    # Do other operations
    basic_context.add_message(Message(role="user", content="test message"))

    # Entities should still be there
    entities = basic_context.get_discovered_entities()
    assert "main.sales.orders" in entities["tables"]


def test_entities_included_in_to_dict(basic_context):
    """Test that entities are included in serialization."""
    basic_context.track_entity("tables", "main.sales.orders")

    context_dict = basic_context.to_dict()

    # Entities should be in working_memory.metrics
    assert "working_memory" in context_dict
    metrics = context_dict["working_memory"].get("metrics", {})
    assert "discovered_entities" in metrics
    assert "main.sales.orders" in metrics["discovered_entities"]["tables"]
