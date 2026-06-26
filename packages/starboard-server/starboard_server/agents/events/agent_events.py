# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Core agent execution events.

This module defines events related to the agent's reasoning and execution:
- ThinkingEvent: LLM reasoning output
- ThinkingStepUpdate: Enhanced thinking step with sub-tasks
- StepCompleteEvent: Reasoning step completion
- ErrorEvent: Error during execution

Example:
    >>> from starboard_server.agents.events import ThinkingEvent, ErrorEvent
    >>> thinking = ThinkingEvent(step=1, content="Analyzing...", is_complete=False)
    >>> error = ErrorEvent(step=2, error="Connection timeout", is_recoverable=False)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from starboard_server.agents.events.base import EventType, StreamingEvent


class ToolPosition(BaseModel):
    """
    Position information for inline tool display.

    Defines where a tool call should appear within the thinking text content.
    Used for structured rendering without regex parsing.

    Attributes:
        tool_call_id: ID of the tool call to display
        position: Character position in content where tool should appear
        display: Display mode (inline, group, or hidden)

    Example:
        >>> pos = ToolPosition(
        ...     tool_call_id="tool_abc123",
        ...     position=45,
        ...     display="inline"
        ... )
    """

    tool_call_id: str = Field(..., description="Tool call ID reference")
    position: int = Field(..., ge=0, description="Character position in content")
    display: Literal["inline", "group", "hidden"] = Field(
        default="inline", description="Display mode for this tool"
    )


class SubTask(BaseModel):
    """
    Sub-task within a thinking step.

    Represents a discrete piece of work within a larger thinking step,
    with optional metrics/values for display.

    Attributes:
        id: Unique identifier for the sub-task
        description: Human-readable description
        status: Current status (pending, in_progress, completed, failed)
        value: Optional metric value (e.g., "342 nodes", "10 shuffles")

    Example:
        >>> task = SubTask(
        ...     id="parse_plan",
        ...     description="Parsed execution plan",
        ...     status="completed",
        ...     value="342 nodes"
        ... )
    """

    id: str = Field(..., description="Unique sub-task identifier")
    description: str = Field(..., description="Human-readable description")
    status: Literal["pending", "in_progress", "completed", "failed"] = Field(
        default="pending", description="Current status"
    )
    value: str | int | None = Field(None, description="Optional metric value")


class ThinkingEvent(StreamingEvent):
    """
    LLM thinking/reasoning text event.

    Emitted token-by-token as the LLM generates its response. This provides
    real-time visibility into the LLM's reasoning process.

    **Phase 1 P0-3 Enhancement:**
    Supports structured tool positions for rendering without regex parsing.
    When tool_positions is provided, the content should be clean text without
    {{TOOL:...}} markers. Tools are rendered at specified positions.

    Attributes:
        type: Always EventType.THINKING
        step: Current reasoning step
        content: Text content (clean, no tool markers when using tool_positions)
        is_complete: Whether this is the final token in the thinking sequence
        tool_positions: Optional structured tool position data (Phase 1 P0-3)

    Example (Legacy - with markers):
        >>> event = ThinkingEvent(step=1, content="Analyzing {{TOOL:fetch:running}}...")
        >>> print(event.content)

    Example (New - structured):
        >>> event = ThinkingEvent(
        ...     step=1,
        ...     content="Analyzing query...",
        ...     tool_positions=[
        ...         ToolPosition(tool_call_id="tool_123", position=18, display="inline")
        ...     ]
        ... )
    """

    type: Literal[EventType.THINKING] = Field(default=EventType.THINKING)
    content: str = Field(
        ..., description="Text content (clean when using tool_positions)"
    )
    is_complete: bool = Field(default=False, description="Whether thinking is complete")
    tool_positions: list[ToolPosition] | None = Field(
        None, description="Structured tool position data (Phase 1 P0-3)"
    )

    def __str__(self) -> str:
        return f"[Step {self.step}] Thinking: {self.content[:50]}..."

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """
        Format as message.delta event with nested delta structure.

        Includes tool_positions if provided for structured rendering.
        """
        delta: dict[str, Any] = {"content": self.content}

        # Include tool_positions if provided (Phase 1 P0-3)
        if self.tool_positions:
            delta["tool_positions"] = [
                {
                    "tool_call_id": pos.tool_call_id,
                    "position": pos.position,
                    "display": pos.display,
                }
                for pos in self.tool_positions
            ]

        return {
            "message_id": message_id,
            "delta": delta,
        }


class ThinkingStepUpdate(StreamingEvent):
    """
    Enhanced thinking step update event with sub-tasks.

    Provides rich progress information for UI visualization, including
    step title, status, duration, progress percentage, and sub-tasks
    with their own metrics.

    Attributes:
        type: Always EventType.STEP_START
        step: Current reasoning step number
        step_id: Unique identifier for this thinking step
        title: Human-readable step title (e.g., "Resolving Query")
        status: Current status (pending, in_progress, completed, failed)
        start_time: Epoch timestamp when step started
        end_time: Epoch timestamp when step completed (if completed)
        progress: Progress percentage (0-100) for in-progress steps
        sub_tasks: List of sub-tasks with their status and values
        metadata: Additional step-specific metadata

    Example:
        >>> event = ThinkingStepUpdate(
        ...     step=1,
        ...     step_id="resolve_query",
        ...     title="Resolving Query",
        ...     status="in_progress",
        ...     start_time=1701432000.0,
        ...     progress=50,
        ...     sub_tasks=[
        ...         SubTask(
        ...             id="fetch_sql",
        ...             description="Retrieved SQL from query history",
        ...             status="completed",
        ...             value="1,247 lines"
        ...         )
        ...     ]
        ... )
    """

    type: Literal[EventType.STEP_START] = Field(default=EventType.STEP_START)
    step_id: str = Field(..., description="Unique step identifier")
    title: str = Field(..., description="Human-readable step title")
    status: Literal["pending", "in_progress", "completed", "failed"] = Field(
        default="pending", description="Current step status"
    )
    start_time: float | None = Field(None, description="Epoch timestamp when started")
    end_time: float | None = Field(None, description="Epoch timestamp when completed")
    progress: float | None = Field(
        None, ge=0, le=100, description="Progress percentage (0-100)"
    )
    sub_tasks: list[SubTask] = Field(
        default_factory=list, description="Sub-tasks with status and metrics"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional step metadata"
    )

    def __str__(self) -> str:
        return f"[Step {self.step}] {self.title}: {self.status}"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format as step.start event with enhanced structure."""
        return {
            "message_id": message_id,
            "thinking_step": {
                "step_id": self.step_id,
                "title": self.title,
                "status": self.status,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "progress": self.progress,
                "sub_tasks": [
                    {
                        "id": t.id,
                        "description": t.description,
                        "status": t.status,
                        "value": t.value,
                    }
                    for t in self.sub_tasks
                ],
                "metadata": self.metadata,
            },
        }


class StepCompleteEvent(StreamingEvent):
    """
    Reasoning step complete event.

    Emitted when a full reasoning step is complete (LLM call + tool executions).
    Marks a checkpoint in the agent's reasoning process.

    Attributes:
        type: Always EventType.STEP_COMPLETE
        step: The step number that just completed
        reasoning: Optional summary of the reasoning in this step
        tools_called: List of tool names that were called in this step

    Example:
        >>> event = StepCompleteEvent(
        ...     step=2,
        ...     reasoning="Analyzed query plan and identified bottleneck",
        ...     tools_called=["analyze_query_plan", "fetch_table_metadata"]
        ... )
    """

    type: Literal[EventType.STEP_COMPLETE] = Field(default=EventType.STEP_COMPLETE)
    reasoning: str | None = Field(None, description="Summary of reasoning in this step")
    tools_called: list[str] = Field(
        default_factory=list, description="Tools called in this step"
    )

    def __str__(self) -> str:
        tools_str = ", ".join(self.tools_called) if self.tools_called else "none"
        return f"[Step {self.step}] Complete (tools: {tools_str})"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format as step.complete event."""
        return {
            "message_id": message_id,
            "step": self.step,
            "reasoning": self.reasoning,
            "tools_called": self.tools_called,
        }


class ErrorEvent(StreamingEvent):
    """
    Error event during agent execution.

    Emitted when an error occurs that may or may not halt execution.
    Provides context about the error for debugging and user feedback.

    Attributes:
        type: Always EventType.ERROR
        step: Step where error occurred
        error: Error message
        error_type: Type of error (e.g., "ToolExecutionError", "LLMError")
        is_recoverable: Whether the agent can continue after this error
        context: Additional error context

    Example:
        >>> event = ErrorEvent(
        ...     step=2,
        ...     error="Connection timeout to database",
        ...     error_type="DatabaseError",
        ...     is_recoverable=True,
        ...     context={"retry_count": 1, "max_retries": 3}
        ... )
    """

    type: Literal[EventType.ERROR] = Field(default=EventType.ERROR)
    error: str = Field(..., description="Error message")
    error_type: str | None = Field(None, description="Type of error")
    is_recoverable: bool = Field(
        default=False, description="Whether execution can continue"
    )
    context: dict[str, Any] = Field(
        default_factory=dict, description="Additional error context"
    )

    def __str__(self) -> str:
        return f"[Step {self.step}] Error: {self.error}"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format as error event."""
        return {
            "message_id": message_id,
            "error": {
                "message": self.error,
                "type": self.error_type,
                "is_recoverable": self.is_recoverable,
                "context": self.context,
            },
        }
