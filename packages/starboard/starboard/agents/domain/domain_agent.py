# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Domain agent as orchestration facade.

Thin orchestrator that coordinates 7 specialized components:
- ReasoningEngine: Handles LLM reasoning
- ToolExecutor: Executes tools with retry/circuit breaking
- EventStreamer: Emits events for real-time UX
- OutputBuilder: Formats final output
- CompleteToolWrapper: Normalizes LLM completion output
- StateInitializer: Builds initial agent state
- ReasoningLoop: Orchestrates the reasoning cycle

Design Pattern: Facade
- Coordinates complex subsystems with simple interface
- Delegates all work to specialized components
- Single responsibility per component
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from starboard_core.domain.models.llm import OptimizationMode

from starboard.adapters.llm.base import BaseLLMClient
from starboard.agents.config.agent_config import AgentConfig
from starboard.agents.domain.complete_tool import register_complete_tool
from starboard.agents.domain.event_streamer import EventStreamer
from starboard.agents.domain.output_builder import OutputBuilder
from starboard.agents.domain.partial_report import (
    build_context_summary as _build_context_summary_impl,
)
from starboard.agents.domain.partial_report import (
    generate_partial_report as _generate_partial_report_impl,
)
from starboard.agents.domain.reasoning_engine import ReasoningEngine
from starboard.agents.domain.reasoning_loop import (
    FINALIZATION_BUDGET,
    reasoning_loop_stream,
)
from starboard.agents.domain.reasoning_loop import (
    should_continue_reasoning as _should_continue_reasoning_impl,
)
from starboard.agents.domain.state_initializer import (
    StateInitializer,
)
from starboard.agents.domain.state_initializer import (
    build_handoff_context as _build_handoff_context_impl,
)
from starboard.agents.domain.tool_executor import ToolExecutor
from starboard.agents.events import (
    StreamingEvent,
    create_error_event,
)
from starboard.agents.events.user_events import FinalOutputEvent
from starboard.agents.observability.metrics import AgentMetrics
from starboard.agents.output.domain_output_mixin import DomainAgentOutputMixin
from starboard.agents.tools import ToolRegistry
from starboard.infra.observability.events import EventEmitter
from starboard.infra.observability.logging import get_logger
from starboard.infra.observability.tracing import get_tracer

logger = get_logger(__name__)
_tracer = get_tracer("starboard.agents")

# Re-export FINALIZATION_BUDGET for backward compatibility
__all__ = ["DomainAgent", "FINALIZATION_BUDGET"]


def _should_continue_reasoning(
    state: Any,
    max_steps: int = 15,
    enforce_budget: bool = True,
) -> bool:
    """Backward-compatible shim for tests that import from domain_agent.

    Tests call: _should_continue_reasoning(state, max_steps=15)
    Delegates to: reasoning_loop.should_continue_reasoning(state, config)
    """
    # Build a minimal config-like object with the fields that
    # should_continue_reasoning reads: max_steps, enforce_budget
    _config = AgentConfig(
        domain="query",  # irrelevant for continuation check
        model="stub",
        max_steps=max_steps,
        enforce_budget=enforce_budget,
    )
    return _should_continue_reasoning_impl(state, _config)


class DomainAgent(DomainAgentOutputMixin):
    """
    Domain agent - thin orchestration facade.

    Coordinates 7 specialized components instead of handling everything itself:
    1. ReasoningEngine - LLM reasoning & streaming
    2. ToolExecutor - Parallel tool execution with retries
    3. EventStreamer - Event creation & emission
    4. OutputBuilder - Final output formatting
    5. CompleteToolWrapper - LLM output normalization
    6. StateInitializer - Initial state construction
    7. ReasoningLoop - Main reasoning cycle orchestration

    Backward compatible with old DomainAgent API:
    - Same __init__ signature
    - Same run_stream() method
    - Same get_metrics() method

    Example:
        >>> agent = DomainAgent(llm_client, registry, config)
        >>> async for event in agent.run_stream("optimize this query", mode, context):
        ...     print(event)
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        tool_registry: ToolRegistry,
        config: AgentConfig,
        events: EventEmitter | None = None,
        enable_metrics: bool = True,
        session_id: str | None = None,
    ):
        """Initialize facade and create specialized components."""
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.config = config
        self.events = events or EventEmitter()
        self.enable_metrics = enable_metrics

        # Initialize metrics
        self.current_metrics: AgentMetrics | None = None
        if self.enable_metrics:
            self.current_metrics = AgentMetrics(
                session_id=session_id or f"run_{uuid.uuid4().hex[:8]}",
                agent_type="domain",
                model=config.model,
                max_steps=config.max_steps,
                budget_tokens=config.max_tokens,
            )

        # Create specialized components (delegation targets)
        self.reasoning = ReasoningEngine(
            llm_client=llm_client,
            tool_registry=tool_registry,
            max_steps=config.max_steps,
            temperature=config.temperature,
        )

        self.executor = ToolExecutor(
            tool_registry=tool_registry,
            enable_retry=True,
            max_retries=2,
            circuit_breaker_threshold=5,
        )

        self.streamer = EventStreamer()

        self.builder = OutputBuilder(
            config=config,
            metrics=self.current_metrics,
        )

        self.state_initializer = StateInitializer(config=config)

        # Register completion tool (backward compatibility)
        if config.domain and config.domain != "router":
            register_complete_tool(
                domain=config.domain,
                tool_registry=tool_registry,
            )

        logger.debug(
            "domain_agent_refactored_initialized",
            domain=config.domain,
            model=config.model,
        )

    def get_metrics(self) -> AgentMetrics | None:
        """Get current metrics."""
        return self.current_metrics

    # =========================================================================
    # Backward-compatible delegation methods
    # These preserve the old API for tests that call private methods directly.
    # =========================================================================

    def _initialize_state(
        self,
        user_input: str,
        mode: OptimizationMode,
        user_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Delegate to StateInitializer.initialize (backward compat)."""
        return self.state_initializer.initialize(user_input, mode, user_id, context)

    def _generate_partial_report(self, state: Any) -> dict[str, Any]:
        """Delegate to partial_report.generate_partial_report (backward compat)."""
        return _generate_partial_report_impl(state, self.config)

    def _build_handoff_context(
        self, conversation_history: list[dict[str, Any] | Any]
    ) -> str:
        """Delegate to state_initializer.build_handoff_context (backward compat)."""
        return _build_handoff_context_impl(conversation_history)

    def _build_context_summary(
        self,
        state: Any,
        tools_used: list[str],
        discovered: dict[str, Any],
    ) -> str:
        """Delegate to partial_report.build_context_summary (backward compat)."""
        return _build_context_summary_impl(state, tools_used, discovered)

    def _should_continue_reasoning(self, state: Any) -> bool:
        """Delegate to reasoning_loop.should_continue_reasoning (backward compat)."""
        return _should_continue_reasoning_impl(state, self.config)

    async def run_stream(
        self,
        user_input: str,
        mode: OptimizationMode,
        user_id: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamingEvent | FinalOutputEvent]:
        """
        Execute agent with streaming events (main entry point).

        Orchestrates all components to execute the agent:
        1. Initialize state (via StateInitializer)
        2. Loop: reason -> execute tools -> stream events (via reasoning_loop)
        3. Build & return final output (via OutputBuilder)

        Args:
            user_input: User's request
            mode: Optimization mode
            user_id: Authenticated user ID
            context: Additional context

        Yields:
            StreamingEvent or FinalOutputEvent instances
        """
        start_time = time.time()
        context = context or {}
        span = _tracer.start_span(
            "agent.run_stream",
            attributes={
                "agent.domain": self.config.domain or "unknown",
                "agent.model": self.config.model,
                "message.length": len(user_input),
            },
        )

        # Initialize metrics
        if self.current_metrics:
            self.current_metrics.run_start_time = datetime.now(UTC)
            self.current_metrics.optimization_mode = (
                mode.value if hasattr(mode, "value") else str(mode)
            )

        logger.info("agent_run_started", domain=self.config.domain)

        try:
            # Initialize state (via StateInitializer)
            state = self.state_initializer.initialize(
                user_input, mode, user_id, context
            )

            # Execute reasoning loop (CORE ORCHESTRATION - via reasoning_loop module)
            async for event in reasoning_loop_stream(
                state=state,
                config=self.config,
                reasoning=self.reasoning,
                executor=self.executor,
                streamer=self.streamer,
                builder=self.builder,
                metrics=self.current_metrics,
            ):
                yield event

            # Record completion metrics
            if self.current_metrics:
                self.current_metrics.run_end_time = datetime.now(UTC)
                self.current_metrics.success = True
                self.current_metrics.total_latency_seconds = time.time() - start_time

            span.set_attribute("agent.steps", state.current_step)
            span.set_attribute(
                "agent.duration_seconds", round(time.time() - start_time, 2)
            )
            span.end()

            logger.info(
                "agent_run_completed",
                domain=self.config.domain,
                steps=state.current_step,
                duration_seconds=round(time.time() - start_time, 2),
            )

        except Exception as e:  # noqa: BLE001 - top-level agent error boundary
            # Intentional: top-level agent error boundary — catch all to emit
            # error events and metrics rather than crashing the conversation.
            logger.error("agent_run_failed", error=str(e), exc_info=True)

            if self.current_metrics:
                self.current_metrics.run_end_time = datetime.now(UTC)
                self.current_metrics.success = False
                self.current_metrics.failure_reason = str(e)

            span.record_exception(e)
            span.end()

            # Emit error event
            yield create_error_event(
                step=0,
                error="Agent failed: " + str(e),
                error_type="fatal_error",
                is_recoverable=False,
            )
