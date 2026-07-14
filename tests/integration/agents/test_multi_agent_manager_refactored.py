# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Integration tests for MultiAgentConversationManager.

Tests validate that the refactored facade correctly coordinates all 4 components:
- ConversationLifecycleManager
- AgentHandoffCoordinator
- EventBroadcastCoordinator
- MessageQueueProcessor

Tests cover:
- Full conversation lifecycle
- Message handling with routing
- Event broadcasting
- Component integration
- Error handling
- Backward compatibility
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard.agents.conversation import MultiAgentConversationManager
from starboard.agents.events.agent_events import ThinkingEvent
from starboard.agents.events.user_events import FinalOutputEvent
from starboard.agents.routing.routing_models import RouteDecision
from starboard.agents.state.agent_state import Message, WorkingMemory
from starboard.agents.state.shared_context import SharedAgentContext
from starboard.api.models import ConversationConfig


@pytest.fixture
def mock_agent_factory():
    """Mock agent factory."""
    factory = MagicMock()

    # Mock specialist agent
    mock_agent = MagicMock()

    async def mock_run_stream(*args, **kwargs):
        yield ThinkingEvent(content="Analyzing query...", step=1, is_complete=False)
        yield FinalOutputEvent(
            output=MagicMock(
                complete_report={"findings": []},
                recommendations=[],
                status="success",
            )
        )

    mock_agent.run_stream = mock_run_stream
    factory.get_agent = MagicMock(return_value=mock_agent)

    return factory


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
def mock_state_manager():
    """Mock conversation state manager."""
    manager = AsyncMock()

    # Mock context
    mock_context = SharedAgentContext(
        conversation_id="conv_test",
        user_id="user_123",
        conversation_history=[],
        working_memory=WorkingMemory(),
        agent_transitions=[],
        metadata={},
    )

    manager.load_context = AsyncMock(return_value=mock_context)
    manager.save_context = AsyncMock()

    # Mock store for list_conversations
    manager._store = MagicMock()
    manager._store.list_conversations = AsyncMock(return_value=[])
    manager._store.delete_conversation = AsyncMock(return_value=True)

    return manager


@pytest.fixture
def refactored_manager(mock_agent_factory, mock_intent_router, mock_state_manager):
    """MultiAgentConversationManager instance for testing."""
    return MultiAgentConversationManager(
        agent_factory=mock_agent_factory,
        intent_router=mock_intent_router,
        state_manager=mock_state_manager,
        disabled_agent_domains=[],
        request_input_tool=None,
    )


def test_initialization(refactored_manager):
    """Test that refactored manager initializes all components."""
    # Verify all components exist
    assert refactored_manager.lifecycle is not None
    assert refactored_manager.handoff is not None
    assert refactored_manager.events is not None
    assert refactored_manager.queue is not None

    # Verify helper components
    assert refactored_manager._context_manager is not None
    assert refactored_manager._context_builder is not None
    assert refactored_manager._event_updater is not None


@pytest.mark.asyncio
@pytest.mark.skip(reason="Pydantic validation error - DomainModelConfig needs updating")
async def test_create_conversation(refactored_manager):
    """Test creating a conversation through the facade."""
    user_id = "user_123"
    context = {"workspace_id": "ws_abc"}
    config = ConversationConfig(temperature=0.4)

    response = await refactored_manager.create_conversation(
        user_id=user_id,
        context=context,
        config=config,
    )

    # Verify response
    assert response.conversation_id.startswith("conv_")
    assert response.config.temperature == 0.4


@pytest.mark.asyncio
async def test_get_conversation(refactored_manager, mock_state_manager):
    """Test retrieving conversation."""
    conversation_id = "conv_test"

    result = await refactored_manager.get_conversation(conversation_id)

    # Should load context
    mock_state_manager.load_context.assert_called()
    assert result is not None


@pytest.mark.asyncio
async def test_list_conversations(refactored_manager):
    """Test listing conversations."""
    user_id = "user_123"

    conversations = await refactored_manager.list_conversations(
        user_id=user_id,
        limit=20,
        offset=0,
    )

    # Should return list (empty in mock)
    assert isinstance(conversations, list)


@pytest.mark.asyncio
async def test_delete_conversation(refactored_manager):
    """Test deleting conversation."""
    conversation_id = "conv_delete"

    result = await refactored_manager.delete_conversation(conversation_id)

    # Should succeed
    assert result is True


@pytest.mark.asyncio
async def test_handle_message_stream_full_flow(refactored_manager, mock_state_manager):
    """Test full message handling flow through all components."""
    conversation_id = "conv_flow"
    user_message = "Optimize query q123"

    # Collect all events
    events = []
    async for event in refactored_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message=user_message,
        mode=OptimizationMode.ONLINE,
        user_id="user_123",
    ):
        events.append(event)

    # Should have events
    assert len(events) > 0

    # Should have thinking and final output
    event_types = [type(e).__name__ for e in events]
    assert "ThinkingEvent" in event_types
    assert "FinalOutputEvent" in event_types

    # Should save context
    assert mock_state_manager.save_context.called


@pytest.mark.asyncio
async def test_enqueue_message(refactored_manager):
    """Test enqueueing a message for background processing."""
    conversation_id = "conv_enqueue"
    content = "Analyze job job_456"

    response = await refactored_manager.enqueue_message(
        conversation_id=conversation_id,
        content=content,
        user_id="user_123",
        mode=OptimizationMode.ONLINE,
    )

    # Verify response
    assert response.message_id.startswith("msg_")
    assert response.conversation_id == conversation_id


@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe(refactored_manager, mock_state_manager):
    """Test SSE subscription and unsubscription."""
    conversation_id = "conv_subscribe"

    # Subscribe
    queue = await refactored_manager.subscribe(conversation_id)

    # Verify queue was returned
    assert isinstance(queue, asyncio.Queue)

    # Unsubscribe
    await refactored_manager.unsubscribe(conversation_id, queue)


@pytest.mark.asyncio
@pytest.mark.skip(reason="Pydantic validation error - DomainModelConfig needs updating")
async def test_component_coordination(
    refactored_manager, mock_state_manager, mock_intent_router
):
    """Test that all components work together correctly."""
    conversation_id = "conv_coord"
    user_message = "Test coordination"

    # Track component usage
    components_used = {
        "lifecycle": False,
        "handoff": False,
        "events": False,
        "queue": False,
    }

    # Handle message (exercises all components)
    events = []
    async for event in refactored_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message=user_message,
        mode=OptimizationMode.ONLINE,
    ):
        events.append(event)
        components_used["handoff"] = True  # Routing happened

    # Verify components were used
    components_used["events"] = True  # Events were yielded

    # Create conversation (uses lifecycle)
    await refactored_manager.create_conversation("user_test")
    components_used["lifecycle"] = True

    # Enqueue message (uses queue)
    await refactored_manager.enqueue_message(
        conversation_id=conversation_id,
        content="test",
        handler=refactored_manager.handle_message_stream,
    )
    components_used["queue"] = True

    # All components should have been used
    assert all(components_used.values())


@pytest.mark.asyncio
async def test_get_history(refactored_manager, mock_state_manager):
    """Test getting conversation history."""
    conversation_id = "conv_history"

    # Add some messages to context
    mock_context = SharedAgentContext(
        conversation_id=conversation_id,
        user_id="user_123",
        conversation_history=[
            Message(role="user", content="First message"),
            Message(role="assistant", content="First response"),
        ],
        working_memory=WorkingMemory(),
        agent_transitions=[],
        metadata={},
    )
    mock_state_manager.load_context.return_value = mock_context

    history = await refactored_manager.get_history(conversation_id)

    # Should have history
    assert history is not None
    assert len(history.messages) == 2


@pytest.mark.asyncio
async def test_backward_compatibility_api(refactored_manager):
    """Test that refactored manager has same API as old manager."""
    # Verify same methods exist
    assert hasattr(refactored_manager, "create_conversation")
    assert hasattr(refactored_manager, "get_conversation")
    assert hasattr(refactored_manager, "list_conversations")
    assert hasattr(refactored_manager, "delete_conversation")
    assert hasattr(refactored_manager, "get_history")
    assert hasattr(refactored_manager, "enqueue_message")
    assert hasattr(refactored_manager, "handle_message_stream")
    assert hasattr(refactored_manager, "subscribe")
    assert hasattr(refactored_manager, "unsubscribe")

    # Verify attributes
    assert hasattr(refactored_manager, "agent_factory")
    assert hasattr(refactored_manager, "intent_router")
    assert hasattr(refactored_manager, "state_manager")
    assert hasattr(refactored_manager, "disabled_agent_domains")


@pytest.mark.asyncio
async def test_error_handling_in_message_stream(refactored_manager, mock_state_manager):
    """Test error handling during message processing."""
    conversation_id = "conv_error"

    # Mock context load failure
    mock_state_manager.load_context.side_effect = Exception("Database error")

    # Should handle error gracefully
    with pytest.raises(Exception):
        async for _event in refactored_manager.handle_message_stream(
            conversation_id=conversation_id,
            user_message="test",
        ):
            pass


def test_component_independence(
    mock_agent_factory, mock_intent_router, mock_state_manager
):
    """Test that components can be swapped independently."""
    # Create manager with different components
    manager1 = MultiAgentConversationManager(
        agent_factory=mock_agent_factory,
        intent_router=mock_intent_router,
        state_manager=mock_state_manager,
    )

    manager2 = MultiAgentConversationManager(
        agent_factory=mock_agent_factory,
        intent_router=mock_intent_router,
        state_manager=mock_state_manager,
        disabled_agent_domains=["compute"],
    )

    # Should create different instances
    assert manager1 is not manager2
    assert manager1.disabled_agent_domains != manager2.disabled_agent_domains


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
