"""SDK event types for streaming responses.

These are stable public types owned by the SDK. Internal server events are
mapped to these in the SDK layer so consumers never need to import from
``starboard_server``.

Example::

    from starboard_sdk.event_types import AgentEvent, ToolStartEvent

    async for event in session.ask_stream("Analyze job 12345"):
        if isinstance(event, ToolStartEvent):
            print(f"Running tool: {event.tool_name}")
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class ToolStartEvent:
    """Emitted when the agent begins executing a tool."""

    tool_name: str
    friendly_name: str
    tool_call_id: str
    arguments: dict[str, object]


@dataclasses.dataclass(frozen=True)
class ToolEndEvent:
    """Emitted when a tool execution completes."""

    tool_name: str
    friendly_name: str
    tool_call_id: str
    success: bool
    duration_seconds: float
    error: str | None = None


@dataclasses.dataclass(frozen=True)
class ErrorEvent:
    """Emitted when the agent encounters an error."""

    error_type: str
    error: str
    is_recoverable: bool


@dataclasses.dataclass(frozen=True)
class FinalOutputEvent:
    """Emitted when the agent produces its final output."""

    output: dict[str, object]


@dataclasses.dataclass(frozen=True)
class StreamingEvent:
    """Emitted for intermediate streaming content (thinking, partial text)."""

    event_type: str
    content: str


AgentEvent = (
    ToolStartEvent | ToolEndEvent | ErrorEvent | FinalOutputEvent | StreamingEvent
)
"""Union of all events that ``ask_stream()`` can yield."""
