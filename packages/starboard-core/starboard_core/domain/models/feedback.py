# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Domain models for user feedback on agent responses.

These models support Pattern 4: Feedback Collection.
All models are immutable and use frozen dataclasses/Pydantic models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class FeedbackRating(StrEnum):
    """
    User rating for agent response.

    Attributes:
        POSITIVE: User found the response helpful
        NEGATIVE: User found the response unhelpful
    """

    POSITIVE = "positive"
    NEGATIVE = "negative"


class FeedbackCategory(StrEnum):
    """
    Categories for negative feedback.

    Used to classify what went wrong with an agent response.

    Attributes:
        INACCURATE: Response contained incorrect information
        MISSING_INFO: Response was missing important details
        TOO_VAGUE: Response was not specific enough
        DIDNT_ANSWER: Response did not address the user's question
        TOO_LONG: Response was unnecessarily verbose
        WRONG_AGENT: User was routed to the wrong agent
        OTHER: Other unspecified issue
    """

    INACCURATE = "inaccurate"
    MISSING_INFO = "missing_info"
    TOO_VAGUE = "too_vague"
    DIDNT_ANSWER = "didnt_answer"
    TOO_LONG = "too_long"
    WRONG_AGENT = "wrong_agent"
    OTHER = "other"


@dataclass(frozen=True)
class FeedbackContext:
    """
    Rich context captured with feedback for analysis.

    This snapshot preserves all relevant information about the interaction
    to enable deep analysis of feedback patterns.

    Attributes:
        user_query: The user's original query
        agent_response: The agent's response that was rated
        conversation_history: Recent message history (tuples of role/content dicts)
        agent_version: Version of the agent that generated the response
        prompt_version: Version of the prompt template used
        model_used: LLM model identifier (e.g., "gpt-4")
        temperature: Temperature setting used for generation
        response_length: Length of the agent response in characters
        num_tool_calls: Number of tool calls made during response generation
        tool_names: Names of tools that were invoked
        had_next_steps: Whether the response included next step suggestions
        response_time_ms: Time taken to generate the response
        token_count: Total tokens used (input + output)
        cost_usd: Cost in USD for this response
        user_session_length: Number of messages in the conversation
        is_repeat_query: Whether this query is similar to a previous one
    """

    user_query: str
    agent_response: str
    conversation_history: tuple[dict[str, Any], ...]
    agent_version: str
    prompt_version: str
    model_used: str
    temperature: float
    response_length: int
    num_tool_calls: int
    tool_names: tuple[str, ...]
    had_next_steps: bool
    response_time_ms: float
    token_count: int
    cost_usd: float
    user_session_length: int
    is_repeat_query: bool


@dataclass(frozen=True)
class UserFeedback:
    """
    Complete user feedback record.

    Represents a single piece of user feedback on an agent response,
    including rating, optional categories, comments, and full context snapshot.

    Attributes:
        feedback_id: Unique identifier for this feedback
        conversation_id: ID of the conversation this feedback belongs to
        message_id: ID of the specific message being rated
        user_id: ID of the user providing feedback
        agent_name: Name of the agent that generated the response
        rating: Positive or negative rating
        categories: Optional categories for negative feedback
        comment: Optional free-text comment
        timestamp: When the feedback was submitted
        context_snapshot: Rich context about the interaction
    """

    feedback_id: UUID
    conversation_id: UUID
    message_id: UUID
    user_id: str
    agent_name: str
    rating: FeedbackRating
    categories: tuple[FeedbackCategory, ...] | None
    comment: str | None
    timestamp: datetime
    context_snapshot: FeedbackContext


@dataclass(frozen=True)
class AgentPerformanceReport:
    """
    Performance report based on user feedback.

    Aggregates feedback data for a specific agent over a time period.

    Attributes:
        agent_name: Name of the agent
        period_days: Number of days covered by this report
        total_feedback: Total number of feedback submissions
        positive_count: Number of positive ratings
        negative_count: Number of negative ratings
        satisfaction_rate: Ratio of positive feedback (0.0 to 1.0)
        negative_categories: Breakdown of negative feedback categories with counts
        generated_at: When this report was generated
    """

    agent_name: str
    period_days: int
    total_feedback: int
    positive_count: int
    negative_count: int
    satisfaction_rate: float
    negative_categories: dict[str, int]
    generated_at: datetime
