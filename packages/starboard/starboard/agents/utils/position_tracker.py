# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Position tracker for calculating tool positions during streaming.

Replaces post-streaming position calculation with real-time tracking.
See: /changes/ui_20251202/IMPLEMENTATION_PLAN_STREAMING_POSITIONS.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolPositionData:
    """
    Single tool position data.

    Attributes:
        tool_call_id: Unique identifier for the tool call
        position: Character index in content where tool should render
        display: Display mode (inline/group/hidden)
    """

    tool_call_id: str
    position: int
    display: str = "inline"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "tool_call_id": self.tool_call_id,
            "position": self.position,
            "display": self.display,
        }


class PositionTracker:
    """
    Track content length and calculate tool positions during streaming.

    Incrementally tracks content as thinking tokens arrive and calculates
    natural insertion points for tools when they start executing.

    Usage:
        >>> tracker = PositionTracker()
        >>>
        >>> # As thinking arrives
        >>> tracker.add_thinking("Analyzing query. ")
        >>>
        >>> # When tool starts
        >>> position = tracker.add_tool_position("tool_123", "fetch_query")
        >>> print(position.position)  # 17
        >>>
        >>> # Get all positions for metadata
        >>> positions = tracker.get_all_positions()

    Design Philosophy:
        - Simple: Use content length as position (no complex heuristics)
        - Fast: O(1) for adding thinking, O(1) for adding tool
        - Reliable: Monotonic positions (never go backward)
        - Extensible: Can add smart positioning later if needed
    """

    def __init__(self) -> None:
        """Initialize empty tracker."""
        self.content_length: int = 0
        self.tool_positions: list[ToolPositionData] = []
        self._last_tool_position: int = 0

    def add_thinking(self, text: str | None) -> None:
        """
        Add thinking content and update cumulative length.

        Called each time a ThinkingEvent arrives with new content.

        Args:
            text: Thinking text chunk (token, sentence, or paragraph)

        Example:
            >>> tracker = PositionTracker()
            >>> tracker.add_thinking("Analyzing ")
            >>> tracker.add_thinking("query...")
            >>> tracker.content_length
            18
        """
        if not text:
            return

        self.content_length += len(text)

    def add_tool_position(
        self,
        tool_call_id: str,
        tool_name: str,
        display: str = "inline",
    ) -> ToolPositionData:
        """
        Calculate and store position for a tool at current content point.

        Called when a ToolStartEvent arrives. Position is based on current
        content length at the moment the tool starts.

        Args:
            tool_call_id: Unique tool call identifier
            tool_name: Tool name (for potential smart positioning)
            display: Display mode (inline/group/hidden), default: inline

        Returns:
            ToolPositionData for this tool

        Example:
            >>> tracker = PositionTracker()
            >>> tracker.add_thinking("Analyzing query. ")
            >>> pos = tracker.add_tool_position("t1", "fetch_query")
            >>> pos.position
            17
            >>> pos.tool_call_id
            't1'
        """
        # Unused for now, but available for future smart positioning
        _ = tool_name

        # Use current content length as position
        position = self.content_length

        # Ensure we don't go backward (safety check)
        if position < self._last_tool_position:
            position = self._last_tool_position

        # Create position data
        pos_data = ToolPositionData(
            tool_call_id=tool_call_id,
            position=position,
            display=display,
        )

        self.tool_positions.append(pos_data)
        self._last_tool_position = position

        return pos_data

    def get_all_positions(self) -> list[dict[str, Any]]:
        """
        Get all tool positions as serializable dicts.

        Used for:
        - Sending positions in SSE events
        - Storing positions in message metadata

        Returns:
            List of position dicts with keys: tool_call_id, position, display

        Example:
            >>> tracker = PositionTracker()
            >>> tracker.add_thinking("Content ")
            >>> tracker.add_tool_position("t1", "fetch")
            >>> tracker.get_all_positions()
            [{'tool_call_id': 't1', 'position': 8, 'display': 'inline'}]
        """
        return [pos.to_dict() for pos in self.tool_positions]

    def reset(self) -> None:
        """
        Reset tracker to initial state.

        Useful for testing or if tracker is reused across messages.
        """
        self.content_length = 0
        self.tool_positions = []
        self._last_tool_position = 0
