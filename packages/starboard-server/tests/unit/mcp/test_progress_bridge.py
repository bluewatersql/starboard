# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for MCPProgressBridge."""

from starboard_server.infra.observability.events import (
    EventEmitter,
    EventType,
    StatusEvent,
)
from starboard_server.mcp.agent_bridge import MCPProgressBridge


class TestMCPProgressBridge:
    """Tests for MCPProgressBridge event forwarding."""

    def test_subscribe_collects_info_events(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter)
        bridge.subscribe()

        event = StatusEvent(type=EventType.INFO, source="test", message="hello")
        emitter.emit(event)

        assert len(bridge.events) == 1
        assert bridge.events[0].message == "hello"

    def test_ignores_trace_events_by_default(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter)
        bridge.subscribe()

        emitter.emit(StatusEvent(type=EventType.TRACE, source="test", message="trace"))
        assert len(bridge.events) == 0

    def test_include_trace_collects_trace_events(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter, include_trace=True)
        bridge.subscribe()

        emitter.emit(StatusEvent(type=EventType.TRACE, source="test", message="trace"))
        assert len(bridge.events) == 1
        assert bridge.events[0].message == "trace"

    def test_unsubscribe_stops_collection(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter)
        bridge.subscribe()
        bridge.unsubscribe()

        emitter.emit(StatusEvent(type=EventType.INFO, source="test", message="after"))
        assert len(bridge.events) == 0

    def test_unsubscribe_idempotent(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter)
        bridge.subscribe()
        bridge.unsubscribe()
        bridge.unsubscribe()  # Should not raise

    def test_callback_invoked_on_info(self) -> None:
        emitter = EventEmitter()
        received: list[StatusEvent] = []
        bridge = MCPProgressBridge(emitter, callback=received.append)
        bridge.subscribe()

        event = StatusEvent(type=EventType.INFO, source="test", message="cb")
        emitter.emit(event)

        assert len(received) == 1
        assert received[0].message == "cb"

    def test_callback_error_does_not_crash(self) -> None:
        emitter = EventEmitter()

        def bad_callback(_: StatusEvent) -> None:
            raise ValueError("boom")

        bridge = MCPProgressBridge(emitter, callback=bad_callback)
        bridge.subscribe()

        # Should not raise
        emitter.emit(StatusEvent(type=EventType.INFO, source="test", message="ok"))
        # Event is still collected despite callback failure
        assert len(bridge.events) == 1

    def test_events_returns_copy(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter)
        bridge.subscribe()

        emitter.emit(StatusEvent(type=EventType.INFO, source="test", message="a"))
        events = bridge.events
        emitter.emit(StatusEvent(type=EventType.INFO, source="test", message="b"))

        # The returned list should be a snapshot (copy)
        assert len(events) == 1
        assert len(bridge.events) == 2
