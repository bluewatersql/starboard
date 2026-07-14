# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Streaming events package for agent execution.

This package defines Pydantic models for real-time streaming events emitted during
agent execution. Events are validated at runtime and provide type-safe interfaces.

Organization:
- base: EventType enum and StreamingEvent base class
- agent_events: Core agent events (thinking, step complete, error)
- tool_events: Tool execution events (start, progress, end)
- user_events: User interaction events (input request/response, final output)
- conversation_events: Conversation pattern events (next steps, clarification, handoff)
- lifecycle_events: Interruptible reasoning events (checkpoint, interrupt, replan)
- factories: Factory functions for creating events

Example:
    >>> from starboard.agents.events import (
    ...     EventType,
    ...     ThinkingEvent,
    ...     ToolStartEvent,
    ...     create_thinking_event,
    ...     create_tool_start_event,
    ... )
    >>>
    >>> # Create events using factory functions
    >>> thinking = create_thinking_event(step=1, content="Analyzing...", is_complete=False)
    >>> tool_start = create_tool_start_event(
    ...     step=2,
    ...     tool_name="fetch_data",
    ...     tool_call_id="call_123",
    ...     arguments={"table": "users"}
    ... )
    >>>
    >>> # Or create directly
    >>> thinking = ThinkingEvent(step=1, content="Analyzing...", is_complete=False)
"""

# Base
# Agent events
from starboard.agents.events.agent_events import (
    ErrorEvent,
    StepCompleteEvent,
    SubTask,
    ThinkingEvent,
    ThinkingStepUpdate,
)
from starboard.agents.events.base import EventType, StreamEvent, StreamingEvent

# Conversation events
from starboard.agents.events.conversation_events import (
    ClarificationRequestEvent,
    HandoffEvent,
    NextStepsEvent,
)

# Factory functions
from starboard.agents.events.factories import (
    create_checkpoint_event,
    create_error_event,
    create_final_output_event,
    create_interrupt_received_event,
    create_replan_event,
    create_solicitation_event,
    create_step_complete_event,
    create_thinking_event,
    create_thinking_step_update,
    create_tool_end_event,
    create_tool_start_event,
    create_user_input_request_event,
)

# Lifecycle events
from starboard.agents.events.lifecycle_events import (
    CheckpointEvent,
    InterruptReceivedEvent,
    ReplanEvent,
    SolicitationEvent,
)

# Tool events
from starboard.agents.events.tool_events import (
    ToolEndEvent,
    ToolProgressEvent,
    ToolStartEvent,
)

# User events
from starboard.agents.events.user_events import (
    FinalOutputEvent,
    UserInputRequestEvent,
    UserInputResponseEvent,
)

__all__ = [
    # Base
    "EventType",
    "StreamingEvent",
    "StreamEvent",
    # Agent events
    "ThinkingEvent",
    "ThinkingStepUpdate",
    "SubTask",
    "StepCompleteEvent",
    "ErrorEvent",
    # Tool events
    "ToolStartEvent",
    "ToolProgressEvent",
    "ToolEndEvent",
    # User events
    "UserInputRequestEvent",
    "UserInputResponseEvent",
    "FinalOutputEvent",
    # Conversation events
    "NextStepsEvent",
    "ClarificationRequestEvent",
    "HandoffEvent",
    # Lifecycle events
    "CheckpointEvent",
    "InterruptReceivedEvent",
    "ReplanEvent",
    "SolicitationEvent",
    # Factory functions
    "create_thinking_event",
    "create_thinking_step_update",
    "create_tool_start_event",
    "create_tool_end_event",
    "create_step_complete_event",
    "create_user_input_request_event",
    "create_final_output_event",
    "create_error_event",
    "create_checkpoint_event",
    "create_interrupt_received_event",
    "create_replan_event",
    "create_solicitation_event",
]
