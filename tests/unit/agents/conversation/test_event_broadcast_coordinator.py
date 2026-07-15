# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for EventBroadcastCoordinator.

Tests cover:
- Subscribing with validation
- Unsubscribing clients
- Broadcasting events
- Clearing conversations
- Getting subscriber counts
- Error handling
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard.agents.conversation.event_broadcast_coordinator import (
    EventBroadcastCoordinator,
)
from starboard.domain.conversation.api_types import ChatEvent, EventType


@pytest.fixture
def mock_state_manager():
    """Mock conversation state manager."""
    manager = AsyncMock()
    manager.load_context = AsyncMock()
    return manager


@pytest.fixture
def event_coordinator(mock_state_manager):
    """EventBroadcastCoordinator instance for testing."""
    return EventBroadcastCoordinator(
        state_manager=mock_state_manager,
        queue_maxsize=100,
        broadcast_timeout=1.0,
    )


@pytest.mark.asyncio
async def test_subscribe_success(event_coordinator, mock_state_manager):
    """Test subscribing to a conversation."""
    conversation_id = "conv_123"

    # Mock conversation exists
    mock_context = MagicMock()
    mock_state_manager.load_context.return_value = mock_context

    queue = await event_coordinator.subscribe(conversation_id)

    # Verify queue was returned
    assert isinstance(queue, asyncio.Queue)

    # Verify context was loaded
    mock_state_manager.load_context.assert_called_once_with(conversation_id)


@pytest.mark.asyncio
async def test_subscribe_conversation_not_found(event_coordinator, mock_state_manager):
    """Test subscribing to non-existent conversation raises error."""
    conversation_id = "conv_nonexistent"

    # Mock conversation doesn't exist
    mock_state_manager.load_context.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await event_coordinator.subscribe(conversation_id)


@pytest.mark.asyncio
async def test_unsubscribe(event_coordinator, mock_state_manager):
    """Test unsubscribing from a conversation."""
    conversation_id = "conv_123"

    # Mock conversation exists
    mock_context = MagicMock()
    mock_state_manager.load_context.return_value = mock_context

    # Subscribe first
    queue = await event_coordinator.subscribe(conversation_id)

    # Unsubscribe
    await event_coordinator.unsubscribe(conversation_id, queue)

    # Subscriber count should be 0
    assert event_coordinator.get_subscriber_count(conversation_id) == 0


@pytest.mark.asyncio
async def test_broadcast_event(event_coordinator, mock_state_manager):
    """Test broadcasting an event to subscribers."""
    conversation_id = "conv_123"

    # Mock conversation exists
    mock_context = MagicMock()
    mock_state_manager.load_context.return_value = mock_context

    # Subscribe
    queue = await event_coordinator.subscribe(conversation_id)

    # Create event
    event = ChatEvent(
        event_id="evt_123",
        type=EventType.MESSAGE_START,
        data={"content": "test"},
        timestamp=datetime.now(UTC),
    )

    # Broadcast
    await event_coordinator.broadcast(conversation_id, event)

    # Verify event was received
    received_event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received_event.event_id == "evt_123"
    assert received_event.type == EventType.MESSAGE_START


@pytest.mark.asyncio
async def test_broadcast_to_multiple_subscribers(event_coordinator, mock_state_manager):
    """Test broadcasting to multiple subscribers."""
    conversation_id = "conv_123"

    # Mock conversation exists
    mock_context = MagicMock()
    mock_state_manager.load_context.return_value = mock_context

    # Subscribe multiple clients
    queue1 = await event_coordinator.subscribe(conversation_id)
    queue2 = await event_coordinator.subscribe(conversation_id)

    # Verify subscriber count
    assert event_coordinator.get_subscriber_count(conversation_id) == 2

    # Create event
    event = ChatEvent(
        event_id="evt_456",
        type=EventType.THINKING,
        data={"content": "thinking..."},
        timestamp=datetime.now(UTC),
    )

    # Broadcast
    await event_coordinator.broadcast(conversation_id, event)

    # Both queues should receive the event
    event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    event2 = await asyncio.wait_for(queue2.get(), timeout=1.0)

    assert event1.event_id == "evt_456"
    assert event2.event_id == "evt_456"


def test_clear_conversation(event_coordinator):
    """Test clearing all subscribers for a conversation."""
    conversation_id = "conv_123"

    # Clear conversation
    event_coordinator.clear_conversation(conversation_id)

    # Subscriber count should be 0
    assert event_coordinator.get_subscriber_count(conversation_id) == 0


@pytest.mark.asyncio
async def test_clear_conversation_with_subscribers(
    event_coordinator, mock_state_manager
):
    """Test clearing conversation removes all subscribers."""
    conversation_id = "conv_123"

    # Mock conversation exists
    mock_context = MagicMock()
    mock_state_manager.load_context.return_value = mock_context

    # Subscribe
    await event_coordinator.subscribe(conversation_id)
    assert event_coordinator.get_subscriber_count(conversation_id) == 1

    # Clear
    event_coordinator.clear_conversation(conversation_id)

    # Subscriber count should be 0
    assert event_coordinator.get_subscriber_count(conversation_id) == 0


def test_get_subscriber_count_no_subscribers(event_coordinator):
    """Test getting subscriber count for conversation with no subscribers."""
    conversation_id = "conv_empty"

    count = event_coordinator.get_subscriber_count(conversation_id)

    assert count == 0


@pytest.mark.asyncio
async def test_get_subscriber_count_with_subscribers(
    event_coordinator, mock_state_manager
):
    """Test getting subscriber count with active subscribers."""
    conversation_id = "conv_123"

    # Mock conversation exists
    mock_context = MagicMock()
    mock_state_manager.load_context.return_value = mock_context

    # Subscribe multiple clients
    await event_coordinator.subscribe(conversation_id)
    await event_coordinator.subscribe(conversation_id)
    await event_coordinator.subscribe(conversation_id)

    count = event_coordinator.get_subscriber_count(conversation_id)

    assert count == 3


def test_initialization(mock_state_manager):
    """Test EventBroadcastCoordinator initialization."""
    coordinator = EventBroadcastCoordinator(
        state_manager=mock_state_manager,
        queue_maxsize=50,
        broadcast_timeout=2.0,
    )

    assert coordinator.state_manager == mock_state_manager
    assert coordinator._broadcaster is not None


@pytest.mark.asyncio
async def test_broadcast_no_subscribers(event_coordinator):
    """Test broadcasting when there are no subscribers (should not error)."""
    conversation_id = "conv_no_subs"

    event = ChatEvent(
        event_id="evt_789",
        type=EventType.MESSAGE_END,
        data={},
        timestamp=datetime.now(UTC),
    )

    # Should not raise error
    await event_coordinator.broadcast(conversation_id, event)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
