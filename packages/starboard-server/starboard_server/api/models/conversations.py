# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
API conversation models.

The canonical ``ConversationResponse``, ``ConversationMetadata``, and
``ConversationHistory`` definitions live in the domain layer
(``starboard_server.domain.conversation.models``) and are re-exported here.
``CreateConversationRequest`` and ``ConversationListItem`` are API-only request
models and remain defined locally.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from starboard_server.domain.conversation.models import (
    ConversationConfig,
    ConversationHistory,
    ConversationMetadata,
    ConversationResponse,
)

__all__ = [
    "ConversationHistory",
    "ConversationListItem",
    "ConversationMetadata",
    "ConversationResponse",
    "CreateConversationRequest",
]


class CreateConversationRequest(BaseModel):
    """
    Request to create a new conversation session.

    Note: user_id is now extracted from authentication middleware,
    not from the request body.

    Args:
        context: Initial context for the conversation (job_id, workspace, etc.).
        config: Conversation configuration (temperature, model, etc.).
        initial_message: Optional message to send immediately after creation.
        metadata: Optional metadata for the conversation.

    Examples:
        >>> # Minimal request
        >>> request = CreateConversationRequest()

        >>> # With initial message (UX vNext)
        >>> request = CreateConversationRequest(
        ...     initial_message="Analyze job performance for job 12345",
        ...     context={"job_id": "12345"},
        ...     metadata={"source": "homepage"}
        ... )

        >>> # Traditional request
        >>> request = CreateConversationRequest(
        ...     context={"workspace_id": "ws_abc"},
        ...     config=ConversationConfig(temperature=0.4)
        ... )
    """

    context: dict[str, Any] | None = Field(
        default=None,
        description="Initial context for the conversation",
    )
    config: ConversationConfig | None = Field(
        default=None,
        description="Conversation configuration",
    )
    initial_message: str | None = Field(
        default=None,
        min_length=1,
        max_length=10000,
        description="Optional initial message to send immediately after creation (UX vNext Phase 1)",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata for the conversation",
    )


class ConversationListItem(BaseModel):
    """
    Summary information for a conversation in a list.

    Args:
        conversation_id: Unique conversation identifier.
        user_id: User who owns the conversation.
        friendly_name: Human-readable conversation title.
        created_at: UTC timestamp when conversation was created.
        last_message_at: UTC timestamp of most recent message (optional).
        message_count: Total number of messages in the conversation.

    Examples:
        >>> item = ConversationListItem(
        ...     conversation_id="conv_abc123",
        ...     user_id="user_456",
        ...     friendly_name="Cost Analysis Session",
        ...     created_at=datetime.utcnow(),
        ...     last_message_at=datetime.utcnow(),
        ...     message_count=15
        ... )
    """

    conversation_id: str = Field(
        ...,
        description="Unique conversation identifier",
    )
    user_id: str = Field(
        ...,
        description="User who owns the conversation",
    )
    friendly_name: str = Field(
        ...,
        description="Human-readable conversation title",
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when conversation was created",
    )
    last_message_at: datetime | None = Field(
        None,
        description="UTC timestamp of most recent message",
    )
    message_count: int = Field(
        default=0,
        ge=0,
        description="Total number of messages",
    )
