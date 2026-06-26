# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Repository for conversation patterns data access.

Provides methods for storing and retrieving conversation pattern data:
- Agent handoffs (Pattern 3: Agent Routing)
- User feedback (Pattern 4: Feedback Collection)
- Suggestion interactions (Pattern 5: Agent Discovery)

Part of Phase 1: Foundation

Examples:
    >>> repo = ConversationPatternsRepository(db_client)
    >>>
    >>> # Save an agent handoff
    >>> await repo.save_handoff(
    ...     handoff_id="h123",
    ...     conversation_id="conv-456",
    ...     source_agent_id="query_optimizer",
    ...     target_agent_id="cost_analyzer",
    ...     capability_id="analyze_costs",
    ...     handoff_context={"warehouse_id": "prod"},
    ...     status="initiated",
    ... )
    >>>
    >>> # Record user feedback
    >>> await repo.save_feedback(
    ...     feedback_id="f789",
    ...     conversation_id="conv-456",
    ...     message_id="msg-012",
    ...     user_id="user-345",
    ...     agent_name="query_optimizer",
    ...     rating="positive",
    ...     categories=None,
    ...     comment="Very helpful!",
    ...     context_snapshot={},
    ... )
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol


class DatabaseClient(Protocol):
    """Protocol for database client operations."""

    async def execute(self, query: str, *params: Any) -> str:
        """Execute a query that doesn't return results (INSERT/UPDATE/DELETE).

        Args:
            query: SQL query with $1, $2, ... placeholders
            *params: Query parameters

        Returns:
            Status string (e.g., "INSERT 0 1")
        """
        ...

    async def fetch_one(self, query: str, *params: Any) -> dict[str, Any] | None:
        """Fetch a single row.

        Args:
            query: SQL query with $1, $2, ... placeholders
            *params: Query parameters

        Returns:
            Single row as dict or None if not found
        """
        ...

    async def fetch_all(self, query: str, *params: Any) -> list[dict[str, Any]]:
        """Fetch all rows.

        Args:
            query: SQL query with $1, $2, ... placeholders
            *params: Query parameters

        Returns:
            List of rows as dicts
        """
        ...


class ConversationPatternsRepository:
    """Repository for conversation patterns data.

    Provides data access methods for:
    - Agent handoffs (routing between agents)
    - User feedback (ratings and comments)
    - Suggestion interactions (agent discovery tracking)

    Attributes:
        db: Database client for executing queries

    Examples:
        >>> repo = ConversationPatternsRepository(postgres_client)
        >>>
        >>> # Track agent handoff
        >>> await repo.save_handoff(
        ...     handoff_id=str(uuid4()),
        ...     conversation_id="conv-123",
        ...     source_agent_id="optimizer",
        ...     target_agent_id="analyzer",
        ...     capability_id="cost_analysis",
        ...     handoff_context={},
        ...     status="initiated",
        ... )
        >>>
        >>> # Get handoff history
        >>> handoffs = await repo.get_conversation_handoffs("conv-123")
    """

    def __init__(self, db: DatabaseClient):
        """Initialize repository with database client.

        Args:
            db: Database client implementing DatabaseClient protocol
        """
        self.db = db

    # ==========================================
    # Agent Handoffs (Pattern 3: Agent Routing)
    # ==========================================

    async def save_handoff(
        self,
        handoff_id: str,
        conversation_id: str,
        source_agent_id: str,
        target_agent_id: str,
        capability_id: str | None,
        handoff_context: dict[str, Any],
        status: Literal["initiated", "completed", "failed"],
    ) -> None:
        """Save an agent handoff record.

        Records when a conversation is routed from one agent to another.

        Args:
            handoff_id: Unique handoff identifier
            conversation_id: Conversation being handed off
            source_agent_id: Agent initiating the handoff
            target_agent_id: Agent receiving the handoff
            capability_id: Capability/tool triggering the handoff (optional)
            handoff_context: Additional context for the handoff
            status: Current status of the handoff

        Examples:
            >>> await repo.save_handoff(
            ...     handoff_id="h-001",
            ...     conversation_id="conv-123",
            ...     source_agent_id="query_optimizer",
            ...     target_agent_id="cost_analyzer",
            ...     capability_id="analyze_warehouse_costs",
            ...     handoff_context={"warehouse_id": "prod_dw"},
            ...     status="initiated",
            ... )
        """
        query = """
            INSERT INTO agent_handoffs (
                id,
                conversation_id,
                source_agent_id,
                target_agent_id,
                capability_id,
                handoff_context,
                status,
                initiated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """

        await self.db.execute(
            query,
            handoff_id,
            conversation_id,
            source_agent_id,
            target_agent_id,
            capability_id,
            handoff_context,  # Will be stored as JSONB
            status,
            datetime.now(UTC),
        )

    async def complete_handoff(
        self,
        handoff_id: str,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Mark a handoff as complete or failed.

        Updates handoff status and records completion time.

        Args:
            handoff_id: Handoff to update
            success: Whether handoff succeeded
            error_message: Error details if failed (optional)

        Examples:
            >>> # Successful handoff
            >>> await repo.complete_handoff("h-001", success=True)
            >>>
            >>> # Failed handoff
            >>> await repo.complete_handoff(
            ...     "h-002",
            ...     success=False,
            ...     error_message="Target agent unavailable"
            ... )
        """
        status = "completed" if success else "failed"

        query = """
            UPDATE agent_handoffs
            SET
                status = $2,
                completed_at = $3,
                error_message = $4
            WHERE id = $1
        """

        await self.db.execute(
            query,
            handoff_id,
            status,
            datetime.now(UTC),
            error_message,
        )

    async def get_conversation_handoffs(
        self,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        """Get all handoffs for a conversation.

        Retrieves handoff history ordered by initiation time.

        Args:
            conversation_id: Conversation to query

        Returns:
            List of handoff records (newest first)

        Examples:
            >>> handoffs = await repo.get_conversation_handoffs("conv-123")
            >>> for h in handoffs:
            ...     print(f"{h['source_agent_id']} -> {h['target_agent_id']}")
        """
        query = """
            SELECT
                id,
                conversation_id,
                source_agent_id,
                target_agent_id,
                capability_id,
                handoff_context,
                status,
                initiated_at,
                completed_at,
                error_message
            FROM agent_handoffs
            WHERE conversation_id = $1
            ORDER BY initiated_at DESC
        """

        return await self.db.fetch_all(query, conversation_id)

    @staticmethod
    def _row_to_handoff(row: dict[str, Any]) -> Any:
        """Convert a database row to an AgentHandoff domain model.

        Args:
            row: Database row as dictionary

        Returns:
            AgentHandoff domain model
        """
        from uuid import UUID

        from starboard_server.services.coordination.handoff_manager import (
            AgentHandoff,
            HandoffStatus,
        )

        return AgentHandoff(
            handoff_id=UUID(row["id"]),
            conversation_id=row["conversation_id"],
            source_agent_id=row["source_agent_id"],
            target_agent_id=row["target_agent_id"],
            capability_id=row["capability_id"],
            status=HandoffStatus(row["status"]),
            handoff_context=row["handoff_context"] or {},
            initiated_at=row["initiated_at"],
            completed_at=row["completed_at"],
            failure_reason=row["error_message"],
        )

    async def get_handoff(self, handoff_id: Any) -> Any | None:
        """Get a handoff by ID.

        Retrieves a single handoff record.

        Args:
            handoff_id: UUID of handoff to retrieve

        Returns:
            AgentHandoff domain model if found, None otherwise

        Examples:
            >>> handoff = await repo.get_handoff(uuid4())
            >>> if handoff:
            ...     print(f"Status: {handoff.status}")
        """
        query = """
            SELECT
                id,
                conversation_id,
                source_agent_id,
                target_agent_id,
                capability_id,
                handoff_context,
                status,
                initiated_at,
                completed_at,
                error_message
            FROM agent_handoffs
            WHERE id = $1
        """

        row = await self.db.fetch_one(query, str(handoff_id))
        if not row:
            return None

        return self._row_to_handoff(row)

    async def get_handoffs_for_conversation(
        self,
        conversation_id: str,
    ) -> list[Any]:
        """Get all handoffs for a conversation as domain models.

        Returns handoffs as AgentHandoff domain models, ordered chronologically.

        Args:
            conversation_id: Conversation to query

        Returns:
            List of AgentHandoff domain models

        Examples:
            >>> handoffs = await repo.get_handoffs_for_conversation("conv-123")
            >>> for handoff in handoffs:
            ...     print(f"{handoff.source_agent_id} -> {handoff.target_agent_id}")
        """
        rows = await self.get_conversation_handoffs(conversation_id)
        return [self._row_to_handoff(row) for row in rows]

    async def save_handoff_model(self, handoff: Any) -> None:
        """Save an agent handoff domain model.

        Wrapper that accepts AgentHandoff domain model and calls save_handoff.

        Args:
            handoff: AgentHandoff domain model to save

        Examples:
            >>> handoff = AgentHandoff(...)
            >>> await repo.save_handoff_model(handoff)
        """
        await self.save_handoff(
            handoff_id=str(handoff.handoff_id),
            conversation_id=handoff.conversation_id,
            source_agent_id=handoff.source_agent_id,
            target_agent_id=handoff.target_agent_id,
            capability_id=handoff.capability_id,
            handoff_context=handoff.handoff_context,
            status=handoff.status.value,
        )

    async def update_handoff_status(
        self,
        handoff_id: Any,
        status: Any,
        failure_reason: str | None = None,
    ) -> None:
        """Update handoff status.

        Wrapper for complete_handoff that works with domain types.

        Args:
            handoff_id: UUID of handoff to update
            status: New HandoffStatus
            failure_reason: Failure reason if status is FAILED

        Examples:
            >>> await repo.update_handoff_status(
            ...     handoff_id=uuid4(),
            ...     status=HandoffStatus.COMPLETED,
            ...     failure_reason=None,
            ... )
        """
        from starboard_server.services.coordination.handoff_manager import HandoffStatus

        success = status == HandoffStatus.COMPLETED
        await self.complete_handoff(
            handoff_id=str(handoff_id),
            success=success,
            error_message=failure_reason,
        )

    # ================================================
    # User Feedback (Pattern 4: Feedback Collection)
    # ================================================

    async def save_feedback(
        self,
        feedback_id: str,
        conversation_id: str,
        message_id: str,
        user_id: str,
        agent_name: str,
        rating: Literal["positive", "negative"],
        categories: list[str] | None,
        comment: str | None,
        context_snapshot: dict[str, Any],
    ) -> None:
        """Save user feedback on an agent response.

        Records user satisfaction with agent responses for quality tracking.

        Args:
            feedback_id: Unique feedback identifier
            conversation_id: Conversation containing the message
            message_id: Specific message being rated
            user_id: User providing feedback
            agent_name: Agent that generated the response
            rating: User rating (positive/negative)
            categories: Feedback categories (e.g., ["too_vague", "helpful"])
            comment: Optional free-text comment
            context_snapshot: Snapshot of conversation context at feedback time

        Examples:
            >>> await repo.save_feedback(
            ...     feedback_id="fb-001",
            ...     conversation_id="conv-123",
            ...     message_id="msg-456",
            ...     user_id="user-789",
            ...     agent_name="query_optimizer",
            ...     rating="positive",
            ...     categories=["accurate", "helpful"],
            ...     comment="Great analysis!",
            ...     context_snapshot={"model": "gpt-4", "tokens": 150},
            ... )
        """
        query = """
            INSERT INTO user_feedback (
                id,
                conversation_id,
                message_id,
                user_id,
                agent_name,
                rating,
                categories,
                comment,
                context_snapshot,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """

        await self.db.execute(
            query,
            feedback_id,
            conversation_id,
            message_id,
            user_id,
            agent_name,
            rating,
            categories or [],  # Empty list if None
            comment,
            context_snapshot,  # Will be stored as JSONB
            datetime.now(UTC),
        )

    async def get_feedback_by_message(
        self,
        message_id: str,
    ) -> dict[str, Any] | None:
        """Get feedback for a specific message.

        Args:
            message_id: Message to query

        Returns:
            Feedback record or None if not found

        Examples:
            >>> feedback = await repo.get_feedback_by_message("msg-456")
            >>> if feedback:
            ...     print(f"Rating: {feedback['rating']}")
        """
        query = """
            SELECT
                id,
                conversation_id,
                message_id,
                user_id,
                agent_name,
                rating,
                categories,
                comment,
                context_snapshot,
                created_at
            FROM user_feedback
            WHERE message_id = $1
            LIMIT 1
        """

        return await self.db.fetch_one(query, message_id)

    async def get_agent_feedback_stats(
        self,
        agent_name: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """Get aggregate feedback stats for an agent.

        Calculates positive/negative counts and satisfaction rate.

        Args:
            agent_name: Agent to analyze
            days: Time window in days (default: 7)

        Returns:
            Stats dict with counts and satisfaction_rate

        Examples:
            >>> stats = await repo.get_agent_feedback_stats(
            ...     agent_name="query_optimizer",
            ...     days=7,
            ... )
            >>> print(f"Satisfaction: {stats['satisfaction_rate']:.1%}")
        """
        since = datetime.now(UTC) - timedelta(days=days)

        query = """
            SELECT
                COUNT(*) FILTER (WHERE rating = 'positive') as positive_count,
                COUNT(*) FILTER (WHERE rating = 'negative') as negative_count,
                COUNT(*) as total_count
            FROM user_feedback
            WHERE agent_name = $1 AND created_at >= $2
        """

        result = await self.db.fetch_one(query, agent_name, since)

        if not result or result["total_count"] == 0:
            return {
                "positive_count": 0,
                "negative_count": 0,
                "total_count": 0,
                "satisfaction_rate": 0.0,
            }

        return {
            "positive_count": result["positive_count"],
            "negative_count": result["negative_count"],
            "total_count": result["total_count"],
            "satisfaction_rate": result["positive_count"] / result["total_count"],
        }

    # ======================================================
    # Suggestion Interactions (Pattern 5: Agent Discovery)
    # ======================================================

    async def record_suggestion_interaction(
        self,
        interaction_id: str,
        suggestion_id: str,
        user_id: str,
        conversation_id: str,
        target_agent_id: str,
        action: Literal["presented", "clicked", "dismissed", "converted"],
    ) -> None:
        """Record user interaction with an agent suggestion.

        Tracks suggestion presentation and user engagement.

        Args:
            interaction_id: Unique interaction identifier
            suggestion_id: Suggestion being tracked
            user_id: User interacting with suggestion
            conversation_id: Conversation containing suggestion
            target_agent_id: Agent being suggested
            action: User action (presented/clicked/dismissed/converted)

        Examples:
            >>> # Record suggestion presentation
            >>> await repo.record_suggestion_interaction(
            ...     interaction_id="int-001",
            ...     suggestion_id="sug-123",
            ...     user_id="user-456",
            ...     conversation_id="conv-789",
            ...     target_agent_id="cost_analyzer",
            ...     action="presented",
            ... )
            >>>
            >>> # Record user click
            >>> await repo.record_suggestion_interaction(
            ...     interaction_id="int-002",
            ...     suggestion_id="sug-123",
            ...     user_id="user-456",
            ...     conversation_id="conv-789",
            ...     target_agent_id="cost_analyzer",
            ...     action="clicked",
            ... )
        """
        query = """
            INSERT INTO suggestion_interactions (
                id,
                suggestion_id,
                user_id,
                conversation_id,
                target_agent_id,
                action,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """

        await self.db.execute(
            query,
            interaction_id,
            suggestion_id,
            user_id,
            conversation_id,
            target_agent_id,
            action,
            datetime.now(UTC),
        )

    async def get_suggestion_metrics(
        self,
        target_agent_id: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """Get suggestion effectiveness metrics for an agent.

        Calculates presentation counts, click-through rate, and conversion rate.

        Args:
            target_agent_id: Agent to analyze
            days: Time window in days (default: 7)

        Returns:
            Metrics dict with counts and rates

        Examples:
            >>> metrics = await repo.get_suggestion_metrics(
            ...     target_agent_id="cost_analyzer",
            ...     days=7,
            ... )
            >>> print(f"CTR: {metrics['click_through_rate']:.1%}")
        """
        since = datetime.now(UTC) - timedelta(days=days)

        query = """
            SELECT
                COUNT(*) FILTER (WHERE action = 'presented') as presented_count,
                COUNT(*) FILTER (WHERE action = 'clicked') as clicked_count,
                COUNT(*) FILTER (WHERE action = 'converted') as converted_count,
                COUNT(DISTINCT user_id) as unique_users
            FROM suggestion_interactions
            WHERE target_agent_id = $1 AND created_at >= $2
        """

        result = await self.db.fetch_one(query, target_agent_id, since)

        if not result or result["presented_count"] == 0:
            return {
                "presented_count": 0,
                "clicked_count": 0,
                "converted_count": 0,
                "unique_users": 0,
                "click_through_rate": 0.0,
                "conversion_rate": 0.0,
            }

        presented = result["presented_count"]
        return {
            "presented_count": presented,
            "clicked_count": result["clicked_count"],
            "converted_count": result["converted_count"],
            "unique_users": result["unique_users"],
            "click_through_rate": result["clicked_count"] / presented,
            "conversion_rate": result["converted_count"] / presented,
        }
