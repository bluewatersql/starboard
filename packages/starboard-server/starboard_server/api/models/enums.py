# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""API enums for message and event models.

The shared role/status/event enums are defined in the domain layer
(``starboard_server.domain.conversation.models``) and re-exported here so that
existing ``from ...api.models import X`` callers keep working. Feedback enums
are API-only and remain defined locally.
"""

from enum import StrEnum

from starboard_server.domain.conversation.models import (
    EventType,
    MessageRole,
    MessageStatus,
)

__all__ = [
    "EventType",
    "FeedbackCategoryEnum",
    "FeedbackRatingEnum",
    "MessageRole",
    "MessageStatus",
]


class FeedbackRatingEnum(StrEnum):
    """User feedback rating for agent responses."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class FeedbackCategoryEnum(StrEnum):
    """Categories for negative feedback."""

    INACCURATE = "inaccurate"
    TOO_VAGUE = "too_vague"
    TOO_VERBOSE = "too_verbose"
    IRRELEVANT = "irrelevant"
    MISSING_INFO = "missing_info"
    BAD_FORMAT = "bad_format"
    OTHER = "other"
