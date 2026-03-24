"""
API event models.

Models for Server-Sent Events (SSE) streaming:
- ChatEvent: Single SSE event in conversation stream
- StreamingChatEvent: Streaming chat update event
- ErrorResponse: Standard error response format

Extracted from models.py for better organization.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from .enums import EventType


class ChatEvent(BaseModel):
    """
    A single Server-Sent Event in a conversation stream.

    Args:
        event_id: Unique event identifier (for resumption with Last-Event-ID).
        type: Type of event (message.start, message.delta, etc.).
        data: Event payload (varies by event type).
        timestamp: UTC timestamp when event was emitted.

    Examples:
        >>> event = ChatEvent(
        ...     event_id="evt_001",
        ...     type=EventType.MESSAGE_DELTA,
        ...     data={"message_id": "msg_abc", "delta": {"content": "Hello"}},
        ...     timestamp=datetime.utcnow()
        ... )
    """

    event_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique event identifier",
    )
    type: EventType = Field(
        ...,
        description="Type of event",
    )
    data: dict[str, Any] = Field(
        ...,
        description="Event payload",
    )
    timestamp: datetime = Field(
        ...,
        description="UTC timestamp when event was emitted",
    )


class StreamingChatEvent(BaseModel):
    """
    Server-Sent Event for streaming chat updates.

    This model is used by the SSE streaming endpoint to send real-time
    updates to clients during conversation processing.

    Args:
        event_id: Unique event identifier (for event ordering and resumption).
        conversation_id: Parent conversation identifier.
        event_type: Type of event being streamed (message.delta, tool.call, etc.).
        data: Event payload (varies by event type).
        timestamp: UTC timestamp when event was emitted (auto-generated if not provided).

    Examples:
        >>> event = StreamingChatEvent(
        ...     event_id="evt_001",
        ...     conversation_id="conv_abc123",
        ...     event_type="message.delta",
        ...     data={"content": "Hello "}
        ... )
    """

    event_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique event identifier",
    )
    conversation_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Parent conversation identifier",
    )
    event_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Type of event being streamed",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event payload (varies by event type)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when event was emitted",
    )


class ErrorResponse(BaseModel):
    """
    Standard error response format.

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        details: Additional error context.
        trace_id: Distributed tracing identifier (for debugging).

    Examples:
        >>> error = ErrorResponse(
        ...     code="VALIDATION_ERROR",
        ...     message="Invalid request body",
        ...     details={"field": "content", "issue": "empty"},
        ...     trace_id="trace_001"
        ... )
    """

    code: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Machine-readable error code",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Human-readable error message",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Additional error context",
    )
    trace_id: str | None = Field(
        default=None,
        description="Distributed tracing identifier",
    )
