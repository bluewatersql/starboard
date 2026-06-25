"""Converter for translating agent StreamingEvents to SSE ChatEvents.

This module provides a simple, declarative approach to converting internal agent
streaming events into SSE-compatible ChatEvent objects that can be broadcast to
frontend clients.

It lives in the adapters layer because it bridges the agents layer
(``starboard_server.agents.events``) and the domain conversation models
(``starboard_server.domain.conversation.models``). The old import path
``starboard_server.api.event_converter`` re-exports these symbols for backward
compatibility.

Design Philosophy:
- Events are self-serializing via to_sse_data() method
- EVENT_TYPE_MAPPING provides declarative type routing
- No manual isinstance() checks or complex branching
- Type-safe conversions with validation
- Easy to extend: add event class → add mapping entry

Example:
    >>> from starboard_server.agents.events import ThinkingEvent
    >>> streaming_event = ThinkingEvent(step=1, content="Analyzing query...")
    >>> chat_event = convert_streaming_event_to_chat_event(
    ...     event=streaming_event,
    ...     conversation_id="conv_123",
    ...     message_id="msg_456"
    ... )
    >>> chat_event.type == EventType.MESSAGE_DELTA
    True
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from starboard_server.agents.events import (
    CheckpointEvent,
    ClarificationRequestEvent,
    ErrorEvent,
    FinalOutputEvent,
    InterruptReceivedEvent,
    NextStepsEvent,
    ReplanEvent,
    SolicitationEvent,
    StepCompleteEvent,
    StreamingEvent,
    ThinkingEvent,
    ThinkingStepUpdate,
    ToolEndEvent,
    ToolProgressEvent,
    ToolStartEvent,
    UserInputRequestEvent,
    UserInputResponseEvent,
)
from starboard_server.domain.conversation.models import ChatEvent, EventType
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


# ==============================================================================
# Event Type Mapping Configuration
# ==============================================================================
#
# Maps internal StreamingEvent types to SSE EventType for frontend consumption.
# This declarative mapping eliminates the need for complex isinstance() checks.
#
# To add a new event:
#   1. Add to_sse_data() method to the event class (in streaming_events.py)
#   2. Add mapping entry here: EventClass: EventType.TARGET_TYPE
#   3. Done! No other changes needed.
#
EVENT_TYPE_MAPPING: dict[type[StreamingEvent] | type[FinalOutputEvent], EventType] = {
    # Content streaming events
    ThinkingEvent: EventType.MESSAGE_DELTA,
    ThinkingStepUpdate: EventType.STEP_START,  # Enhanced thinking steps for UI
    ErrorEvent: EventType.ERROR,  # Maps to error handler in frontend
    # Tool execution events
    ToolStartEvent: EventType.TOOL_CALL_START,
    ToolProgressEvent: EventType.TOOL_PROGRESS,
    ToolEndEvent: EventType.TOOL_CALL_RESULT,
    # Step and completion events
    StepCompleteEvent: EventType.STEP_COMPLETE,
    FinalOutputEvent: EventType.FINAL_OUTPUT,
    # User interaction events
    UserInputRequestEvent: EventType.USER_INPUT_REQUEST,
    UserInputResponseEvent: EventType.USER_INPUT_RESPONSE,
    # Phase 3: Interruptible reasoning events
    CheckpointEvent: EventType.CHECKPOINT,
    InterruptReceivedEvent: EventType.INTERRUPT_RECEIVED,
    ReplanEvent: EventType.REPLAN,
    SolicitationEvent: EventType.SOLICITATION,
    # Phase 1: Conversation patterns
    NextStepsEvent: EventType.NEXT_STEPS,
    # Phase 7: Clarification pattern
    ClarificationRequestEvent: EventType.CLARIFICATION_REQUEST,
}


# ==============================================================================
# Conversion Functions
# ==============================================================================


def convert_streaming_event_to_chat_event(
    event: StreamingEvent | FinalOutputEvent,
    conversation_id: str,
    event_id: str | None = None,
    message_id: str | None = None,
) -> ChatEvent:
    """
    Convert a StreamingEvent to a ChatEvent for SSE broadcasting.

    This function delegates to event.to_sse_data() for event-specific formatting,
    then wraps the result in a ChatEvent with appropriate metadata.

    Args:
        event: The StreamingEvent (or FinalOutputEvent) from the agent
        conversation_id: The conversation ID for this event (currently unused but kept for API compatibility)
        event_id: Optional explicit event ID (auto-generated if None)
        message_id: Optional message ID for UI correlation

    Returns:
        ChatEvent suitable for SSE transmission

    Raises:
        ValueError: If event type is not in EVENT_TYPE_MAPPING

    Example:
        >>> from starboard_server.agents.events import ToolStartEvent
        >>> tool_event = ToolStartEvent(
        ...     step=1,
        ...     tool_name="get_query_plan",
        ...     friendly_name="Getting Query Plan",
        ...     tool_call_id="call_123",
        ...     arguments={"statement_id": "abc123"}
        ... )
        >>> chat_event = convert_streaming_event_to_chat_event(
        ...     event=tool_event,
        ...     conversation_id="conv_123",
        ...     message_id="msg_456"
        ... )
        >>> chat_event.type == EventType.TOOL_CALL_START
        True
    """
    # Get event type from mapping
    event_type = EVENT_TYPE_MAPPING.get(type(event))
    if not event_type:
        logger.error(
            "unknown_event_type",
            event_type=type(event).__name__,
            available_types=[cls.__name__ for cls in EVENT_TYPE_MAPPING],
        )
        raise ValueError(
            f"Unknown event type: {type(event).__name__}. "
            f"Add to EVENT_TYPE_MAPPING in event_converter.py"
        )

    # Generate event ID if not provided
    if event_id is None:
        event_id = f"evt_{uuid4().hex[:12]}"

    # Get event-specific data formatting from event's to_sse_data() method
    try:
        event_data = event.to_sse_data(  # type: ignore[call-arg]
            message_id=message_id, conversation_id=conversation_id
        )
    except TypeError:
        # Fallback: method does not accept conversation_id
        try:
            event_data = event.to_sse_data(message_id=message_id)  # type: ignore[call-arg]
        except Exception as e:  # noqa: BLE001 - API error boundary
            logger.error(
                "event_serialization_failed",
                event_type=type(event).__name__,
                error=str(e),
                exc_info=True,
            )
            return ChatEvent(
                event_id=event_id,
                type=EventType.ERROR,
                data={
                    "message_id": message_id,
                    "error": {
                        "message": f"Failed to serialize event: {str(e)}",
                        "code": "SERIALIZATION_ERROR",
                    },
                },
                timestamp=datetime.now(UTC),
            )
    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error(
            "event_serialization_failed",
            event_type=type(event).__name__,
            error=str(e),
            exc_info=True,
        )
        # Return an error event instead of crashing (format must match frontend ErrorDataSchema)
        return ChatEvent(
            event_id=event_id,
            type=EventType.ERROR,
            data={
                "message_id": message_id,
                "error": {
                    "message": f"Failed to serialize event: {str(e)}",
                    "code": "SERIALIZATION_ERROR",
                },
            },
            timestamp=datetime.now(UTC),
        )

    # Debug logging for final_output events
    if event_type == EventType.FINAL_OUTPUT and isinstance(event_data, dict):
        logger.debug(
            "convert_event_final_output",
            event_data_keys=list(event_data.keys()),
            has_formatted_markdown="formatted_markdown" in event_data,
            formatted_markdown_length=(
                len(event_data.get("formatted_markdown", ""))
                if event_data.get("formatted_markdown")
                else 0
            ),
        )

    # Wrap in ChatEvent
    return ChatEvent(
        event_id=event_id,
        type=event_type,
        data=event_data,
        timestamp=datetime.now(UTC),
    )


# ==============================================================================
# Validation (for startup checks)
# ==============================================================================


def validate_event_coverage() -> tuple[bool, list[str]]:
    """
    Validate that all StreamingEvent subclasses are registered in EVENT_TYPE_MAPPING.

    This function should be called at application startup to ensure no events
    are accidentally missing from the mapping.

    Returns:
        Tuple of (is_valid, missing_events)
        - is_valid: True if all events are covered
        - missing_events: List of class names missing from mapping

    Example:
        >>> is_valid, missing = validate_event_coverage()
        >>> if not is_valid:
        ...     raise RuntimeError(f"Missing event mappings: {missing}")
    """
    # Get all direct subclasses of StreamingEvent
    from starboard_server.agents.events import StreamingEvent

    all_event_classes: set[type[StreamingEvent] | type[FinalOutputEvent]] = set(
        StreamingEvent.__subclasses__()
    )

    # FinalOutputEvent is special - it inherits from BaseModel, not StreamingEvent
    # but is still a valid event type, so we need to include it manually
    all_event_classes.add(FinalOutputEvent)

    registered_classes = set(EVENT_TYPE_MAPPING.keys())

    missing = all_event_classes - registered_classes
    missing_names = sorted([cls.__name__ for cls in missing])

    if missing_names:
        logger.warning(
            "missing_event_mappings",
            missing_events=missing_names,
            registered_events=[cls.__name__ for cls in registered_classes],
        )

    return (not missing_names, missing_names)
