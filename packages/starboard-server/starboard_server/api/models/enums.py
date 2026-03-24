"""API enums for message and event models."""

from enum import Enum


class MessageRole(str, Enum):
    """Role of message sender."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageStatus(str, Enum):
    """Status of message processing."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(str, Enum):
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


class FeedbackRatingEnum(str, Enum):
    """User feedback rating for agent responses."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class FeedbackCategoryEnum(str, Enum):
    """Categories for negative feedback."""

    INACCURATE = "inaccurate"
    TOO_VAGUE = "too_vague"
    TOO_VERBOSE = "too_verbose"
    IRRELEVANT = "irrelevant"
    MISSING_INFO = "missing_info"
    BAD_FORMAT = "bad_format"
    OTHER = "other"
