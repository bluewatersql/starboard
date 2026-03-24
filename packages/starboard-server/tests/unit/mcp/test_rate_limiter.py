# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for MCPRateLimiter."""

import time

import pytest
from starboard_server.mcp.exceptions import RateLimitError
from starboard_server.mcp.rate_limiter import MCPRateLimiter, TokenBucket


class TestTokenBucket:
    """Tests for the TokenBucket implementation."""

    def test_consume_within_capacity(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        for _ in range(5):
            assert bucket.consume() is True

    def test_consume_exceeds_capacity(self) -> None:
        bucket = TokenBucket(capacity=2, refill_rate=1.0)
        assert bucket.consume() is True
        assert bucket.consume() is True
        assert bucket.consume() is False

    def test_time_to_refill_when_empty(self) -> None:
        bucket = TokenBucket(capacity=1, refill_rate=1.0)
        bucket.consume()
        wait = bucket.time_to_refill()
        assert wait >= 1

    def test_time_to_refill_when_available(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        assert bucket.time_to_refill() == 0


class TestMCPRateLimiter:
    """Tests for MCPRateLimiter."""

    def test_under_limit_passes(self) -> None:
        limiter = MCPRateLimiter(per_session_limit=10, global_limit=100)
        # Should not raise
        limiter.check("session-1")

    def test_session_limit_exceeded_raises(self) -> None:
        limiter = MCPRateLimiter(per_session_limit=2, global_limit=100)
        limiter.check("session-1")
        limiter.check("session-1")
        with pytest.raises(RateLimitError) as exc_info:
            limiter.check("session-1")
        assert exc_info.value.code == "RATE_SESSION_EXCEEDED"

    def test_global_limit_exceeded_raises(self) -> None:
        limiter = MCPRateLimiter(per_session_limit=100, global_limit=2)
        limiter.check("session-1")
        limiter.check("session-2")
        with pytest.raises(RateLimitError) as exc_info:
            limiter.check("session-3")
        assert exc_info.value.code == "RATE_GLOBAL_EXCEEDED"

    def test_retry_after_is_positive(self) -> None:
        limiter = MCPRateLimiter(per_session_limit=1, global_limit=100)
        limiter.check("s1")
        with pytest.raises(RateLimitError) as exc_info:
            limiter.check("s1")
        assert exc_info.value.retry_after is not None
        assert exc_info.value.retry_after >= 1

    def test_separate_sessions_have_separate_limits(self) -> None:
        limiter = MCPRateLimiter(per_session_limit=1, global_limit=100)
        limiter.check("session-a")
        # session-b should still have its own bucket
        limiter.check("session-b")  # Should not raise

    def test_tokens_refill_over_time(self) -> None:
        bucket = TokenBucket(capacity=1, refill_rate=100.0)  # Fast refill
        assert bucket.consume() is True
        assert bucket.consume() is False
        # Wait a tiny bit for refill
        time.sleep(0.02)
        assert bucket.consume() is True
