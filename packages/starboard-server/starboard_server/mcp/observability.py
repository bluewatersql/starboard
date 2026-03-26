# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""MCP observability: spans, structured logging, cost tags, and token budgets.

Provides lightweight span tracking, structured log helpers for all MCP events,
cost attribution via ``MCPCostTag``, and per-session token budget enforcement.
Integrates with the existing ``ObservabilityContext`` and ``structlog`` setup.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from starboard_server.infra.observability.context import ObservabilityContext
from starboard_server.infra.observability.logging import get_logger, set_request_id

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Cost Attribution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MCPCostTag:
    """Cost attribution tag attached to every MCP LLM call.

    Attributes:
        feature: Always ``"mcp"`` for MCP-originated calls.
        agent: Domain agent name (e.g. ``"query"``, ``"job"``).
        workspace_id: Resolved workspace identifier.
        mcp_session_id: MCP session identifier.
        tenant_id: Optional tenant for multi-tenant attribution.
        user_id: Optional user identifier.
        team: Optional team name.
        environment: Optional environment label (production/staging/dev).
    """

    feature: str = "mcp"
    agent: str = ""
    workspace_id: str = ""
    mcp_session_id: str = ""
    tenant_id: str | None = None
    user_id: str | None = None
    team: str | None = None
    environment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured logging, omitting None values."""
        result: dict[str, Any] = {
            "feature": self.feature,
            "agent": self.agent,
            "workspace_id": self.workspace_id,
            "mcp_session_id": self.mcp_session_id,
        }
        if self.tenant_id is not None:
            result["tenant_id"] = self.tenant_id
        if self.user_id is not None:
            result["user_id"] = self.user_id
        if self.team is not None:
            result["team"] = self.team
        if self.environment is not None:
            result["environment"] = self.environment
        return result


# ---------------------------------------------------------------------------
# Span Tracking
# ---------------------------------------------------------------------------


@dataclass
class MCPSpan:
    """Lightweight span for MCP operation tracking.

    Captures timing, status, and attributes for a single operation within
    the MCP execution pipeline.

    Attributes:
        name: Span name (e.g. ``mcp.tool.resolve_query``).
        trace_id: Parent trace identifier.
        span_id: Unique span identifier.
        parent_span_id: Parent span ID for nesting.
        start_time: Monotonic start timestamp.
        end_time: Monotonic end timestamp (set on close).
        status: ``"ok"`` or ``"error"``.
        attributes: Arbitrary span attributes.
        error_code: Error code if status is ``"error"``.
    """

    name: str
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: str | None = None
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None
    status: str = "ok"
    attributes: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None

    @property
    def duration_ms(self) -> float:
        """Wall-clock duration in milliseconds."""
        end = self.end_time if self.end_time is not None else time.monotonic()
        return (end - self.start_time) * 1000

    def close(self, status: str = "ok", error_code: str | None = None) -> None:
        """Close the span and record final status.

        Args:
            status: Final status (``"ok"`` or ``"error"``).
            error_code: Machine-readable error code if applicable.
        """
        self.end_time = time.monotonic()
        self.status = status
        if error_code is not None:
            self.error_code = error_code

    def child(self, name: str) -> MCPSpan:
        """Create a child span inheriting the trace context.

        Args:
            name: Child span name.

        Returns:
            New ``MCPSpan`` with same ``trace_id`` and this span as parent.
        """
        return MCPSpan(
            name=name,
            trace_id=self.trace_id,
            parent_span_id=self.span_id,
        )

    def to_log_dict(self) -> dict[str, Any]:
        """Convert span to a dict suitable for structured logging."""
        result: dict[str, Any] = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "span_name": self.name,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
        }
        if self.parent_span_id is not None:
            result["parent_span_id"] = self.parent_span_id
        if self.error_code is not None:
            result["error_code"] = self.error_code
        result.update(self.attributes)
        return result


def create_root_span(
    tool_name: str | None = None,
    agent_domain: str | None = None,
    *,
    session_id: str = "",
    workspace_id: str = "",
) -> MCPSpan:
    """Create a root span for an MCP call.

    Args:
        tool_name: Tool name for tool calls.
        agent_domain: Agent domain for agent calls.
        session_id: MCP session identifier.
        workspace_id: Resolved workspace identifier.

    Returns:
        New root ``MCPSpan`` with appropriate name and attributes.
    """
    if tool_name:
        name = f"mcp.tool.{tool_name}"
    elif agent_domain:
        name = f"mcp.agent.{agent_domain}"
    else:
        name = "mcp.unknown"

    span = MCPSpan(name=name)
    span.attributes["feature"] = "mcp"
    if session_id:
        span.attributes["mcp_session_id"] = session_id
    if workspace_id:
        span.attributes["mcp.workspace_id"] = workspace_id
    if tool_name:
        span.attributes["mcp.tool_name"] = tool_name
    if agent_domain:
        span.attributes["mcp.agent_domain"] = agent_domain
    return span


def create_observability_context_from_span(
    span: MCPSpan,
    *,
    session_id: str = "",
    user_id: str | None = None,
    agent_domain: str | None = None,
) -> ObservabilityContext:
    """Create an ``ObservabilityContext`` from an MCP span.

    Bridges MCP spans to the existing observability infrastructure so that
    downstream tool/LLM calls inherit the trace context.

    Args:
        span: The MCP root span.
        session_id: MCP session identifier (maps to conversation_id).
        user_id: Optional user identifier.
        agent_domain: Optional agent domain.

    Returns:
        ``ObservabilityContext`` with trace_id and span_id from the span.
    """
    return ObservabilityContext(
        trace_id=span.trace_id,
        span_id=span.span_id,
        conversation_id=session_id,
        user_id=user_id,
        agent_domain=agent_domain,
    )


# ---------------------------------------------------------------------------
# Structured Logging Helpers
# ---------------------------------------------------------------------------

_COMMON_FIELDS = ("trace_id", "span_id", "mcp_session_id", "workspace_id", "feature")


def _base_log_extra(
    span: MCPSpan,
    *,
    session_id: str = "",
    workspace_id: str = "",
) -> dict[str, Any]:
    """Build the base extra dict required for all MCP log events."""
    return {
        "trace_id": span.trace_id,
        "span_id": span.span_id,
        "mcp_session_id": session_id,
        "workspace_id": workspace_id,
        "feature": "mcp",
    }


def log_tool_started(
    span: MCPSpan,
    tool_name: str,
    *,
    session_id: str = "",
    workspace_id: str = "",
) -> None:
    """Log ``mcp_tool_started`` event."""
    extra = _base_log_extra(span, session_id=session_id, workspace_id=workspace_id)
    extra["mcp_tool_name"] = tool_name
    logger.info("mcp_tool_started", **extra)


def log_tool_completed(
    span: MCPSpan,
    tool_name: str,
    *,
    session_id: str = "",
    workspace_id: str = "",
    duration_ms: float = 0.0,
    truncated: bool = False,
) -> None:
    """Log ``mcp_tool_completed`` event."""
    extra = _base_log_extra(span, session_id=session_id, workspace_id=workspace_id)
    extra["mcp_tool_name"] = tool_name
    extra["duration_ms"] = round(duration_ms, 2)
    if truncated:
        extra["truncated"] = True
    logger.info("mcp_tool_completed", **extra)


def log_tool_error(
    span: MCPSpan,
    tool_name: str,
    error_code: str,
    error_message: str,
    *,
    session_id: str = "",
    workspace_id: str = "",
    duration_ms: float = 0.0,
) -> None:
    """Log ``mcp_tool_error`` event."""
    extra = _base_log_extra(span, session_id=session_id, workspace_id=workspace_id)
    extra["mcp_tool_name"] = tool_name
    extra["error_code"] = error_code
    extra["error_message"] = error_message
    extra["duration_ms"] = round(duration_ms, 2)
    logger.error("mcp_tool_error", **extra)


def log_tool_truncated(
    span: MCPSpan,
    tool_name: str,
    *,
    session_id: str = "",
    workspace_id: str = "",
    original_size: int = 0,
    truncated_size: int = 0,
) -> None:
    """Log ``mcp_tool_truncated`` warning event."""
    extra = _base_log_extra(span, session_id=session_id, workspace_id=workspace_id)
    extra["mcp_tool_name"] = tool_name
    extra["original_size"] = original_size
    extra["truncated_size"] = truncated_size
    logger.warning("mcp_tool_truncated", **extra)


def log_rate_limited(
    span: MCPSpan,
    *,
    session_id: str = "",
    workspace_id: str = "",
    limit_type: str = "session",
) -> None:
    """Log ``mcp_rate_limited`` warning event."""
    extra = _base_log_extra(span, session_id=session_id, workspace_id=workspace_id)
    extra["limit_type"] = limit_type
    logger.warning("mcp_rate_limited", **extra)


def log_circuit_open(
    span: MCPSpan,
    *,
    session_id: str = "",
    workspace_id: str = "",
) -> None:
    """Log ``mcp_circuit_open`` warning event."""
    extra = _base_log_extra(span, session_id=session_id, workspace_id=workspace_id)
    logger.warning("mcp_circuit_open", **extra)


def log_auth_failed(
    span: MCPSpan,
    *,
    session_id: str = "",
    workspace_id: str = "",
    reason: str = "",
) -> None:
    """Log ``mcp_auth_failed`` error event."""
    extra = _base_log_extra(span, session_id=session_id, workspace_id=workspace_id)
    if reason:
        extra["reason"] = reason
    logger.error("mcp_auth_failed", **extra)


def log_pii_redacted(
    span: MCPSpan,
    *,
    session_id: str = "",
    workspace_id: str = "",
    field_count: int = 0,
) -> None:
    """Log ``mcp_pii_redacted`` debug event."""
    extra = _base_log_extra(span, session_id=session_id, workspace_id=workspace_id)
    extra["field_count"] = field_count
    logger.debug("mcp_pii_redacted", **extra)


def log_budget_exceeded(
    span: MCPSpan,
    *,
    session_id: str = "",
    workspace_id: str = "",
    budget: int = 0,
    used: int = 0,
) -> None:
    """Log ``mcp_budget_exceeded`` warning event."""
    extra = _base_log_extra(span, session_id=session_id, workspace_id=workspace_id)
    extra["token_budget"] = budget
    extra["tokens_used"] = used
    logger.warning("mcp_budget_exceeded", **extra)


def set_mcp_request_id(trace_id: str) -> None:
    """Set the trace_id as the request ID context var for downstream code.

    This ensures that downstream LLM clients and tools pick up the
    MCP trace_id for correlation.

    Args:
        trace_id: The trace identifier to propagate.
    """
    set_request_id(trace_id)


# ---------------------------------------------------------------------------
# Token Budget Tracker
# ---------------------------------------------------------------------------


class TokenBudgetTracker:
    """Tracks cumulative token usage per MCP session.

    Thread-safe in-memory tracker. Token budgets are enforced at the
    session level; when a session exceeds its budget, ``check_budget``
    returns ``False``.

    Attributes:
        default_budget: Default token budget (``None`` means unlimited).
    """

    def __init__(self, default_budget: int | None = None) -> None:
        self._default_budget = default_budget
        self._sessions: dict[str, int] = {}
        self._budgets: dict[str, int | None] = {}

    @property
    def default_budget(self) -> int | None:
        """Return the default token budget."""
        return self._default_budget

    def set_budget(self, session_id: str, budget: int | None) -> None:
        """Override the budget for a specific session.

        Args:
            session_id: MCP session identifier.
            budget: Token budget (``None`` for unlimited).
        """
        self._budgets[session_id] = budget

    def get_used(self, session_id: str) -> int:
        """Return tokens used so far for a session.

        Args:
            session_id: MCP session identifier.

        Returns:
            Cumulative tokens consumed in this session.
        """
        return self._sessions.get(session_id, 0)

    def get_budget(self, session_id: str) -> int | None:
        """Return the effective budget for a session.

        Args:
            session_id: MCP session identifier.

        Returns:
            Token budget, or ``None`` if unlimited.
        """
        return self._budgets.get(session_id, self._default_budget)

    def record_usage(self, session_id: str, tokens: int) -> None:
        """Record token usage for a session.

        Args:
            session_id: MCP session identifier.
            tokens: Number of tokens consumed.
        """
        self._sessions[session_id] = self._sessions.get(session_id, 0) + tokens

    def check_budget(self, session_id: str) -> bool:
        """Check whether a session is within its token budget.

        Args:
            session_id: MCP session identifier.

        Returns:
            ``True`` if the session can proceed, ``False`` if budget is exceeded.
        """
        budget = self.get_budget(session_id)
        if budget is None:
            return True
        return self.get_used(session_id) < budget

    def remaining(self, session_id: str) -> int | None:
        """Return remaining tokens for a session.

        Args:
            session_id: MCP session identifier.

        Returns:
            Remaining tokens, or ``None`` if unlimited.
        """
        budget = self.get_budget(session_id)
        if budget is None:
            return None
        return max(0, budget - self.get_used(session_id))

    def reset_session(self, session_id: str) -> None:
        """Reset token usage for a session.

        Args:
            session_id: MCP session identifier.
        """
        self._sessions.pop(session_id, None)
        self._budgets.pop(session_id, None)
