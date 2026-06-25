"""Re-export API model types for use by the agent layer.

This module provides a domain-layer facade over api.models types that agents
need. Agents import from here (domain layer) rather than directly from the api
layer, preserving the architectural rule: agents → domain, not agents → api.

ARCHITECTURAL DEBT (F-3-1a-001)
--------------------------------
The imports below invert the clean-architecture dependency direction: this
domain module currently depends on starboard_server.api, which is an outer
layer.  The correct direction is api → domain.

Migration path (requires editing files outside this module):
  1. Move the shared types — ChatEvent, ConversationConfig, ConversationHistory,
     ConversationMetadata, ConversationResponse, DomainModelConfig, EventType,
     Message, MessageResponse, MessageStatus, ToolCall — from
     ``starboard_server/api/models/`` into
     ``starboard_server/domain/conversation/models.py`` (new file).
  2. Update ``starboard_server/api/models/__init__.py`` to re-export the moved
     types from domain instead of defining them locally.
  3. Move ``convert_streaming_event_to_chat_event`` (and its EVENT_TYPE_MAPPING)
     from ``starboard_server/api/event_converter.py`` into a new adapter module
     such as ``starboard_server/adapters/conversation/event_converter.py``, which
     is allowed to import from both domain and api.
  4. Replace the imports in this file with imports from the new domain location.
  5. This file then becomes the stable canonical re-export and api/models/
     re-exports from it — reversing the direction.

Until that migration is executed the imports below are intentional technical
debt, tracked as finding F-3-1a-001.
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
