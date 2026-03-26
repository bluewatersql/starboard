"""
Conversation lifecycle management.

Handles CRUD operations for conversations:
- Create new conversations with metadata
- Retrieve conversation information
- List user's conversations
- Delete conversations

Extracted from MultiAgentConversationManager for clean separation of concerns.
Follows Single Responsibility Principle - only manages conversation lifecycle.

Design:
- Pure CRUD logic, no routing or orchestration
- Delegates persistence to ConversationStateManager
- Generates friendly names for conversations
- Validates conversation access

Example:
    >>> manager = ConversationLifecycleManager(
    ...     state_manager=db_state_manager,
    ...     config_generator=config_gen,
    ... )
    >>>
    >>> # Create conversation
    >>> response = await manager.create(
    ...     user_id="user_123",
    ...     context={"workspace_id": "ws_abc"},
    ... )
    >>> print(response.conversation_id)  # "conv_abc123"
    >>>
    >>> # List conversations
    >>> conversations = await manager.list_for_user(
    ...     user_id="user_123",
    ...     limit=20,
    ... )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starboard_server.agents.state.agent_state import WorkingMemory
from starboard_server.agents.state.shared_context import SharedAgentContext
from starboard_server.domain.conversation.api_types import (
    ConversationConfig,
    ConversationResponse,
    DomainModelConfig,
)
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ConversationListItem:
    """
    Simple container for conversation list items.

    API expects objects with attributes (not dicts).
    """

    conversation_id: str
    user_id: str
    friendly_name: str
    created_at: str
    config: ConversationConfig


class ConversationLifecycleManager:
    """
    Manages conversation lifecycle operations (CRUD).

    Responsibilities:
    - Create new conversations with initial context
    - Retrieve conversation metadata
    - List conversations for a user (with pagination)
    - Delete conversations and their associated context
    - Generate friendly conversation names

    Does NOT:
    - Route messages to agents (AgentHandoffCoordinator)
    - Manage message queue (MessageQueueProcessor)
    - Handle SSE broadcasting (EventBroadcastManager)

    Example:
        >>> manager = ConversationLifecycleManager(
        ...     state_manager=db_state_manager,
        ...     config_generator=config_gen,
        ... )
        >>>
        >>> response = await manager.create(
        ...     user_id="user_123",
        ...     context={"workspace_id": "ws_abc"},
        ...     config=ConversationConfig(temperature=0.4),
        ... )
        >>>
        >>> conversations = await manager.list_for_user("user_123", limit=20)
    """

    def __init__(
        self,
        state_manager: Any,  # ConversationStateManager protocol
        config_generator: Any,  # DomainModelConfigGenerator
    ):
        """
        Initialize conversation lifecycle manager.

        Args:
            state_manager: Manager for persisting conversation context
            config_generator: Generator for domain model configurations
        """
        self.state_manager = state_manager
        self.config_generator = config_generator

    async def create(
        self,
        user_id: str,
        context: dict[str, Any] | None = None,
        config: ConversationConfig | None = None,
    ) -> ConversationResponse:
        """
        Create a new conversation session.

        Args:
            user_id: User identifier
            context: Initial context (workspace_id, job_id, etc.)
            config: Conversation configuration (or defaults)

        Returns:
            ConversationResponse with conversation_id and config

        Example:
            >>> response = await manager.create(
            ...     user_id="user_123",
            ...     context={"workspace_id": "ws_abc"},
            ...     config=ConversationConfig(temperature=0.4),
            ... )
            >>> print(response.conversation_id)  # "conv_abc123"
        """
        conversation_id = f"conv_{uuid4().hex[:12]}"
        conversation_config = config or ConversationConfig()
        created_at = datetime.now(UTC)

        # Create initial shared context with conversation config
        initial_metadata = context or {}
        initial_metadata["conversation_config"] = conversation_config.model_dump()

        # Generate domain model configurations (structured data)
        domain_models = self.config_generator.generate(conversation_config)
        logger.debug(
            "create_conversation_domain_models",
            conversation_id=conversation_id,
            domain_models=domain_models,
        )

        shared_context = SharedAgentContext(
            conversation_id=conversation_id,
            user_id=user_id,
            conversation_history=[],  # Start with empty history
            working_memory=WorkingMemory(),
            agent_transitions=[],
            metadata=initial_metadata,
        )

        # Save context to state manager
        await self.state_manager.save_context(shared_context)

        # Generate friendly name
        friendly_name = f"New Conversation {created_at.strftime('%Y-%m-%d %I:%M%p')}"

        logger.info(
            "conversation_created",
            conversation_id=conversation_id,
            user_id=user_id,
        )

        return ConversationResponse(
            conversation_id=conversation_id,
            user_id=user_id,
            friendly_name=friendly_name,
            created_at=created_at,
            config=conversation_config,
            domain_models=[DomainModelConfig(**dm) for dm in domain_models],
        )

    async def get(self, conversation_id: str) -> dict[str, Any] | None:
        """
        Get conversation by ID (existence check).

        Returns a minimal dict with conversation info if it exists.

        Args:
            conversation_id: Unique conversation identifier

        Returns:
            Dict with conversation_id and user_id if found, None otherwise

        Example:
            >>> info = await manager.get("conv_abc123")
            >>> if info:
            ...     print(f"Found conversation for user {info['user_id']}")
        """
        # Load context from state manager
        context = await self.state_manager.load_context(conversation_id)
        if not context:
            return None

        # Context can be either a SharedAgentContext object or a dict
        # Handle both cases for compatibility
        if isinstance(context, dict):
            user_id = context.get("user_id", "unknown")
        else:
            user_id = context.user_id

        # Return minimal conversation info
        return {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "exists": True,
        }

    async def list_for_user(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ConversationListItem]:
        """
        List conversations for a user.

        Fetches conversations from the persistent state store (SQLite/Postgres)
        and returns conversation metadata objects.

        Args:
            user_id: User identifier to filter conversations
            limit: Maximum number of conversations to return
            offset: Pagination offset

        Returns:
            List of ConversationListItem objects

        Example:
            >>> conversations = await manager.list_for_user(
            ...     user_id="user_123",
            ...     limit=20,
            ...     offset=0,
            ... )
            >>> for conv in conversations:
            ...     print(f"{conv.friendly_name} ({conv.conversation_id})")
        """
        # Delegate to state_manager which uses the ConversationRepository
        if not hasattr(self.state_manager, "_store"):
            logger.warning(
                "list_conversations_state_manager_incompatible",
                user_id=user_id,
                state_manager_type=type(self.state_manager).__name__,
            )
            return []

        # Use the state store's list_conversations method
        try:
            from starboard_core.models.conversation import ConversationMetadata

            metadata_list: list[
                ConversationMetadata
            ] = await self.state_manager._store.list_conversations(
                user_id=user_id,
                limit=limit,
                offset=offset,
            )

            # Convert to ConversationListItem objects
            conversations = []
            for meta in metadata_list:
                item = ConversationListItem(
                    conversation_id=meta.id,
                    user_id=meta.user_id,
                    friendly_name=meta.title or f"Conversation {meta.id[:8]}",
                    created_at=meta.created_at.isoformat(),
                    config=ConversationConfig(),  # Default config, can be enhanced later
                )
                conversations.append(item)

            logger.debug(
                "list_conversations_success",
                user_id=user_id,
                count=len(conversations),
                limit=limit,
                offset=offset,
            )

            return conversations

        except Exception as e:  # noqa: BLE001 - lifecycle boundary
            logger.error(
                "list_conversations_failed",
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            return []

    async def delete(self, conversation_id: str) -> bool:
        """
        Delete a conversation and its associated context.

        Args:
            conversation_id: Unique conversation identifier

        Returns:
            True if deleted successfully, False otherwise

        Example:
            >>> success = await manager.delete("conv_abc123")
            >>> if success:
            ...     print("Conversation deleted")
        """
        try:
            # Load context to verify it exists
            context = await self.state_manager.load_context(conversation_id)
            if not context:
                logger.warning(
                    "delete_conversation_not_found",
                    conversation_id=conversation_id,
                )
                return False

            # Delete from state manager
            # Note: State manager interface may need a delete method
            # For now, we'll try to delete if the method exists
            if hasattr(self.state_manager, "delete_context"):
                await self.state_manager.delete_context(conversation_id)
            elif hasattr(self.state_manager, "_store"):
                # Fallback: try using the store directly
                await self.state_manager._store.delete_conversation(conversation_id)
            else:
                logger.error(
                    "delete_conversation_no_delete_method",
                    conversation_id=conversation_id,
                    state_manager_type=type(self.state_manager).__name__,
                )
                return False

            logger.info(
                "conversation_deleted",
                conversation_id=conversation_id,
            )
            return True

        except Exception as e:  # noqa: BLE001 - lifecycle boundary
            logger.error(
                "delete_conversation_failed",
                conversation_id=conversation_id,
                error=str(e),
                exc_info=True,
            )
            return False

    async def delete_all(self, user_id: str) -> int:
        """
        Delete all conversations for a user (batch operation).

        Much more efficient than deleting one-by-one.
        Used by "Clear All Conversations" feature.

        Args:
            user_id: User identifier

        Returns:
            Number of conversations deleted

        Example:
            >>> count = await manager.delete_all("user_123")
            >>> print(f"Deleted {count} conversations")
            Deleted 42 conversations
        """
        try:
            # Try to use the store's batch delete method directly
            if hasattr(self.state_manager, "_store"):
                store = self.state_manager._store
                if hasattr(store, "delete_all_conversations"):
                    count = await store.delete_all_conversations(user_id)
                    logger.debug(
                        "all_conversations_deleted",
                        user_id=user_id,
                        count=count,
                    )
                    return count

            # Fallback: delete one-by-one (less efficient)
            logger.warning(
                "delete_all_fallback_to_individual",
                user_id=user_id,
                reason="store lacks delete_all_conversations method",
            )

            conversations = await self.list_for_user(user_id=user_id, limit=1000)
            count = 0
            for conv in conversations:
                if await self.delete(conv.conversation_id):
                    count += 1

            logger.debug(
                "all_conversations_deleted_fallback",
                user_id=user_id,
                count=count,
            )
            return count

        except Exception as e:  # noqa: BLE001 - lifecycle boundary
            logger.error(
                "delete_all_conversations_failed",
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            return 0

    def generate_friendly_name(self, domain: str, extracted_ids: dict[str, str]) -> str:
        """
        Generate a friendly conversation name based on domain and extracted IDs.

        Args:
            domain: Agent domain (query, job, table, compute, diagnostic)
            extracted_ids: Extracted identifiers from user input

        Returns:
            Friendly conversation name

        Example:
            >>> name = manager.generate_friendly_name(
            ...     domain="query",
            ...     extracted_ids={"query_id": "q123"},
            ... )
            >>> print(name)  # "Query Optimization: q123"
        """
        # Map domain to friendly prefix
        domain_prefixes = {
            "query": "Query Optimization",
            "job": "Job Analysis",
            "uc": "Unity Catalog",
            "cluster": "Cluster Resources",
            "warehouse": "Warehouse Analysis",
            "diagnostic": "Diagnostics",
            "analytics": "Analytics",
        }

        prefix = domain_prefixes.get(domain, "Conversation")

        # Add primary ID if available
        if extracted_ids:
            # Try to find the most relevant ID for this domain
            primary_id_keys = {
                "query": ["query_id", "statement_id"],
                "job": ["job_id", "run_id"],
                "uc": ["table_name", "catalog", "schema"],
                "cluster": ["cluster_id"],
                "warehouse": ["warehouse_id"],
                "diagnostic": ["error_id", "issue_id"],
                "analytics": ["metric_name", "report_id"],
            }

            keys_to_try = primary_id_keys.get(domain, [])
            for key in keys_to_try:
                if key in extracted_ids:
                    value = extracted_ids[key]
                    return f"{prefix}: {value}"

        # Fallback to generic name
        return prefix
