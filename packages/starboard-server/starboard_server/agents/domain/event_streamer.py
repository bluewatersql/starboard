# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Event streaming for real-time UX updates.

This module extracts event emission logic from DomainAgent,
providing a clean interface for streaming events to the frontend.

Responsibilities:
- Convert tool execution results to StreamingEvent format
- Emit events for reasoning steps (thinking, tool calls, completion)
- Handle event ordering and timing
- Format events for SSE streaming

Does NOT:
- Execute tools (that's ToolExecutor)
- Build final outputs (that's OutputBuilder)
- Make decisions about reasoning (that's ReasoningEngine)
"""

from __future__ import annotations

from typing import Any

from starboard_server.agents.domain.reasoning_engine import ReasoningStep
from starboard_server.agents.domain.tool_executor import ToolExecutionResult
from starboard_server.agents.events import (
    StreamingEvent,
    create_step_complete_event,
    create_thinking_event,
    create_thinking_step_update,
    create_tool_end_event,
    create_tool_start_event,
)
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class EventStreamer:
    """
    Stream events for real-time UX updates.

    Converts internal agent state changes into StreamingEvent objects
    that can be sent to the frontend via SSE.

    Example:
        >>> streamer = EventStreamer()
        >>>
        >>> # Stream thinking event
        >>> event = streamer.create_thinking_event("Analyzing query...", step=1, is_complete=False)
        >>> send_to_frontend(event)
        >>>
        >>> # Stream tool execution events
        >>> for event in streamer.stream_tool_execution(tool_result, step=1):
        ...     send_to_frontend(event)
    """

    def __init__(self):
        """Initialize event streamer."""
        pass

    def create_thinking_event(
        self,
        content: str,
        step: int,
        is_complete: bool = False,
    ) -> StreamingEvent:
        """
        Create a thinking event.

        Args:
            content: Thinking content from LLM
            step: Current reasoning step
            is_complete: Whether thinking is complete

        Returns:
            ThinkingEvent for streaming
        """
        return create_thinking_event(
            content=content,
            step=step,
            is_complete=is_complete,
        )

    def create_thinking_step_update(
        self,
        step: int,
        step_id: str,
        title: str,
        status: str = "pending",
        start_time: float | None = None,
        end_time: float | None = None,
        progress: float | None = None,
        sub_tasks: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StreamingEvent:
        """
        Create an enhanced thinking step update event.

        Args:
            step: Current reasoning step number
            step_id: Unique identifier for this thinking step
            title: Human-readable step title (e.g., "Resolving Query")
            status: Current status (pending, in_progress, completed, failed)
            start_time: Epoch timestamp when step started
            end_time: Epoch timestamp when step completed
            progress: Progress percentage (0-100)
            sub_tasks: List of sub-task dicts with id, description, status, value
            metadata: Additional step-specific metadata

        Returns:
            ThinkingStepUpdate for streaming

        Example:
            >>> event = streamer.create_thinking_step_update(
            ...     step=1,
            ...     step_id="analyze_plan",
            ...     title="Analyzing Query Plan",
            ...     status="in_progress",
            ...     progress=50,
            ...     sub_tasks=[
            ...         {"id": "parse", "description": "Parsed plan", "status": "completed", "value": "342 nodes"}
            ...     ]
            ... )
        """
        return create_thinking_step_update(
            step=step,
            step_id=step_id,
            title=title,
            status=status,
            start_time=start_time,
            end_time=end_time,
            progress=progress,
            sub_tasks=sub_tasks,
            metadata=metadata,
        )

    def create_tool_start_event(
        self,
        step: int,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, Any],
    ) -> StreamingEvent:
        """
        Create a tool start event.

        Args:
            step: Current reasoning step
            tool_name: Name of tool being executed
            tool_call_id: Unique ID for this tool call
            arguments: Tool arguments

        Returns:
            ToolStartEvent for streaming
        """
        return create_tool_start_event(
            step=step,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            arguments=arguments,
        )

    def create_tool_end_event(
        self,
        step: int,
        tool_execution: ToolExecutionResult,
    ) -> StreamingEvent:
        """
        Create a tool end event from execution result.

        Args:
            step: Current reasoning step
            tool_execution: Tool execution result

        Returns:
            ToolEndEvent for streaming
        """
        import json

        # Extract result summary for event
        result_summary = None
        output_dict: dict[str, Any] | None = None

        if tool_execution.success and tool_execution.result:
            # Get content from tool result
            content = getattr(tool_execution.result, "content", None)
            if content:
                result_summary = content[:200] if len(content) > 200 else content

                # Try to parse content as JSON for entity extraction
                try:
                    output_dict = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("tool_end_event_json_decode_error", content=content)

            # Also check for raw_result which may be a dict already
            raw_result = getattr(tool_execution.result, "raw_result", None)
            if raw_result and isinstance(raw_result, dict):
                output_dict = raw_result

        return create_tool_end_event(
            step=step,
            tool_name=tool_execution.tool_call.name,
            tool_call_id=tool_execution.tool_call.id,
            success=tool_execution.success,
            duration_seconds=tool_execution.duration_seconds,
            error=tool_execution.error,
            result_summary=result_summary,
            arguments=tool_execution.arguments,
            output=output_dict,
        )

    def create_step_complete_event(
        self,
        step: int,
        tools_called: int,
        tokens_used: int,  # noqa: ARG002
        budget_remaining: int,  # noqa: ARG002
        is_final: bool,  # noqa: ARG002
    ) -> StreamingEvent:
        """
        Create a step complete event.

        Args:
            step: Current reasoning step
            tools_called: Number of tools called in this step
            tokens_used: Tokens used in this step (ignored - for backward compatibility)
            budget_remaining: Remaining token budget (ignored - for backward compatibility)
            is_final: Whether this is the final step (ignored - for backward compatibility)

        Returns:
            StepCompleteEvent for streaming
        """
        # Note: The factory function signature changed during refactoring
        # We only pass what it accepts: step and tools_called (as list)
        tool_names = (
            [f"tool_{i}" for i in range(tools_called)] if tools_called > 0 else None
        )
        return create_step_complete_event(
            step=step,
            tools_called=tool_names,
        )

    def stream_reasoning_step_events(
        self,
        reasoning_step: ReasoningStep,
        current_step: int,
    ) -> list[StreamingEvent]:
        """
        Convert a reasoning step into streaming events.

        Args:
            reasoning_step: Completed reasoning step
            current_step: Current step number

        Returns:
            List of events to stream
        """
        events = []

        # Emit thinking event if there was content
        if reasoning_step.thinking_content:
            events.append(
                self.create_thinking_event(
                    content=reasoning_step.thinking_content,
                    step=current_step,
                    is_complete=True,
                )
            )

        # Tool call events handled separately by tool executor

        # Emit step complete event
        tokens_used = 0
        if reasoning_step.usage:
            tokens_used = reasoning_step.usage.get("total_tokens", 0)

        events.append(
            self.create_step_complete_event(
                step=current_step,
                tools_called=len(reasoning_step.tool_calls),
                tokens_used=tokens_used,
                budget_remaining=0,  # Updated by caller with actual state
                is_final=reasoning_step.completed,
            )
        )

        return events

    def stream_tool_execution_events(
        self,
        tool_executions: list[ToolExecutionResult],
        current_step: int,
    ) -> list[StreamingEvent]:
        """
        Convert tool execution results into streaming events.

        Args:
            tool_executions: List of tool execution results
            current_step: Current step number

        Returns:
            List of events to stream (start + end for each tool)
        """
        events = []

        # Emit start events for all tools
        for execution in tool_executions:
            events.append(
                self.create_tool_start_event(
                    step=current_step,
                    tool_name=execution.tool_call.name,
                    tool_call_id=execution.tool_call.id,
                    arguments=execution.arguments,
                )
            )

        # Emit end events for all tools
        for execution in tool_executions:
            events.append(
                self.create_tool_end_event(
                    step=current_step,
                    tool_execution=execution,
                )
            )

        logger.debug(
            "streamed_tool_execution_events",
            num_tools=len(tool_executions),
            num_events=len(events),
        )

        return events
