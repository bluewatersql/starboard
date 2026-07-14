# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Observability context for distributed tracing and structured logging.

This module provides a lightweight, immutable context for passing observability
information through the call chain. All adapters should accept an optional
ObservabilityContext parameter and include its fields in log entries.

Standards Reference: .cursor/05_observability_and_cost.md
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ObservabilityContext:
    """Immutable context for distributed tracing and structured logging.

    Designed to be passed through adapter call chains to enable:
    - Distributed tracing (trace_id, span_id)
    - Request correlation across agent boundaries
    - Cost attribution (user_id, agent_domain)
    - Debugging and production monitoring

    Attributes:
        trace_id: Distributed tracing ID (correlates all operations in a request)
        span_id: Current span ID (for nested operations)
        conversation_id: Conversation/session identifier
        user_id: User identifier for attribution (optional)
        agent_domain: Current agent domain for cost attribution (optional)

    Example:
        >>> ctx = ObservabilityContext(
        ...     trace_id="trace-abc123",
        ...     span_id="span-def456",
        ...     conversation_id="conv-789",
        ...     user_id="user@example.com",
        ...     agent_domain="warehouse"
        ... )
        >>> logger.debug("operation_completed", extra=ctx.to_log_dict())
    """

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    user_id: str | None = None
    agent_domain: str | None = None

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured logging.

        Returns only non-None fields to avoid cluttering logs.

        Returns:
            Dictionary with observability fields for logger extra parameter.

        Example:
            >>> ctx = ObservabilityContext(trace_id="t1", span_id="s1")
            >>> logger.debug("event", extra=ctx.to_log_dict())
        """
        result: dict[str, Any] = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }
        if self.conversation_id:
            result["conversation_id"] = self.conversation_id
        if self.user_id:
            result["user_id"] = self.user_id
        if self.agent_domain:
            result["agent_domain"] = self.agent_domain
        return result

    def with_span(self, span_id: str | None = None) -> ObservabilityContext:
        """Create new context with a new span_id (for child operations).

        Args:
            span_id: New span ID. If None, generates a new UUID.

        Returns:
            New ObservabilityContext with same trace_id but new span_id.

        Example:
            >>> parent_ctx = ObservabilityContext(trace_id="t1")
            >>> child_ctx = parent_ctx.with_span()
            >>> assert parent_ctx.trace_id == child_ctx.trace_id
            >>> assert parent_ctx.span_id != child_ctx.span_id
        """
        return ObservabilityContext(
            trace_id=self.trace_id,
            span_id=span_id or str(uuid.uuid4()),
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            agent_domain=self.agent_domain,
        )

    def with_domain(self, agent_domain: str) -> ObservabilityContext:
        """Create new context with agent domain set.

        Args:
            agent_domain: Agent domain for cost attribution.

        Returns:
            New ObservabilityContext with domain set.

        Example:
            >>> ctx = ObservabilityContext(trace_id="t1")
            >>> wh_ctx = ctx.with_domain("warehouse")
            >>> assert wh_ctx.agent_domain == "warehouse"
        """
        return ObservabilityContext(
            trace_id=self.trace_id,
            span_id=self.span_id,
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            agent_domain=agent_domain,
        )


def create_observability_context(
    conversation_id: str = "",
    user_id: str | None = None,
    agent_domain: str | None = None,
) -> ObservabilityContext:
    """Factory function to create an observability context.

    Args:
        conversation_id: Conversation/session identifier
        user_id: User identifier for attribution
        agent_domain: Current agent domain

    Returns:
        New ObservabilityContext with generated trace_id and span_id.

    Example:
        >>> ctx = create_observability_context(
        ...     conversation_id="conv-123",
        ...     user_id="user@example.com"
        ... )
        >>> assert ctx.trace_id  # Auto-generated
    """
    return ObservabilityContext(
        conversation_id=conversation_id,
        user_id=user_id,
        agent_domain=agent_domain,
    )
