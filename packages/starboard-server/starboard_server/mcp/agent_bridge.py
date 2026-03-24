# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Agent bridge: wraps domain agents as MCP tools with non-interactive execution.

Provides ``MCPAgentExecutor`` for headless agent invocation and
``MCPProgressBridge`` for forwarding agent events to MCP clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import TYPE_CHECKING, Any

import structlog

from starboard_server.agents.output.envelope import (
    AgentMetrics,
    AgentResultEnvelope,
    PartialInfo,
)
from starboard_server.agents.routing.routing_models import AgentDomain, RouteDecision
from starboard_server.infra.observability.events import (
    EventEmitter,
    EventType,
    StatusEvent,
)
from starboard_server.mcp.models import MCPAgentResponse, MCPResponseMetadata
from starboard_server.mcp.observability import (
    TokenBudgetTracker,
    create_root_span,
    log_tool_error,
    set_mcp_request_id,
)

if TYPE_CHECKING:
    from starboard_server.agents.agent_factory import AgentFactory
    from starboard_server.agents.events.user_events import FinalOutputEvent
    from starboard_server.agents.routing.intent_router import IntentRouter

logger = structlog.get_logger(__name__)

# All 8 domain agent tool names
AGENT_DOMAINS: tuple[AgentDomain, ...] = (
    "query",
    "job",
    "uc",
    "cluster",
    "analytics",
    "warehouse",
    "diagnostic",
    "discovery",
)

_AGENT_DESCRIPTIONS: dict[str, str] = {
    "query_agent": (
        "Analyze SQL query performance, execution plans, and suggest "
        "optimizations for Databricks SQL queries"
    ),
    "job_agent": (
        "Analyze Databricks job configuration, run history, failures, "
        "and suggest performance improvements"
    ),
    "uc_agent": (
        "Explore Unity Catalog assets, lineage, governance policies, "
        "and storage optimization"
    ),
    "cluster_agent": (
        "Analyze Databricks cluster configuration, health, resource "
        "utilization, and autoscaling"
    ),
    "analytics_agent": (
        "Run FinOps cost analysis, billing queries, budget forecasting, "
        "and usage trend analysis"
    ),
    "warehouse_agent": (
        "Analyze SQL warehouse portfolio, health, sizing, user activity, and chargeback"
    ),
    "diagnostic_agent": (
        "Troubleshoot Databricks issues with error pattern detection, "
        "log analysis, and root cause analysis"
    ),
    "discovery_agent": (
        "Run comprehensive workspace health assessment and product usage discovery"
    ),
}

_AGENT_TOOL_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "Natural language request or question",
        },
        "workspace_id": {
            "type": "string",
            "description": "Workspace ID override (optional, uses default)",
        },
        "conversation_id": {
            "type": "string",
            "description": "Conversation ID for multi-turn continuity (optional)",
        },
        "config_overrides": {
            "type": "object",
            "description": "Optional agent configuration overrides",
            "properties": {
                "model": {"type": "string", "description": "LLM model override"},
                "temperature": {
                    "type": "number",
                    "description": "Temperature override",
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Max reasoning iterations",
                },
            },
        },
    },
    "required": ["message"],
}

AGENT_TOOL_METADATA: list[dict[str, Any]] = [
    {
        "name": f"{domain}_agent",
        "description": _AGENT_DESCRIPTIONS[f"{domain}_agent"],
        "parameters": _AGENT_TOOL_PARAMS,
    }
    for domain in AGENT_DOMAINS
]

# Map tool names to domains
TOOL_NAME_TO_DOMAIN: dict[str, AgentDomain] = {
    f"{domain}_agent": domain for domain in AGENT_DOMAINS
}

LOW_CONFIDENCE_THRESHOLD = 0.7


def generate_conversation_id() -> str:
    """Generate a unique conversation ID for multi-turn sessions."""
    return f"mcp-conv-{uuid.uuid4().hex[:12]}"


class MCPProgressBridge:
    """Forwards ``EventEmitter`` INFO events to a callback for MCP notifications.

    Subscribes to an ``EventEmitter`` and forwards ``INFO`` events through
    a provided callback. Automatically unsubscribes on teardown.

    Args:
        emitter: The event emitter to subscribe to.
        callback: Function called with each INFO ``StatusEvent``.
        include_trace: Whether to also forward TRACE events.
    """

    def __init__(
        self,
        emitter: EventEmitter,
        callback: Any | None = None,
        *,
        include_trace: bool = False,
    ) -> None:
        self._emitter = emitter
        self._callback = callback
        self._include_trace = include_trace
        self._events: list[StatusEvent] = []
        self._subscribed = False

    def subscribe(self) -> None:
        """Start listening for events."""
        if not self._subscribed:
            self._emitter.on(self._handle_event)
            self._subscribed = True

    def unsubscribe(self) -> None:
        """Stop listening and clean up."""
        if self._subscribed:
            with contextlib.suppress(ValueError):
                self._emitter.handlers.remove(self._handle_event)
            self._subscribed = False

    @property
    def events(self) -> list[StatusEvent]:
        """Return collected events."""
        return list(self._events)

    def _handle_event(self, event: StatusEvent) -> None:
        """Process an event from the emitter."""
        try:
            if (
                event.type == EventType.INFO
                or self._include_trace
                and event.type == EventType.TRACE
            ):
                self._events.append(event)
                if self._callback is not None:
                    self._callback(event)
        except Exception:
            logger.debug("mcp_progress_bridge_handler_error", exc_info=True)


class MCPAgentExecutor:
    """Executes domain agents in non-interactive MCP mode.

    Wraps ``AgentFactory`` and optionally ``IntentRouter`` to provide
    headless agent execution with timeout handling, token budget
    enforcement, and automatic routing on low confidence.

    Args:
        agent_factory: Factory for creating domain agents.
        intent_router: Optional router for when domain is not specified.
        token_budget_tracker: Optional token budget tracker.
        default_timeout: Default agent execution timeout in seconds.
    """

    def __init__(
        self,
        agent_factory: AgentFactory,
        intent_router: IntentRouter | None = None,
        token_budget_tracker: TokenBudgetTracker | None = None,
        default_timeout: int = 120,
    ) -> None:
        self._agent_factory = agent_factory
        self._intent_router = intent_router
        self._token_budget_tracker = token_budget_tracker
        self._default_timeout = default_timeout

    async def execute(
        self,
        message: str,
        workspace_id: str,
        *,
        domain: AgentDomain | None = None,
        session_id: str = "default",
        conversation_id: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> MCPAgentResponse:
        """Execute a domain agent in non-interactive mode.

        Args:
            message: User message to process.
            workspace_id: Resolved workspace identifier.
            domain: Optional domain (skips router if provided).
            session_id: MCP session identifier.
            conversation_id: Optional conversation ID for continuity.
            config_overrides: Optional overrides (agent_timeout, token_budget).

        Returns:
            Structured ``MCPAgentResponse`` with envelope and metadata.
        """
        overrides = config_overrides or {}
        timeout = overrides.get("agent_timeout", self._default_timeout)

        # Ensure every execution has a conversation_id for multi-turn tracking
        if conversation_id is None:
            conversation_id = generate_conversation_id()

        # Create span for tracing
        root_span = create_root_span(
            agent_domain=domain or "unknown",
            session_id=session_id,
            workspace_id=workspace_id,
        )
        set_mcp_request_id(root_span.trace_id)
        start_time = time.monotonic()

        # Check token budget before executing
        if (
            self._token_budget_tracker is not None
            and not self._token_budget_tracker.check_budget(session_id)
        ):
            return self._budget_exceeded_response(
                domain=domain or "unknown",
                workspace_id=workspace_id,
                trace_id=root_span.trace_id,
                _session_id=session_id,
                start_time=start_time,
            )

        # Route if domain not specified
        confidence = 1.0
        low_confidence = False
        auto_selected = False
        reasoning = "Domain specified directly"

        if domain is None:
            if self._intent_router is None:
                return self._error_response(
                    domain="unknown",
                    workspace_id=workspace_id,
                    trace_id=root_span.trace_id,
                    start_time=start_time,
                    error_msg="No domain specified and no intent router available",
                )
            route_decision: RouteDecision = await self._intent_router.classify_intent(
                message, []
            )
            domain = route_decision.domain
            confidence = route_decision.confidence
            reasoning = route_decision.reasoning or ""
            if confidence < LOW_CONFIDENCE_THRESHOLD:
                low_confidence = True
                auto_selected = True

        # Get agent
        agent = self._agent_factory.get_agent(domain)

        # Set up progress bridge
        emitter = self._agent_factory.events or EventEmitter()
        bridge = MCPProgressBridge(emitter)
        bridge.subscribe()

        try:
            # Execute with timeout
            envelope = await asyncio.wait_for(
                self._run_agent(agent, message, workspace_id, conversation_id),
                timeout=timeout,
            )
        except TimeoutError:
            bridge.unsubscribe()
            return self._timeout_response(
                domain=domain,
                workspace_id=workspace_id,
                trace_id=root_span.trace_id,
                confidence=confidence,
                low_confidence=low_confidence,
                auto_selected=auto_selected,
                reasoning=reasoning,
                start_time=start_time,
                conversation_id=conversation_id,
            )
        except Exception as exc:
            bridge.unsubscribe()
            log_tool_error(
                root_span,
                f"{domain}_agent",
                error_code="AGENT_EXECUTION_ERROR",
                error_message=str(exc),
                session_id=session_id,
                workspace_id=workspace_id,
            )
            return self._error_response(
                domain=domain,
                workspace_id=workspace_id,
                trace_id=root_span.trace_id,
                start_time=start_time,
                error_msg=str(exc),
            )
        finally:
            bridge.unsubscribe()

        duration_ms = (time.monotonic() - start_time) * 1000

        # Record token usage if available
        if (
            self._token_budget_tracker is not None
            and envelope is not None
            and envelope.metrics is not None
        ):
            self._token_budget_tracker.record_usage(
                session_id, envelope.metrics.tokens_used
            )

        metadata = MCPResponseMetadata(
            workspace_id_used=workspace_id,
            domain_selected=domain,
            confidence=confidence,
            low_confidence=low_confidence,
            auto_selected_path=auto_selected,
            reasoning_summary=reasoning,
            trace_id=root_span.trace_id,
            duration_ms=round(duration_ms, 2),
            conversation_id=conversation_id,
        )

        return MCPAgentResponse(
            status="success",
            workspace_id_used=workspace_id,
            agent_domain=domain,
            response_text=self._extract_response_text(envelope),
            tools_used=self._extract_tools_used(envelope),
            confidence=confidence,
            trace_id=root_span.trace_id,
            duration_ms=round(duration_ms, 2),
            envelope=envelope.model_dump() if envelope else {},
            mcp_metadata=metadata,
            progress_events=self._serialize_progress_events(bridge),
        )

    async def _run_agent(
        self,
        agent: Any,
        message: str,
        workspace_id: str,
        conversation_id: str | None,
    ) -> AgentResultEnvelope | None:
        """Run agent's streaming loop and collect the final output envelope.

        The agent runs in non-interactive mode: ``request_user_input``
        calls return immediately with the first suggestion or a synthetic
        response.
        """
        from datetime import UTC, datetime

        from starboard_server.agents.events.user_events import FinalOutputEvent
        from starboard_server.agents.output.envelope_translator import (
            EnvelopeTranslator,
        )

        final_output: FinalOutputEvent | None = None

        agent_context: dict[str, Any] = {"workspace_id": workspace_id}
        if conversation_id is not None:
            agent_context["conversation_id"] = conversation_id

        try:
            async for event in agent.run_stream(
                user_input=message,
                mode="optimize",
                user_id="mcp",
                context=agent_context,
            ):
                if isinstance(event, FinalOutputEvent):
                    final_output = event
        except Exception:
            logger.debug("agent_run_stream_error", exc_info=True)
            raise

        agent_domain = agent.config.domain or "unknown"

        if final_output is not None and final_output.output is not None:
            translator = EnvelopeTranslator()
            return translator.translate(
                final_output.output,
                domain=agent_domain,
                trace_id="",
            )

        # Fallback: return a minimal envelope
        return AgentResultEnvelope(
            domain=agent_domain,
            timestamp=datetime.now(UTC),
            trace_id="",
            status="error",
            report_type="advisor",
            payload={"error": "No output produced"},
            metrics=AgentMetrics(
                tokens_used=0,
                cost_usd=0.0,
                duration_seconds=0.0,
                steps_taken=0,
            ),
            partial=None,
        )

    def _extract_response_text(self, envelope: AgentResultEnvelope | None) -> str:
        """Extract human-readable text from the envelope payload."""
        if envelope is None:
            return ""
        payload = envelope.payload
        # Try common keys for response text
        for key in ("summary", "overview", "response", "message", "text"):
            if key in payload and isinstance(payload[key], str):
                return payload[key]
        return str(payload) if payload else ""

    def _extract_tools_used(self, envelope: AgentResultEnvelope | None) -> list[str]:
        """Extract list of tools used from envelope payload."""
        if envelope is None:
            return []
        payload = envelope.payload
        tools = payload.get("tools_used", [])
        if isinstance(tools, list):
            return [str(t) for t in tools]
        return []

    @staticmethod
    def _serialize_progress_events(
        bridge: MCPProgressBridge,
    ) -> list[dict[str, Any]] | None:
        """Serialize collected progress events for inclusion in responses."""
        events = bridge.events
        if not events:
            return None
        return [
            {
                "type": event.type.value
                if hasattr(event.type, "value")
                else str(event.type),
                "source": event.source,
                "message": event.message,
            }
            for event in events
        ]

    def _timeout_response(
        self,
        *,
        domain: str,
        workspace_id: str,
        trace_id: str,
        confidence: float,
        low_confidence: bool,
        auto_selected: bool,
        reasoning: str,
        start_time: float,
        conversation_id: str | None,
    ) -> MCPAgentResponse:
        """Build a partial response for timeout."""
        duration_ms = (time.monotonic() - start_time) * 1000
        metadata = MCPResponseMetadata(
            workspace_id_used=workspace_id,
            domain_selected=domain,
            confidence=confidence,
            low_confidence=low_confidence,
            auto_selected_path=auto_selected,
            reasoning_summary=reasoning,
            trace_id=trace_id,
            duration_ms=round(duration_ms, 2),
            conversation_id=conversation_id,
        )
        return MCPAgentResponse(
            status="timeout",
            workspace_id_used=workspace_id,
            agent_domain=domain,
            response_text="Agent execution timed out. Partial results may be available.",
            trace_id=trace_id,
            duration_ms=round(duration_ms, 2),
            envelope={
                "status": "partial",
                "partial": PartialInfo(
                    reason="timeout",
                    recovery_hint="Retry with a longer timeout or simpler query.",
                ).model_dump(),
            },
            mcp_metadata=metadata,
        )

    def _budget_exceeded_response(
        self,
        *,
        domain: str,
        workspace_id: str,
        trace_id: str,
        _session_id: str,
        start_time: float,
    ) -> MCPAgentResponse:
        """Build a partial response for budget exceeded."""
        duration_ms = (time.monotonic() - start_time) * 1000
        metadata = MCPResponseMetadata(
            workspace_id_used=workspace_id,
            domain_selected=domain,
            confidence=0.0,
            low_confidence=False,
            auto_selected_path=False,
            reasoning_summary="Token budget exceeded before execution",
            trace_id=trace_id,
            duration_ms=round(duration_ms, 2),
        )
        return MCPAgentResponse(
            status="partial",
            workspace_id_used=workspace_id,
            agent_domain=domain,
            response_text="Token budget exceeded for this session.",
            trace_id=trace_id,
            duration_ms=round(duration_ms, 2),
            envelope={
                "status": "budget_exceeded",
                "partial": PartialInfo(
                    reason="budget_exceeded",
                    recovery_hint="Start a new session or increase the token budget.",
                ).model_dump(),
            },
            mcp_metadata=metadata,
        )

    def _error_response(
        self,
        *,
        domain: str,
        workspace_id: str,
        trace_id: str,
        start_time: float,
        error_msg: str,
    ) -> MCPAgentResponse:
        """Build an error response."""
        duration_ms = (time.monotonic() - start_time) * 1000
        metadata = MCPResponseMetadata(
            workspace_id_used=workspace_id,
            domain_selected=domain,
            confidence=0.0,
            low_confidence=False,
            auto_selected_path=False,
            reasoning_summary=f"Error: {error_msg}",
            trace_id=trace_id,
            duration_ms=round(duration_ms, 2),
        )
        return MCPAgentResponse(
            status="error",
            workspace_id_used=workspace_id,
            agent_domain=domain,
            response_text=error_msg,
            trace_id=trace_id,
            duration_ms=round(duration_ms, 2),
            envelope={"status": "error", "error": error_msg},
            mcp_metadata=metadata,
        )
