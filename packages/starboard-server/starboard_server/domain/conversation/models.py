# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Canonical domain models for conversations, messages, and streaming events.

These types are the innermost, stable definitions used across the agent and
conversation layers. The API layer (``starboard_server.api.models``) re-exports
them, preserving the clean-architecture dependency direction: api → domain.

Only the types shared between the domain/agent layer and the API layer live
here. Pure HTTP request models (e.g. ``SendMessageRequest``, ``FileAttachment``)
and API-only enums remain in ``starboard_server.api.models``.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class MessageRole(StrEnum):
    """Role of message sender."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageStatus(StrEnum):
    """Status of message processing."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(StrEnum):
    """Event types for server-sent events (SSE)."""

    # Agent events
    THINKING = "thinking"
    STEP_COMPLETE = "step.complete"
    ERROR = "error"

    # Tool events
    TOOL_START = "tool_start"
    TOOL_CALL_START = "tool.call.start"
    TOOL_PROGRESS = "tool.progress"
    TOOL_END = "tool_end"
    TOOL_CALL_RESULT = "tool.call.result"

    # User interaction events
    USER_INPUT_REQUEST = "user_input_request"
    USER_INPUT_RESPONSE = "user_input_response"
    FINAL_OUTPUT = "final_output"

    # Conversation events
    NEXT_STEPS = "next_steps"
    CLARIFICATION_REQUEST = "clarification.request"
    HANDOFF = "handoff"
    ROUTING_DECISION = "routing.decision"
    FRIENDLY_NAME_UPDATE = "friendly_name.update"
    AGENT_TRANSITION = "agent.transition"

    # Lifecycle events
    CHECKPOINT = "checkpoint"
    INTERRUPT_RECEIVED = "interrupt.received"
    REPLAN = "replan"
    SOLICITATION = "solicitation"

    # Message events (for SSE streaming)
    MESSAGE_START = "message.start"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_END = "message.end"
    STEP_START = "step.start"


# =============================================================================
# Message models
# =============================================================================


class ToolCall(BaseModel):
    """Tool call information for display."""

    tool_call_id: str = Field(..., description="Unique tool call identifier")
    tool_name: str = Field(..., description="Internal tool name")
    friendly_name: str | None = Field(None, description="Display name for tool")
    status: str = Field(..., description="Tool call status (running/completed/failed)")
    arguments: dict[str, Any] | None = Field(None, description="Tool input arguments")
    output: str | None = Field(None, description="Tool result summary")
    error: str | None = Field(None, description="Error message if failed")
    duration_ms: int | None = Field(None, description="Execution time in milliseconds")


class Message(BaseModel):
    """API message model."""

    id: str
    conversation_id: str
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    status: MessageStatus = MessageStatus.COMPLETED
    metadata: dict = Field(default_factory=dict)
    tool_calls: list[ToolCall] = Field(
        default_factory=list, description="Tool calls executed in this message"
    )
    next_steps: list[Any] | None = Field(
        None, description="Next step options for interactive conversation flow"
    )


class MessageResponse(BaseModel):
    """Response after submitting a message."""

    message_id: str
    conversation_id: str
    status: MessageStatus
    trace_id: str | None = None


# =============================================================================
# Configuration models
# =============================================================================


class DomainModelConfig(BaseModel):
    """
    Domain-specific model configuration.

    Args:
        domain: Domain name (e.g., "Query Optimization", "Job Analysis").
        domain_key: Internal domain key (e.g., "query", "job").
        model: LLM model identifier for this domain.

    Examples:
        >>> config = DomainModelConfig(
        ...     domain="Query Optimization",
        ...     domain_key="query",
        ...     model="databricks-gpt-5-1"
        ... )
    """

    domain: str = Field(..., description="Human-readable domain name")
    domain_key: str = Field(..., description="Internal domain key")
    model: str = Field(..., description="LLM model identifier for this domain")


class ConversationConfig(BaseModel):
    """
    Configuration for a conversation session.

    Args:
        temperature: LLM sampling temperature (0.1-1.0). Lower is more deterministic.
        max_tokens: Maximum tokens in response (10,000-200,000).
        use_max_model_tokens: If True, automatically use model's max output tokens.
        safe_mode: If True, disable destructive operations and external calls.
        streaming: If True, stream responses via SSE; else return complete response.
        model: LLM model identifier (supported models from Databricks).
        budget_enforced: If True, enforce session token budget limits.
        max_steps: Maximum reasoning steps allowed (5-25).
        logging_level: Logging verbosity level.
        domain_model_overrides: Per-domain model overrides (domain_key -> model_name).
        domain_temperature_overrides: Per-domain temperature overrides (domain_key -> temperature).

    Examples:
        >>> config = ConversationConfig(temperature=0.4, max_tokens=120000)
        >>> config.temperature
        0.4
        >>> config.budget_enforced
        False
        >>> config_with_overrides = ConversationConfig(
        ...     domain_model_overrides={"query": "databricks-gpt-5"},
        ...     domain_temperature_overrides={"diagnostic": 0.7}
        ... )
    """

    temperature: float = Field(
        default=0.4,
        ge=0.1,
        le=1.0,
        description="LLM sampling temperature",
    )
    max_tokens: int = Field(
        default=120000,
        ge=10000,
        le=200000,
        description="Maximum tokens in response",
    )
    use_max_model_tokens: bool = Field(
        default=False,
        description="Automatically use model's maximum output token limit",
    )
    safe_mode: bool = Field(
        default=False,
        description="Disable destructive operations if True",
    )
    streaming: bool = Field(
        default=True,
        description="Stream responses via SSE",
    )
    model: str = Field(
        default="databricks-claude-sonnet-4-5",
        min_length=1,
        max_length=100,
        description="LLM model identifier",
    )
    budget_enforced: bool = Field(
        default=False,
        description="Enforce session token budget limits",
    )
    max_steps: int = Field(
        default=20,
        ge=5,
        le=25,
        description="Maximum reasoning steps allowed",
    )
    logging_level: str = Field(
        default="INFO",
        description="Logging verbosity level",
    )
    domain_model_overrides: dict[str, str] | None = Field(
        default=None,
        description="Per-domain model overrides (domain_key -> model_name)",
    )
    domain_temperature_overrides: dict[str, float] | None = Field(
        default=None,
        description="Per-domain temperature overrides (domain_key -> temperature)",
    )
    offline_mode: bool = Field(
        default=False,
        description="Force OFFLINE mode - disables tools that require Databricks API calls",
    )

    model_config = {"frozen": True}  # Immutable after creation


# =============================================================================
# Conversation models
# =============================================================================


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


# =============================================================================
# Streaming event models
# =============================================================================


class ChatEvent(BaseModel):
    """
    A single Server-Sent Event in a conversation stream.

    Args:
        event_id: Unique event identifier (for resumption with Last-Event-ID).
        type: Type of event (message.start, message.delta, etc.).
        data: Event payload (varies by event type).
        timestamp: UTC timestamp when event was emitted.

    Examples:
        >>> event = ChatEvent(
        ...     event_id="evt_001",
        ...     type=EventType.MESSAGE_DELTA,
        ...     data={"message_id": "msg_abc", "delta": {"content": "Hello"}},
        ...     timestamp=datetime.utcnow()
        ... )
    """

    event_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique event identifier",
    )
    type: EventType = Field(
        ...,
        description="Type of event",
    )
    data: dict[str, Any] = Field(
        ...,
        description="Event payload",
    )
    timestamp: datetime = Field(
        ...,
        description="UTC timestamp when event was emitted",
    )


__all__ = [
    "ChatEvent",
    "ConversationConfig",
    "ConversationHistory",
    "ConversationMetadata",
    "ConversationResponse",
    "DomainModelConfig",
    "EventType",
    "Message",
    "MessageResponse",
    "MessageRole",
    "MessageStatus",
    "ToolCall",
]
