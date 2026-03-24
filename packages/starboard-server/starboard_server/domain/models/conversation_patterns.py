"""Domain models for interactive conversation patterns.

This module defines models for:
- Pattern 1: Option Selection (NextStepOption, AgentResponse, OptionSelection)
- Pattern 2: Conversation Extension (IntentClassification, ConversationContext) — planned
- Pattern 3: Agent Routing (RoutingDecision, AgentHandoff) — planned
- Pattern 4: Feedback Collection (UserFeedback, FeedbackContext) — planned
- Pattern 5: Agent Discovery (AgentSuggestion, SuggestionContext) — planned

All models follow these principles:
- Immutable (frozen dataclasses)
- Type-safe
- Serializable (to_dict/from_dict)
- Well-documented with examples
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal


class ActionType(Enum):
    """Type of action for a next step option.

    Actions determine how the system handles a user's selection:
    - CONTINUE: Stay with current agent, continue conversation
    - ROUTE: Hand off to a different specialized agent
    - TOOL_CALL: Execute a tool/function with parameters

    Examples:
        >>> ActionType.TOOL_CALL.value
        'tool_call'
        >>> ActionType("route")
        <ActionType.ROUTE: 'route'>
    """

    CONTINUE = "continue"
    ROUTE = "route"
    TOOL_CALL = "tool_call"


@dataclass(frozen=True)
class NextStepOption:
    """A single actionable option presented to the user.

    Part of Pattern 1: Option Selection. Represents one numbered option
    that a user can select to continue the conversation.

    Attributes:
        id: Unique identifier for this option (e.g., "optimize_query")
        number: Display number 1-9 for user selection
        title: Short, actionable title (e.g., "Optimize query execution plan")
        description: Optional longer explanation
        action_type: What happens when user selects this option
        target_agent: Agent ID if action_type is ROUTE
        tool_name: Tool name if action_type is TOOL_CALL
        parameters: Pre-filled parameters for the action

    Examples:
        >>> option = NextStepOption(
        ...     id="opt1",
        ...     number=1,
        ...     title="Optimize query",
        ...     description="Rewrite query for better performance",
        ...     action_type=ActionType.TOOL_CALL,
        ...     target_agent=None,
        ...     tool_name="optimize_query",
        ...     parameters={"query_id": "123"},
        ... )
        >>> option.number
        1
        >>> option.action_type
        <ActionType.TOOL_CALL: 'tool_call'>
    """

    id: str
    number: int
    title: str
    description: str | None
    action_type: ActionType
    target_agent: str | None
    tool_name: str | None
    parameters: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage or API responses.

        Returns:
            Dictionary representation with action_type as string value

        Examples:
            >>> option = NextStepOption(...)
            >>> data = option.to_dict()
            >>> data["action_type"]
            'tool_call'
        """
        return {
            "id": self.id,
            "number": self.number,
            "title": self.title,
            "description": self.description,
            "action_type": self.action_type.value,
            "target_agent": self.target_agent,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NextStepOption:
        """Deserialize from dict.

        Args:
            data: Dictionary with option data

        Returns:
            NextStepOption instance

        Examples:
            >>> data = {"id": "opt1", "number": 1, ..., "action_type": "route"}
            >>> option = NextStepOption.from_dict(data)
            >>> option.action_type
            <ActionType.ROUTE: 'route'>
        """
        return cls(
            id=data["id"],
            number=data["number"],
            title=data["title"],
            description=data.get("description"),
            action_type=ActionType(data["action_type"]),
            target_agent=data.get("target_agent"),
            tool_name=data.get("tool_name"),
            parameters=data.get("parameters"),
        )


@dataclass(frozen=True)
class AgentResponse:
    """Agent response with optional structured next steps.

    Part of Pattern 1: Option Selection. Extends the basic agent response
    to include structured options that users can select.

    Attributes:
        content: Main response text (markdown supported)
        next_steps: Optional tuple of NextStepOption for user selection
        conversation_id: ID of the conversation
        message_id: Unique ID for this message
        agent_name: Name of the agent that generated this response
        metadata: Additional metadata (token count, cost, latency, etc.)

    Examples:
        >>> response = AgentResponse(
        ...     content="Query analyzed. Here are your options:",
        ...     next_steps=(
        ...         NextStepOption(...),
        ...         NextStepOption(...),
        ...     ),
        ...     conversation_id="conv-123",
        ...     message_id="msg-456",
        ...     agent_name="query_optimizer",
        ...     metadata={"token_count": 150, "latency_ms": 1200},
        ... )
        >>> len(response.next_steps)
        2
    """

    content: str
    next_steps: tuple[NextStepOption, ...] | None
    conversation_id: str
    message_id: str
    agent_name: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage or API responses.

        Returns:
            Dictionary representation with serialized next_steps

        Examples:
            >>> response = AgentResponse(...)
            >>> data = response.to_dict()
            >>> isinstance(data["next_steps"], list)
            True
        """
        return {
            "content": self.content,
            "next_steps": (
                [opt.to_dict() for opt in self.next_steps] if self.next_steps else None
            ),
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "agent_name": self.agent_name,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentResponse:
        """Deserialize from dict.

        Args:
            data: Dictionary with response data

        Returns:
            AgentResponse instance

        Examples:
            >>> data = {"content": "...", "next_steps": [...], ...}
            >>> response = AgentResponse.from_dict(data)
        """
        return cls(
            content=data["content"],
            next_steps=(
                tuple(NextStepOption.from_dict(opt) for opt in data["next_steps"])
                if data.get("next_steps")
                else None
            ),
            conversation_id=data["conversation_id"],
            message_id=data["message_id"],
            agent_name=data["agent_name"],
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class OptionSelection:
    """Result of processing user's option selection.

    Part of Pattern 1: Option Selection. Represents the outcome of analyzing
    user input to determine if they selected an option or entered free text.

    Attributes:
        selection_type: Whether input matched an option or is free text
        selected_option: The matched option (None if free text)
        original_input: Raw user input
        confidence: Confidence score 0.0-1.0 for the match

    Examples:
        >>> # User typed "2"
        >>> selection = OptionSelection(
        ...     selection_type="option",
        ...     selected_option=NextStepOption(...),
        ...     original_input="2",
        ...     confidence=1.0,
        ... )
        >>> selection.selected_option.number
        2

        >>> # User typed free text
        >>> selection = OptionSelection(
        ...     selection_type="free_text",
        ...     selected_option=None,
        ...     original_input="Tell me about costs",
        ...     confidence=1.0,
        ... )
        >>> selection.selection_type
        'free_text'
    """

    selection_type: Literal["option", "free_text"]
    selected_option: NextStepOption | None
    original_input: str
    confidence: float


# ==============================================================================
# Phase 2: Conversation Extension Pattern
# ==============================================================================


class UserIntentType(Enum):
    """Type of user intent in multi-turn conversation.

    Part of Pattern 2: Conversation Extension. Classifies how a user's message
    relates to the ongoing conversation context.

    Intent Types:
    - EXTENSION: Add constraints or scope to current topic
    - REFINEMENT: Adjust or correct current analysis
    - CLARIFICATION: Answer agent's question
    - NEW_QUERY: Start completely different topic
    - FEEDBACK: React to agent's response (positive/negative)

    Examples:
        >>> UserIntentType.EXTENSION.value
        'extension'
        >>> UserIntentType("refinement")
        <UserIntentType.REFINEMENT: 'refinement'>
    """

    EXTENSION = "extension"
    REFINEMENT = "refinement"
    CLARIFICATION = "clarification"
    NEW_QUERY = "new_query"
    FEEDBACK = "feedback"


@dataclass(frozen=True)
class IntentClassification:
    """Result of classifying user intent in conversation.

    Part of Pattern 2: Conversation Extension. Represents the outcome of analyzing
    a user's message to determine how it relates to the ongoing conversation.

    Attributes:
        intent_type: Detected intent (extension, refinement, etc.)
        confidence: Confidence score 0.0-1.0 for the classification
        reasoning: Human-readable explanation of why this intent was detected
        extracted_entities: New constraints, parameters, or context from message

    Examples:
        >>> # User adding time constraint to query analysis
        >>> classification = IntentClassification(
        ...     intent_type=UserIntentType.EXTENSION,
        ...     confidence=0.92,
        ...     reasoning="User is adding time-based constraints to existing query analysis",
        ...     extracted_entities={"timeframe": "morning", "metric": "performance"},
        ... )
        >>> classification.intent_type
        <UserIntentType.EXTENSION: 'extension'>
        >>> classification.extracted_entities["timeframe"]
        'morning'

        >>> # User starting completely new topic
        >>> classification = IntentClassification(
        ...     intent_type=UserIntentType.NEW_QUERY,
        ...     confidence=0.98,
        ...     reasoning="Topic completely different from previous conversation",
        ...     extracted_entities={},
        ... )
        >>> classification.intent_type
        <UserIntentType.NEW_QUERY: 'new_query'>
    """

    intent_type: UserIntentType
    confidence: float
    reasoning: str
    extracted_entities: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage or API responses.

        Returns:
            Dictionary representation with intent_type as string value

        Examples:
            >>> classification = IntentClassification(
            ...     intent_type=UserIntentType.EXTENSION,
            ...     confidence=0.87,
            ...     reasoning="Adding constraints",
            ...     extracted_entities={"timeframe": "morning"},
            ... )
            >>> data = classification.to_dict()
            >>> data["intent_type"]
            'extension'
            >>> data["confidence"]
            0.87
        """
        return {
            "intent_type": self.intent_type.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "extracted_entities": self.extracted_entities,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentClassification:
        """Deserialize from dict.

        Args:
            data: Dictionary with classification data

        Returns:
            IntentClassification instance

        Examples:
            >>> data = {
            ...     "intent_type": "extension",
            ...     "confidence": 0.87,
            ...     "reasoning": "Adding constraints",
            ...     "extracted_entities": {"timeframe": "morning"},
            ... }
            >>> classification = IntentClassification.from_dict(data)
            >>> classification.intent_type
            <UserIntentType.EXTENSION: 'extension'>
        """
        return cls(
            intent_type=UserIntentType(data["intent_type"]),
            confidence=data["confidence"],
            reasoning=data["reasoning"],
            extracted_entities=data.get("extracted_entities", {}),
        )
