# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Factory functions for creating streaming events.

This module provides convenient factory functions for creating event instances
with proper defaults and validation.

Example:
    >>> from starboard.agents.events import create_thinking_event, create_tool_start_event
    >>> thinking = create_thinking_event(step=1, content="Analyzing...", is_complete=False)
    >>> tool_start = create_tool_start_event(step=2, tool_name="fetch_data", tool_call_id="call_123", arguments={})
"""

from __future__ import annotations

from typing import Any

from starboard.agents.events.agent_events import (
    ErrorEvent,
    StepCompleteEvent,
    SubTask,
    ThinkingEvent,
    ThinkingStepUpdate,
)
from starboard.agents.events.lifecycle_events import (
    CheckpointEvent,
    InterruptReceivedEvent,
    ReplanEvent,
    SolicitationEvent,
)
from starboard.agents.events.tool_events import ToolEndEvent, ToolStartEvent
from starboard.agents.events.user_events import (
    FinalOutputEvent,
    UserInputRequestEvent,
)
from starboard.agents.tool_display import get_friendly_name


def create_thinking_event(
    step: int, content: str, is_complete: bool = False
) -> ThinkingEvent:
    """Factory function for ThinkingEvent."""
    return ThinkingEvent(step=step, content=content, is_complete=is_complete)


def create_thinking_step_update(
    step: int,
    step_id: str,
    title: str,
    status: str = "pending",
    start_time: float | None = None,
    end_time: float | None = None,
    progress: float | None = None,
    sub_tasks: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ThinkingStepUpdate:
    """
    Factory function for ThinkingStepUpdate.

    Args:
        step: Current reasoning step number
        step_id: Unique identifier for this thinking step
        title: Human-readable step title
        status: Current status (pending, in_progress, completed, failed)
        start_time: Epoch timestamp when step started
        end_time: Epoch timestamp when step completed
        progress: Progress percentage (0-100)
        sub_tasks: List of sub-task dicts with id, description, status, value
        metadata: Additional step-specific metadata

    Returns:
        ThinkingStepUpdate event

    Example:
        >>> event = create_thinking_step_update(
        ...     step=1,
        ...     step_id="resolve_query",
        ...     title="Resolving Query",
        ...     status="in_progress",
        ...     progress=50,
        ...     sub_tasks=[
        ...         {"id": "fetch", "description": "Fetched SQL", "status": "completed", "value": "100 lines"}
        ...     ]
        ... )
    """
    # Convert sub_task dicts to SubTask objects
    sub_task_objects = []
    if sub_tasks:
        for st in sub_tasks:
            sub_task_objects.append(
                SubTask(
                    id=st.get("id", "unknown"),
                    description=st.get("description", ""),
                    status=st.get("status", "pending"),
                    value=st.get("value"),
                )
            )

    return ThinkingStepUpdate(
        step=step,
        step_id=step_id,
        title=title,
        status=status,  # type: ignore[arg-type]
        start_time=start_time,
        end_time=end_time,
        progress=progress,
        sub_tasks=sub_task_objects,
        metadata=metadata or {},
    )


def create_tool_start_event(
    step: int,
    tool_name: str,
    tool_call_id: str,
    arguments: dict[str, Any],
    friendly_name: str | None = None,
) -> ToolStartEvent:
    """
    Factory function for ToolStartEvent.

    Args:
        step: Current reasoning step
        tool_name: Technical name of the tool
        tool_call_id: Unique ID for this tool call
        arguments: Tool arguments
        friendly_name: Human-friendly display name (auto-generated if not provided)

    Returns:
        ToolStartEvent with friendly_name
    """
    # Generate friendly name if not provided
    if friendly_name is None:
        friendly_name = get_friendly_name(tool_name, arguments)

    return ToolStartEvent(
        step=step,
        tool_name=tool_name,
        friendly_name=friendly_name,
        tool_call_id=tool_call_id,
        arguments=arguments,
    )


def create_tool_end_event(
    step: int,
    tool_name: str,
    tool_call_id: str,
    success: bool,
    duration_seconds: float,
    result_summary: str | None = None,
    error: str | None = None,
    friendly_name: str | None = None,
    arguments: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
) -> ToolEndEvent:
    """
    Factory function for ToolEndEvent.

    Args:
        step: Current reasoning step
        tool_name: Technical name of the tool
        tool_call_id: Unique ID for this tool call
        success: Whether tool execution succeeded
        duration_seconds: Tool execution duration
        result_summary: Summary of result (truncated)
        error: Error message if failed
        friendly_name: Human-friendly display name (auto-generated if not provided)
        arguments: Tool arguments (for friendly name generation)
        output: Full tool output dict for entity extraction (internal use only)

    Returns:
        ToolEndEvent with friendly_name
    """
    # Generate friendly name if not provided
    if friendly_name is None:
        friendly_name = get_friendly_name(tool_name, arguments or {})

    return ToolEndEvent(
        step=step,
        tool_name=tool_name,
        friendly_name=friendly_name,
        tool_call_id=tool_call_id,
        success=success,
        result_summary=result_summary,
        output=output,
        error=error,
        duration_seconds=duration_seconds,
    )


def create_step_complete_event(
    step: int,
    reasoning: str | None = None,
    tools_called: list[str] | None = None,
) -> StepCompleteEvent:
    """
    Factory function for StepCompleteEvent.

    Args:
        step: The step number that just completed
        reasoning: Optional summary of the reasoning in this step
        tools_called: List of tool names that were called in this step

    Returns:
        StepCompleteEvent
    """
    return StepCompleteEvent(
        step=step,
        reasoning=reasoning,
        tools_called=tools_called or [],
    )


def create_user_input_request_event(
    step: int,
    question: str,
    request_id: str,
    context: str | None = None,
    suggestions: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> UserInputRequestEvent:
    """Factory function for UserInputRequestEvent."""
    return UserInputRequestEvent(
        step=step,
        question=question,
        context=context,
        suggestions=suggestions or [],
        timeout_seconds=timeout_seconds,
        request_id=request_id,
    )


def create_final_output_event(output: Any) -> FinalOutputEvent:
    """Factory function for FinalOutputEvent."""
    return FinalOutputEvent(output=output)


def create_error_event(
    step: int,
    error: str,
    error_type: str | None = None,
    is_recoverable: bool = False,
    context: dict[str, Any] | None = None,
) -> ErrorEvent:
    """Factory function for ErrorEvent."""
    return ErrorEvent(
        step=step,
        error=error,
        error_type=error_type,
        is_recoverable=is_recoverable,
        context=context or {},
    )


# ==============================================================================
# Factory Functions for Interruptible Reasoning Events
# ==============================================================================


def create_checkpoint_event(
    step: int,
    checkpoint_id: str,
    checkpoint_type: str,
    can_interrupt: bool = True,
    metadata: dict[str, Any] | None = None,
) -> CheckpointEvent:
    """Factory function for CheckpointEvent."""
    return CheckpointEvent(
        step=step,
        checkpoint_id=checkpoint_id,
        checkpoint_type=checkpoint_type,
        can_interrupt=can_interrupt,
        metadata=metadata or {},
    )


def create_interrupt_received_event(
    step: int,
    input_id: str,
    input_type: str,
    content_preview: str,
    checkpoint_id: str,
) -> InterruptReceivedEvent:
    """Factory function for InterruptReceivedEvent."""
    return InterruptReceivedEvent(
        step=step,
        input_id=input_id,
        input_type=input_type,
        content_preview=content_preview,
        checkpoint_id=checkpoint_id,
    )


def create_replan_event(
    step: int,
    decision_id: str,
    strategy: str,
    reasoning: str,
    impact_score: float,
    affected_steps: list[int] | None = None,
    actions: list[str] | None = None,
) -> ReplanEvent:
    """Factory function for ReplanEvent."""
    return ReplanEvent(
        step=step,
        decision_id=decision_id,
        strategy=strategy,
        reasoning=reasoning,
        impact_score=impact_score,
        affected_steps=affected_steps or [],
        actions=actions or [],
    )


def create_solicitation_event(
    step: int,
    solicitation_id: str,
    question: str,
    context: str | None = None,
    expected_response_type: str = "text",
    suggestions: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> SolicitationEvent:
    """Factory function for SolicitationEvent."""
    return SolicitationEvent(
        step=step,
        solicitation_id=solicitation_id,
        question=question,
        context=context,
        expected_response_type=expected_response_type,
        suggestions=suggestions or [],
        timeout_seconds=timeout_seconds,
    )
