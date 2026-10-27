# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for MessageQueueProcessor.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from starboard.agents.conversation.message_queue_processor import (
    MessageQueueProcessor,
)
from starboard.domain.conversation.models import (
    EventType,
    MessageResponse,
    MessageStatus,
)


@pytest.fixture
def mock_event_coordinator():
    """Create mock EventBroadcastCoordinator."""
    coordinator = Mock()
    coordinator.broadcast = AsyncMock()
    return coordinator


@pytest.fixture
def processor(mock_event_coordinator):
    """Create MessageQueueProcessor with mocks."""
    return MessageQueueProcessor(event_coordinator=mock_event_coordinator)


@pytest.mark.asyncio
async def test_enqueue_starts_processing_task(processor, mock_event_coordinator):
    """Should start a background processing task."""

    # Mock handler
    async def mock_handler(conversation_id, user_message, user_id, metadata=None):
        yield Mock(type=EventType.MESSAGE_DELTA, content="test")

    # Enqueue message
    response = await processor.enqueue(
        conversation_id="conv_123",
        content="test message",
        handler=mock_handler,
    )

    assert isinstance(response, MessageResponse)
    assert response.status == MessageStatus.PENDING

    # Wait for task to complete
    assert processor.has_active_task("conv_123")

    # Allow background task to run
    await asyncio.sleep(0.05)

    # Should have broadcasted events
    assert mock_event_coordinator.broadcast.called
    assert not processor.has_active_task("conv_123")


@pytest.mark.asyncio
async def test_enqueue_cancels_existing_task(processor):
    """Should cancel existing task when enqueuing new message."""

    # Use events to coordinate task execution deterministically
    task1_started = asyncio.Event()
    task1_cancelled = False

    async def mock_handler_1(conversation_id, user_message, user_id, metadata=None):
        nonlocal task1_cancelled
        task1_started.set()
        try:
            # Use a loop with small sleep to be responsive to cancellation
            # while simulating long running task
            for _ in range(10):
                await asyncio.sleep(0.01)
            yield Mock(type=EventType.THINKING, content="...")
        except asyncio.CancelledError:
            task1_cancelled = True
            raise

    async def mock_handler_2(conversation_id, user_message, user_id, metadata=None):
        yield Mock(type=EventType.MESSAGE_DELTA, content="test2")

    # Start first task
    await processor.enqueue(
        conversation_id="conv_123",
        content="message 1",
        handler=mock_handler_1,
    )

    # Wait for it to start
    await asyncio.wait_for(task1_started.wait(), timeout=1.0)
    assert processor.has_active_task("conv_123")

    # Start second task (should cancel first)
    await processor.enqueue(
        conversation_id="conv_123",
        content="message 2",
        handler=mock_handler_2,
    )

    # Wait a bit for cancellation to propagate
    await asyncio.sleep(0.05)

    # First task should be cancelled
    assert task1_cancelled

    # Processor should still have an active task (the second one, or it might have finished)
    # But crucially, it shouldn't be empty if the second task is still running
    # Since mock_handler_2 finishes immediately, let's check the task identity instead

    # Verify that the task was replaced correctly, regardless of completion
    # We can't easily check internal state here without peeking, but the fact that
    # task1 was cancelled proves the logic ran.


# =============================================================================
# Tests for duplicate user input handling (grace period protection)
# =============================================================================


@pytest.fixture
def mock_request_input_tool():
    """Create mock RequestUserInputTool."""
    tool = Mock()
    tool.inject_response = Mock()
    return tool


@pytest.fixture
def processor_with_input_tool(mock_event_coordinator, mock_request_input_tool):
    """Create MessageQueueProcessor with request_input_tool."""
    return MessageQueueProcessor(
        event_coordinator=mock_event_coordinator,
        request_input_tool=mock_request_input_tool,
    )


@pytest.mark.asyncio
async def test_duplicate_user_input_does_not_cancel_task(
    processor_with_input_tool, mock_event_coordinator, mock_request_input_tool
):
    """
    Duplicate user input within grace period should not cancel the processing task.

    Scenario:
    1. Agent is running and requests user input
    2. User submits response (injected to waiting agent)
    3. User accidentally submits same response again (duplicate)
    4. Task should NOT be cancelled - grace period protection
    """
    processor = processor_with_input_tool
    conversation_id = "conv_duplicate"

    # Events for coordinating test
    task_started = asyncio.Event()
    task_received_input = asyncio.Event()
    task_cancelled = False
    task_completed = False

    async def mock_handler(conversation_id, user_message, user_id, metadata=None):
        nonlocal task_cancelled, task_completed
        task_started.set()
        try:
            # Simulate waiting for user input
            await task_received_input.wait()
            # Simulate processing the response
            for _ in range(5):
                await asyncio.sleep(0.01)
            yield Mock(type=EventType.MESSAGE_DELTA, content="processing response")
            task_completed = True
        except asyncio.CancelledError:
            task_cancelled = True
            raise

    # Start the task
    await processor.enqueue(
        conversation_id=conversation_id,
        content="Initial question",
        handler=mock_handler,
    )

    # Wait for task to start
    await asyncio.wait_for(task_started.wait(), timeout=1.0)

    # Simulate: user input was requested and response injected
    processor._pending_input_requests[conversation_id] = {
        "request_id": "req_123",
        "question": "Which cluster?",
    }

    # First submission - inject user response
    response1 = await processor.enqueue(
        conversation_id=conversation_id,
        content="cluster-123",
        handler=mock_handler,
    )
    assert response1.status == MessageStatus.PENDING

    # Check that injection timestamp was recorded
    assert conversation_id in processor._last_input_injection

    # Signal the task to continue processing
    task_received_input.set()

    # Second submission (duplicate) - should NOT cancel task
    response2 = await processor.enqueue(
        conversation_id=conversation_id,
        content="cluster-123",
        handler=mock_handler,
    )
    assert response2.status == MessageStatus.PENDING

    # Wait a bit for potential cancellation to happen
    await asyncio.sleep(0.1)

    # Task should NOT have been cancelled
    assert not task_cancelled, "Task was incorrectly cancelled by duplicate submission"


@pytest.mark.asyncio
async def test_different_message_still_cancels_task_after_grace_period(
    processor_with_input_tool, mock_event_coordinator, mock_request_input_tool
):
    """
    Different message content should still cancel active task after grace period.

    This ensures we don't break legitimate interruption functionality.
    """
    processor = processor_with_input_tool
    conversation_id = "conv_interrupt"

    task1_started = asyncio.Event()
    task1_cancelled = False

    async def mock_handler_1(conversation_id, user_message, user_id, metadata=None):
        nonlocal task1_cancelled
        task1_started.set()
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
            yield Mock(type=EventType.THINKING, content="...")
        except asyncio.CancelledError:
            task1_cancelled = True
            raise

    async def mock_handler_2(conversation_id, user_message, user_id, metadata=None):
        yield Mock(type=EventType.MESSAGE_DELTA, content="new task")

    # Start first task
    await processor.enqueue(
        conversation_id=conversation_id,
        content="message 1",
        handler=mock_handler_1,
    )

    await asyncio.wait_for(task1_started.wait(), timeout=1.0)

    # Set an old injection timestamp (outside grace period)
    old_time = datetime.now(UTC) - timedelta(seconds=60)
    processor._last_input_injection[conversation_id] = old_time

    # Send different message - should cancel the task
    await processor.enqueue(
        conversation_id=conversation_id,
        content="completely different message",
        handler=mock_handler_2,
    )

    # Wait for cancellation
    await asyncio.sleep(0.05)

    # Task should have been cancelled (grace period expired)
    assert task1_cancelled, "Task should be cancelled after grace period expires"


@pytest.mark.asyncio
async def test_grace_period_constant_is_configured():
    """Test that grace period constant is properly configured."""
    assert MessageQueueProcessor.INPUT_INJECTION_GRACE_PERIOD_SECONDS > 0
    assert MessageQueueProcessor.INPUT_INJECTION_GRACE_PERIOD_SECONDS == 30


@pytest.mark.asyncio
async def test_injection_timestamp_cleaned_up_on_task_complete(
    processor_with_input_tool, mock_event_coordinator
):
    """Test that injection timestamps are cleaned up when tasks complete."""
    processor = processor_with_input_tool
    conversation_id = "conv_cleanup"

    async def mock_handler(conversation_id, user_message, user_id, metadata=None):
        yield Mock(type=EventType.MESSAGE_DELTA, content="done")

    # Set an injection timestamp
    processor._last_input_injection[conversation_id] = datetime.now(UTC)

    # Start and complete a task
    await processor.enqueue(
        conversation_id=conversation_id,
        content="test",
        handler=mock_handler,
    )

    # Wait for task to complete
    await asyncio.sleep(0.1)

    # Injection timestamp should be cleaned up
    assert conversation_id not in processor._last_input_injection
