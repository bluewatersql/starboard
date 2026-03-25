"""Re-export API model types for use by the agent layer.

This module provides a domain-layer facade over api.models types that agents
need. Agents must import from here (domain layer) rather than directly from
the api layer, preserving the architectural rule: agents → domain, not
agents → api.

When these models are eventually moved fully into domain, this module becomes
the canonical location and the api.models re-exports from here instead.
"""

# ruff: noqa: F401 — re-exports
from starboard_server.api.event_converter import (
    convert_streaming_event_to_chat_event,
)
from starboard_server.api.models import (
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
