"""
Integration tests for SSE streaming endpoints.

Tests SSE formatting, event streaming, heartbeats, and client disconnection.
"""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, Request
from starboard_server.api.models import ChatEvent, EventType
from starboard_server.api.streaming import (
    event_stream,
    format_sse_event,
    format_sse_heartbeat,
    format_sse_retry,
    stream_conversation_events,
)


class TestFormatSSEEvent:
    """Tests for SSE event formatting."""

    def test_format_sse_event_with_enum_type(self):
        """Test formatting event with EventType enum."""
        event = ChatEvent(
            event_id="evt_123",
            type=EventType.MESSAGE_DELTA,
            data={"content": "Hello", "delta": "H"},
            timestamp=datetime.now(UTC),
        )

        result = format_sse_event(event)

        assert result.startswith("event: message.delta")
        assert "\ndata: " in result
        assert result.endswith("\n\n")
        assert "evt_123" in result
        assert "Hello" in result

    def test_format_sse_event_with_error_type(self):
        """Test formatting event with ERROR type."""
        event = ChatEvent(
            event_id="evt_456",
            type=EventType.ERROR,
            data={"error": "Something went wrong"},
            timestamp=datetime.now(UTC),
        )

        result = format_sse_event(event)

        assert "event: error" in result
        assert "data: " in result
        assert result.endswith("\n\n")
        assert "Something went wrong" in result

    def test_format_sse_event_with_complex_data(self):
        """Test formatting event with nested data."""
        event = ChatEvent(
            event_id="evt_789",
            type=EventType.TOOL_CALL_START,
            data={
                "tool": "query_runner",
                "args": {"sql": "SELECT * FROM table", "params": [1, 2, 3]},
                "metadata": {"cost": 0.001, "latency_ms": 123},
            },
            timestamp=datetime.now(UTC),
        )

        result = format_sse_event(event)

        # Verify structure
        lines = result.split("\n")
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        assert lines[2] == ""

        # Verify data is valid JSON
        data_line = lines[1][6:]  # Remove "data: " prefix
        data = json.loads(data_line)
        assert data["event_id"] == "evt_789"
        assert data["data"]["tool"] == "query_runner"
        assert data["data"]["args"]["params"] == [1, 2, 3]


class TestFormatSSEHeartbeat:
    """Tests for SSE heartbeat formatting."""

    def test_format_sse_heartbeat(self):
        """Test heartbeat format."""
        result = format_sse_heartbeat()

        assert result == ": heartbeat\n\n"
        assert result.startswith(": ")
        assert result.endswith("\n\n")


class TestFormatSSERetry:
    """Tests for SSE retry formatting."""

    def test_format_sse_retry_default(self):
        """Test retry format with default interval."""
        result = format_sse_retry(3000)

        assert result == "retry: 3000\n\n"

    def test_format_sse_retry_custom(self):
        """Test retry format with custom interval."""
        result = format_sse_retry(5000)

        assert result == "retry: 5000\n\n"

    def test_format_sse_retry_zero(self):
        """Test retry format with zero interval."""
        result = format_sse_retry(0)

        assert result == "retry: 0\n\n"


class TestEventStream:
    """Tests for event_stream async generator."""

    @pytest.fixture
    def mock_request(self):
        """Mock FastAPI Request."""
        request = AsyncMock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.is_disconnected = AsyncMock(return_value=False)
        return request

    @pytest.fixture
    def mock_manager(self):
        """Mock MultiAgentConversationManager."""
        manager = AsyncMock()
        manager.__class__.__name__ = "MultiAgentConversationManager"

        # Create a mock queue
        mock_queue = AsyncMock()
        manager.subscribe = AsyncMock(return_value=mock_queue)
        manager.unsubscribe = AsyncMock()

        return manager

    @pytest.mark.asyncio
    async def test_event_stream_sends_retry_first(self, mock_request, mock_manager):
        """Test that stream sends retry instruction first."""
        # Setup queue to raise TimeoutError immediately (no events)
        mock_queue = AsyncMock()
        mock_queue.get = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_manager.subscribe.return_value = mock_queue

        # Make request disconnect after first heartbeat
        disconnect_count = 0

        async def is_disconnected():
            nonlocal disconnect_count
            disconnect_count += 1
            return disconnect_count > 2  # Disconnect after a couple checks

        mock_request.is_disconnected = is_disconnected

        # Collect streamed messages
        messages = []
        async for msg in event_stream("conv_123", mock_request, mock_manager):
            messages.append(msg)
            if len(messages) >= 2:  # Get retry + maybe heartbeat
                break

        # First message should be retry instruction
        assert len(messages) > 0
        assert messages[0].startswith("retry: ")
        assert "3000" in messages[0]

    @pytest.mark.asyncio
    async def test_event_stream_sends_events(self, mock_request, mock_manager):
        """Test that stream sends events from queue."""
        # Setup queue with events
        event1 = ChatEvent(
            event_id="evt_1",
            type=EventType.MESSAGE_DELTA,
            data={"content": "Hello"},
            timestamp=datetime.now(UTC),
        )
        event2 = ChatEvent(
            event_id="evt_2",
            type=EventType.MESSAGE_END,
            data={"content": "Hello World"},
            timestamp=datetime.now(UTC),
        )

        mock_queue = AsyncMock()
        events_to_send = [event1, event2]

        async def get_event():
            if events_to_send:
                return events_to_send.pop(0)
            # After events exhausted, disconnect client
            mock_request.is_disconnected = AsyncMock(return_value=True)
            raise TimeoutError

        mock_queue.get = get_event
        mock_manager.subscribe.return_value = mock_queue

        # Collect all messages
        messages = []
        async for msg in event_stream("conv_123", mock_request, mock_manager):
            messages.append(msg)

        # Should have: retry + event1 + event2
        assert len(messages) >= 3
        assert "retry:" in messages[0]
        assert "event: message.delta" in messages[1]
        assert "event: message.end" in messages[2]

    @pytest.mark.asyncio
    async def test_event_stream_sends_heartbeat(self, mock_request, mock_manager):
        """Test that stream sends heartbeats when no events."""
        # Setup queue with no events (always timeout)
        mock_queue = AsyncMock()
        mock_queue.get = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_manager.subscribe.return_value = mock_queue

        # Track time to trigger heartbeat
        call_count = 0

        async def is_disconnected():
            nonlocal call_count
            call_count += 1
            return call_count > 20  # Let it run for a bit

        mock_request.is_disconnected = is_disconnected

        # Collect messages
        messages = []
        with patch("asyncio.get_event_loop") as mock_loop:
            # Mock time progression to trigger heartbeat
            time_values = [0.0, 1.0, 2.0, 16.0, 17.0, 18.0]  # Jump to 16s
            mock_loop().time = Mock(side_effect=time_values + [100.0] * 100)

            async for msg in event_stream("conv_123", mock_request, mock_manager):
                messages.append(msg)
                if len(messages) >= 3:  # retry + heartbeat(s)
                    break

        # Should have retry + at least one heartbeat
        assert len(messages) >= 2
        assert messages[0].startswith("retry:")
        # One of the messages should be a heartbeat
        heartbeats = [m for m in messages if m == ": heartbeat\n\n"]
        assert len(heartbeats) > 0

    @pytest.mark.asyncio
    async def test_event_stream_detects_disconnection(self, mock_request, mock_manager):
        """Test that stream detects client disconnection."""
        # Setup
        mock_queue = AsyncMock()
        mock_queue.get = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_manager.subscribe.return_value = mock_queue

        # Client disconnects immediately
        mock_request.is_disconnected = AsyncMock(side_effect=[False, True])

        # Run stream
        messages = []
        async for msg in event_stream("conv_123", mock_request, mock_manager):
            messages.append(msg)

        # Should unsubscribe after disconnect
        mock_manager.unsubscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_stream_handles_subscription_error(
        self, mock_request, mock_manager
    ):
        """Test that stream handles subscription errors."""
        # Setup manager to fail subscription
        mock_manager.subscribe.side_effect = ValueError("Conversation not found")

        # Should raise ValueError
        with pytest.raises(ValueError, match="Conversation not found"):
            async for _ in event_stream("nonexistent", mock_request, mock_manager):
                pass

    @pytest.mark.asyncio
    async def test_event_stream_sends_error_event_on_exception(
        self, mock_request, mock_manager
    ):
        """Test that stream sends error event on unexpected exception."""
        # Setup queue that raises an error
        mock_queue = AsyncMock()
        mock_queue.get = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        mock_manager.subscribe.return_value = mock_queue

        # Run stream
        messages = []
        async for msg in event_stream("conv_123", mock_request, mock_manager):
            messages.append(msg)

        # Should have retry + error event
        assert len(messages) >= 2
        assert "retry:" in messages[0]
        # Last message should be error event
        assert "event: error" in messages[-1]
        assert "Unexpected error" in messages[-1]

        # Should still unsubscribe
        mock_manager.unsubscribe.assert_called_once()


class TestStreamConversationEvents:
    """Tests for stream_conversation_events endpoint."""

    @pytest.fixture
    def mock_request(self):
        """Mock FastAPI Request."""
        request = AsyncMock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.is_disconnected = AsyncMock(return_value=False)
        return request

    @pytest.fixture
    def mock_manager(self):
        """Mock MultiAgentConversationManager."""
        manager = AsyncMock()
        manager.__class__.__name__ = "MultiAgentConversationManager"

        # Mock state_manager
        manager.state_manager = AsyncMock()
        manager.state_manager.load_context = AsyncMock(
            return_value={"conversation_id": "conv_123"}
        )

        # Mock subscribe/unsubscribe
        mock_queue = AsyncMock()
        mock_queue.get = AsyncMock(side_effect=asyncio.TimeoutError)
        manager.subscribe = AsyncMock(return_value=mock_queue)
        manager.unsubscribe = AsyncMock()

        return manager

    @pytest.mark.asyncio
    async def test_stream_conversation_events_success(self, mock_request, mock_manager):
        """Test successful streaming response creation."""
        response = await stream_conversation_events(
            conversation_id="conv_123",
            request=mock_request,
            manager=mock_manager,
        )

        # Verify response type and headers
        assert response.media_type == "text/event-stream"
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["X-Accel-Buffering"] == "no"
        assert response.headers["Connection"] == "keep-alive"

        # Verify context was loaded
        mock_manager.state_manager.load_context.assert_called_once_with("conv_123")

    @pytest.mark.asyncio
    async def test_stream_conversation_events_not_found(
        self, mock_request, mock_manager
    ):
        """Test streaming for non-existent conversation."""
        # Make state_manager return None (conversation not found)
        mock_manager.state_manager.load_context.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await stream_conversation_events(
                conversation_id="nonexistent",
                request=mock_request,
                manager=mock_manager,
            )

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_stream_conversation_events_load_error(
        self, mock_request, mock_manager
    ):
        """Test streaming when context load fails."""
        # Make state_manager raise ValueError
        mock_manager.state_manager.load_context.side_effect = ValueError("Load failed")

        with pytest.raises(HTTPException) as exc_info:
            await stream_conversation_events(
                conversation_id="conv_123",
                request=mock_request,
                manager=mock_manager,
            )

        assert exc_info.value.status_code == 404


class TestStreamingIntegration:
    """Integration tests for complete streaming workflows."""

    @pytest.mark.asyncio
    async def test_complete_streaming_workflow(self):
        """Test complete workflow: subscribe → send events → disconnect → cleanup."""
        # Setup
        mock_request = AsyncMock(spec=Request)
        mock_request.client = Mock()
        mock_request.client.host = "127.0.0.1"

        mock_manager = AsyncMock()
        mock_manager.__class__.__name__ = "TestManager"

        # Create events to send
        events = [
            ChatEvent(
                event_id="evt_1",
                type=EventType.MESSAGE_START,
                data={"message_id": "msg_1"},
                timestamp=datetime.now(UTC),
            ),
            ChatEvent(
                event_id="evt_2",
                type=EventType.MESSAGE_DELTA,
                data={"delta": "Hello"},
                timestamp=datetime.now(UTC),
            ),
            ChatEvent(
                event_id="evt_3",
                type=EventType.MESSAGE_END,
                data={"content": "Hello World"},
                timestamp=datetime.now(UTC),
            ),
        ]

        # Setup queue
        mock_queue = AsyncMock()
        events_copy = events.copy()

        async def get_event():
            if events_copy:
                await asyncio.sleep(0.001)  # Simulate async
                return events_copy.pop(0)
            # After all events, disconnect
            mock_request.is_disconnected = AsyncMock(return_value=True)
            raise TimeoutError

        mock_queue.get = get_event
        mock_manager.subscribe.return_value = mock_queue
        mock_manager.unsubscribe = AsyncMock()

        # Initially not disconnected
        mock_request.is_disconnected = AsyncMock(return_value=False)

        # Run stream
        messages = []
        async for msg in event_stream("conv_123", mock_request, mock_manager):
            messages.append(msg)

        # Verify workflow
        assert len(messages) >= 4  # retry + 3 events
        assert "retry:" in messages[0]
        assert "event: message.start" in messages[1]
        assert "event: message.delta" in messages[2]
        assert "event: message.end" in messages[3]

        # Verify cleanup
        mock_manager.unsubscribe.assert_called_once_with("conv_123", mock_queue)
