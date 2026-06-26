# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for retry decorator with exponential backoff.

Tests cover:
- Async retry path (happy path, exhaustion, delay calculation)
- Sync retry path (happy path, exhaustion)
- Runtime guard: sync wrapper raises RuntimeError inside async context
- Runtime guard: sync wrapper succeeds outside async context
- _check_not_in_async_context helper
- Rate-limit-aware delay calculation
- Jitter behavior
"""

from unittest.mock import MagicMock, patch

import pytest
from starboard_server.infra.reliability.retry import (
    _calculate_delay,
    _check_not_in_async_context,
    retry_with_backoff,
)

# ---------------------------------------------------------------------------
# _check_not_in_async_context
# ---------------------------------------------------------------------------


class TestCheckNotInAsyncContext:
    """Tests for the _check_not_in_async_context runtime guard."""

    def test_no_running_loop_passes_silently(self) -> None:
        """Guard returns without error when no asyncio loop is running."""
        # Outside any async context, this should not raise.
        _check_not_in_async_context("my_func")

    @pytest.mark.asyncio
    async def test_raises_inside_running_loop(self) -> None:
        """Guard raises RuntimeError when called inside a running event loop."""
        with pytest.raises(
            RuntimeError, match="sync retry_with_backoff called from async context"
        ):
            _check_not_in_async_context("my_func")

    @pytest.mark.asyncio
    async def test_error_message_contains_function_name(self) -> None:
        """Error message includes the offending function name."""
        with pytest.raises(RuntimeError, match="'do_stuff'"):
            _check_not_in_async_context("do_stuff")


# ---------------------------------------------------------------------------
# Sync retry wrapper
# ---------------------------------------------------------------------------


class TestSyncRetryWrapper:
    """Tests for the sync path of retry_with_backoff."""

    def test_sync_success_no_retry(self) -> None:
        """Sync function that succeeds on first call is not retried."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_delay=0.01)
        def succeeding_func() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeeding_func()
        assert result == "ok"
        assert call_count == 1

    @patch("starboard_server.infra.reliability.retry.time.sleep")
    def test_sync_retries_on_failure(self, mock_sleep: MagicMock) -> None:
        """Sync function retries up to max_attempts on repeated failures."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_delay=1.0, jitter=False)
        def failing_func() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            failing_func()

        assert call_count == 3
        assert mock_sleep.call_count == 2  # sleeps between attempts 1->2, 2->3

    @patch("starboard_server.infra.reliability.retry.time.sleep")
    def test_sync_succeeds_after_transient_failure(self, mock_sleep: MagicMock) -> None:
        """Sync function succeeds on second attempt after one failure."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_delay=0.01)
        def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("transient")
            return "recovered"

        result = flaky_func()
        assert result == "recovered"
        assert call_count == 2
        assert mock_sleep.call_count == 1

    @pytest.mark.asyncio
    async def test_sync_wrapper_raises_in_async_context(self) -> None:
        """Sync retry wrapper raises RuntimeError when invoked inside async context."""

        @retry_with_backoff(max_attempts=2, initial_delay=0.01)
        def sync_fn() -> str:
            return "should not reach"

        with pytest.raises(
            RuntimeError, match="sync retry_with_backoff called from async context"
        ):
            sync_fn()

    @pytest.mark.asyncio
    async def test_sync_wrapper_guard_includes_function_name(self) -> None:
        """RuntimeError message from sync guard includes the decorated function name."""

        @retry_with_backoff(max_attempts=2, initial_delay=0.01)
        def my_special_function() -> str:
            return "nope"

        with pytest.raises(RuntimeError, match="'my_special_function'"):
            my_special_function()


# ---------------------------------------------------------------------------
# Async retry wrapper
# ---------------------------------------------------------------------------


class TestAsyncRetryWrapper:
    """Tests for the async path of retry_with_backoff."""

    @pytest.mark.asyncio
    async def test_async_success_no_retry(self) -> None:
        """Async function that succeeds on first call is not retried."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_delay=0.01)
        async def succeeding_func() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeeding_func()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_retries_on_failure(self) -> None:
        """Async function retries up to max_attempts on repeated failures."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_delay=0.001, jitter=False)
        async def failing_func() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("async boom")

        with pytest.raises(ValueError, match="async boom"):
            await failing_func()

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_succeeds_after_transient_failure(self) -> None:
        """Async function succeeds on second attempt after one failure."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_delay=0.001, jitter=False)
        async def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("transient")
            return "recovered"

        result = await flaky_func()
        assert result == "recovered"
        assert call_count == 2


# ---------------------------------------------------------------------------
# _calculate_delay
# ---------------------------------------------------------------------------


class TestCalculateDelay:
    """Tests for delay calculation with backoff, rate-limit awareness, and jitter."""

    def test_base_delay_first_attempt(self) -> None:
        """First attempt delay equals initial_delay (no jitter)."""
        delay = _calculate_delay(
            attempt=1,
            initial_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=False,
            error=ValueError("test"),
        )
        assert delay == 1.0

    def test_exponential_growth(self) -> None:
        """Delay doubles with each attempt (base=2, no jitter)."""
        delays = [
            _calculate_delay(
                attempt=i,
                initial_delay=1.0,
                max_delay=60.0,
                exponential_base=2.0,
                jitter=False,
                error=ValueError("test"),
            )
            for i in range(1, 5)
        ]
        assert delays == [1.0, 2.0, 4.0, 8.0]

    def test_max_delay_cap(self) -> None:
        """Delay does not exceed max_delay."""
        delay = _calculate_delay(
            attempt=10,
            initial_delay=1.0,
            max_delay=30.0,
            exponential_base=2.0,
            jitter=False,
            error=ValueError("test"),
        )
        assert delay == 30.0

    def test_rate_limit_doubles_delay(self) -> None:
        """Rate limit errors double the base delay."""

        # Create a RateLimitError-like exception
        rate_err = ValueError("429 rate limit exceeded")
        normal_delay = _calculate_delay(
            attempt=1,
            initial_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=False,
            error=ValueError("normal error"),
        )
        rate_delay = _calculate_delay(
            attempt=1,
            initial_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=False,
            error=rate_err,
        )
        assert rate_delay == normal_delay * 2

    def test_jitter_varies_delay(self) -> None:
        """With jitter enabled, repeated calls produce varying delays within +-25%."""
        delays = set()
        for _ in range(20):
            d = _calculate_delay(
                attempt=1,
                initial_delay=10.0,
                max_delay=60.0,
                exponential_base=2.0,
                jitter=True,
                error=ValueError("test"),
            )
            delays.add(round(d, 4))
            # Each value must be within 75%-125% of base
            assert 7.5 <= d <= 12.5

        # With 20 samples we should see some variation
        assert len(delays) > 1

    def test_request_limit_exceeded_is_rate_limit(self) -> None:
        """'request_limit_exceeded' in error string triggers rate-limit logic."""
        delay = _calculate_delay(
            attempt=1,
            initial_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=False,
            error=ValueError("request_limit_exceeded"),
        )
        # Rate-limit doubles: 1.0 * 2 = 2.0
        assert delay == 2.0
