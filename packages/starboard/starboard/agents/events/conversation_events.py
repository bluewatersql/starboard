# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Conversation pattern events.

This module defines events related to conversation patterns:
- NextStepsEvent: Suggested next steps for the user
- ClarificationRequestEvent: Agent requests clarification
- HandoffEvent: Agent handoff to another domain

Example:
    >>> from starboard.agents.events import NextStepsEvent, HandoffEvent
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from starboard.agents.events.base import EventType, StreamingEvent


class NextStepsEvent(StreamingEvent):
    """
    Next steps event for interactive conversation patterns.

    Emitted when the agent provides suggested next steps for the user to select from.
    Part of Phase 1: Pattern 1 (Option Selection).

    Attributes:
        type: Always EventType.NEXT_STEPS
        step: Current reasoning step
        next_steps: List of suggested next step options (1-9 options)

    Example:
        >>> from starboard.domain.models.conversation_patterns import (
        ...     NextStepOption, ActionType
        ... )
        >>> event = NextStepsEvent(
        ...     step=5,
        ...     next_steps=[
        ...         NextStepOption(
        ...             id="opt1",
        ...             number=1,
        ...             title="Optimize query",
        ...             description="Rewrite for performance",
        ...             action_type=ActionType.TOOL_CALL,
        ...             target_agent=None,
        ...             tool_name="optimize",
        ...             parameters={},
        ...         )
        ...     ],
        ... )
        >>> print(f"Offering {len(event.next_steps)} options")
    """

    type: Literal[EventType.NEXT_STEPS] = Field(default=EventType.NEXT_STEPS)
    next_steps: list[Any] = Field(
        ..., description="List of NextStepOption objects"
    )  # Avoid circular import

    def __str__(self) -> str:
        return f"[Step {self.step}] Next Steps: {len(self.next_steps)} options"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format as next_steps event with serialized options."""
        return {
            "message_id": message_id,
            "next_steps": [
                opt.to_dict() if hasattr(opt, "to_dict") else opt
                for opt in self.next_steps
            ],
        }


class ClarificationRequestEvent(StreamingEvent):
    """
    Clarification request event for ambiguous queries.

    Emitted when the framework detects an ambiguous or incomplete query and
    needs user clarification before proceeding. Part of Phase 7: Pattern 7
    (Clarification Request).

    This event is distinct from UserInputRequestEvent (which is agent-driven,
    mid-execution clarification). ClarificationRequestEvent is framework-driven,
    pre-execution ambiguity detection.

    Attributes:
        type: Always EventType.CLARIFICATION_REQUEST
        step: Current reasoning step (typically 0 for pre-execution)
        clarification_id: Unique identifier for this clarification
        clarification_type: Type of ambiguity detected
        question: User-friendly clarification question
        options: Predefined options for user to choose from (optional)
        allow_custom_response: Whether user can provide free text
        is_required: Whether response is required to continue
        target_tool: Tool that will be called after clarification

    Example:
        >>> from starboard.domain.models.clarification import ClarificationType
        >>> event = ClarificationRequestEvent(
        ...     step=0,
        ...     clarification_id="clar_abc123",
        ...     clarification_type=ClarificationType.MISSING_PARAMETER,
        ...     question="What warehouse size would you like?",
        ...     options=[
        ...         {"option_id": "1", "display_text": "Small", "value": "small"},
        ...         {"option_id": "2", "display_text": "Medium", "value": "medium"},
        ...     ],
        ...     allow_custom_response=True,
        ...     is_required=True,
        ...     target_tool="create_warehouse",
        ... )
        >>> print(f"Clarification needed: {event.question}")
    """

    type: Literal[EventType.CLARIFICATION_REQUEST] = Field(
        default=EventType.CLARIFICATION_REQUEST
    )
    clarification_id: str = Field(..., description="Unique clarification identifier")
    clarification_type: str = Field(..., description="Type of ambiguity detected")
    question: str = Field(..., description="User-friendly clarification question")
    options: list[dict[str, Any]] | None = Field(
        None, description="Predefined options for user to choose from"
    )
    allow_custom_response: bool = Field(
        True, description="Whether user can provide custom text"
    )
    is_required: bool = Field(
        True, description="Whether response is required to continue"
    )
    target_tool: str | None = Field(
        None, description="Tool that will be called after clarification"
    )

    def __str__(self) -> str:
        return f"[Step {self.step}] Clarification: {self.question}"

    def to_sse_data(
        self, message_id: str | None = None, conversation_id: str | None = None
    ) -> dict[str, Any]:
        """Format as clarification.request event with all clarification details."""
        result = {
            "clarification_id": self.clarification_id,
            "clarification_type": self.clarification_type,
            "question": self.question,
            "options": self.options,
            "allow_custom_response": self.allow_custom_response,
            "is_required": self.is_required,
            "target_tool": self.target_tool,
        }
        if message_id:
            result["message_id"] = message_id
        if conversation_id:
            result["conversation_id"] = conversation_id
        return result


class HandoffEvent(BaseModel):
    """
    Agent handoff event for routing between agents.

    Emitted when a user selects a routing option and the conversation is
    being handed off to another specialized agent. Part of Phase 3: Pattern 3
    (Agent Routing).

    This event doesn't belong to a specific reasoning step, so it doesn't
    inherit from StreamingEvent.

    Attributes:
        type: Always EventType.HANDOFF
        handoff_id: Unique identifier for this handoff
        source_agent_id: ID of agent initiating the handoff
        target_agent_id: ID of agent receiving the handoff
        capability_id: Capability being invoked (optional)
        handoff_reason: Human-readable reason for handoff
        status: Status of handoff ("initiated", "completed", "failed")

    Example:
        >>> from uuid import uuid4
        >>> event = HandoffEvent(
        ...     handoff_id=uuid4(),
        ...     source_agent_id="query_optimizer",
        ...     target_agent_id="performance_analyzer",
        ...     capability_id="identify_slow_queries",
        ...     handoff_reason="Find slowest queries in warehouse",
        ...     status="initiated",
        ... )
        >>> print(f"Routing from {event.source_agent_id} to {event.target_agent_id}")
    """

    type: Literal[EventType.HANDOFF] = Field(default=EventType.HANDOFF)
    handoff_id: Any = Field(..., description="UUID of handoff")  # Avoid UUID import
    source_agent_id: str = Field(..., description="Source agent ID")
    target_agent_id: str = Field(..., description="Target agent ID")
    capability_id: str | None = Field(None, description="Capability being invoked")
    handoff_reason: str = Field(..., description="Reason for handoff")
    status: str = Field(..., description="Handoff status")

    model_config = ConfigDict(
        frozen=True,  # Immutable
        use_enum_values=True,  # Serialize enums as values
    )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for SSE streaming.

        Returns:
            Dictionary with all handoff metadata including timestamp

        Example:
            >>> event = HandoffEvent(...)
            >>> data = event.to_dict()
            >>> print(data["type"])  # "handoff"
        """
        from datetime import UTC, datetime

        return {
            "type": EventType.HANDOFF,
            "handoff_id": str(self.handoff_id),
            "source_agent_id": self.source_agent_id,
            "target_agent_id": self.target_agent_id,
            "capability_id": self.capability_id,
            "handoff_reason": self.handoff_reason,
            "status": self.status,
            "timestamp": datetime.now(UTC).isoformat(),
        }
