# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Conversation repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from starboard_core.models.conversation import (
    Conversation,
    ConversationMetadata,
    Message,
)
from starboard_core.ports.state_store import StateStore


class ConversationRepository:
    """High-level interface for conversation operations."""

    def __init__(self, store: StateStore):
        """
        Initialize conversation repository.

        Args:
            store: StateStore implementation for persistence
        """
        self._store = store

    async def get_or_create(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Conversation:
        """
        Get conversation or create if doesn't exist.

        Args:
            conversation_id: Conversation identifier
            user_id: User identifier

        Returns:
            Conversation (existing or newly created)
        """
        conv = await self._store.get_conversation(conversation_id)
        if conv is None:
            conv = Conversation(
                id=conversation_id,
                user_id=user_id,
                messages=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await self._store.save_conversation(conv)
        return conv

    async def get(self, conversation_id: str) -> Conversation | None:
        """
        Get conversation by ID.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Conversation if found, None otherwise
        """
        return await self._store.get_conversation(conversation_id)

    async def add_message(
        self,
        conversation_id: str,
        message: Message,
    ) -> None:
        """
        Append message to conversation.

        Args:
            conversation_id: Conversation identifier
            message: Message to append

        Raises:
            ValueError: If conversation not found
        """
        conv = await self._store.get_conversation(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Mutate conversation (this is OK in repository layer)
        conv.messages.append(message)
        conv.updated_at = datetime.now(UTC)

        await self._store.save_conversation(conv)

    async def get_recent_messages(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> list[Message]:
        """
        Get recent messages (for context window).

        Args:
            conversation_id: Conversation identifier
            limit: Maximum number of messages to return

        Returns:
            List of recent messages (most recent last)
        """
        conv = await self._store.get_conversation(conversation_id)
        if conv is None:
            return []
        return conv.messages[-limit:]

    async def list_for_user(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationMetadata]:
        """
        List conversations for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of conversations to return
            offset: Pagination offset

        Returns:
            List of conversation metadata
        """
        return await self._store.list_conversations(user_id, limit, offset)

    async def set_title(
        self,
        conversation_id: str,
        title: str,
    ) -> None:
        """
        Update conversation title.

        Args:
            conversation_id: Conversation identifier
            title: New title
        """
        await self._store.update_metadata(conversation_id, {"title": title})

    async def delete(self, conversation_id: str) -> bool:
        """
        Delete conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if deleted, False if not found
        """
        return await self._store.delete_conversation(conversation_id)

    async def save_context(self, context: Any) -> None:
        """
        Save shared agent context (for multi-agent orchestration).

        This stores the working memory and agent transitions in the conversation metadata.
        The conversation history is stored in the messages list.

        Args:
            context: SharedAgentContext instance (from starboard-server)
        """
        # Get or create conversation
        conv = await self._store.get_conversation(context.conversation_id)
        if conv is None:
            conv = Conversation(
                id=context.conversation_id,
                user_id=context.user_id,
                messages=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

        # Update messages from context
        conv.messages = context.conversation_history
        conv.updated_at = datetime.now(UTC)

        # Store working memory and agent transitions in metadata
        conv.metadata["working_memory"] = (
            context.working_memory.to_dict()
            if hasattr(context.working_memory, "to_dict")
            else {}
        )
        conv.metadata["agent_transitions"] = [
            t.to_dict() if hasattr(t, "to_dict") else t
            for t in context.agent_transitions
        ]
        conv.metadata["context_metadata"] = context.metadata

        await self._store.save_conversation(conv)

    async def load_context(self, conversation_id: str) -> Any:
        """
        Load shared agent context (for multi-agent orchestration).

        Args:
            conversation_id: Conversation identifier

        Returns:
            SharedAgentContext instance (from starboard-server) or None if not found

        Note:
            This returns a dictionary representation that can be used to reconstruct
            the SharedAgentContext in starboard-server. We avoid importing
            starboard-server types here to prevent circular dependencies.
        """
        conv = await self._store.get_conversation(conversation_id)
        if conv is None:
            return None

        # Return a dict that can be used to construct SharedAgentContext
        # The actual reconstruction happens in starboard-server
        return {
            "conversation_id": conv.id,
            "user_id": conv.user_id,
            "conversation_history": conv.messages,
            "working_memory": conv.metadata.get("working_memory", {}),
            "agent_transitions": conv.metadata.get("agent_transitions", []),
            "metadata": conv.metadata.get("context_metadata", {}),
        }
