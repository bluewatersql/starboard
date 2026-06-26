# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Stable re-export facade for conversation types used by the agent layer.

Agents import the shared conversation models from here (the domain layer) rather
than from the api layer, preserving the architectural rule: agents → domain,
not agents → api.

The canonical model definitions now live in
``starboard_server.domain.conversation.models``; this module simply re-exports
them. The streaming-event converter is an adapter concern and is re-exported
from ``starboard_server.adapters.conversation.event_converter``.

The previous architectural-debt inversion (finding F-3-1a-001), where this
module imported from ``starboard_server.api``, has been resolved: the api layer
now re-exports these types from domain, so the dependency direction is correct
(api → domain).
"""

# ruff: noqa: F401 — re-exports
from typing import TYPE_CHECKING, Any

from starboard_server.domain.conversation.models import (
    ChatEvent,
    ConversationConfig,
    ConversationHistory,
    ConversationMetadata,
    ConversationResponse,
    DomainModelConfig,
    EventType,
    Message,
    MessageResponse,
    MessageStatus,
    ToolCall,
)

if TYPE_CHECKING:
    # Imported lazily at runtime (see __getattr__) to avoid a circular import:
    # the adapter imports starboard_server.agents.events, whose package __init__
    # imports the agents.conversation package, which imports this module.
    from starboard_server.adapters.conversation.event_converter import (
        convert_streaming_event_to_chat_event,
    )


def __getattr__(name: str) -> Any:
    """Lazily expose the streaming-event converter.

    Re-exporting ``convert_streaming_event_to_chat_event`` at module load time
    would pull in the agents package and create a circular import. Deferring the
    import until first access keeps the public name available while breaking the
    cycle.
    """
    if name == "convert_streaming_event_to_chat_event":
        from starboard_server.adapters.conversation.event_converter import (
            convert_streaming_event_to_chat_event,
        )

        return convert_streaming_event_to_chat_event
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
