# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Event broadcasting coordinator for multi-agent conversations.

Coordinates SSE event broadcasting and subscription management,
providing a higher-level API that includes conversation validation
and state manager integration.

Extracted from MultiAgentConversationManager for clean separation of concerns.
Wraps the lower-level SSEBroadcaster with conversation-aware logic.

Design:
- Delegates to SSEBroadcaster for actual broadcasting
- Adds conversation existence validation
- Provides unified API for subscribe/unsubscribe/broadcast operations

Example:
    >>> coordinator = EventBroadcastCoordinator(
    ...     state_manager=db_state_manager,
    ... )
    >>>
    >>> # Subscribe with validation
    >>> queue = await coordinator.subscribe("conv_123")
    >>>
    >>> # Broadcast event
    >>> await coordinator.broadcast("conv_123", chat_event)
"""

from __future__ import annotations

import asyncio
from typing import Any

from starboard_server.agents.observability.sse_broadcaster import SSEBroadcaster
from starboard_server.domain.conversation.api_types import ChatEvent
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class EventBroadcastCoordinator:
    """
    Coordinates SSE event broadcasting with conversation validation.

    Responsibilities:
    - Subscribe clients to conversation events (with validation)
    - Unsubscribe clients from conversation events
    - Broadcast events to all subscribers
    - Clear subscribers for a conversation
    - Get subscriber counts

    Does NOT:
    - Manage conversation CRUD (ConversationLifecycleManager)
    - Route messages or handoff agents (AgentHandoffCoordinator)
    - Process message queues (MessageQueueProcessor)

    Example:
        >>> coordinator = EventBroadcastCoordinator(
        ...     state_manager=db_state_manager,
        ...     queue_maxsize=100,
        ...     broadcast_timeout=1.0,
        ... )
        >>>
        >>> # Subscribe
        >>> queue = await coordinator.subscribe("conv_123")
        >>>
        >>> # Broadcast
        >>> event = ChatEvent(...)
        >>> await coordinator.broadcast("conv_123", event)
        >>>
        >>> # Unsubscribe
        >>> await coordinator.unsubscribe("conv_123", queue)
    """

    def __init__(
        self,
        state_manager: Any,  # ConversationStateManager protocol
        queue_maxsize: int = 100,
        broadcast_timeout: float = 1.0,
    ):
        """
        Initialize event broadcast coordinator.

        Args:
            state_manager: Manager for conversation state (for validation)
            queue_maxsize: Maximum size of subscriber queues
            broadcast_timeout: Timeout for putting events in queues (seconds)
        """
        self.state_manager = state_manager

        # Delegate to SSEBroadcaster for actual broadcasting
        self._broadcaster = SSEBroadcaster(
            queue_maxsize=queue_maxsize,
            broadcast_timeout=broadcast_timeout,
        )

    async def subscribe(self, conversation_id: str) -> asyncio.Queue[ChatEvent]:
        """
        Subscribe to events for a conversation.

        Creates and returns an asyncio.Queue that will receive all events
        broadcast to this conversation. Validates that the conversation exists.

        Args:
            conversation_id: Conversation to subscribe to

        Returns:
            asyncio.Queue that will receive ChatEvent objects

        Raises:
            ValueError: If conversation doesn't exist in state manager

        Example:
            >>> queue = await coordinator.subscribe("conv_123")
            >>> event = await queue.get()
            >>> print(f"Received: {event.type}")
        """
        # Verify conversation exists by trying to load it
        context = await self.state_manager.load_context(conversation_id)
        if context is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Delegate to SSEBroadcaster
        queue = self._broadcaster.subscribe(conversation_id)

        logger.debug(
            "client_subscribed",
            conversation_id=conversation_id,
            subscriber_count=self._broadcaster.get_subscriber_count(conversation_id),
        )

        return queue

    async def unsubscribe(
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
            >>> queue = await coordinator.subscribe("conv_123")
            >>> # ... consume events ...
            >>> await coordinator.unsubscribe("conv_123", queue)
        """
        # Delegate to SSEBroadcaster
        self._broadcaster.unsubscribe(conversation_id, queue)

        logger.debug(
            "client_unsubscribed",
            conversation_id=conversation_id,
            remaining_subscribers=self._broadcaster.get_subscriber_count(
                conversation_id
            ),
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
            >>> event = ChatEvent(...)
            >>> await coordinator.broadcast("conv_123", event)
        """
        # Delegate to SSEBroadcaster
        await self._broadcaster.broadcast(conversation_id, event)

    def clear_conversation(self, conversation_id: str) -> None:
        """
        Clear all subscribers for a conversation.

        Removes all subscribers, typically called when a conversation is deleted.

        Args:
            conversation_id: Conversation identifier

        Example:
            >>> coordinator.clear_conversation("conv_123")
        """
        self._broadcaster.clear_conversation(conversation_id)

        logger.debug(
            "conversation_subscribers_cleared",
            conversation_id=conversation_id,
        )

    def get_subscriber_count(self, conversation_id: str) -> int:
        """
        Get number of subscribers for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Number of active subscribers

        Example:
            >>> count = coordinator.get_subscriber_count("conv_123")
            >>> print(f"Subscribers: {count}")
        """
        return self._broadcaster.get_subscriber_count(conversation_id)
