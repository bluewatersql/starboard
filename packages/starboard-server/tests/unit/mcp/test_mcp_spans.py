# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for MCP span tracking."""

from starboard_server.mcp.observability import (
    MCPSpan,
    create_observability_context_from_span,
    create_root_span,
)


class TestMCPSpan:
    """Tests for MCPSpan lifecycle."""

    def test_root_span_created_for_tool_call(self) -> None:
        span = create_root_span(tool_name="resolve_query")
        assert span.name == "mcp.tool.resolve_query"
        assert span.trace_id
        assert span.span_id
        assert span.parent_span_id is None

    def test_root_span_created_for_agent_call(self) -> None:
        span = create_root_span(agent_domain="query")
        assert span.name == "mcp.agent.query"
        assert span.attributes["mcp.agent_domain"] == "query"

    def test_child_spans_created_in_order(self) -> None:
        root = create_root_span(tool_name="resolve_query")
        child1 = root.child("mcp.workspace.resolve")
        child2 = root.child("mcp.auth.credentials")

        assert child1.trace_id == root.trace_id
        assert child2.trace_id == root.trace_id
        assert child1.parent_span_id == root.span_id
        assert child2.parent_span_id == root.span_id
        assert child1.span_id != child2.span_id

    def test_span_attributes_populated(self) -> None:
        span = create_root_span(
            tool_name="resolve_query",
            session_id="sess-1",
            workspace_id="prod",
        )
        assert span.attributes["feature"] == "mcp"
        assert span.attributes["mcp_session_id"] == "sess-1"
        assert span.attributes["mcp.workspace_id"] == "prod"
        assert span.attributes["mcp.tool_name"] == "resolve_query"

    def test_trace_id_propagated_to_context(self) -> None:
        span = create_root_span(tool_name="resolve_query")
        ctx = create_observability_context_from_span(
            span, session_id="s1", user_id="u1"
        )
        assert ctx.trace_id == span.trace_id
        assert ctx.span_id == span.span_id
        assert ctx.conversation_id == "s1"
        assert ctx.user_id == "u1"

    def test_duration_ms_recorded_on_span(self) -> None:
        span = MCPSpan(name="test")
        span.close()
        assert span.duration_ms >= 0
        assert span.end_time is not None

    def test_status_recorded_on_error(self) -> None:
        span = MCPSpan(name="test")
        span.close(status="error", error_code="EXEC_FAILED")
        assert span.status == "error"
        assert span.error_code == "EXEC_FAILED"

    def test_to_log_dict_includes_all_fields(self) -> None:
        span = MCPSpan(name="test")
        span.close()
        d = span.to_log_dict()
        assert "trace_id" in d
        assert "span_id" in d
        assert "span_name" in d
        assert "duration_ms" in d
        assert "status" in d

    def test_unknown_span_name_fallback(self) -> None:
        span = create_root_span()
        assert span.name == "mcp.unknown"
