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

from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest
from starboard.infra.reliability.retry import (
    _calculate_delay,
    _check_not_in_async_context,
    _retry_after_seconds,
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

    @patch("starboard.infra.reliability.retry.time.sleep")
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

    @patch("starboard.infra.reliability.retry.time.sleep")
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


# ---------------------------------------------------------------------------
# Retry-After honoring + longer rate-limit backoff (429 window ~60s)
# ---------------------------------------------------------------------------


class _FakeHeaders:
    """Minimal case-sensitive header map exposing ``.get`` like httpx.Headers."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._m = mapping

    def get(self, key: str) -> str | None:
        return self._m.get(key)


class _FakeResponse:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = _FakeHeaders(headers)


class _FakeRateLimitError(Exception):
    """Stands in for openai ``RateLimitError`` carrying an optional Retry-After."""

    def __init__(self, message: str = "429 rate limit", retry_after: str | None = None) -> None:
        super().__init__(message)
        headers: dict[str, str] = {}
        if retry_after is not None:
            headers["retry-after"] = retry_after
        self.response = _FakeResponse(headers)


class TestRetryAfterSeconds:
    """Tests for the Retry-After header extractor."""

    def test_numeric_seconds(self) -> None:
        assert _retry_after_seconds(_FakeRateLimitError(retry_after="30")) == 30.0

    def test_no_header_returns_none(self) -> None:
        assert _retry_after_seconds(_FakeRateLimitError()) is None

    def test_error_without_response_returns_none(self) -> None:
        assert _retry_after_seconds(ValueError("429 rate limit")) is None

    def test_http_date_is_parsed(self) -> None:
        from datetime import datetime, timedelta
        from email.utils import format_datetime

        future = datetime.now(UTC) + timedelta(seconds=20)
        seconds = _retry_after_seconds(
            _FakeRateLimitError(retry_after=format_datetime(future))
        )
        assert seconds is not None
        assert 10.0 <= seconds <= 20.0  # allow for clock/rounding + 1s granularity


class TestRateLimitBackoff:
    """Tests for the longer 429 backoff and Retry-After honoring in _calculate_delay."""

    def test_retry_after_honored_as_delay(self) -> None:
        """A server Retry-After becomes the delay (no jitter)."""
        delay = _calculate_delay(
            attempt=1,
            initial_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=False,
            error=_FakeRateLimitError(retry_after="45"),
            rate_limit_max_delay=90.0,
        )
        assert delay == 45.0

    def test_retry_after_capped_at_rate_limit_max(self) -> None:
        """A huge Retry-After is capped at rate_limit_max_delay."""
        delay = _calculate_delay(
            attempt=1,
            initial_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=False,
            error=_FakeRateLimitError(retry_after="600"),
            rate_limit_max_delay=90.0,
        )
        assert delay == 90.0

    def test_no_header_backoff_uses_longer_rate_cap(self) -> None:
        """Without Retry-After, a 429 backs off past max_delay up to the rate cap."""
        delay = _calculate_delay(
            attempt=6,  # 2 * 2^5 = 64 -> min(64, 60)=60 base -> *2 = 120 -> cap 90
            initial_delay=2.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=False,
            error=_FakeRateLimitError(),
            rate_limit_max_delay=90.0,
        )
        assert delay == 90.0

    def test_server_directed_wait_only_jitters_upward(self) -> None:
        """With jitter, a Retry-After is a floor — never retried early."""
        for _ in range(30):
            delay = _calculate_delay(
                attempt=1,
                initial_delay=1.0,
                max_delay=60.0,
                exponential_base=2.0,
                jitter=True,
                error=_FakeRateLimitError(retry_after="40"),
                rate_limit_max_delay=90.0,
            )
            assert 40.0 <= delay <= 50.0  # >= server value, up to +25%

    def test_none_rate_cap_preserves_max_delay_behavior(self) -> None:
        """When rate_limit_max_delay is None, the cap falls back to max_delay."""
        delay = _calculate_delay(
            attempt=6,
            initial_delay=2.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=False,
            error=_FakeRateLimitError(),
            rate_limit_max_delay=None,
        )
        assert delay == 60.0


# ---------------------------------------------------------------------------
# Permanent-error fail-fast (no retry storm on a nonexistent endpoint / auth)
# ---------------------------------------------------------------------------


class _FakeStatusError(Exception):
    """Stands in for an ``openai.APIStatusError`` carrying an HTTP status code."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class TestIsPermanentError:
    """Tests for the permanent-vs-transient error classifier."""

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 422])
    def test_client_errors_are_permanent(self, status: int) -> None:
        """4xx client errors that cannot succeed on retry are permanent."""
        from starboard.infra.reliability.retry import is_permanent_error

        assert is_permanent_error(_FakeStatusError("nope", status)) is True

    @pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504])
    def test_transient_statuses_are_not_permanent(self, status: int) -> None:
        """Rate-limit, timeout, conflict and 5xx are transient -> retryable."""
        from starboard.infra.reliability.retry import is_permanent_error

        assert is_permanent_error(_FakeStatusError("retry me", status)) is False

    def test_error_without_status_is_not_permanent(self) -> None:
        """A plain exception with no HTTP status stays retryable (unchanged)."""
        from starboard.infra.reliability.retry import is_permanent_error

        assert is_permanent_error(ValueError("boom")) is False
        assert is_permanent_error(ConnectionError("dropped")) is False

    def test_status_on_response_attr_is_read(self) -> None:
        """Status is also read from a nested ``response.status_code``."""
        from starboard.infra.reliability.retry import is_permanent_error

        class _Resp:
            status_code = 404

        class _Err(Exception):
            response = _Resp()

        assert is_permanent_error(_Err()) is True


class TestRetryFailFastOnPermanentError:
    """The decorator must NOT retry a permanent error - one attempt, then raise."""

    @pytest.mark.asyncio
    async def test_async_permanent_error_not_retried(self) -> None:
        """A 404 aborts immediately: exactly one call, no backoff sleeps."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_delay=0.001, jitter=False)
        async def dead_endpoint() -> str:
            nonlocal call_count
            call_count += 1
            raise _FakeStatusError("RESOURCE_DOES_NOT_EXIST", 404)

        with pytest.raises(_FakeStatusError):
            await dead_endpoint()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_transient_error_still_retried(self) -> None:
        """A 503 is still retried up to max_attempts (regression guard)."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_delay=0.001, jitter=False)
        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            raise _FakeStatusError("temporarily down", 503)

        with pytest.raises(_FakeStatusError):
            await flaky()
        assert call_count == 3

    @patch("starboard.infra.reliability.retry.time.sleep")
    def test_sync_permanent_error_not_retried(self, mock_sleep: MagicMock) -> None:
        """Sync path also aborts a permanent error on the first attempt."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_delay=0.001, jitter=False)
        def dead_endpoint() -> str:
            nonlocal call_count
            call_count += 1
            raise _FakeStatusError("unauthorized", 401)

        with pytest.raises(_FakeStatusError):
            dead_endpoint()
        assert call_count == 1
        assert mock_sleep.call_count == 0
