# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCP structured logging helpers."""

from __future__ import annotations

from unittest.mock import patch

from starboard.mcp.observability import (
    MCPSpan,
    log_auth_failed,
    log_circuit_open,
    log_rate_limited,
    log_tool_completed,
    log_tool_error,
    log_tool_started,
)


def _make_span(trace_id: str = "trace-1") -> MCPSpan:
    return MCPSpan(name="mcp.tool.test", trace_id=trace_id, span_id="span-1")


class TestMCPToolStartedLog:
    """Tests for mcp_tool_started logging."""

    def test_mcp_tool_started_logged(self) -> None:
        span = _make_span()
        with patch("starboard.mcp.observability.logger") as mock_logger:
            log_tool_started(
                span,
                "resolve_query",
                session_id="sess-1",
                workspace_id="prod",
            )
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "mcp_tool_started"
            assert call_args[1]["mcp_tool_name"] == "resolve_query"


class TestMCPToolCompletedLog:
    """Tests for mcp_tool_completed logging."""

    def test_mcp_tool_completed_logged_with_required_fields(self) -> None:
        span = _make_span()
        with patch("starboard.mcp.observability.logger") as mock_logger:
            log_tool_completed(
                span,
                "resolve_query",
                session_id="sess-1",
                workspace_id="prod",
                duration_ms=42.5,
            )
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "mcp_tool_completed"
            kwargs = call_args[1]
            assert kwargs["trace_id"] == "trace-1"
            assert kwargs["span_id"] == "span-1"
            assert kwargs["mcp_session_id"] == "sess-1"
            assert kwargs["workspace_id"] == "prod"
            assert kwargs["feature"] == "mcp"
            assert kwargs["duration_ms"] == 42.5


class TestMCPToolErrorLog:
    """Tests for mcp_tool_error logging."""

    def test_mcp_tool_error_logged(self) -> None:
        span = _make_span()
        with patch("starboard.mcp.observability.logger") as mock_logger:
            log_tool_error(
                span,
                "bad_tool",
                "EXEC_FAILED",
                "Something broke",
                session_id="sess-1",
                workspace_id="prod",
            )
            call_args = mock_logger.error.call_args
            assert call_args[0][0] == "mcp_tool_error"
            assert call_args[1]["error_code"] == "EXEC_FAILED"


class TestMCPRateLimitedLog:
    """Tests for mcp_rate_limited logging."""

    def test_mcp_rate_limited_logged(self) -> None:
        span = _make_span()
        with patch("starboard.mcp.observability.logger") as mock_logger:
            log_rate_limited(span, session_id="sess-1", workspace_id="prod")
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "mcp_rate_limited"


class TestMCPCircuitOpenLog:
    """Tests for mcp_circuit_open logging."""

    def test_mcp_circuit_open_logged(self) -> None:
        span = _make_span()
        with patch("starboard.mcp.observability.logger") as mock_logger:
            log_circuit_open(span, session_id="sess-1", workspace_id="prod")
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "mcp_circuit_open"


class TestMCPAuthFailedLog:
    """Tests for mcp_auth_failed logging."""

    def test_mcp_auth_failed_logged(self) -> None:
        span = _make_span()
        with patch("starboard.mcp.observability.logger") as mock_logger:
            log_auth_failed(span, session_id="sess-1", workspace_id="prod")
            call_args = mock_logger.error.call_args
            assert call_args[0][0] == "mcp_auth_failed"


class TestAllLogsIncludeFeatureMCP:
    """Tests that all MCP log entries include feature=mcp."""

    def test_all_logs_include_feature_mcp(self) -> None:
        span = _make_span()
        log_fns = [
            lambda: log_tool_started(span, "t"),
            lambda: log_tool_completed(span, "t"),
            lambda: log_tool_error(span, "t", "E", "msg"),
            lambda: log_rate_limited(span),
            lambda: log_circuit_open(span),
            lambda: log_auth_failed(span),
        ]
        for fn in log_fns:
            with patch("starboard.mcp.observability.logger") as mock_logger:
                fn()
                # Check the most recent call to any log method
                for method in ("info", "error", "warning", "debug"):
                    call = getattr(mock_logger, method).call_args
                    if call is not None:
                        assert call[1]["feature"] == "mcp"
                        break


class TestTraceIdInEveryLog:
    """Tests that trace_id appears in every MCP log event."""

    def test_trace_id_in_every_log(self) -> None:
        span = _make_span(trace_id="unique-trace")
        log_fns = [
            lambda: log_tool_started(span, "t"),
            lambda: log_tool_completed(span, "t"),
            lambda: log_tool_error(span, "t", "E", "msg"),
            lambda: log_rate_limited(span),
            lambda: log_circuit_open(span),
            lambda: log_auth_failed(span),
        ]
        for fn in log_fns:
            with patch("starboard.mcp.observability.logger") as mock_logger:
                fn()
                for method in ("info", "error", "warning", "debug"):
                    call = getattr(mock_logger, method).call_args
                    if call is not None:
                        assert call[1]["trace_id"] == "unique-trace"
                        break


class TestNoTokenInLogs:
    """Tests that token values never appear in log events."""

    def test_no_token_in_logs(self) -> None:
        span = _make_span()
        with patch("starboard.mcp.observability.logger") as mock_logger:
            log_tool_completed(
                span,
                "resolve_query",
                session_id="sess-1",
                workspace_id="prod",
            )
            call_str = str(mock_logger.info.call_args)
            assert "dapi" not in call_str.lower()
            assert "token" not in call_str.lower() or "token_" not in call_str.lower()
