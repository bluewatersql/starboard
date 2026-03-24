"""
Unit tests for AgentHandoffCoordinator.

Tests cover:
- Intent classification and routing
- Clarification handling
- Specialist agent selection
- Transition recording
- Event generation
- Error handling and edge cases
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.agents.conversation import AgentHandoffCoordinator
from starboard_server.agents.routing.routing_models import (
    AgentTransition,
    RouteDecision,
)
from starboard_server.agents.state.agent_state import Message, WorkingMemory
from starboard_server.agents.state.shared_context import SharedAgentContext
from starboard_server.api.models import EventType


@pytest.fixture
def mock_intent_router():
    """Mock intent router."""
    router = AsyncMock()
    router.classify_intent = AsyncMock(
        return_value=RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={"query_id": "q123"},
            context={},
            clarification_needed=False,
            reasoning="High confidence query optimization request",
        )
    )
    return router


@pytest.fixture
def mock_agent_factory():
    """Mock agent factory."""
    factory = MagicMock()
    factory.get_agent = MagicMock(return_value=MagicMock())
    return factory


@pytest.fixture
def handoff_coordinator(mock_intent_router, mock_agent_factory):
    """AgentHandoffCoordinator instance for testing."""
    return AgentHandoffCoordinator(
        intent_router=mock_intent_router,
        agent_factory=mock_agent_factory,
        disabled_domains=[],
    )


@pytest.mark.asyncio
async def test_classify_and_route_normal(handoff_coordinator, mock_intent_router):
    """Test normal intent classification without clarification."""
    user_message = "Optimize query q123"
    conversation_history = [Message(role="user", content=user_message)]
    conversation_id = "conv_123"

    route_decision = await handoff_coordinator.classify_and_route(
        user_message=user_message,
        conversation_history=conversation_history,
        conversation_id=conversation_id,
    )

    # Verify result
    assert route_decision.domain == "query"
    assert route_decision.confidence == 0.9
    assert route_decision.should_route()

    # Verify intent router was called (attachments defaults to None)
    mock_intent_router.classify_intent.assert_called_once_with(
        user_message,
        conversation_history,
        attachments=None,
    )


@pytest.mark.asyncio
async def test_classify_and_route_with_clarification_response(handoff_coordinator):
    """Test routing when user responds to clarification."""
    conversation_id = "conv_456"

    # Mark clarification as pending
    handoff_coordinator._clarification_pending[conversation_id] = True

    user_message = "1"  # User selects first option
    conversation_history = []

    route_decision = await handoff_coordinator.classify_and_route(
        user_message=user_message,
        conversation_history=conversation_history,
        conversation_id=conversation_id,
    )

    # Should parse as "query" (first domain option)
    assert route_decision.domain == "query"
    assert route_decision.confidence == 0.95
    assert "selected 'query'" in route_decision.reasoning.lower()

    # Clarification pending should be cleared
    assert not handoff_coordinator._clarification_pending.get(conversation_id, False)


@pytest.mark.asyncio
async def test_parse_clarification_response_numeric(handoff_coordinator):
    """Test parsing numeric clarification response."""
    conversation_id = "conv_789"
    handoff_coordinator._clarification_pending[conversation_id] = True

    # Test numeric responses
    assert (
        handoff_coordinator._parse_clarification_response("1", conversation_id)
        == "query"
    )
    assert (
        handoff_coordinator._parse_clarification_response("2", conversation_id) == "job"
    )
    assert (
        handoff_coordinator._parse_clarification_response("3", conversation_id) == "uc"
    )


@pytest.mark.asyncio
async def test_parse_clarification_response_keyword(handoff_coordinator):
    """Test parsing keyword clarification response."""
    conversation_id = "conv_abc"
    handoff_coordinator._clarification_pending[conversation_id] = True

    # Test keyword responses
    assert (
        handoff_coordinator._parse_clarification_response("sql query", conversation_id)
        == "query"
    )
    assert (
        handoff_coordinator._parse_clarification_response(
            "databricks job", conversation_id
        )
        == "job"
    )
    assert (
        handoff_coordinator._parse_clarification_response(
            "troubleshoot", conversation_id
        )
        == "diagnostic"
    )


@pytest.mark.asyncio
async def test_parse_clarification_response_not_pending(handoff_coordinator):
    """Test that clarification parsing returns None when not pending."""
    conversation_id = "conv_xyz"
    # Don't mark as pending

    result = handoff_coordinator._parse_clarification_response("1", conversation_id)

    assert result is None


def test_should_request_clarification(handoff_coordinator):
    """Test checking if clarification should be requested."""
    # High confidence - no clarification needed
    route_decision = RouteDecision(
        domain="query",
        confidence=0.9,
        extracted_ids={},
        context={},
        clarification_needed=False,
        reasoning="High confidence",
    )
    assert not handoff_coordinator.should_request_clarification(route_decision)

    # Low confidence - clarification needed
    route_decision_low = RouteDecision(
        domain="query",
        confidence=0.3,
        extracted_ids={},
        context={},
        clarification_needed=True,
        reasoning="Low confidence",
    )
    assert handoff_coordinator.should_request_clarification(route_decision_low)


def test_generate_clarification_events(handoff_coordinator):
    """Test generating clarification events."""
    conversation_id = "conv_def"

    events = handoff_coordinator.generate_clarification_events(conversation_id)

    # Should generate events
    assert len(events) > 0

    # Clarification pending should be set
    assert handoff_coordinator._clarification_pending[conversation_id] is True


def test_generate_clarification_events_all_disabled():
    """Test generating clarification when all domains disabled."""
    coordinator = AgentHandoffCoordinator(
        intent_router=AsyncMock(),
        agent_factory=MagicMock(),
        disabled_domains=["query", "job", "uc", "cluster", "warehouse", "diagnostic"],
    )

    conversation_id = "conv_ghi"
    events = coordinator.generate_clarification_events(conversation_id)

    # Should return empty list
    assert events == []


def test_create_routing_event(handoff_coordinator):
    """Test creating routing decision event."""
    route_decision = RouteDecision(
        domain="query",
        confidence=0.9,
        extracted_ids={"query_id": "q123"},
        context={},
        clarification_needed=False,
        reasoning="High confidence query optimization",
    )

    event = handoff_coordinator.create_routing_event(route_decision)

    assert event.type == EventType.ROUTING_DECISION
    assert event.data["domain"] == "query"
    assert event.data["confidence"] == 0.9
    assert event.data["reasoning"] == "High confidence query optimization"
    assert event.data["clarification_needed"] is False


def test_create_friendly_name_event_routing(handoff_coordinator):
    """Test creating friendly name event when routing."""
    route_decision = RouteDecision(
        domain="query",
        confidence=0.9,
        extracted_ids={"query_id": "q123"},
        context={},
        clarification_needed=False,
        reasoning="Query optimization",
    )

    event = handoff_coordinator.create_friendly_name_event(route_decision)

    assert event is not None
    assert event.type == EventType.FRIENDLY_NAME_UPDATE
    assert "Query Optimization" in event.data["friendly_name"]


def test_create_friendly_name_event_no_routing(handoff_coordinator):
    """Test creating friendly name event when not routing (clarification needed)."""
    route_decision = RouteDecision(
        domain="query",
        confidence=0.3,
        extracted_ids={},
        context={},
        clarification_needed=True,
        reasoning="Low confidence",
    )

    event = handoff_coordinator.create_friendly_name_event(route_decision)

    assert event is None


def test_generate_friendly_name_query_domain(handoff_coordinator):
    """Test generating friendly name for query domain."""
    name = handoff_coordinator._generate_friendly_name(
        domain="query",
        extracted_ids={"query_id": "q123"},
    )

    assert name == "Query Optimization: q123"


def test_generate_friendly_name_job_domain(handoff_coordinator):
    """Test generating friendly name for job domain."""
    name = handoff_coordinator._generate_friendly_name(
        domain="job",
        extracted_ids={"job_id": "job_456"},
    )

    assert name == "Job Optimization: job_456"


def test_generate_friendly_name_no_ids(handoff_coordinator):
    """Test generating friendly name without extracted IDs."""
    name = handoff_coordinator._generate_friendly_name(
        domain="diagnostic",
        extracted_ids={},
    )

    assert name == "Diagnostics"


def test_get_specialist(handoff_coordinator, mock_agent_factory):
    """Test getting specialist agent."""
    domain = "query"
    conversation_config = {"temperature": 0.4}

    specialist = handoff_coordinator.get_specialist(
        domain=domain,
        conversation_config=conversation_config,
    )

    assert specialist is not None
    mock_agent_factory.get_agent.assert_called_once_with(
        domain,
        conversation_config=conversation_config,
    )


def test_record_transition(handoff_coordinator):
    """Test recording agent transition."""
    shared_context = SharedAgentContext(
        conversation_id="conv_123",
        user_id="user_123",
        conversation_history=[],
        working_memory=WorkingMemory(),
        agent_transitions=[],
        metadata={},
    )

    route_decision = RouteDecision(
        domain="query",
        confidence=0.9,
        extracted_ids={"query_id": "q123"},
        context={"some": "context"},
        clarification_needed=False,
        reasoning="Query optimization request",
    )

    transition = handoff_coordinator.record_transition(
        shared_context=shared_context,
        route_decision=route_decision,
        from_agent="router",
    )

    # Verify transition
    assert isinstance(transition, AgentTransition)
    assert transition.from_agent == "router"
    assert transition.to_agent == "query"
    assert transition.reason == "Query optimization request"
    assert transition.context_passed == {"some": "context"}

    # Verify added to context
    assert len(shared_context.agent_transitions) == 1
    assert shared_context.agent_transitions[0] == transition


def test_create_transition_event(handoff_coordinator):
    """Test creating agent transition event."""
    transition = AgentTransition(
        from_agent="router",
        to_agent="query",
        timestamp=datetime.now(UTC),
        reason="Query optimization",
        context_passed={"query_id": "q123"},
    )

    event = handoff_coordinator.create_transition_event(transition)

    assert event.type == EventType.AGENT_TRANSITION
    assert event.data["from_agent"] == "router"
    assert event.data["to_agent"] == "query"
    assert event.data["reason"] == "Query optimization"
    assert event.data["context_passed"] == {"query_id": "q123"}


def test_clear_clarification_pending(handoff_coordinator):
    """Test clearing clarification pending state."""
    conversation_id = "conv_test"

    # Set pending state
    handoff_coordinator._clarification_pending[conversation_id] = True
    assert conversation_id in handoff_coordinator._clarification_pending

    # Clear
    handoff_coordinator.clear_clarification_pending(conversation_id)
    assert conversation_id not in handoff_coordinator._clarification_pending


def test_clear_clarification_pending_not_set(handoff_coordinator):
    """Test clearing clarification pending when not set (should not error)."""
    conversation_id = "conv_nonexistent"

    # Should not raise error
    handoff_coordinator.clear_clarification_pending(conversation_id)


def test_initialization(mock_intent_router, mock_agent_factory):
    """Test AgentHandoffCoordinator initialization."""
    coordinator = AgentHandoffCoordinator(
        intent_router=mock_intent_router,
        agent_factory=mock_agent_factory,
        disabled_domains=["compute"],
    )

    assert coordinator.intent_router == mock_intent_router
    assert coordinator.agent_factory == mock_agent_factory
    assert coordinator.disabled_domains == ["compute"]
    assert coordinator._clarification_pending == {}


def test_initialization_no_disabled_domains(mock_intent_router, mock_agent_factory):
    """Test initialization without disabled domains."""
    coordinator = AgentHandoffCoordinator(
        intent_router=mock_intent_router,
        agent_factory=mock_agent_factory,
    )

    assert coordinator.disabled_domains == []


@pytest.mark.asyncio
async def test_classify_and_route_with_tuple_history(
    handoff_coordinator, mock_intent_router
):
    """Test classify_and_route accepts tuple conversation history."""
    user_message = "Analyze job job_456"
    conversation_history = (
        Message(role="user", content="Previous message"),
        Message(role="assistant", content="Previous response"),
    )
    conversation_id = "conv_tuple"

    route_decision = await handoff_coordinator.classify_and_route(
        user_message=user_message,
        conversation_history=conversation_history,
        conversation_id=conversation_id,
    )

    # Should work with tuple
    assert route_decision is not None
    mock_intent_router.classify_intent.assert_called_once()


def test_generate_friendly_name_multiple_ids(handoff_coordinator):
    """Test generating friendly name with multiple extracted IDs (uses first match)."""
    name = handoff_coordinator._generate_friendly_name(
        domain="query",
        extracted_ids={
            "query_id": "q123",
            "statement_id": "stmt_456",
        },
    )

    # Should use query_id (first in priority list)
    assert name == "Query Optimization: q123"


def test_generate_friendly_name_unknown_domain(handoff_coordinator):
    """Test generating friendly name for unknown domain."""
    name = handoff_coordinator._generate_friendly_name(
        domain="unknown",
        extracted_ids={},
    )

    assert name == "Conversation"


def test_generate_friendly_name_long_id_truncation(handoff_coordinator):
    """Test that long IDs (like UUIDs) are truncated properly."""
    long_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    name = handoff_coordinator._generate_friendly_name(
        domain="query",
        extracted_ids={"query_id": long_uuid},
    )

    # Long IDs should be truncated to first 8 and last 8 chars
    assert "a1b2c3d4" in name
    assert "34567890" in name  # Last 8 chars of the UUID
    assert "..." in name


def test_generate_friendly_name_from_user_message(handoff_coordinator):
    """Test generating friendly name from user message content."""
    name = handoff_coordinator._generate_friendly_name(
        domain="diagnostic",
        extracted_ids={},
        user_message="My Spark job is failing with OOM errors",
    )

    # Should use cleaned user message
    assert "Spark" in name or "job" in name or "OOM" in name


def test_generate_friendly_name_topic_extraction_expensive(handoff_coordinator):
    """Test topic extraction for 'expensive' queries."""
    name = handoff_coordinator._generate_friendly_name(
        domain="analytics",
        extracted_ids={},
        user_message="Show me the top 10 most expensive queries",
    )

    # Should extract the topic
    assert "expensive" in name.lower() or "queries" in name.lower()


def test_generate_friendly_name_topic_extraction_cost(handoff_coordinator):
    """Test topic extraction for cost queries."""
    name = handoff_coordinator._generate_friendly_name(
        domain="analytics",
        extracted_ids={},
        user_message="What is the cost of warehouses?",
    )

    # Should extract cost-related topic
    assert "cost" in name.lower() or "warehouses" in name.lower()


def test_generate_friendly_name_topic_extraction_spend(handoff_coordinator):
    """Test topic extraction for spend analysis queries."""
    name = handoff_coordinator._generate_friendly_name(
        domain="analytics",
        extracted_ids={},
        user_message="How much did we spend last month?",
    )

    # Should match spend pattern
    assert "spend" in name.lower() or "analysis" in name.lower()


def test_generate_friendly_name_option_prefix_stripping(handoff_coordinator):
    """Test that [Option N] prefixes are stripped from user messages."""
    name = handoff_coordinator._generate_friendly_name(
        domain="job",
        extracted_ids={},
        user_message="[Option 2] Optimize the slow job",
    )

    # Should not contain the option prefix
    assert "[Option" not in name
    assert "Optimize" in name or "slow" in name


def test_generate_friendly_name_id_in_message(handoff_coordinator):
    """Test extraction of ID from message like 'The job is 12345678901234'."""
    name = handoff_coordinator._generate_friendly_name(
        domain="job",
        extracted_ids={},
        user_message="The job is 12345678901234",
    )

    # Should extract the ID and use prefix format
    assert "Job Optimization" in name
    assert "12345678901234" in name


def test_generate_friendly_name_short_message_fallback(handoff_coordinator):
    """Test that very short messages fall back to domain prefix."""
    name = handoff_coordinator._generate_friendly_name(
        domain="query",
        extracted_ids={},
        user_message="Hi",
    )

    # Short message should fall back to prefix
    assert name == "Query Optimization"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
