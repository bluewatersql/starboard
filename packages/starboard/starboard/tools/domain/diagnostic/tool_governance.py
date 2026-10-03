# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Tool call governance for diagnostic agent.

This module implements limits and prioritization for tool calls during
diagnostic exploration to prevent runaway costs and ensure efficient
use of the tool budget.

Design reference: changes/diagnostic_agent/UNIFIED_DESIGN.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Default governance limits
DEFAULT_MAX_TOOLS_PER_TURN = 6
DEFAULT_TOKEN_BUDGET = 8000

# Tool priority mappings (tool_name -> priority)
_TOOL_PRIORITIES: dict[str, str] = {
    # HIGH priority - key diagnostic tools
    "get_run_output": "high",
    "resolve_job": "high",
    "resolve_query": "high",
    # MEDIUM priority - supporting context
    "get_job_config": "medium",
    "analyze_job_history": "medium",
    "get_cluster_events": "medium",
    "get_spark_logs": "medium",
    "get_cluster_config": "medium",
    "get_warehouse_config": "medium",
    # LOW priority - supplementary
    "list_jobs": "low",
    "list_clusters": "low",
}


class ToolPriority(Enum):
    """Priority levels for tool requests.

    Lower value = higher priority (sorted ascending).
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    def __lt__(self, other: ToolPriority) -> bool:
        """Enable sorting by priority (critical < high < medium < low)."""
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return order[self.value] < order[other.value]


@dataclass
class ToolRequest:
    """A request to call a tool.

    Contains metadata for governance decisions.
    """

    tool_name: str
    """Name of the tool to call."""

    priority: ToolPriority
    """Priority level for this request."""

    estimated_tokens: int
    """Estimated token cost for this tool call."""

    rationale: str
    """Why this tool is needed for diagnosis."""

    tool_args: dict[str, Any] = field(default_factory=dict)
    """Arguments to pass to the tool."""


@dataclass
class RejectedRequest:
    """A tool request that was rejected by governance."""

    request: ToolRequest
    """The rejected request."""

    reason: str
    """Why the request was rejected."""


@dataclass
class ToolGovernance:
    """Governs tool call limits and prioritization.

    Enforces:
    - Maximum tools per turn (default 6)
    - Token budget per turn (default 8000)
    - Priority-based selection when limits exceeded
    """

    max_tools_per_turn: int = DEFAULT_MAX_TOOLS_PER_TURN
    """Maximum number of tools that can be called per turn."""

    token_budget: int = DEFAULT_TOKEN_BUDGET
    """Maximum tokens that can be used for tool calls per turn."""

    _approved: list[ToolRequest] = field(default_factory=list)
    """Approved tool requests for this turn."""

    _rejected: list[RejectedRequest] = field(default_factory=list)
    """Rejected tool requests with reasons."""

    _tokens_used: int = field(default=0)
    """Tokens allocated so far this turn."""

    def approve_requests(self, requests: list[ToolRequest]) -> list[ToolRequest]:
        """Approve tool requests within governance limits.

        Prioritizes requests by priority level, then by order.
        Rejects requests that exceed limits.

        Args:
            requests: List of tool requests to evaluate.

        Returns:
            List of approved requests (may be subset of input).
        """
        if not requests:
            return []

        # Sort by priority (critical first), preserving order within priority
        sorted_requests = sorted(
            enumerate(requests), key=lambda x: (x[1].priority, x[0])
        )

        approved: list[ToolRequest] = []

        for _original_idx, request in sorted_requests:
            # Check tool count limit
            if len(approved) >= self.max_tools_per_turn:
                self._rejected.append(
                    RejectedRequest(
                        request=request,
                        reason=f"Exceeded max tools per turn ({self.max_tools_per_turn})",
                    )
                )
                continue

            # Check token budget
            if self._tokens_used + request.estimated_tokens > self.token_budget:
                self._rejected.append(
                    RejectedRequest(
                        request=request,
                        reason=f"Exceeded token budget ({self.token_budget})",
                    )
                )
                continue

            # Approve the request
            approved.append(request)
            self._tokens_used += request.estimated_tokens

        self._approved.extend(approved)
        return approved

    def get_usage_stats(self) -> dict[str, int]:
        """Get current usage statistics.

        Returns:
            Dictionary with usage stats.
        """
        return {
            "tools_approved": len(self._approved),
            "tokens_allocated": self._tokens_used,
            "tools_remaining": self.max_tools_per_turn - len(self._approved),
            "budget_remaining": self.token_budget - self._tokens_used,
        }

    def get_decision_report(self) -> dict[str, Any]:
        """Get detailed report of governance decisions.

        Returns:
            Dictionary with approved and rejected requests.
        """
        return {
            "approved": [
                {
                    "tool_name": r.tool_name,
                    "priority": r.priority.value,
                    "estimated_tokens": r.estimated_tokens,
                    "rationale": r.rationale,
                }
                for r in self._approved
            ],
            "rejected": [
                {
                    "tool_name": r.request.tool_name,
                    "priority": r.request.priority.value,
                    "reason": r.reason,
                }
                for r in self._rejected
            ],
            "stats": self.get_usage_stats(),
        }

    def reset(self) -> None:
        """Reset governance state for a new turn."""
        self._approved = []
        self._rejected = []
        self._tokens_used = 0

    def get_default_priority(self, tool_name: str) -> ToolPriority:
        """Get the default priority for a tool.

        Args:
            tool_name: Name of the tool.

        Returns:
            ToolPriority based on tool type.
        """
        priority_str = _TOOL_PRIORITIES.get(tool_name, "low")
        return ToolPriority(priority_str)

    def can_call_more_tools(self) -> bool:
        """Check if more tools can be called this turn.

        Returns:
            True if within limits, False otherwise.
        """
        return (
            len(self._approved) < self.max_tools_per_turn
            and self._tokens_used < self.token_budget
        )

    def create_request(
        self,
        tool_name: str,
        estimated_tokens: int,
        rationale: str,
        tool_args: dict[str, Any] | None = None,
        priority: ToolPriority | None = None,
    ) -> ToolRequest:
        """Helper to create a tool request with default priority.

        Args:
            tool_name: Name of the tool.
            estimated_tokens: Estimated token cost.
            rationale: Why this tool is needed.
            tool_args: Optional tool arguments.
            priority: Optional priority override.

        Returns:
            ToolRequest ready for approval.
        """
        return ToolRequest(
            tool_name=tool_name,
            priority=priority or self.get_default_priority(tool_name),
            estimated_tokens=estimated_tokens,
            rationale=rationale,
            tool_args=tool_args or {},
        )
