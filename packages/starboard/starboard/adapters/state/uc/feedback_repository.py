# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unity Catalog native feedback repository (Phase 2 C2).

``UCFeedbackRepository`` mirrors :class:`SQLiteFeedbackRepository` over the UC
``user_feedback`` Delta table, backed by :class:`UCStorageAdapter`. Aggregate
statistics are computed Python-side over ``read`` results to avoid backend-
specific SQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from starboard_core.domain.models.feedback import (
    FeedbackCategory,
    FeedbackContext,
    FeedbackRating,
    UserFeedback,
)

from starboard.adapters.state.uc import _serde
from starboard.adapters.state.uc.tables import USER_FEEDBACK
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.infra.storage.uc_adapter import UCStorageAdapter

logger = get_logger(__name__)


def _serialize_context(context: FeedbackContext) -> dict[str, Any]:
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


def _deserialize_context(data: dict[str, Any]) -> FeedbackContext:
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


def _row_to_feedback(row: dict[str, Any]) -> UserFeedback:
    categories = None
    cats = _serde.loads(row.get("categories"), None)
    if cats:
        categories = tuple(FeedbackCategory(c) for c in cats)
    return UserFeedback(
        feedback_id=row["feedback_id"],
        conversation_id=row["conversation_id"],
        message_id=row["message_id"],
        user_id=row["user_id"],
        agent_name=row["agent_name"],
        rating=FeedbackRating(row["rating"]),
        categories=categories,
        comment=row.get("comment"),
        timestamp=_serde.parse_dt(row["created_at"]),
        context_snapshot=_deserialize_context(
            _serde.loads(row.get("context_snapshot"), {})
        ),
    )


class UCFeedbackRepository:
    """User feedback persisted to a Unity Catalog ``user_feedback`` Delta table.

    Args:
        adapter: A configured :class:`UCStorageAdapter`.
    """

    def __init__(self, adapter: UCStorageAdapter) -> None:
        self._adapter = adapter

    async def save(self, feedback: UserFeedback) -> None:
        """Persist a feedback record (upsert on ``feedback_id``)."""
        categories = (
            [c.value for c in feedback.categories] if feedback.categories else None
        )
        await self._adapter.upsert(
            USER_FEEDBACK,
            {
                "feedback_id": str(feedback.feedback_id),
                "conversation_id": str(feedback.conversation_id),
                "message_id": str(feedback.message_id),
                "user_id": feedback.user_id,
                "agent_name": feedback.agent_name,
                "rating": feedback.rating.value,
                "categories": _serde.dumps(categories),
                "comment": feedback.comment,
                "context_snapshot": _serde.dumps(
                    _serialize_context(feedback.context_snapshot)
                ),
                "created_at": feedback.timestamp,
            },
        )
        logger.debug("uc_feedback_saved", feedback_id=str(feedback.feedback_id))

    async def get_by_message(self, message_id: str) -> UserFeedback | None:
        """Get feedback for a specific message."""
        row = await self._adapter.read_one(USER_FEEDBACK, {"message_id": message_id})
        return _row_to_feedback(row) if row else None

    async def get_by_conversation(self, conversation_id: str) -> list[UserFeedback]:
        """Get all feedback for a conversation, newest first."""
        rows = await self._adapter.read(
            USER_FEEDBACK,
            filters={"conversation_id": conversation_id},
            order_by="created_at DESC",
        )
        return [_row_to_feedback(r) for r in rows]

    async def get_agent_feedback_stats(
        self,
        agent_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, Any]:
        """Aggregate feedback stats for an agent over a time range (Python-side)."""
        rows = await self._adapter.read(USER_FEEDBACK, filters={"agent_name": agent_name})
        in_range = [
            r for r in rows if start_date <= _serde.parse_dt(r["created_at"]) <= end_date
        ]
        total = len(in_range)
        if total == 0:
            return {
                "total_feedback": 0,
                "positive_count": 0,
                "negative_count": 0,
                "satisfaction_rate": 0.0,
            }
        positive = sum(1 for r in in_range if r.get("rating") == "positive")
        negative = sum(1 for r in in_range if r.get("rating") == "negative")
        return {
            "total_feedback": total,
            "positive_count": positive,
            "negative_count": negative,
            "satisfaction_rate": positive / total if total else 0.0,
        }

    async def get_negative_feedback_categories(
        self,
        agent_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, int]:
        """Breakdown of negative-feedback categories over a time range."""
        rows = await self._adapter.read(USER_FEEDBACK, filters={"agent_name": agent_name})
        counts: dict[str, int] = {}
        for r in rows:
            if r.get("rating") != "negative":
                continue
            if not (start_date <= _serde.parse_dt(r["created_at"]) <= end_date):
                continue
            for cat in _serde.loads(r.get("categories"), []) or []:
                counts[cat] = counts.get(cat, 0) + 1
        return counts
