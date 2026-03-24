"""In-memory state store implementation."""

from datetime import UTC, datetime
from typing import Any

from starboard_core.models.conversation import Conversation, ConversationMetadata


class InMemoryStateStore:
    """In-memory conversation state store for development/testing."""

    def __init__(self):
        """Initialize in-memory store."""
        self._conversations: dict[str, Conversation] = {}

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Retrieve conversation by ID."""
        return self._conversations.get(conversation_id)

    async def save_conversation(self, conversation: Conversation) -> None:
        """Persist conversation (create or update)."""
        # Store conversation (in-memory, so no deep copy needed)
        self._conversations[conversation.id] = conversation

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete conversation."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False

    async def delete_all_conversations(self, user_id: str) -> int:
        """
        Delete all conversations for a user (batch operation).

        Args:
            user_id: User identifier

        Returns:
            Number of conversations deleted
        """
        # Find all conversation IDs for this user
        to_delete = [
            conv_id
            for conv_id, conv in self._conversations.items()
            if conv.user_id == user_id
        ]

        # Delete them
        for conv_id in to_delete:
            del self._conversations[conv_id]

        return len(to_delete)

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationMetadata]:
        """List conversations for a user (paginated)."""
        # Filter by user
        user_convs = [
            c
            for c in self._conversations.values()
            if c.user_id == user_id and not c.archived
        ]

        # Sort by updated_at (descending)
        user_convs.sort(key=lambda c: c.updated_at, reverse=True)

        # Paginate
        paginated = user_convs[offset : offset + limit]

        return [ConversationMetadata.from_conversation(c) for c in paginated]

    async def update_metadata(
        self,
        conversation_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update conversation metadata (title, tags, etc.)."""
        conv = self._conversations.get(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Apply updates (mutate in place for in-memory store)
        for key, value in updates.items():
            if hasattr(conv, key):
                setattr(conv, key, value)

        conv.updated_at = datetime.now(UTC)
