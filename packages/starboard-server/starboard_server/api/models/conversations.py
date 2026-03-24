"""
API conversation models.

Models for conversation management:
- CreateConversationRequest: Request to create a conversation
- ConversationResponse: Response after creating a conversation
- ConversationMetadata: Metadata about a conversation
- ConversationHistory: Complete conversation history

Extracted from models.py for better organization.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .config import ConversationConfig, DomainModelConfig
from .messages import Message


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


class ConversationResponse(BaseModel):
    """
    Response after creating a conversation.

    Args:
        conversation_id: Unique conversation identifier.
        friendly_name: Human-readable conversation title.
        created_at: UTC timestamp when conversation was created.
        config: Conversation configuration.

    Examples:
        >>> response = ConversationResponse(
        ...     conversation_id="conv_abc123",
        ...     friendly_name="New Conversation 2025-11-17 02:30PM",
        ...     created_at=datetime.utcnow(),
        ...     config=ConversationConfig()
        ... )
    """

    conversation_id: str = Field(
        ...,
        description="Unique conversation identifier",
    )
    user_id: str | None = Field(
        None,
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
    config: ConversationConfig = Field(
        ...,
        description="Conversation configuration",
    )
    domain_models: list[DomainModelConfig] = Field(
        default_factory=list,
        description="Domain-specific model configurations (non-default models)",
    )


class ConversationMetadata(BaseModel):
    """
    Metadata about a conversation.

    Args:
        total_messages: Total number of messages in the conversation.
        total_tokens: Total tokens used across all messages.
        total_cost: Total cost in USD across all messages.
        created_at: UTC timestamp when conversation was created.
        updated_at: UTC timestamp when conversation was last updated.
        friendly_name: Human-readable conversation title.

    Examples:
        >>> metadata = ConversationMetadata(
        ...     total_messages=10,
        ...     total_tokens=1500,
        ...     total_cost=0.015,
        ...     created_at=datetime.utcnow(),
        ...     updated_at=datetime.utcnow(),
        ...     friendly_name="Query Optimization Session"
        ... )
    """

    total_messages: int = Field(
        ...,
        ge=0,
        description="Total number of messages",
    )
    total_tokens: int = Field(
        default=0,
        ge=0,
        description="Total tokens used",
    )
    total_cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Total cost in USD",
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when conversation was created",
    )
    updated_at: datetime = Field(
        ...,
        description="UTC timestamp when conversation was last updated",
    )
    friendly_name: str = Field(
        ...,
        description="Human-readable conversation title",
    )


class ConversationHistory(BaseModel):
    """
    Complete conversation history.

    Args:
        conversation_id: Unique conversation identifier.
        messages: List of all messages in the conversation.
        metadata: Conversation metadata (totals, timestamps).

    Examples:
        >>> history = ConversationHistory(
        ...     conversation_id="conv_abc123",
        ...     messages=[message1, message2],
        ...     metadata=metadata
        ... )
    """

    conversation_id: str = Field(
        ...,
        description="Unique conversation identifier",
    )
    messages: list[Message] = Field(
        ...,
        description="List of all messages in the conversation",
    )
    metadata: ConversationMetadata = Field(
        ...,
        description="Conversation metadata",
    )
    domain_models: list[DomainModelConfig] = Field(
        default_factory=list,
        description="Domain-specific model configurations (non-default models)",
    )
