"""Feedback service for collecting and analyzing user feedback on agent responses.

Provides business logic for:
- Submitting user feedback with context enrichment
- Building rich context snapshots from conversation history
- Generating agent performance reports
- Special handling for negative feedback

Part of Pattern 4: Feedback Collection

Examples:
    >>> service = FeedbackService(feedback_repo, conversation_repo)
    >>>
    >>> # Submit positive feedback
    >>> feedback = await service.submit_feedback(
    ...     conversation_id="conv-123",
    ...     message_id="msg-456",
    ...     rating=FeedbackRating.POSITIVE,
    ...     comment="Very helpful!",
    ... )
    >>>
    >>> # Get performance report
    >>> report = await service.get_agent_performance(
    ...     agent_name="query_optimizer",
    ...     days=7,
    ... )
    >>> print(f"Satisfaction rate: {report.satisfaction_rate:.1%}")
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from starboard_core.domain.models.feedback import (
    AgentPerformanceReport,
    FeedbackCategory,
    FeedbackContext,
    FeedbackRating,
    UserFeedback,
)
from starboard_core.models.conversation import Conversation, Message

from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_core.repositories.conversation import ConversationRepository

    from starboard_server.repositories.feedback_repository import (
        PostgresFeedbackRepository as FeedbackRepository,
    )

logger = get_logger(__name__)


class FeedbackService:
    """
    Business logic for feedback collection and processing.

    Coordinates feedback submission with context enrichment and
    provides performance analytics based on user feedback.

    Attributes:
        repository: FeedbackRepository for persistence
        conversation_repository: ConversationRepository for context retrieval

    Examples:
        >>> service = FeedbackService(feedback_repo, conversation_repo)
        >>> feedback = await service.submit_feedback(
        ...     conversation_id="conv-123",
        ...     message_id="msg-456",
        ...     rating=FeedbackRating.POSITIVE,
        ... )
    """

    def __init__(
        self,
        repository: FeedbackRepository,
        conversation_repository: ConversationRepository,
    ):
        """
        Initialize feedback service.

        Args:
            repository: Feedback repository for persistence
            conversation_repository: Conversation repository for context
        """
        self.repository = repository
        self.conversation_repository = conversation_repository

    async def submit_feedback(
        self,
        conversation_id: str,
        message_id: str,
        rating: FeedbackRating,
        categories: list[FeedbackCategory] | None = None,
        comment: str | None = None,
    ) -> UserFeedback:
        """
        Submit user feedback for a message.

        Retrieves the conversation context, builds a rich context snapshot,
        creates a feedback record, and saves it to the repository. Triggers
        special handling for negative feedback.

        Args:
            conversation_id: ID of the conversation containing the message
            message_id: ID of the message being rated
            rating: User's rating (positive/negative)
            categories: Optional list of feedback categories (for negative feedback)
            comment: Optional free-text comment from user

        Returns:
            UserFeedback record that was saved

        Raises:
            ValueError: If conversation or message not found

        Examples:
            >>> feedback = await service.submit_feedback(
            ...     conversation_id="conv-123",
            ...     message_id="msg-456",
            ...     rating=FeedbackRating.POSITIVE,
            ...     comment="Great analysis!",
            ... )
        """
        # Get conversation
        conversation = await self.conversation_repository.get(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Find the message being rated
        message = self._find_message(conversation, message_id)
        if message is None:
            raise ValueError(f"Message {message_id} not found in conversation")

        # Build context snapshot
        context_snapshot = await self._build_context_snapshot(
            message=message,
            conversation=conversation,
        )

        # Create feedback record
        feedback = UserFeedback(
            feedback_id=uuid4(),
            conversation_id=UUID(conversation_id),
            message_id=UUID(message_id),
            user_id=conversation.user_id,
            agent_name=message.role,  # Simplified - could be extracted from metadata
            rating=rating,
            categories=tuple(categories) if categories else None,
            comment=comment,
            timestamp=datetime.now(UTC),
            context_snapshot=context_snapshot,
        )

        # Save to repository
        await self.repository.save(feedback)

        # Log for analytics
        logger.debug(
            "user_feedback_submitted",
            feedback_id=feedback.feedback_id,
            message_id=message_id,
            rating=rating.value,
            has_comment=comment is not None,
            num_categories=len(categories) if categories else 0,
        )

        # If negative feedback, trigger follow-up
        if rating == FeedbackRating.NEGATIVE:
            await self._handle_negative_feedback(feedback)

        return feedback

    async def get_agent_performance(
        self,
        agent_name: str,
        days: int = 7,
    ) -> AgentPerformanceReport:
        """
        Get performance report based on feedback.

        Aggregates feedback statistics and negative feedback categories
        over the specified time period to generate a performance report.

        Args:
            agent_name: Name of the agent to analyze
            days: Number of days to include in report (default: 7)

        Returns:
            AgentPerformanceReport with aggregated statistics

        Examples:
            >>> report = await service.get_agent_performance(
            ...     agent_name="query_optimizer",
            ...     days=30,
            ... )
            >>> print(f"Satisfaction: {report.satisfaction_rate:.1%}")
        """
        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=days)

        # Get aggregate stats
        stats = await self.repository.get_agent_feedback_stats(
            agent_name=agent_name,
            start_date=start_date,
            end_date=end_date,
        )

        # Get negative feedback breakdown
        negative_categories = await self.repository.get_negative_feedback_categories(
            agent_name=agent_name,
            start_date=start_date,
            end_date=end_date,
        )

        return AgentPerformanceReport(
            agent_name=agent_name,
            period_days=days,
            total_feedback=stats["total_feedback"],
            positive_count=stats["positive_count"],
            negative_count=stats["negative_count"],
            satisfaction_rate=stats["satisfaction_rate"],
            negative_categories=negative_categories,
            generated_at=datetime.now(UTC),
        )

    async def _build_context_snapshot(
        self,
        message: Message,
        conversation: Conversation,
    ) -> FeedbackContext:
        """
        Build rich context snapshot for feedback.

        Extracts metadata from the agent message and constructs conversation
        history to provide comprehensive context for feedback analysis.

        Args:
            message: The message being rated
            conversation: The full conversation

        Returns:
            FeedbackContext with rich metadata
        """
        # Get previous messages for history (before the rated message)
        history = self._get_message_history(
            conversation, message.metadata.get("id", "")
        )

        # Extract agent metadata from message
        metadata = message.metadata or {}

        return FeedbackContext(
            user_query=self._get_user_query(history),
            agent_response=message.content,
            conversation_history=tuple(
                {"role": m.role, "content": m.content[:200]}  # Truncate for storage
                for m in history
            ),
            agent_version=metadata.get("agent_version", "unknown"),
            prompt_version=metadata.get("prompt_version", "unknown"),
            model_used=metadata.get("model", "unknown"),
            temperature=metadata.get("temperature", 0.0),
            response_length=len(message.content),
            num_tool_calls=metadata.get("num_tool_calls", 0),
            tool_names=tuple(metadata.get("tool_names", [])),
            had_next_steps=False,  # Could check if next_steps exist
            response_time_ms=metadata.get("response_time_ms", 0.0),
            token_count=metadata.get("token_count", 0),
            cost_usd=metadata.get("cost_usd", 0.0),
            user_session_length=len(history),
            is_repeat_query=self._is_repeat_query(history),
        )

    def _find_message(
        self,
        conversation: Conversation,
        message_id: str,
    ) -> Message | None:
        """
        Find a message in the conversation by ID.

        Args:
            conversation: Conversation to search
            message_id: ID of message to find (stored in metadata)

        Returns:
            Message if found, None otherwise
        """
        for message in conversation.messages:
            if message.metadata.get("id") == message_id:
                return message
        return None

    def _get_message_history(
        self,
        conversation: Conversation,
        message_id: str,
        limit: int = 5,
    ) -> list[Message]:
        """
        Get message history before the specified message.

        Args:
            conversation: Conversation containing messages
            message_id: ID of the message to get history before (stored in metadata)
            limit: Maximum number of historical messages to return

        Returns:
            List of messages before the specified message (up to limit)
        """
        # Find the index of the message being rated
        message_index = None
        for i, msg in enumerate(conversation.messages):
            if msg.metadata.get("id") == message_id:
                message_index = i
                break

        if message_index is None:
            return []

        # Return messages before this one (up to limit)
        start_index = max(0, message_index - limit)
        return conversation.messages[start_index:message_index]

    def _get_user_query(self, history: list[Message]) -> str:
        """
        Extract the user query that led to this agent response.

        Finds the most recent user message in the history.

        Args:
            history: List of previous messages

        Returns:
            User query content or "Unknown" if not found
        """
        # Find the most recent user message before this agent message
        for msg in reversed(history):
            if msg.role == "user":
                return msg.content
        return "Unknown"

    def _is_repeat_query(self, history: list[Message]) -> bool:
        """
        Check if user query is similar to a previous one.

        Uses simple word overlap to detect repeat queries. Could be
        enhanced with embedding-based similarity in the future.

        Args:
            history: List of previous messages

        Returns:
            True if the last query is similar to a previous one
        """
        # Simple implementation - could use embedding similarity
        user_messages = [m for m in history if m.role == "user"]

        if len(user_messages) < 2:
            return False

        # Check last two user messages for similarity
        last_query = user_messages[-1].content.lower()
        prev_query = user_messages[-2].content.lower()

        # Simple word overlap check
        last_words = set(last_query.split())
        prev_words = set(prev_query.split())

        overlap = len(last_words & prev_words)
        total = len(last_words | prev_words)

        similarity = overlap / total if total > 0 else 0.0

        return similarity > 0.6

    async def _handle_negative_feedback(self, feedback: UserFeedback) -> None:
        """
        Handle negative feedback with follow-up actions.

        Logs negative feedback for immediate attention and checks for
        specific categories that might trigger automatic retry or
        escalation.

        Args:
            feedback: The negative feedback record
        """
        # Log for immediate attention
        logger.warning(
            "negative_feedback_received",
            feedback_id=feedback.feedback_id,
            agent_name=feedback.agent_name,
            categories=(
                [cat.value for cat in feedback.categories]
                if feedback.categories
                else []
            ),
            comment=feedback.comment,
        )

        # Check if we should offer to retry
        if feedback.categories and FeedbackCategory.DIDNT_ANSWER in feedback.categories:
            # Could trigger automatic retry with refined prompt
            logger.debug(
                "negative_feedback_retry_candidate",
                feedback_id=feedback.feedback_id,
            )
