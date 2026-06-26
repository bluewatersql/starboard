# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for ObservabilityContext.

Tests the observability context dataclass for distributed tracing.
"""

import uuid

import pytest
from starboard_server.infra.observability import (
    ObservabilityContext,
    create_observability_context,
)


class TestObservabilityContext:
    """Tests for ObservabilityContext dataclass."""

    def test_default_values(self) -> None:
        """Test that defaults are generated correctly."""
        ctx = ObservabilityContext()
        assert ctx.trace_id  # Should be auto-generated UUID
        assert ctx.span_id  # Should be auto-generated UUID
        assert ctx.conversation_id == ""
        assert ctx.user_id is None
        assert ctx.agent_domain is None

    def test_custom_values(self) -> None:
        """Test that custom values are preserved."""
        ctx = ObservabilityContext(
            trace_id="trace-123",
            span_id="span-456",
            conversation_id="conv-789",
            user_id="user@example.com",
            agent_domain="warehouse",
        )
        assert ctx.trace_id == "trace-123"
        assert ctx.span_id == "span-456"
        assert ctx.conversation_id == "conv-789"
        assert ctx.user_id == "user@example.com"
        assert ctx.agent_domain == "warehouse"

    def test_is_frozen(self) -> None:
        """Test that context is immutable."""
        ctx = ObservabilityContext(trace_id="trace-123")
        with pytest.raises(AttributeError):
            ctx.trace_id = "new-trace"  # type: ignore

    def test_to_log_dict_minimal(self) -> None:
        """Test to_log_dict with minimal fields."""
        ctx = ObservabilityContext(trace_id="t1", span_id="s1")
        log_dict = ctx.to_log_dict()
        assert log_dict == {"trace_id": "t1", "span_id": "s1"}

    def test_to_log_dict_full(self) -> None:
        """Test to_log_dict with all fields."""
        ctx = ObservabilityContext(
            trace_id="t1",
            span_id="s1",
            conversation_id="c1",
            user_id="u1",
            agent_domain="warehouse",
        )
        log_dict = ctx.to_log_dict()
        assert log_dict == {
            "trace_id": "t1",
            "span_id": "s1",
            "conversation_id": "c1",
            "user_id": "u1",
            "agent_domain": "warehouse",
        }

    def test_with_span_creates_new_context(self) -> None:
        """Test with_span creates new context with new span_id."""
        parent = ObservabilityContext(
            trace_id="trace-123",
            span_id="span-parent",
            conversation_id="conv-1",
            user_id="user@example.com",
        )
        child = parent.with_span()

        # trace_id should be same
        assert child.trace_id == parent.trace_id
        # span_id should be different
        assert child.span_id != parent.span_id
        # other fields preserved
        assert child.conversation_id == parent.conversation_id
        assert child.user_id == parent.user_id

    def test_with_span_custom_id(self) -> None:
        """Test with_span with custom span_id."""
        parent = ObservabilityContext(trace_id="trace-123")
        child = parent.with_span("custom-span-id")
        assert child.span_id == "custom-span-id"

    def test_with_domain(self) -> None:
        """Test with_domain sets agent domain."""
        ctx = ObservabilityContext(trace_id="t1")
        wh_ctx = ctx.with_domain("warehouse")
        assert wh_ctx.agent_domain == "warehouse"
        assert wh_ctx.trace_id == ctx.trace_id


class TestCreateObservabilityContext:
    """Tests for create_observability_context factory."""

    def test_creates_with_auto_ids(self) -> None:
        """Test factory generates trace_id and span_id."""
        ctx = create_observability_context()
        # Should be valid UUIDs
        uuid.UUID(ctx.trace_id)
        uuid.UUID(ctx.span_id)

    def test_creates_with_params(self) -> None:
        """Test factory accepts all parameters."""
        ctx = create_observability_context(
            conversation_id="conv-123",
            user_id="user@example.com",
            agent_domain="query",
        )
        assert ctx.conversation_id == "conv-123"
        assert ctx.user_id == "user@example.com"
        assert ctx.agent_domain == "query"
