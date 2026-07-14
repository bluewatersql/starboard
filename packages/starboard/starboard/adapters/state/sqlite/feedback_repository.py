# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
SQLite-specific feedback repository implementation.

Provides CRUD operations for feedback data using aiosqlite.
Follows the adapter pattern for database-specific implementations.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

import aiosqlite
from starboard_core.domain.models.feedback import (
    FeedbackCategory,
    FeedbackContext,
    FeedbackRating,
    UserFeedback,
)

from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class SQLiteFeedbackRepository:
    """
    SQLite-specific repository for user feedback persistence.

    Handles saving and retrieving user feedback on agent responses
    using aiosqlite with SQLite-specific SQL syntax.

    Attributes:
        db: aiosqlite.Connection instance
    """

    def __init__(self, db_conn: aiosqlite.Connection) -> None:
        """
        Initialize the SQLite feedback repository.

        Args:
            db_conn: aiosqlite.Connection instance
        """
        self.db = db_conn

    async def save(self, feedback: UserFeedback) -> None:
        """
        Save user feedback to the database.

        Args:
            feedback: UserFeedback record to save
        """
        query = """
        INSERT INTO user_feedback (
            feedback_id,
            conversation_id,
            message_id,
            user_id,
            agent_name,
            rating,
            categories,
            comment,
            context_snapshot,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        # Serialize categories
        categories_list = (
            [cat.value for cat in feedback.categories] if feedback.categories else None
        )

        # Serialize context snapshot to JSON
        context_dict = self._serialize_context(feedback.context_snapshot)

        await self.db.execute(
            query,
            (
                str(feedback.feedback_id),
                str(feedback.conversation_id),
                str(feedback.message_id),
                feedback.user_id,
                feedback.agent_name,
                feedback.rating.value,
                json.dumps(categories_list) if categories_list else None,
                feedback.comment,
                json.dumps(context_dict),
                feedback.timestamp.isoformat(),
            ),
        )
        await self.db.commit()

        logger.debug(
            "feedback_saved",
            feedback_id=str(feedback.feedback_id),
            message_id=str(feedback.message_id),
            rating=feedback.rating.value,
            agent_name=feedback.agent_name,
        )

    async def get_by_message(self, message_id: str) -> UserFeedback | None:
        """
        Get feedback for a specific message.

        Args:
            message_id: The message ID to retrieve feedback for

        Returns:
            UserFeedback if found, None otherwise
        """
        query = """
        SELECT
            feedback_id,
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
        WHERE message_id = ?
        """

        async with self.db.execute(query, (message_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        # Convert tuple to dict for _row_to_feedback
        columns = [
            "feedback_id",
            "conversation_id",
            "message_id",
            "user_id",
            "agent_name",
            "rating",
            "categories",
            "comment",
            "context_snapshot",
            "created_at",
        ]
        record = dict(zip(columns, row))

        return self._row_to_feedback(record)

    async def get_by_conversation(self, conversation_id: str) -> list[UserFeedback]:
        """
        Get all feedback for a conversation.

        Args:
            conversation_id: The conversation ID to retrieve feedback for

        Returns:
            List of UserFeedback records, ordered by creation time (newest first)
        """
        query = """
        SELECT
            feedback_id,
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
        WHERE conversation_id = ?
        ORDER BY created_at DESC
        """

        async with self.db.execute(query, (conversation_id,)) as cursor:
            rows = await cursor.fetchall()

        # Convert tuples to dicts for _row_to_feedback
        columns = [
            "feedback_id",
            "conversation_id",
            "message_id",
            "user_id",
            "agent_name",
            "rating",
            "categories",
            "comment",
            "context_snapshot",
            "created_at",
        ]
        records = [dict(zip(columns, row)) for row in rows]

        return [self._row_to_feedback(record) for record in records]

    async def get_agent_feedback_stats(
        self,
        agent_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, Any]:
        """
        Get aggregate feedback statistics for an agent.

        Args:
            agent_name: Name of the agent
            start_date: Start of time range
            end_date: End of time range

        Returns:
            Dictionary with total_feedback, positive_count, negative_count, satisfaction_rate
        """
        query = """
        SELECT
            COUNT(*) as total_feedback,
            SUM(CASE WHEN rating = 'positive' THEN 1 ELSE 0 END) as positive_count,
            SUM(CASE WHEN rating = 'negative' THEN 1 ELSE 0 END) as negative_count,
            CAST(SUM(CASE WHEN rating = 'positive' THEN 1 ELSE 0 END) AS REAL) /
                NULLIF(COUNT(*), 0) as satisfaction_rate
        FROM user_feedback
        WHERE agent_name = ?
          AND created_at BETWEEN ? AND ?
        """

        async with self.db.execute(
            query,
            (agent_name, start_date.isoformat(), end_date.isoformat()),
        ) as cursor:
            row = await cursor.fetchone()

        if not row or row[0] == 0:
            return {
                "total_feedback": 0,
                "positive_count": 0,
                "negative_count": 0,
                "satisfaction_rate": 0.0,
            }

        return {
            "total_feedback": row[0],
            "positive_count": row[1],
            "negative_count": row[2],
            "satisfaction_rate": float(row[3] or 0.0),
        }

    async def get_negative_feedback_categories(
        self,
        agent_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, int]:
        """
        Get breakdown of negative feedback categories.

        Note: SQLite doesn't have UNNEST, so we parse JSON arrays in Python.

        Args:
            agent_name: Name of the agent
            start_date: Start of time range
            end_date: End of time range

        Returns:
            Dictionary mapping category name to count
        """
        query = """
        SELECT categories
        FROM user_feedback
        WHERE agent_name = ?
          AND rating = 'negative'
          AND created_at BETWEEN ? AND ?
          AND categories IS NOT NULL
        """

        async with self.db.execute(
            query,
            (agent_name, start_date.isoformat(), end_date.isoformat()),
        ) as cursor:
            rows = await cursor.fetchall()

        # Count categories in Python (SQLite doesn't have UNNEST)
        category_counts: dict[str, int] = {}
        for (categories_json,) in rows:
            if categories_json:
                categories = json.loads(categories_json)
                for category in categories:
                    category_counts[category] = category_counts.get(category, 0) + 1

        return category_counts

    def _row_to_feedback(self, row: dict) -> UserFeedback:
        """
        Convert database row to UserFeedback domain model.

        Args:
            row: Database row as dictionary

        Returns:
            UserFeedback instance
        """
        # Deserialize categories
        categories = None
        if row["categories"]:
            categories_list = json.loads(row["categories"])
            categories = tuple(FeedbackCategory(cat) for cat in categories_list)

        # Deserialize context snapshot
        context_data = row["context_snapshot"]
        if isinstance(context_data, str):
            context_data = json.loads(context_data)

        context_snapshot = self._deserialize_context(context_data)

        # Parse ISO8601 timestamp
        timestamp = datetime.fromisoformat(row["created_at"])

        return UserFeedback(
            feedback_id=row["feedback_id"],
            conversation_id=row["conversation_id"],
            message_id=row["message_id"],
            user_id=row["user_id"],
            agent_name=row["agent_name"],
            rating=FeedbackRating(row["rating"]),
            categories=categories,
            comment=row["comment"],
            timestamp=timestamp,
            context_snapshot=context_snapshot,
        )

    def _serialize_context(self, context: FeedbackContext) -> dict[str, Any]:
        """
        Serialize FeedbackContext to JSON-compatible dictionary.

        Args:
            context: FeedbackContext to serialize

        Returns:
            Dictionary representation
        """
        return {
            "user_query": context.user_query,
            "agent_response": context.agent_response,
            "conversation_history": list(context.conversation_history),
            "agent_version": context.agent_version,
            "prompt_version": context.prompt_version,
            "model_used": context.model_used,
            "temperature": context.temperature,
            "response_length": context.response_length,
            "num_tool_calls": context.num_tool_calls,
            "tool_names": list(context.tool_names),
            "had_next_steps": context.had_next_steps,
            "response_time_ms": context.response_time_ms,
            "token_count": context.token_count,
            "cost_usd": context.cost_usd,
            "user_session_length": context.user_session_length,
            "is_repeat_query": context.is_repeat_query,
        }

    def _deserialize_context(self, data: dict[str, Any]) -> FeedbackContext:
        """
        Deserialize JSON dictionary to FeedbackContext.

        Args:
            data: Dictionary from JSON

        Returns:
            FeedbackContext instance
        """
        return FeedbackContext(
            user_query=data["user_query"],
            agent_response=data["agent_response"],
            conversation_history=tuple(data.get("conversation_history", [])),
            agent_version=data["agent_version"],
            prompt_version=data["prompt_version"],
            model_used=data["model_used"],
            temperature=data["temperature"],
            response_length=data["response_length"],
            num_tool_calls=data["num_tool_calls"],
            tool_names=tuple(data.get("tool_names", [])),
            had_next_steps=data["had_next_steps"],
            response_time_ms=data["response_time_ms"],
            token_count=data["token_count"],
            cost_usd=data["cost_usd"],
            user_session_length=data["user_session_length"],
            is_repeat_query=data["is_repeat_query"],
        )
