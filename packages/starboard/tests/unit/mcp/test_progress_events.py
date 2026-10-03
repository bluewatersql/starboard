# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for progress event serialization in MCPAgentExecutor."""

from starboard.infra.observability.events import (
    EventEmitter,
    EventType,
    StatusEvent,
)
from starboard.mcp.agent_bridge import MCPAgentExecutor, MCPProgressBridge


class TestSerializeProgressEvents:
    """Tests for _serialize_progress_events static method."""

    def _make_event(
        self,
        event_type: EventType = EventType.INFO,
        source: str = "test",
        message: str = "test message",
    ) -> StatusEvent:
        return StatusEvent(type=event_type, source=source, message=message)

    def test_returns_none_when_no_events(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter)
        result = MCPAgentExecutor._serialize_progress_events(bridge)
        assert result is None

    def test_serializes_single_event(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter)
        bridge.subscribe()
        emitter.emit(self._make_event(message="Step 1 complete"))
        bridge.unsubscribe()

        result = MCPAgentExecutor._serialize_progress_events(bridge)
        assert result is not None
        assert len(result) == 1
        assert result[0]["message"] == "Step 1 complete"
        assert result[0]["source"] == "test"
        assert result[0]["type"] == "info"

    def test_serializes_multiple_events(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter)
        bridge.subscribe()
        emitter.emit(self._make_event(message="Step 1"))
        emitter.emit(self._make_event(message="Step 2"))
        emitter.emit(self._make_event(message="Step 3"))
        bridge.unsubscribe()

        result = MCPAgentExecutor._serialize_progress_events(bridge)
        assert result is not None
        assert len(result) == 3
        messages = [e["message"] for e in result]
        assert messages == ["Step 1", "Step 2", "Step 3"]

    def test_includes_event_type(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter, include_trace=True)
        bridge.subscribe()
        emitter.emit(self._make_event(event_type=EventType.INFO, message="info"))
        emitter.emit(self._make_event(event_type=EventType.TRACE, message="trace"))
        bridge.unsubscribe()

        result = MCPAgentExecutor._serialize_progress_events(bridge)
        assert result is not None
        assert len(result) == 2
        assert result[0]["type"] == "info"
        assert result[1]["type"] == "trace"

    def test_includes_source(self) -> None:
        emitter = EventEmitter()
        bridge = MCPProgressBridge(emitter)
        bridge.subscribe()
        emitter.emit(self._make_event(source="task:analyze_query"))
        bridge.unsubscribe()

        result = MCPAgentExecutor._serialize_progress_events(bridge)
        assert result is not None
        assert result[0]["source"] == "task:analyze_query"


class TestProgressEventsInResponse:
    """Tests that progress_events field appears in MCPAgentResponse."""

    def test_response_model_accepts_progress_events(self) -> None:
        from starboard.mcp.models import MCPAgentResponse

        response = MCPAgentResponse(
            status="success",
            workspace_id_used="ws-1",
            agent_domain="query",
            response_text="Done",
            progress_events=[
                {"type": "info", "source": "test", "message": "Step 1"},
            ],
        )
        assert response.progress_events is not None
        assert len(response.progress_events) == 1

    def test_response_model_defaults_to_none(self) -> None:
        from starboard.mcp.models import MCPAgentResponse

        response = MCPAgentResponse(
            status="success",
            workspace_id_used="ws-1",
            agent_domain="query",
            response_text="Done",
        )
        assert response.progress_events is None
