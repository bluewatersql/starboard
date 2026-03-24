"""State store protocol (interface)."""

from typing import Any, Protocol

from starboard_core.models.conversation import Conversation, ConversationMetadata


class StateStore(Protocol):
    """
    Abstract interface for conversation state persistence.

    Implementations must be thread-safe and support concurrent access.
    All methods are async to support I/O-bound operations.
    """

    async def get_conversation(
        self,
        conversation_id: str,
    ) -> Conversation | None:
        """
        Retrieve conversation by ID.

        Args:
            conversation_id: Unique conversation identifier

        Returns:
            Conversation if found, None otherwise
        """
        ...

    async def save_conversation(
        self,
        conversation: Conversation,
    ) -> None:
        """
        Persist conversation (create or update).

        Args:
            conversation: Conversation to persist

        Raises:
            StorageError: If save operation fails
        """
        ...

    async def delete_conversation(
        self,
        conversation_id: str,
    ) -> bool:
        """
        Delete conversation.

        Args:
            conversation_id: Unique conversation identifier

        Returns:
            True if deleted, False if not found
        """
        ...

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationMetadata]:
        """
        List conversations for a user (paginated).

        Args:
            user_id: User identifier
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of conversation metadata (id, title, updated_at, etc.)
        """
        ...

    async def update_metadata(
        self,
        conversation_id: str,
        updates: dict[str, Any],
    ) -> None:
        """
        Update conversation metadata (title, tags, etc.).

        Args:
            conversation_id: Unique conversation identifier
            updates: Key-value pairs to update
        """
        ...
