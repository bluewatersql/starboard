"""
SSE (Server-Sent Events) broadcaster for multi-agent conversations.

Manages subscription/unsubscription and event broadcasting to multiple
connected clients via asyncio queues.

Follows Python AI Agent Engineering Standards:
- Single responsibility (event broadcasting only)
- Async-first design
- Explicit error handling
- Type hints on all functions
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from starboard_server.api.models import ChatEvent

logger = structlog.get_logger(__name__)


class SSEBroadcaster:
    """
    Manages Server-Sent Events broadcasting to multiple subscribers.

    Provides subscription management and event broadcasting for real-time
    communication with frontend clients. Each conversation can have multiple
    subscribers (e.g., multiple browser tabs).

    Design:
    - Async-first (non-blocking operations)
    - Per-conversation subscription lists
    - Automatic cleanup of empty subscriber lists
    - Graceful handling of slow/disconnected clients

    Example:
        ```python
        broadcaster = SSEBroadcaster()

        # Subscribe to a conversation
        queue = broadcaster.subscribe("conv_123")

        # Broadcast an event
        await broadcaster.broadcast("conv_123", event)

        # Consume events
        async for event in broadcaster.stream_events(queue):
            print(f"Received: {event.type}")

        # Unsubscribe
        broadcaster.unsubscribe("conv_123", queue)
        ```
    """

    def __init__(
        self,
        queue_maxsize: int = 100,
        broadcast_timeout: float = 1.0,
    ) -> None:
        """
        Initialize SSE broadcaster.

        Args:
            queue_maxsize: Maximum size of subscriber queues (default: 100)
            broadcast_timeout: Timeout for putting events in queues (default: 1.0s)
        """
        # Maps conversation_id -> list of asyncio.Queue for each subscriber
        self._subscribers: dict[str, list[asyncio.Queue[ChatEvent]]] = defaultdict(list)
        self._queue_maxsize = queue_maxsize
        self._broadcast_timeout = broadcast_timeout

    def subscribe(self, conversation_id: str) -> asyncio.Queue[ChatEvent]:
        """
        Subscribe to events for a conversation.

        Creates and returns an asyncio.Queue that will receive all events
        broadcast to this conversation. The caller should consume events
        from this queue.

        Args:
            conversation_id: Conversation to subscribe to

        Returns:
            asyncio.Queue that will receive ChatEvent objects

        Example:
            >>> broadcaster = SSEBroadcaster()
            >>> queue = broadcaster.subscribe("conv_123")
            >>> event = await queue.get()
            >>> print(f"Received: {event.type}")
        """
        # Create new queue for this subscriber
        queue: asyncio.Queue[ChatEvent] = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers[conversation_id].append(queue)

        logger.debug(
            "subscriber_added",
            conversation_id=conversation_id,
            subscriber_count=len(self._subscribers[conversation_id]),
        )

        return queue

    def unsubscribe(
        self, conversation_id: str, queue: asyncio.Queue[ChatEvent]
    ) -> None:
        """
        Unsubscribe from events for a conversation.

        Removes the given queue from the subscriber list. The queue will
        no longer receive events.

        Args:
            conversation_id: Conversation to unsubscribe from
            queue: The queue that was returned by subscribe()

        Example:
            >>> broadcaster = SSEBroadcaster()
            >>> queue = broadcaster.subscribe("conv_123")
            >>> # ... consume events ...
            >>> broadcaster.unsubscribe("conv_123", queue)
        """
        if conversation_id in self._subscribers:
            try:
                self._subscribers[conversation_id].remove(queue)
                logger.debug(
                    "subscriber_removed",
                    conversation_id=conversation_id,
                    remaining_subscribers=len(self._subscribers[conversation_id]),
                )

                # Clean up empty lists
                if not self._subscribers[conversation_id]:
                    del self._subscribers[conversation_id]

            except ValueError:
                logger.warning(
                    "subscriber_not_found",
                    conversation_id=conversation_id,
                )

    async def broadcast(self, conversation_id: str, event: ChatEvent) -> None:
        """
        Broadcast an event to all subscribers.

        Puts the event into all subscriber queues for this conversation.
        If a queue is full, logs a warning but continues to other subscribers.

        Args:
            conversation_id: Conversation identifier
            event: ChatEvent to broadcast

        Example:
            >>> broadcaster = SSEBroadcaster()
            >>> event = ChatEvent(...)
            >>> await broadcaster.broadcast("conv_123", event)
        """
        if conversation_id not in self._subscribers:
            logger.debug(
                "no_subscribers_for_broadcast",
                conversation_id=conversation_id,
                event_type=(
                    event.type.value
                    if hasattr(event.type, "value")
                    else str(event.type)
                ),
            )
            return

        subscribers = self._subscribers[conversation_id]
        logger.debug(
            "broadcasting_event",
            conversation_id=conversation_id,
            event_type=(
                event.type.value if hasattr(event.type, "value") else str(event.type)
            ),
            subscriber_count=len(subscribers),
        )

        for queue in subscribers:
            try:
                await asyncio.wait_for(
                    queue.put(event), timeout=self._broadcast_timeout
                )
                await asyncio.sleep(0)  # Yield to event loop
            except TimeoutError:
                logger.warning(
                    "broadcast_queue_full",
                    conversation_id=conversation_id,
                    event_type=(
                        event.type.value
                        if hasattr(event.type, "value")
                        else str(event.type)
                    ),
                )
            except Exception as e:
                logger.error(
                    "broadcast_error",
                    conversation_id=conversation_id,
                    error=str(e),
                    exc_info=True,
                )

    def get_subscriber_count(self, conversation_id: str) -> int:
        """
        Get number of active subscribers for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Number of active subscribers
        """
        return len(self._subscribers.get(conversation_id, []))

    def has_subscribers(self, conversation_id: str) -> bool:
        """
        Check if conversation has any subscribers.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if conversation has at least one subscriber
        """
        return (
            conversation_id in self._subscribers
            and len(self._subscribers[conversation_id]) > 0
        )

    def clear_conversation(self, conversation_id: str) -> None:
        """
        Remove all subscribers for a conversation.

        Used when deleting a conversation or during cleanup.

        Args:
            conversation_id: Conversation identifier
        """
        if conversation_id in self._subscribers:
            subscriber_count = len(self._subscribers[conversation_id])
            del self._subscribers[conversation_id]
            logger.debug(
                "conversation_subscribers_cleared",
                conversation_id=conversation_id,
                removed_count=subscriber_count,
            )

    async def stream_events(
        self, queue: asyncio.Queue[ChatEvent]
    ) -> AsyncIterator[ChatEvent]:
        """
        Stream events from a subscriber queue.

        Yields events as they arrive in the queue. This is a helper method
        for consuming events in an async generator pattern.

        Args:
            queue: Queue returned by subscribe()

        Yields:
            ChatEvent objects as they arrive

        Example:
            >>> broadcaster = SSEBroadcaster()
            >>> queue = broadcaster.subscribe("conv_123")
            >>> async for event in broadcaster.stream_events(queue):
            ...     print(f"Event: {event.type}")
        """
        try:
            while True:
                event = await queue.get()
                yield event
        except asyncio.CancelledError:
            # Stream was cancelled (client disconnected)
            logger.debug("event_stream_cancelled")
            raise
        except Exception as e:
            logger.error("event_stream_error", error=str(e), exc_info=True)
            raise

    def get_all_conversation_ids(self) -> list[str]:
        """
        Get list of all conversations with active subscribers.

        Returns:
            List of conversation IDs
        """
        return list(self._subscribers.keys())

    def get_total_subscriber_count(self) -> int:
        """
        Get total number of subscribers across all conversations.

        Returns:
            Total subscriber count
        """
        return sum(len(subs) for subs in self._subscribers.values())
