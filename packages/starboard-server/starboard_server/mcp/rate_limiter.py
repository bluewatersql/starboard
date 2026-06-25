# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Token-bucket rate limiter for MCP calls.

Provides per-session and global rate limiting to protect downstream
services from excessive load.
"""

from __future__ import annotations

import math
import time

from starboard_server.infra.observability.logging import get_logger
from starboard_server.mcp.exceptions import RateLimitError

logger = get_logger(__name__)


class TokenBucket:
    """Token bucket rate limiter.

    Tokens refill at a constant rate up to the bucket capacity.

    Args:
        capacity: Maximum number of tokens the bucket can hold.
        refill_rate: Tokens added per second.
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def consume(self) -> bool:
        """Try to consume one token.

        Returns:
            ``True`` if a token was available and consumed, ``False`` otherwise.
        """
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def time_to_refill(self) -> int:
        """Seconds until at least one token is available.

        Returns:
            Ceiling of seconds to wait, minimum 1.
        """
        self._refill()
        if self._tokens >= 1.0:
            return 0
        deficit = 1.0 - self._tokens
        return max(1, math.ceil(deficit / self._refill_rate))


_DEFAULT_MAX_SESSIONS = 1000


class MCPRateLimiter:
    """Per-session and global rate limiter for MCP calls.

    Session buckets are evicted LRU-style once ``max_sessions`` is reached,
    preventing unbounded memory growth in long-running servers.

    Args:
        per_session_limit: Maximum calls per minute per session.
        global_limit: Maximum calls per minute across all sessions.
        max_sessions: Maximum number of concurrent session buckets to retain.
            Oldest sessions are evicted once this limit is reached.
    """

    def __init__(
        self,
        per_session_limit: int = 60,
        global_limit: int = 300,
        max_sessions: int = _DEFAULT_MAX_SESSIONS,
    ) -> None:
        self._per_session_limit = per_session_limit
        self._global_limit = global_limit
        self._max_sessions = max_sessions
        # Use insertion-ordered dict for simple LRU eviction
        self._session_buckets: dict[str, TokenBucket] = {}
        self._global_bucket = TokenBucket(
            capacity=global_limit,
            refill_rate=global_limit / 60.0,
        )

    def _get_session_bucket(self, session_id: str) -> TokenBucket:
        """Get or create a token bucket for a session.

        Evicts the oldest entry when ``max_sessions`` is exceeded.
        """
        if session_id in self._session_buckets:
            # Move to end (most recently used) by re-inserting
            bucket = self._session_buckets.pop(session_id)
            self._session_buckets[session_id] = bucket
            return bucket
        # Evict oldest entry if at capacity
        if len(self._session_buckets) >= self._max_sessions:
            oldest_key = next(iter(self._session_buckets))
            del self._session_buckets[oldest_key]
            logger.debug(
                "rate_limiter_session_evicted",
                evicted_session=oldest_key,
                max_sessions=self._max_sessions,
            )
        bucket = TokenBucket(
            capacity=self._per_session_limit,
            refill_rate=self._per_session_limit / 60.0,
        )
        self._session_buckets[session_id] = bucket
        return bucket

    def check(self, session_id: str) -> None:
        """Check rate limits and consume a token.

        Args:
            session_id: Caller session identifier.

        Raises:
            RateLimitError: If either per-session or global limit is exceeded.
        """
        # Check global limit first
        if not self._global_bucket.consume():
            retry_after = self._global_bucket.time_to_refill()
            logger.warning(
                "rate_limit_global_exceeded",
                session_id=session_id,
                retry_after=retry_after,
            )
            raise RateLimitError(
                "Global rate limit exceeded.",
                code="RATE_GLOBAL_EXCEEDED",
                retry_after=retry_after,
            )

        # Check per-session limit
        session_bucket = self._get_session_bucket(session_id)
        if not session_bucket.consume():
            retry_after = session_bucket.time_to_refill()
            logger.warning(
                "rate_limit_session_exceeded",
                session_id=session_id,
                retry_after=retry_after,
            )
            raise RateLimitError(
                f"Session rate limit exceeded for {session_id!r}.",
                code="RATE_SESSION_EXCEEDED",
                retry_after=retry_after,
            )
