# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for TokenBudgetTracker."""

from unittest.mock import patch

from starboard_server.mcp.observability import (
    MCPSpan,
    TokenBudgetTracker,
    log_budget_exceeded,
)


class TestTokenBudgetTracker:
    """Tests for TokenBudgetTracker."""

    def test_token_budget_tracks_session(self) -> None:
        tracker = TokenBudgetTracker(default_budget=1000)
        tracker.record_usage("sess-1", 200)
        tracker.record_usage("sess-1", 300)
        assert tracker.get_used("sess-1") == 500
        assert tracker.remaining("sess-1") == 500

    def test_token_budget_exceeded_stops(self) -> None:
        tracker = TokenBudgetTracker(default_budget=100)
        tracker.record_usage("sess-1", 150)
        assert tracker.check_budget("sess-1") is False

    def test_token_budget_within_limit(self) -> None:
        tracker = TokenBudgetTracker(default_budget=1000)
        tracker.record_usage("sess-1", 500)
        assert tracker.check_budget("sess-1") is True

    def test_token_budget_none_skips_tracking(self) -> None:
        tracker = TokenBudgetTracker(default_budget=None)
        tracker.record_usage("sess-1", 999_999)
        assert tracker.check_budget("sess-1") is True
        assert tracker.remaining("sess-1") is None

    def test_per_session_budget_override(self) -> None:
        tracker = TokenBudgetTracker(default_budget=1000)
        tracker.set_budget("sess-1", 50)
        tracker.record_usage("sess-1", 60)
        assert tracker.check_budget("sess-1") is False
        # Other sessions still use default
        assert tracker.check_budget("sess-2") is True

    def test_reset_session(self) -> None:
        tracker = TokenBudgetTracker(default_budget=1000)
        tracker.record_usage("sess-1", 500)
        tracker.set_budget("sess-1", 200)
        tracker.reset_session("sess-1")
        assert tracker.get_used("sess-1") == 0
        assert tracker.get_budget("sess-1") == 1000  # Falls back to default

    def test_multiple_sessions_isolated(self) -> None:
        tracker = TokenBudgetTracker(default_budget=1000)
        tracker.record_usage("sess-1", 500)
        tracker.record_usage("sess-2", 200)
        assert tracker.get_used("sess-1") == 500
        assert tracker.get_used("sess-2") == 200


class TestBudgetExceededLogging:
    """Tests for mcp_budget_exceeded logging."""

    def test_mcp_budget_exceeded_logged(self) -> None:
        span = MCPSpan(name="test", trace_id="t1", span_id="s1")
        with patch("starboard_server.mcp.observability.logger") as mock_logger:
            log_budget_exceeded(
                span,
                session_id="sess-1",
                workspace_id="prod",
                budget=1000,
                used=1500,
            )
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "mcp_budget_exceeded"
            assert call_args[1]["token_budget"] == 1000
            assert call_args[1]["tokens_used"] == 1500
            assert call_args[1]["feature"] == "mcp"
