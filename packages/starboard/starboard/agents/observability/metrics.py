# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Metrics and observability for multi-agent system.

This module provides structured metrics collection for monitoring multi-agent
routing, agent transitions, and specialist performance.

The ``AgentMetrics.export_json`` method uses async file I/O via
``starboard.infra.io`` to avoid blocking the event loop when exporting
metrics during request handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from starboard.infra.io import write_json

logger = structlog.get_logger(__name__)


@dataclass
class RoutingMetrics:
    """Metrics for a single routing decision."""

    domain: str
    """Domain the request was routed to"""

    confidence: float
    """Router confidence in decision (0.0-1.0)"""

    clarification_needed: bool
    """Whether clarification was needed"""

    reasoning: str
    """Why this domain was chosen"""

    extracted_ids: dict[str, str] = field(default_factory=dict)
    """Identifiers extracted from user input"""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When routing decision was made"""

    routing_method: str = "hybrid"
    """Method used: pattern, keyword, llm_fallback"""


@dataclass
class TransitionMetrics:
    """Metrics for agent-to-agent transition."""

    from_agent: str
    """Source agent"""

    to_agent: str
    """Target agent"""

    reason: str
    """Reason for transition"""

    context_size: int
    """Size of context passed (bytes)"""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When transition occurred"""


@dataclass
class SpecialistMetrics:
    """Metrics for specialist agent execution."""

    domain: str
    """Domain of specialist"""

    duration_seconds: float
    """Execution duration"""

    tokens_used: int
    """Total tokens consumed"""

    input_tokens: int
    """Input tokens"""

    output_tokens: int
    """Output tokens"""

    cost_usd: float
    """Estimated cost in USD"""

    tools_called: int
    """Number of tool calls made"""

    tools_used: list[str] = field(default_factory=list)
    """Names of tools called"""

    success: bool = True
    """Whether execution succeeded"""

    error: str | None = None
    """Error message if failed"""

    model: str = "unknown"
    """LLM model used"""

    temperature: float = 0.5
    """Temperature used"""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When execution started"""


class MultiAgentMetrics:
    """
    Centralized metrics collection for multi-agent system.

    Provides structured logging and metric recording for monitoring
    routing accuracy, agent performance, and cost tracking.

    Examples:
        >>> metrics = MultiAgentMetrics()
        >>>
        >>> # Record routing decision
        >>> metrics.record_routing_decision(
        ...     domain="query",
        ...     confidence=0.95,
        ...     clarification_needed=False,
        ...     reasoning="Statement ID detected"
        ... )
        >>>
        >>> # Record agent transition
        >>> metrics.record_agent_transition(
        ...     from_agent="router",
        ...     to_agent="query",
        ...     reason="Statement ID found",
        ...     context_size=1024
        ... )
        >>>
        >>> # Record specialist execution
        >>> metrics.record_specialist_execution(
        ...     domain="query",
        ...     duration_seconds=2.5,
        ...     tokens_used=1500,
        ...     cost_usd=0.015,
        ...     tools_called=3,
        ...     success=True
        ... )
    """

    def __init__(self):
        """Initialize metrics collector."""
        self.routing_decisions: list[RoutingMetrics] = []
        self.transitions: list[TransitionMetrics] = []
        self.specialist_executions: list[SpecialistMetrics] = []

    def record_routing_decision(
        self,
        domain: str,
        confidence: float,
        clarification_needed: bool,
        reasoning: str,
        extracted_ids: dict[str, str] | None = None,
        routing_method: str = "hybrid",
    ) -> None:
        """
        Record a routing decision for monitoring.

        Args:
            domain: Domain the request was routed to
            confidence: Router confidence (0.0-1.0)
            clarification_needed: Whether clarification was needed
            reasoning: Why this domain was chosen
            extracted_ids: Identifiers extracted from input
            routing_method: Method used (pattern, keyword, llm_fallback)
        """
        metrics = RoutingMetrics(
            domain=domain,
            confidence=confidence,
            clarification_needed=clarification_needed,
            reasoning=reasoning,
            extracted_ids=extracted_ids or {},
            routing_method=routing_method,
        )

        self.routing_decisions.append(metrics)

        logger.debug(
            "routing_decision",
            domain=domain,
            confidence=confidence,
            clarification_needed=clarification_needed,
            reasoning=reasoning,
            routing_method=routing_method,
            extracted_ids=extracted_ids or {},
        )

    def record_agent_transition(
        self,
        from_agent: str,
        to_agent: str,
        reason: str,
        context_size: int = 0,
    ) -> None:
        """
        Record an agent-to-agent transition.

        Args:
            from_agent: Source agent
            to_agent: Target agent
            reason: Reason for transition
            context_size: Size of context passed (bytes)
        """
        metrics = TransitionMetrics(
            from_agent=from_agent,
            to_agent=to_agent,
            reason=reason,
            context_size=context_size,
        )

        self.transitions.append(metrics)

        logger.debug(
            "agent_transition",
            from_agent=from_agent,
            to_agent=to_agent,
            reason=reason,
            context_size=context_size,
        )

    def record_specialist_execution(
        self,
        domain: str,
        duration_seconds: float,
        tokens_used: int,
        cost_usd: float,
        tools_called: int,
        success: bool = True,
        error: str | None = None,
        tools_used: list[str] | None = None,
        model: str = "unknown",
        temperature: float = 0.5,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """
        Record specialist agent execution metrics.

        Args:
            domain: Domain of specialist
            duration_seconds: Execution duration
            tokens_used: Total tokens consumed
            cost_usd: Estimated cost
            tools_called: Number of tool calls
            success: Whether execution succeeded
            error: Error message if failed
            tools_used: Names of tools called
            model: LLM model used
            temperature: Temperature used
            input_tokens: Input tokens
            output_tokens: Output tokens
        """
        metrics = SpecialistMetrics(
            domain=domain,
            duration_seconds=duration_seconds,
            tokens_used=tokens_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            tools_called=tools_called,
            tools_used=tools_used or [],
            success=success,
            error=error,
            model=model,
            temperature=temperature,
        )

        self.specialist_executions.append(metrics)

        logger.debug(
            "specialist_execution",
            domain=domain,
            duration_seconds=duration_seconds,
            tokens_used=tokens_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            tools_called=tools_called,
            tools_used=tools_used or [],
            success=success,
            error=error,
            model=model,
            temperature=temperature,
        )

    def get_routing_accuracy(self) -> dict[str, Any]:
        """
        Calculate routing accuracy metrics.

        Returns:
            Dictionary with accuracy statistics
        """
        if not self.routing_decisions:
            return {
                "total_decisions": 0,
                "avg_confidence": 0.0,
                "clarification_rate": 0.0,
                "by_domain": {},
            }

        total = len(self.routing_decisions)
        total_confidence = sum(d.confidence for d in self.routing_decisions)
        clarifications = sum(
            1 for d in self.routing_decisions if d.clarification_needed
        )

        # Group by domain
        by_domain: dict[str, dict[str, Any]] = {}
        for decision in self.routing_decisions:
            if decision.domain not in by_domain:
                by_domain[decision.domain] = {
                    "count": 0,
                    "avg_confidence": 0.0,
                    "clarification_rate": 0.0,
                }
            by_domain[decision.domain]["count"] += 1

        # Calculate per-domain stats
        for domain in by_domain:
            domain_decisions = [d for d in self.routing_decisions if d.domain == domain]
            domain_total = len(domain_decisions)
            domain_confidence = sum(d.confidence for d in domain_decisions)
            domain_clarifications = sum(
                1 for d in domain_decisions if d.clarification_needed
            )

            by_domain[domain]["avg_confidence"] = domain_confidence / domain_total
            by_domain[domain]["clarification_rate"] = (
                domain_clarifications / domain_total
            )

        return {
            "total_decisions": total,
            "avg_confidence": total_confidence / total,
            "clarification_rate": clarifications / total,
            "by_domain": by_domain,
        }

    def get_cost_summary(self) -> dict[str, Any]:
        """
        Calculate cost summary by domain.

        Returns:
            Dictionary with cost statistics
        """
        if not self.specialist_executions:
            return {
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "by_domain": {},
            }

        total_cost = sum(e.cost_usd for e in self.specialist_executions)
        total_tokens = sum(e.tokens_used for e in self.specialist_executions)

        # Group by domain
        by_domain: dict[str, dict[str, Any]] = {}
        for execution in self.specialist_executions:
            if execution.domain not in by_domain:
                by_domain[execution.domain] = {
                    "executions": 0,
                    "total_cost_usd": 0.0,
                    "total_tokens": 0,
                    "avg_cost_usd": 0.0,
                    "avg_tokens": 0,
                }

            by_domain[execution.domain]["executions"] += 1
            by_domain[execution.domain]["total_cost_usd"] += execution.cost_usd
            by_domain[execution.domain]["total_tokens"] += execution.tokens_used

        # Calculate averages
        for domain in by_domain:
            count = by_domain[domain]["executions"]
            by_domain[domain]["avg_cost_usd"] = (
                by_domain[domain]["total_cost_usd"] / count
            )
            by_domain[domain]["avg_tokens"] = by_domain[domain]["total_tokens"] / count

        return {
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
            "by_domain": by_domain,
        }

    def get_transition_stats(self) -> dict[str, Any]:
        """
        Get agent transition statistics.

        Returns:
            Dictionary with transition statistics
        """
        if not self.transitions:
            return {
                "total_transitions": 0,
                "unique_paths": 0,
                "most_common_transitions": [],
            }

        # Count transitions by path
        path_counts: dict[str, int] = {}
        for transition in self.transitions:
            path = f"{transition.from_agent}->{transition.to_agent}"
            path_counts[path] = path_counts.get(path, 0) + 1

        # Sort by frequency
        sorted_paths = sorted(path_counts.items(), key=lambda x: x[1], reverse=True)

        return {
            "total_transitions": len(self.transitions),
            "unique_paths": len(path_counts),
            "most_common_transitions": sorted_paths[:5],  # Top 5
        }

    def clear(self) -> None:
        """Clear all collected metrics."""
        self.routing_decisions.clear()
        self.transitions.clear()
        self.specialist_executions.clear()

        logger.debug("metrics_cleared")


# Global metrics instance (can be replaced with dependency injection)
_global_metrics = MultiAgentMetrics()


def get_metrics() -> MultiAgentMetrics:
    """
    Get global metrics instance.

    Returns:
        Global MultiAgentMetrics instance
    """
    return _global_metrics


@dataclass
class ToolMetrics:
    """Metrics for a single tool execution."""

    tool_name: str
    """Name of the tool"""

    success: bool
    """Whether execution succeeded"""

    duration: float
    """Execution duration in seconds"""

    error_type: str | None = None
    """Error type if failed"""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When tool was executed"""


@dataclass
class StepMetrics:
    """Metrics for a reasoning step."""

    step_number: int
    """Step number in reasoning loop"""

    duration: float
    """Step duration in seconds"""

    tokens_used: int
    """Tokens used in this step"""

    input_tokens: int = 0
    """Input tokens"""

    output_tokens: int = 0
    """Output tokens"""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When step occurred"""


@dataclass
class AgentMetrics:
    """
    Metrics for single-agent execution (compatibility class for DomainAgent).

    This class maintains compatibility with the existing DomainAgent while
    the system transitions to multi-agent metrics.
    """

    session_id: str
    """Unique session identifier"""

    agent_type: str
    """Type of agent (e.g., 'reasoning', 'router')"""

    model: str
    """LLM model used"""

    max_steps: int = 15
    """Maximum reasoning steps allowed"""

    budget_tokens: int = 100_000
    """Token budget for the session"""

    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When agent started"""

    end_time: datetime | None = None
    """When agent completed"""

    # Aliases for backward compatibility with DomainAgent
    run_start_time: datetime | None = None
    """When agent run started (alias for start_time)"""

    run_end_time: datetime | None = None
    """When agent run completed (alias for end_time)"""

    optimization_mode: str | None = None
    """Optimization mode for the run"""

    success: bool | None = None
    """Whether the run succeeded"""

    total_latency_seconds: float | None = None
    """Total latency of the run in seconds"""

    failure_reason: str | None = None
    """Reason for failure if unsuccessful"""

    total_tokens: int = 0
    """Total tokens used"""

    input_tokens: int = 0
    """Total input tokens"""

    output_tokens: int = 0
    """Total output tokens"""

    estimated_cost_usd: float = 0.0
    """Estimated cost in USD"""

    tool_calls: list[ToolMetrics] = field(default_factory=list)
    """Tool execution metrics"""

    steps: list[StepMetrics] = field(default_factory=list)
    """Reasoning step metrics"""

    errors: list[str] = field(default_factory=list)
    """Error types encountered"""

    def record_tool(
        self,
        tool_name: str,
        success: bool,
        duration: float,
        error_type: str | None = None,
    ) -> None:
        """
        Record a tool execution.

        Args:
            tool_name: Name of the tool
            success: Whether execution succeeded
            duration: Execution duration in seconds
            error_type: Error type if failed
        """
        metrics = ToolMetrics(
            tool_name=tool_name,
            success=success,
            duration=duration,
            error_type=error_type,
        )
        self.tool_calls.append(metrics)

        logger.debug(
            "tool_execution",
            session_id=self.session_id,
            tool_name=tool_name,
            success=success,
            duration=duration,
            error_type=error_type,
        )

    def record_step(
        self,
        step_number: int,
        duration: float,
        tokens_used: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """
        Record a reasoning step.

        Args:
            step_number: Step number in reasoning loop
            duration: Step duration in seconds
            tokens_used: Tokens used in this step
            input_tokens: Input tokens
            output_tokens: Output tokens
        """
        metrics = StepMetrics(
            step_number=step_number,
            duration=duration,
            tokens_used=tokens_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        self.steps.append(metrics)

        # Update totals
        self.total_tokens += tokens_used
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

        logger.debug(
            "reasoning_step",
            session_id=self.session_id,
            step_number=step_number,
            duration=duration,
            tokens_used=tokens_used,
        )

    def record_error(self, error_type: str) -> None:
        """
        Record an error.

        Args:
            error_type: Type of error encountered
        """
        self.errors.append(error_type)

        logger.debug(
            "agent_error",
            session_id=self.session_id,
            error_type=error_type,
        )

    def finalize(self) -> None:
        """Mark the agent execution as complete."""
        self.end_time = datetime.now(UTC)

        logger.debug(
            "agent_execution_complete",
            session_id=self.session_id,
            agent_type=self.agent_type,
            total_tokens=self.total_tokens,
            estimated_cost_usd=self.estimated_cost_usd,
            tool_calls=len(self.tool_calls),
            steps=len(self.steps),
            errors=len(self.errors),
        )

    async def export_json(self, filepath: Path) -> None:
        """Export metrics to JSON file asynchronously.

        Uses ``starboard.infra.io.write_json`` for non-blocking I/O
        so the event loop is not blocked during request handling.

        Args:
            filepath: Path to export to.
        """
        # Convert to dict
        data = {
            "session_id": self.session_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "max_steps": self.max_steps,
            "budget_tokens": self.budget_tokens,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_tokens": self.total_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "tool_calls": [
                {
                    "tool_name": t.tool_name,
                    "success": t.success,
                    "duration": t.duration,
                    "error_type": t.error_type,
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in self.tool_calls
            ],
            "steps": [
                {
                    "step_number": s.step_number,
                    "duration": s.duration,
                    "tokens_used": s.tokens_used,
                    "input_tokens": s.input_tokens,
                    "output_tokens": s.output_tokens,
                    "timestamp": s.timestamp.isoformat(),
                }
                for s in self.steps
            ],
            "errors": self.errors,
        }

        # Ensure parent directory exists
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        # Async write via infra.io
        await write_json(filepath, data)

        logger.debug("metrics_exported", filepath=str(filepath))
