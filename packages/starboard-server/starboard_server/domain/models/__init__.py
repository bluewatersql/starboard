"""Domain models for conversation patterns."""

from starboard_core.domain.models.clarification import (
    AmbiguityScore,
    ClarificationOption,
    ClarificationRequest,
    ClarificationResponse,
    ClarificationType,
)

from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    AgentResponse,
    NextStepOption,
    OptionSelection,
)

__all__ = [
    # Conversation patterns (Phases 1-3)
    "ActionType",
    "NextStepOption",
    "AgentResponse",
    "OptionSelection",
    # Clarification requests (Phase 7)
    "AmbiguityScore",
    "ClarificationOption",
    "ClarificationRequest",
    "ClarificationResponse",
    "ClarificationType",
]
