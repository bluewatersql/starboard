# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""SDK event type facade.

Re-exports the SDK-owned event types that consumers need to work with
streaming responses from ``ConversationSession.ask_stream()``.  These
types are stable public API — internal server event types are mapped to
these in the SDK layer.

Example::

    from starboard.sdk.events import (
        FinalOutputEvent,
        StreamingEvent,
        ToolEndEvent,
        ToolStartEvent,
    )

    async for event in session.ask_stream("Analyze job 12345"):
        if isinstance(event, ToolStartEvent):
            print(f"Running tool: {event.tool_name}")
        elif isinstance(event, FinalOutputEvent):
            print("Done!")
"""

from __future__ import annotations

from starboard.sdk.event_types import (
    AgentEvent,
    ErrorEvent,
    FinalOutputEvent,
    StreamingEvent,
    ToolEndEvent,
    ToolStartEvent,
)

__all__ = [
    "AgentEvent",
    "ErrorEvent",
    "FinalOutputEvent",
    "StreamingEvent",
    "ToolEndEvent",
    "ToolStartEvent",
]
