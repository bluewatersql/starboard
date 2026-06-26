# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Agent handoff manager for multi-agent routing.

Phase 3 Component 3: Handoff Manager & Persistence

Manages agent-to-agent handoffs, tracking lifecycle and preserving context
across agent transitions. Prevents circular routing and ensures graceful
degradation on failures.

Examples:
    >>> from starboard_server.services.coordination.handoff_manager import HandoffManager
    >>> from starboard_server.repositories import conversation_patterns_repository
    >>>
    >>> manager = HandoffManager(repository=conversation_patterns_repository)
    >>>
    >>> # Initiate handoff
    >>> handoff = await manager.initiate_handoff(
    ...     conversation_id="conv_123",
    ...     source_agent_id="query_optimizer",
    ...     target_agent_id="performance_analyzer",
    ...     capability_id="identify_slow_queries",
    ...     handoff_context={"warehouse_id": "prod_dw"},
    ... )
    >>>
    >>> # Complete handoff
    >>> await manager.complete_handoff(handoff.handoff_id, success=True)
    >>>
    >>> # Check for circular routing
    >>> is_circular = await manager.is_circular_routing("conv_123", max_handoffs=3)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class HandoffStatus(StrEnum):
    """Status of agent handoff.

    Attributes:
        INITIATED: Handoff initiated, target agent starting work
        COMPLETED: Handoff completed successfully
        FAILED: Handoff failed (target unavailable, error, etc.)
    """

    INITIATED = "initiated"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentHandoff:
    """Represents an agent-to-agent handoff.

    Captures the complete lifecycle of a handoff, from initiation through
    completion or failure. Preserves context needed for seamless transitions.

    Attributes:
        handoff_id: Unique identifier for handoff
        conversation_id: ID of conversation being handed off
        source_agent_id: ID of agent initiating handoff
        target_agent_id: ID of agent receiving handoff
        capability_id: Specific capability being invoked (optional)
        status: Current status of handoff
        handoff_context: Context to pass to target agent
        initiated_at: When handoff was initiated
        completed_at: When handoff completed (None if in progress)
        failure_reason: Reason for failure (None if successful)

    Examples:
        >>> handoff = AgentHandoff(
        ...     handoff_id=uuid4(),
        ...     conversation_id="conv_123",
        ...     source_agent_id="query_optimizer",
        ...     target_agent_id="performance_analyzer",
        ...     capability_id="identify_slow_queries",
        ...     status=HandoffStatus.INITIATED,
        ...     handoff_context={"warehouse_id": "prod_dw"},
        ...     initiated_at=datetime.utcnow(),
        ...     completed_at=None,
        ...     failure_reason=None,
        ... )
    """

    handoff_id: UUID
    conversation_id: str
    source_agent_id: str
    target_agent_id: str
    capability_id: str | None
    status: HandoffStatus
    handoff_context: dict[str, Any]
    initiated_at: datetime
    completed_at: datetime | None
    failure_reason: str | None


class HandoffManager:
    """Manages agent-to-agent handoffs.

    The handoff manager coordinates transitions between agents, ensuring
    context is preserved and handoffs are tracked. Prevents circular routing
    and handles failures gracefully.

    Attributes:
        repository: Repository for persisting handoffs

    Examples:
        >>> manager = HandoffManager(repository=repo)
        >>>
        >>> # Initiate handoff
        >>> handoff = await manager.initiate_handoff(
        ...     conversation_id="conv_123",
        ...     source_agent_id="agent1",
        ...     target_agent_id="agent2",
        ...     capability_id="capability_x",
        ...     handoff_context={"key": "value"},
        ... )
        >>>
        >>> # Complete handoff
        >>> await manager.complete_handoff(handoff.handoff_id, success=True)
    """

    def __init__(self, repository: Any) -> None:
        """Initialize handoff manager.

        Args:
            repository: ConversationPatternsRepository for persistence
        """
        self.repository = repository

    async def initiate_handoff(
        self,
        conversation_id: str,
        source_agent_id: str,
        target_agent_id: str,
        capability_id: str | None,
        handoff_context: dict[str, Any],
    ) -> AgentHandoff:
        """Initiate a handoff from one agent to another.

        Creates a new handoff record, persists it, and returns the handoff
        for tracking.

        Args:
            conversation_id: ID of conversation being handed off
            source_agent_id: ID of agent initiating handoff
            target_agent_id: ID of agent receiving handoff
            capability_id: Specific capability being invoked (optional)
            handoff_context: Context to pass to target agent

        Returns:
            AgentHandoff record with INITIATED status

        Examples:
            >>> handoff = await manager.initiate_handoff(
            ...     conversation_id="conv_123",
            ...     source_agent_id="query_optimizer",
            ...     target_agent_id="performance_analyzer",
            ...     capability_id="identify_slow_queries",
            ...     handoff_context={"warehouse_id": "prod_dw"},
            ... )
            >>> handoff.status
            HandoffStatus.INITIATED
        """
        handoff = AgentHandoff(
            handoff_id=uuid4(),
            conversation_id=conversation_id,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            capability_id=capability_id,
            status=HandoffStatus.INITIATED,
            handoff_context=handoff_context,
            initiated_at=datetime.now(UTC),
            completed_at=None,
            failure_reason=None,
        )

        # Persist handoff
        await self.repository.save_handoff_model(handoff)

        logger.debug(
            "handoff_initiated",
            handoff_id=str(handoff.handoff_id),
            conversation_id=conversation_id,
            source_agent=source_agent_id,
            target_agent=target_agent_id,
            capability_id=capability_id,
        )

        return handoff

    async def complete_handoff(
        self,
        handoff_id: UUID,
        success: bool,
        failure_reason: str | None = None,
    ) -> None:
        """Mark a handoff as completed or failed.

        Args:
            handoff_id: ID of handoff to complete
            success: True if successful, False if failed
            failure_reason: Reason for failure (required if success=False)

        Examples:
            >>> # Success
            >>> await manager.complete_handoff(handoff_id, success=True)
            >>>
            >>> # Failure
            >>> await manager.complete_handoff(
            ...     handoff_id,
            ...     success=False,
            ...     failure_reason="Target agent unavailable",
            ... )
        """
        status = HandoffStatus.COMPLETED if success else HandoffStatus.FAILED

        await self.repository.update_handoff_status(
            handoff_id=handoff_id,
            status=status,
            failure_reason=failure_reason,
        )

        logger.debug(
            "handoff_completed",
            handoff_id=str(handoff_id),
            status=status.value,
            success=success,
            failure_reason=failure_reason,
        )

    async def get_handoff(self, handoff_id: UUID) -> AgentHandoff | None:
        """Retrieve handoff by ID.

        Args:
            handoff_id: ID of handoff to retrieve

        Returns:
            AgentHandoff if found, None otherwise

        Examples:
            >>> handoff = await manager.get_handoff(handoff_id)
            >>> if handoff:
            ...     print(f"Status: {handoff.status}")
        """
        return await self.repository.get_handoff(handoff_id)

    async def get_conversation_handoffs(
        self,
        conversation_id: str,
    ) -> list[AgentHandoff]:
        """Retrieve all handoffs for a conversation.

        Returns handoffs in chronological order (oldest first).

        Args:
            conversation_id: ID of conversation

        Returns:
            List of handoffs (may be empty)

        Examples:
            >>> handoffs = await manager.get_conversation_handoffs("conv_123")
            >>> for handoff in handoffs:
            ...     print(f"{handoff.source_agent_id} -> {handoff.target_agent_id}")
        """
        return await self.repository.get_handoffs_for_conversation(conversation_id)

    async def get_handoff_count(self, conversation_id: str) -> int:
        """Count handoffs for a conversation.

        Used for circular routing detection.

        Args:
            conversation_id: ID of conversation

        Returns:
            Number of handoffs (0 if none)

        Examples:
            >>> count = await manager.get_handoff_count("conv_123")
            >>> print(f"Handoff count: {count}")
        """
        handoffs = await self.get_conversation_handoffs(conversation_id)
        return len(handoffs)

    async def is_circular_routing(
        self,
        conversation_id: str,
        max_handoffs: int = 3,
    ) -> bool:
        """Check if conversation has hit circular routing limit.

        Prevents infinite routing loops by limiting handoffs per conversation.

        Args:
            conversation_id: ID of conversation
            max_handoffs: Maximum allowed handoffs (default: 3)

        Returns:
            True if at/above limit, False otherwise

        Examples:
            >>> # Check before initiating handoff
            >>> if await manager.is_circular_routing("conv_123"):
            ...     print("Max handoffs reached, cannot route")
            ... else:
            ...     # Safe to route
            ...     await manager.initiate_handoff(...)
        """
        count = await self.get_handoff_count(conversation_id)
        return count >= max_handoffs
