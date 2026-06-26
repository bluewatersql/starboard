# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Base event types and classes for agent streaming.

This module defines the core EventType enum and StreamingEvent base class
that all specific event types inherit from.

Example:
    >>> from starboard_server.agents.events import EventType, StreamingEvent
    >>> event = ThinkingEvent(type=EventType.THINKING, step=1, content="...")
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    """Types of streaming events."""

    # Core agent events
    THINKING = "thinking"
    STEP_COMPLETE = "step.complete"
    STEP_START = "step.start"
    ERROR = "error"

    # Tool execution events
    TOOL_START = "tool_start"
    TOOL_PROGRESS = "tool.progress"
    TOOL_END = "tool_end"

    # User interaction events
    USER_INPUT_REQUEST = "user_input_request"
    USER_INPUT_RESPONSE = "user_input_response"
    FINAL_OUTPUT = "final_output"

    # Conversation pattern events
    NEXT_STEPS = "next_steps"
    HANDOFF = "handoff"
    CLARIFICATION_REQUEST = "clarification.request"

    # Interruptible reasoning events
    CHECKPOINT = "checkpoint"
    INTERRUPT_RECEIVED = "interrupt.received"
    REPLAN = "replan"
    SOLICITATION = "solicitation"


class StreamingEvent(BaseModel):
    """
    Base class for all streaming events.

    All events include type and step information for context.

    Events are self-serializing: each event knows how to convert itself
    to SSE format via the to_sse_data() method. This eliminates the need
    for a complex external converter.

    Attributes:
        type: Type of event (from EventType enum)
        step: Current reasoning step number (0-indexed)

    Example:
        >>> event = ThinkingEvent(type=EventType.THINKING, step=1, content="Analyzing...")
        >>> sse_data = event.to_sse_data(message_id="msg_123")
        >>> print(sse_data)
        {"message_id": "msg_123", "delta": {"content": "Analyzing..."}}
    """

    type: EventType = Field(..., description="Type of event")
    step: int = Field(..., ge=0, description="Current reasoning step number")

    model_config = ConfigDict(
        frozen=True,  # Immutable
        use_enum_values=True,  # Serialize enums as values
    )

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """
        Convert event to SSE data format for UI consumption.

        Default implementation: serialize all fields except 'type' and 'step',
        and add message_id if provided.

        Subclasses override this to provide UI-specific formatting
        (e.g., nesting tool data under 'tool_call' key).

        Args:
            message_id: Optional message ID for UI correlation

        Returns:
            Dictionary suitable for SSE ChatEvent.data field

        Example:
            >>> event = ThinkingEvent(step=1, content="Hello")
            >>> event.to_sse_data(message_id="msg_123")
            {"message_id": "msg_123", "delta": {"content": "Hello"}}
        """
        # Default: pass through all fields except type/step
        data = self.model_dump(exclude={"type", "step"})
        if message_id:
            data["message_id"] = message_id
        return data


# Type alias for convenience
StreamEvent = StreamingEvent
