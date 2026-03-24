"""
API feedback models.

Models for user feedback on agent responses:
- SubmitFeedbackRequest: Request to submit feedback
- FeedbackResponse: Response after submitting feedback

Note: FeedbackRatingEnum and FeedbackCategoryEnum are in enums.py

Extracted from models.py for better organization.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .enums import FeedbackCategoryEnum, FeedbackRatingEnum


class SubmitFeedbackRequest(BaseModel):
    """
    Request to submit user feedback on an agent response.

    Args:
        message_id: ID of the message being rated
        rating: User's rating (positive/negative)
        categories: Optional categories for negative feedback
        comment: Optional free-text comment

    Examples:
        >>> request = SubmitFeedbackRequest(
        ...     message_id="msg_123",
        ...     rating="positive"
        ... )
        >>> request_negative = SubmitFeedbackRequest(
        ...     message_id="msg_456",
        ...     rating="negative",
        ...     categories=["inaccurate", "too_vague"],
        ...     comment="Not specific enough"
        ... )
    """

    message_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="ID of the message being rated",
    )
    rating: FeedbackRatingEnum = Field(
        ...,
        description="User's rating (positive or negative)",
    )
    categories: list[FeedbackCategoryEnum] | None = Field(
        default=None,
        description="Categories for negative feedback (required for negative rating)",
    )
    comment: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional free-text comment",
    )


class FeedbackResponse(BaseModel):
    """
    Response after submitting feedback.

    Args:
        feedback_id: Unique identifier for the feedback
        conversation_id: ID of the conversation
        message_id: ID of the message that was rated
        rating: User's rating
        categories: Categories for negative feedback (if any)
        comment: User's comment (if any)
        timestamp: When feedback was submitted

    Examples:
        >>> response = FeedbackResponse(
        ...     feedback_id="fb_abc123",
        ...     conversation_id="conv_456",
        ...     message_id="msg_789",
        ...     rating="positive",
        ...     categories=None,
        ...     comment=None,
        ...     timestamp=datetime.now()
        ... )
    """

    feedback_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique identifier for the feedback",
    )
    conversation_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="ID of the conversation",
    )
    message_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="ID of the message that was rated",
    )
    rating: FeedbackRatingEnum = Field(
        ...,
        description="User's rating",
    )
    categories: list[FeedbackCategoryEnum] | None = Field(
        default=None,
        description="Categories for negative feedback (if any)",
    )
    comment: str | None = Field(
        default=None,
        description="User's comment (if any)",
    )
    timestamp: datetime = Field(
        ...,
        description="When feedback was submitted",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata",
    )
