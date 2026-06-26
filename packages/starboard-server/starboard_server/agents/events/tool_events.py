# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tool execution events.

This module defines events related to tool execution:
- ToolStartEvent: Tool execution begins
- ToolProgressEvent: Tool progress update
- ToolEndEvent: Tool execution completes

Example:
    >>> from starboard_server.agents.events import ToolStartEvent, ToolEndEvent
    >>> start = ToolStartEvent(step=1, tool_name="fetch_data", friendly_name="Fetching...", tool_call_id="call_123", arguments={})
    >>> end = ToolEndEvent(step=1, tool_name="fetch_data", friendly_name="Fetching...", tool_call_id="call_123", success=True, result_summary="100 rows", duration_seconds=0.5)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from starboard_server.agents.events.base import EventType, StreamingEvent


class ToolStartEvent(StreamingEvent):
    """
    Tool execution starting event.

    Emitted when the agent begins executing a tool. Provides tool name and
    arguments for visibility.

    Phase 2 Streaming Positions:
    Added optional tool_positions field to send positions during streaming.
    See: /changes/ui_20251202/IMPLEMENTATION_PLAN_STREAMING_POSITIONS.md

    Attributes:
        type: Always EventType.TOOL_START
        step: Current reasoning step
        tool_name: Name of the tool being executed
        friendly_name: Human-friendly display name for the tool
        tool_call_id: Unique ID for this tool call
        arguments: Tool arguments (may be partial during buffering)
        tool_positions: Optional list of tool positions for inline rendering

    Example:
        >>> event = ToolStartEvent(
        ...     step=2,
        ...     tool_name="fetch_table_metadata",
        ...     friendly_name="Fetching Table Metadata for main.users",
        ...     tool_call_id="call_abc123",
        ...     arguments={"table_name": "users"}
        ... )
    """

    type: Literal[EventType.TOOL_START] = Field(default=EventType.TOOL_START)
    tool_name: str = Field(..., description="Name of the tool")
    friendly_name: str = Field(..., description="Human-friendly display name")
    tool_call_id: str = Field(..., description="Unique ID for this tool call")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )
    tool_positions: list[dict[str, Any]] | None = Field(
        None, description="Tool positions for inline rendering (Phase 2)"
    )

    def __str__(self) -> str:
        return f"[Step {self.step}] Tool Start: {self.friendly_name}"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """
        Format as tool.call.start event with nested tool_call structure.

        Includes tool_positions if provided (Phase 2 streaming positions).
        """
        data: dict[str, Any] = {
            "message_id": message_id,
            "tool_call": {
                "tool_name": self.tool_name,
                "friendly_name": self.friendly_name,
                "tool_call_id": self.tool_call_id,
                "arguments": self.arguments,
                "status": "running",
            },
        }

        # Phase 2: Include positions if provided
        if self.tool_positions:
            data["tool_positions"] = self.tool_positions

        return data


class ToolProgressEvent(StreamingEvent):
    """
    Tool execution progress update event.

    Optional event for long-running tools to report progress. Not all tools
    emit progress events.

    Attributes:
        type: Always EventType.TOOL_PROGRESS
        step: Current reasoning step
        tool_name: Name of the tool
        tool_call_id: Unique ID for this tool call
        progress: Progress percentage (0-100)
        message: Optional progress message

    Example:
        >>> event = ToolProgressEvent(
        ...     step=2,
        ...     tool_name="analyze_query_plan",
        ...     tool_call_id="call_abc123",
        ...     progress=50,
        ...     message="Analyzing execution plan..."
        ... )
    """

    type: Literal[EventType.TOOL_PROGRESS] = Field(default=EventType.TOOL_PROGRESS)
    tool_name: str = Field(..., description="Name of the tool")
    tool_call_id: str = Field(..., description="Unique ID for this tool call")
    progress: float = Field(..., ge=0, le=100, description="Progress percentage")
    message: str | None = Field(None, description="Progress message")

    def __str__(self) -> str:
        return (
            f"[Step {self.step}] Tool Progress: {self.tool_name} ({self.progress:.0f}%)"
        )

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format as tool.progress event with progress information."""
        return {
            "message_id": message_id,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "progress": self.progress,
            "message": self.message,
        }


class ToolEndEvent(StreamingEvent):
    """
    Tool execution complete event.

    Emitted when a tool finishes execution (success or failure). Includes
    result or error information.

    Attributes:
        type: Always EventType.TOOL_END
        step: Current reasoning step
        tool_name: Name of the tool
        friendly_name: Human-friendly display name for the tool
        tool_call_id: Unique ID for this tool call
        success: Whether tool execution succeeded
        result_summary: Brief summary of the result (first 200 chars)
        error: Error message if tool failed
        duration_seconds: How long the tool took to execute

    Example:
        >>> event = ToolEndEvent(
        ...     step=2,
        ...     tool_name="fetch_table_metadata",
        ...     friendly_name="Fetching Table Metadata for main.users",
        ...     tool_call_id="call_abc123",
        ...     success=True,
        ...     result_summary="Table has 5 columns, 1M rows",
        ...     duration_seconds=0.5
        ... )
    """

    type: Literal[EventType.TOOL_END] = Field(default=EventType.TOOL_END)
    tool_name: str = Field(..., description="Name of the tool")
    friendly_name: str = Field(..., description="Human-friendly display name")
    tool_call_id: str = Field(..., description="Unique ID for this tool call")
    success: bool = Field(..., description="Whether tool succeeded")
    result_summary: str | None = Field(
        None, description="Summary of result (truncated)"
    )
    output: dict[str, Any] | None = Field(
        None,
        description="Full tool output for entity extraction (not sent to SSE)",
        exclude=True,  # Don't serialize to SSE - internal use only
    )
    error: str | None = Field(None, description="Error message if failed")
    duration_seconds: float = Field(..., ge=0, description="Tool execution duration")

    def __str__(self) -> str:
        status = "Success" if self.success else "Error"
        return f"[Step {self.step}] Tool End: {self.friendly_name} ({status})"

    def to_sse_data(self, message_id: str | None = None) -> dict[str, Any]:
        """Format as tool.call.result event with nested tool_call structure."""
        status = "completed" if self.success else "failed"
        return {
            "message_id": message_id,
            "tool_call": {
                "tool_name": self.tool_name,
                "friendly_name": self.friendly_name,
                "tool_call_id": self.tool_call_id,
                "success": self.success,
                "status": status,
                "result": self.result_summary,
                "error": self.error,
                "duration_ms": int(self.duration_seconds * 1000),
            },
        }
