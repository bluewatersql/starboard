"""SDK event type facade.

Re-exports only the event types that SDK consumers need to work with
streaming responses from ``ConversationSession.ask_stream()``.  Internal
server event types that are not part of the stable SDK surface are not
re-exported here.

Example::

    from starboard_sdk.events import (
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

from starboard_server.bootstrap import (
    ErrorEvent,
    FinalOutputEvent,
    StreamingEvent,
    ToolEndEvent,
    ToolStartEvent,
)

__all__ = [
    "ErrorEvent",
    "FinalOutputEvent",
    "StreamingEvent",
    "ToolEndEvent",
    "ToolStartEvent",
]
