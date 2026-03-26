"""Maps internal server events to stable SDK event types.

This module is internal to the SDK (prefixed with ``_``). It converts
server-side Pydantic event models into the SDK's frozen dataclasses so
that consumers are fully decoupled from ``starboard_server`` internals.
"""

from __future__ import annotations

from starboard_server.bootstrap import (
    ErrorEvent as _ServerErrorEvent,
    FinalOutputEvent as _ServerFinalOutputEvent,
    StreamingEvent as _ServerStreamingEvent,
    ToolEndEvent as _ServerToolEndEvent,
    ToolStartEvent as _ServerToolStartEvent,
)

from starboard_sdk.event_types import (
    AgentEvent,
    ErrorEvent,
    FinalOutputEvent,
    StreamingEvent,
    ToolEndEvent,
    ToolStartEvent,
)


def map_event(server_event: object) -> AgentEvent | None:
    """Convert a server event to an SDK event.

    Args:
        server_event: A server-side event object.

    Returns:
        The corresponding SDK event, or ``None`` for unmapped types.
    """
    if isinstance(server_event, _ServerToolStartEvent):
        return ToolStartEvent(
            tool_name=server_event.tool_name,
            friendly_name=server_event.friendly_name,
            tool_call_id=server_event.tool_call_id,
            arguments=dict(server_event.arguments),
        )
    if isinstance(server_event, _ServerToolEndEvent):
        return ToolEndEvent(
            tool_name=server_event.tool_name,
            friendly_name=server_event.friendly_name,
            tool_call_id=server_event.tool_call_id,
            success=server_event.success,
            duration_seconds=server_event.duration_seconds,
            error=getattr(server_event, "error", None),
        )
    if isinstance(server_event, _ServerErrorEvent):
        return ErrorEvent(
            error_type=server_event.error_type,
            error=server_event.error,
            is_recoverable=server_event.is_recoverable,
        )
    if isinstance(server_event, _ServerFinalOutputEvent):
        output = (
            server_event.output
            if isinstance(server_event.output, dict)
            else server_event.output.to_dict()
        )
        return FinalOutputEvent(output=output)
    if isinstance(server_event, _ServerStreamingEvent):
        return StreamingEvent(
            event_type=getattr(server_event, "event_type", "streaming"),
            content=getattr(server_event, "content", ""),
        )
    return None
