# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Context manager for conversation state lifecycle.

Handles loading existing contexts from storage and creating new ones,
with proper message format conversion between database and agent formats.

Follows Python AI Agent Engineering Standards:
- Single responsibility (context lifecycle only)
- Explicit dependencies
- Type hints on all functions
- Proper error handling
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from starboard.agents.multi_agent_manager import (
        ConversationStateManager,  # type: ignore[import-untyped]
    )
    from starboard.agents.state.shared_context import SharedAgentContext

from starboard.agents.state.agent_state import Message, WorkingMemory

logger = structlog.get_logger(__name__)


class ContextManager:
    """
    Manages conversation context lifecycle (load/create).

    Handles:
    - Loading existing contexts from state manager
    - Creating new contexts with defaults
    - Converting between database and agent message formats
    - Reconstructing SharedAgentContext from dictionaries

    Design:
    - Delegates storage to ConversationStateManager
    - Handles format conversions transparently
    - Provides clean SharedAgentContext instances

    Example:
        ```python
        manager = ContextManager(state_manager=db_state_manager)

        context = await manager.load_or_create(
            conversation_id="conv_123",
            user_id="user_456",
        )

        print(f"Messages: {len(context.conversation_history)}")
        ```
    """

    def __init__(self, state_manager: ConversationStateManager) -> None:
        """
        Initialize context manager.

        Args:
            state_manager: State manager for persistence
        """
        self.state_manager = state_manager

    async def load_or_create(
        self, conversation_id: str, user_id: str
    ) -> SharedAgentContext:
        """
        Load existing context or create new one.

        Tries to load from state manager first. If not found, creates
        a new context with empty history and working memory.

        Args:
            conversation_id: Unique conversation identifier
            user_id: User identifier

        Returns:
            SharedAgentContext (loaded or newly created)

        Example:
            >>> manager = ContextManager(state_manager)
            >>> context = await manager.load_or_create("conv_123", "user_456")
            >>> print(f"History length: {len(context.conversation_history)}")
        """
        existing = await self.state_manager.load_context(conversation_id)
        if existing:
            logger.debug("loaded_existing_context", conversation_id=conversation_id)
            return self._reconstruct_context(existing)

        logger.debug("creating_new_context", conversation_id=conversation_id)
        return self._create_new_context(conversation_id, user_id)

    def _reconstruct_context(self, existing: Any) -> SharedAgentContext:
        """
        Reconstruct SharedAgentContext from stored data.

        Handles two formats:
        1. Dictionary (from database)
        2. SharedAgentContext object (legacy)

        Args:
            existing: Loaded context data (dict or SharedAgentContext)

        Returns:
            SharedAgentContext instance
        """
        from starboard.agents.state.shared_context import (
            AgentTransition,
            SharedAgentContext,
        )

        # If already a SharedAgentContext object, return as-is
        if not isinstance(existing, dict):
            return existing

        # Reconstruct from dictionary
        # Convert database messages (with timestamps) to agent messages (without timestamps)
        conversation_history = self._convert_messages(
            existing.get("conversation_history", [])
        )

        return SharedAgentContext(
            conversation_id=existing["conversation_id"],
            user_id=existing["user_id"],
            conversation_history=conversation_history,
            working_memory=WorkingMemory.from_dict(existing.get("working_memory", {})),
            agent_transitions=[
                AgentTransition.from_dict(t) if isinstance(t, dict) else t
                for t in existing.get("agent_transitions", [])
            ],
            metadata=existing.get("metadata", {}),
        )

    def _convert_messages(self, messages: list[Any]) -> list[Message]:
        """
        Convert database messages to agent message format.

        Handles two formats:
        1. Dictionary (database format with timestamps)
        2. Message objects (with or without timestamps)

        Args:
            messages: List of messages in database format

        Returns:
            List of agent Message objects (without timestamps)
        """
        converted = []
        for msg in messages:
            if isinstance(msg, dict):
                # Database format (dict) - convert to agent format
                converted.append(
                    Message(
                        role=msg["role"],
                        content=msg["content"],
                        name=msg.get("name"),
                        tool_call_id=msg.get("tool_call_id"),
                        metadata=msg.get("metadata", {}),
                    )
                )
            else:
                # Database Message object - convert to agent Message format
                # (starboard_core.models.conversation.Message has timestamp,
                #  starboard.agents.state.Message does not)
                converted.append(
                    Message(
                        role=msg.role,
                        content=msg.content,
                        name=getattr(msg, "name", None),
                        tool_call_id=getattr(msg, "tool_call_id", None),
                        metadata=getattr(msg, "metadata", {}),
                    )
                )
        return converted

    def _create_new_context(
        self, conversation_id: str, user_id: str
    ) -> SharedAgentContext:
        """
        Create a new empty context.

        Args:
            conversation_id: Unique conversation identifier
            user_id: User identifier

        Returns:
            New SharedAgentContext with empty history
        """
        from starboard.agents.state.shared_context import SharedAgentContext

        return SharedAgentContext(
            conversation_id=conversation_id,
            user_id=user_id,
            conversation_history=[],
            working_memory=WorkingMemory(),
            agent_transitions=[],
        )
