# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""In-memory implementation of ConversationStateManager.

This module provides a simple in-memory storage for SharedAgentContext,
suitable for development and testing. For production, this should be replaced
with a persistent store (e.g., Redis, PostgreSQL).

**Phase 3, Task 3.3**: API Layer Integration
"""

from starboard_server.agents.state.shared_context import SharedAgentContext
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class InMemoryConversationStateManager:
    """
    In-memory storage for SharedAgentContext.

    Stores conversation contexts in a dictionary keyed by conversation_id.
    This implementation is NOT suitable for production multi-instance deployments,
    as each instance maintains its own separate memory.

    For production, replace with a persistent store:
    - Redis: for fast access and expiration policies
    - PostgreSQL: for full persistence and querying
    - DynamoDB/CosmosDB: for cloud-native deployments

    Attributes:
        _store: Dictionary mapping conversation_id to SharedAgentContext

    Example:
        >>> manager = InMemoryConversationStateManager()
        >>> context = SharedAgentContext(conversation_id="conv_123", user_id="user_456")
        >>> await manager.save_context(context)
        >>> loaded = await manager.load_context("conv_123")
        >>> assert loaded == context
    """

    def __init__(self):
        self._store: dict[str, SharedAgentContext] = {}
        logger.debug("in_memory_conversation_state_manager_initialized")

    async def load_context(self, conversation_id: str) -> SharedAgentContext | None:
        """
        Load SharedAgentContext from memory.

        Args:
            conversation_id: Unique conversation identifier

        Returns:
            SharedAgentContext if found, None otherwise

        Example:
            >>> context = await manager.load_context("conv_123")
            >>> if context:
            ...     print(f"Loaded {len(context.conversation_history)} messages")
        """
        context = self._store.get(conversation_id)
        if context:
            logger.debug(
                "loaded_context",
                conversation_id=conversation_id,
                message_count=len(context.conversation_history),
                transition_count=len(context.agent_transitions),
            )
        else:
            logger.debug("context_not_found", conversation_id=conversation_id)
        return context

    async def save_context(self, context: SharedAgentContext) -> None:
        """
        Save SharedAgentContext to memory.

        Args:
            context: SharedAgentContext to save

        Raises:
            ValueError: If context.conversation_id is empty

        Example:
            >>> context = SharedAgentContext(conversation_id="conv_123", user_id="user_456")
            >>> await manager.save_context(context)
        """
        if not context.conversation_id:
            raise ValueError("conversation_id cannot be empty")

        self._store[context.conversation_id] = context
        logger.debug(
            "saved_context",
            conversation_id=context.conversation_id,
            message_count=len(context.conversation_history),
            transition_count=len(context.agent_transitions),
        )

    def clear_context(self, conversation_id: str) -> None:
        """
        Remove a conversation context from memory.

        Args:
            conversation_id: Unique conversation identifier

        Example:
            >>> manager.clear_context("conv_123")
        """
        if conversation_id in self._store:
            del self._store[conversation_id]
            logger.debug("cleared_context", conversation_id=conversation_id)

    def clear_all(self) -> None:
        """
        Clear all conversation contexts from memory.

        Used for testing and cleanup.

        Example:
            >>> manager.clear_all()
        """
        count = len(self._store)
        self._store.clear()
        logger.debug("cleared_all_contexts", count=count)
