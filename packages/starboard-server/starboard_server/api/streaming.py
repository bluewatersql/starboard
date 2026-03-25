"""Server-Sent Events (SSE) streaming for real-time chat updates.

This module implements SSE endpoints for streaming chat events to clients.
It connects to MultiAgentConversationManager event queues and formats events
according to the SSE protocol specification.

Architecture:
- Each client connection gets a dedicated event queue
- Uses MultiAgentConversationManager for all conversations
- SSE format: "event: <type>\\ndata: <json>\\n\\n"
- Heartbeat every 15 seconds to keep connection alive
- Graceful cleanup on client disconnect

Multi-Agent Integration:
- Uses MultiAgentConversationManager for all conversations
- Supports multi-agent specific events (routing, transitions)

Standards Compliance:
- Async streaming with proper cleanup
- Structured logging with trace context
- Error handling with retries
- Client disconnection detection
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from starboard_server.api.dependencies import MultiAgentManagerDep
from starboard_server.api.models import ChatEvent, EventType
from starboard_server.infra.core.config import get_config
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.serialization import json_dumps

logger = get_logger(__name__)


def _build_error_event_data(
    exc: Exception,
    conversation_id: str,
    production: bool | None = None,
) -> dict:
    """Build SSE error event data, sanitizing details in production.

    Args:
        exc: The exception that occurred.
        conversation_id: Conversation ID for context.
        production: If True, return generic message only. If None, reads config.

    Returns:
        dict with "error" key containing message and code.
    """
    if production is None:
        try:
            config = get_config()
            production = config.environment == "production"
        except Exception:
            production = True  # Safe default

    if production:
        return {
            "error": {
                "message": "An error occurred. Please try again.",
                "code": "STREAM_ERROR",
            }
        }

    return {
        "error": {
            "message": str(exc),
            "code": type(exc).__name__,
        }
    }

router = APIRouter(prefix="/api/chat", tags=["Chat Streaming"])

# SSE configuration
SSE_HEARTBEAT_INTERVAL = 15.0  # seconds
SSE_RETRY_MS = 3000  # Client retry interval in milliseconds


def format_sse_event(event: ChatEvent) -> str:
    """
    Format a chat event as an SSE message.

    Args:
        event: Chat event to format

    Returns:
        SSE-formatted string: "event: <type>\\ndata: <json>\\n\\n"

    Examples:
        >>> event = ChatEvent(...)
        >>> formatted = format_sse_event(event)
        >>> assert formatted.startswith("event: ")
        >>> assert "\\ndata: " in formatted
        >>> assert formatted.endswith("\\n\\n")
    """
    # Convert event to dict for JSON serialization
    event_dict = event.model_dump(mode="json")

    # Get event type as string (handle both EventType enum and str)
    event_type_str = (
        event.type.value if hasattr(event.type, "value") else str(event.type)
    )

    json_str = json_dumps(event_dict)

    lines = [
        f"event: {event_type_str}",
        f"data: {json_str}",
        "",  # Blank line to end event
    ]
    sse_formatted = "\n".join(lines) + "\n"

    logger.debug(
        "formatted_sse_event",
        event_type=event_type_str,
        event_id=event.event_id,
    )

    return sse_formatted


def format_sse_heartbeat() -> str:
    """
    Format an SSE heartbeat (comment) to keep connection alive.

    Returns:
        SSE comment string

    Examples:
        >>> heartbeat = format_sse_heartbeat()
        >>> assert heartbeat.startswith(": heartbeat")
    """
    return ": heartbeat\n\n"


def format_sse_retry(retry_ms: int) -> str:
    """
    Format an SSE retry instruction.

    Args:
        retry_ms: Retry interval in milliseconds

    Returns:
        SSE retry string

    Examples:
        >>> retry = format_sse_retry(3000)
        >>> assert retry == "retry: 3000\\n\\n"
    """
    return f"retry: {retry_ms}\n\n"


async def event_stream(
    conversation_id: str,
    request: Request,
    manager,  # MultiAgentConversationManager
) -> AsyncGenerator[str, None]:
    """
    Generate SSE stream for a conversation.

    Subscribes to conversation events and yields SSE-formatted messages.
    Includes heartbeat mechanism and graceful disconnection handling.

    Phase 4: Automatically selects the appropriate manager (multi-agent or legacy)
    based on rollout configuration and consistent hashing.

    Args:
        conversation_id: Conversation to stream events for
        request: FastAPI request (for disconnect detection)

    Yields:
        SSE-formatted event strings

    Raises:
        ValueError: If conversation not found

    Examples:
        >>> async for sse_msg in event_stream(conv_id, request, manager):
        ...     # sse_msg is "event: ...\\ndata: {...}\\n\\n"
        ...     await send_to_client(sse_msg)
    """
    manager_type = type(manager).__name__
    logger.debug(
        "sse_stream_started",
        conversation_id=conversation_id,
        client_host=request.client.host if request.client else "unknown",
        manager_type=manager_type,
    )

    # Send initial retry instruction
    yield format_sse_retry(SSE_RETRY_MS)

    # Subscribe to conversation events
    try:
        event_queue = await manager.subscribe(conversation_id)
    except ValueError as e:
        logger.error(
            "sse_subscription_failed",
            conversation_id=conversation_id,
            error=str(e),
            manager_type=manager_type,
        )
        raise

    last_heartbeat = asyncio.get_event_loop().time()

    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                logger.debug(
                    "sse_client_disconnected",
                    conversation_id=conversation_id,
                )
                break

            # Get event with timeout (for heartbeat check)
            try:
                event = await asyncio.wait_for(
                    event_queue.get(),
                    timeout=1.0,  # Check every second
                )

                # Get event type as string for logging (do this before yield)
                event_type_str = (
                    event.type.value
                    if hasattr(event.type, "value")
                    else str(event.type)
                )

                # Format and yield event immediately
                sse_message = format_sse_event(event)
                yield sse_message

                # Log after yielding (non-blocking)
                logger.debug(
                    "sse_event_sent",
                    conversation_id=conversation_id,
                    event_type=event_type_str,
                    event_id=event.event_id,
                )

                last_heartbeat = asyncio.get_event_loop().time()
                await asyncio.sleep(0)

            except TimeoutError:
                # No event received, check if heartbeat needed
                current_time = asyncio.get_event_loop().time()
                if current_time - last_heartbeat >= SSE_HEARTBEAT_INTERVAL:
                    yield format_sse_heartbeat()
                    last_heartbeat = current_time
                    logger.debug(
                        "sse_heartbeat_sent",
                        conversation_id=conversation_id,
                    )

    except asyncio.CancelledError:
        logger.debug(
            "sse_stream_cancelled",
            conversation_id=conversation_id,
        )
        raise

    except Exception as e:
        logger.error(
            "sse_stream_error",
            conversation_id=conversation_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        # Send error event to client (format must match frontend ErrorDataSchema)
        # Sanitize error details in production to avoid leaking internal state
        error_data = _build_error_event_data(e, conversation_id)
        error_event = ChatEvent(
            event_id=f"error_{conversation_id}",
            type=EventType.ERROR,
            data=error_data,
            timestamp=datetime.now(UTC),
        )
        yield format_sse_event(error_event)

    finally:
        # Unsubscribe on disconnect
        await manager.unsubscribe(conversation_id, event_queue)
        logger.debug(
            "sse_stream_closed",
            conversation_id=conversation_id,
        )


@router.get(
    "/conversations/{conversation_id}/stream",
    summary="Stream conversation events via SSE",
    description=(
        "Establishes a Server-Sent Events (SSE) connection to receive real-time "
        "updates for a conversation. Events include message updates, tool calls, "
        "thinking process, and errors. The connection includes heartbeats to keep "
        "it alive and supports automatic reconnection. "
        "\n\nPhase 4: Automatically routes to multi-agent or legacy manager based on "
        "rollout configuration. Supports multi-agent specific events like routing "
        "decisions and agent transitions."
    ),
    response_description="SSE stream of chat events",
    responses={
        200: {
            "description": "SSE stream established",
            "content": {
                "text/event-stream": {
                    "example": "event: message_delta\ndata: {...}\n\n"
                }
            },
        },
        404: {"description": "Conversation not found"},
        500: {"description": "Internal server error"},
    },
)
async def stream_conversation_events(
    conversation_id: str,
    request: Request,
    manager: MultiAgentManagerDep,
) -> StreamingResponse:
    """
    Stream real-time events for a conversation via Server-Sent Events.

    This endpoint establishes a long-lived HTTP connection that streams events
    as they occur. The client receives updates about:
    - Message creation and updates
    - Agent thinking process
    - Tool calls and results
    - Routing decisions (multi-agent only)
    - Agent transitions (multi-agent only)
    - Errors and completion

    Phase 4 Multi-Agent Integration:
    - Automatically selects manager based on rollout configuration
    - Consistent hashing ensures same conversation uses same manager
    - Supports both legacy and multi-agent event types

    The stream includes:
    - Automatic heartbeats every 15 seconds
    - Retry instructions for client reconnection
    - Graceful handling of client disconnection

    Args:
        conversation_id: ID of the conversation to stream
        request: FastAPI request (for disconnect detection)

    Returns:
        StreamingResponse with SSE events

    Raises:
        HTTPException: 404 if conversation not found

    Examples:
        Client-side (JavaScript):
        ```javascript
        const eventSource = new EventSource(
            '/api/v2/chat/conversations/conv_123/stream'
        );

        eventSource.addEventListener('message_delta', (event) => {
            const data = JSON.parse(event.data);
            console.log('Delta:', data);
        });

        eventSource.addEventListener('routing.decision', (event) => {
            const data = JSON.parse(event.data);
            console.log('Routed to:', data.domain);
        });

        eventSource.addEventListener('agent.transition', (event) => {
            const data = JSON.parse(event.data);
            console.log('Transition:', data.from_agent, '->', data.to_agent);
        });
        ```

        Client-side (Python):
        ```python
        import httpx

        async with httpx.AsyncClient() as client:
            async with client.stream(
                'GET',
                'http://localhost:8000/api/v2/chat/conversations/conv_123/stream'
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith('data: '):
                        data = json_loads(line[6:])
                        print(data)
        ```
    """
    logger.debug(
        "sse_stream_requested",
        conversation_id=conversation_id,
        client_host=request.client.host if request.client else "unknown",
    )

    # Verify conversation exists
    try:
        context = await manager.state_manager.load_context(conversation_id)
        if context is None:
            raise ValueError(f"Conversation {conversation_id} not found")
    except ValueError as e:
        logger.warning(
            "sse_conversation_not_found",
            conversation_id=conversation_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found",
        ) from e

    # Return streaming response
    return StreamingResponse(
        event_stream(conversation_id, request, manager),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )
