"""Tests for retry_with_backoff decorator.

Tests cover:
- Successful execution without retries
- Retry logic with exponential backoff
- Maximum attempts enforcement
- Delay calculation (exponential + capping)
- Exception propagation on final failure
- Edge cases (max_attempts=1, very long delays)
- Async function support
- Rate limit error handling

Examples:
    >>> @retry_with_backoff(max_attempts=3, initial_delay=1.0)
    ... def flaky_function():
    ...     return api_call()
"""

from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from openai import RateLimitError
from starboard_server.infra.reliability.retry import retry_with_backoff


class TestRetryWithBackoffHappyPath:
    """Tests for successful execution paths."""

    def test_successful_first_attempt(self):
        """Test that successful call on first attempt returns immediately."""
        mock_func = Mock(return_value="success")

        @retry_with_backoff(max_attempts=3)
        def test_func():
            return mock_func()

        result = test_func()

        assert result == "success"
        mock_func.assert_called_once()

    def test_returns_function_result(self):
        """Test that decorator returns the function's result."""

        @retry_with_backoff(max_attempts=2)
        def returns_value():
            return {"data": "result"}

        result = returns_value()

        assert result == {"data": "result"}

    def test_passes_args_and_kwargs(self):
        """Test that decorator passes through arguments."""
        mock_func = Mock(return_value="result")

        @retry_with_backoff(max_attempts=2)
        def test_func(arg1, arg2, kwarg1=None):
            return mock_func(arg1, arg2, kwarg1=kwarg1)

        result = test_func("a", "b", kwarg1="c")

        assert result == "result"
        mock_func.assert_called_once_with("a", "b", kwarg1="c")


class TestRetryWithBackoffRetryLogic:
    """Tests for retry behavior and backoff."""

    @patch("time.sleep")
    def test_retries_on_exception(self, mock_sleep):
        """Test that function is retried on exception."""
        mock_func = Mock(
            side_effect=[ValueError("error1"), ValueError("error2"), "success"]
        )

        @retry_with_backoff(max_attempts=3, initial_delay=1.0, jitter=False)
        def test_func():
            return mock_func()

        result = test_func()

        assert result == "success"
        assert mock_func.call_count == 3
        assert mock_sleep.call_count == 2  # 2 retries

    @patch("time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep):
        """Test that delays follow exponential backoff pattern."""
        mock_func = Mock(side_effect=[ValueError(), ValueError(), "success"])

        @retry_with_backoff(
            max_attempts=3, initial_delay=1.0, exponential_base=2.0, jitter=False
        )
        def test_func():
            return mock_func()

        test_func()

        # First retry: 1.0 * 2^0 = 1.0
        # Second retry: 1.0 * 2^1 = 2.0
        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("time.sleep")
    def test_max_delay_caps_exponential_growth(self, mock_sleep):
        """Test that max_delay caps the exponential backoff."""
        mock_func = Mock(
            side_effect=[ValueError(), ValueError(), ValueError(), "success"]
        )

        @retry_with_backoff(
            max_attempts=4,
            initial_delay=1.0,
            max_delay=3.0,
            exponential_base=2.0,
            jitter=False,
        )
        def test_func():
            return mock_func()

        test_func()

        # First retry: min(1.0 * 2^0, 3.0) = 1.0
        # Second retry: min(1.0 * 2^1, 3.0) = 2.0
        # Third retry: min(1.0 * 2^2, 3.0) = 3.0 (capped!)
        assert mock_sleep.call_args_list == [call(1.0), call(2.0), call(3.0)]

    @patch("time.sleep")
    def test_raises_exception_on_max_attempts(self, mock_sleep):
        """Test that exception is raised after max attempts."""
        mock_func = Mock(side_effect=ValueError("persistent_error"))

        @retry_with_backoff(max_attempts=3)
        def test_func():
            return mock_func()

        with pytest.raises(ValueError, match="persistent_error"):
            test_func()

        assert mock_func.call_count == 3
        assert mock_sleep.call_count == 2  # max_attempts - 1


class TestRetryWithBackoffEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_max_attempts_one_no_retry(self):
        """Test that max_attempts=1 means no retries."""
        mock_func = Mock(side_effect=ValueError("error"))

        @retry_with_backoff(max_attempts=1)
        def test_func():
            return mock_func()

        with pytest.raises(ValueError, match="error"):
            test_func()

        mock_func.assert_called_once()

    @patch("time.sleep")
    def test_zero_initial_delay(self, mock_sleep):
        """Test with initial_delay=0."""
        mock_func = Mock(side_effect=[ValueError(), "success"])

        @retry_with_backoff(max_attempts=2, initial_delay=0.0)
        def test_func():
            return mock_func()

        result = test_func()

        assert result == "success"
        mock_sleep.assert_called_once_with(0.0)

    @patch("time.sleep")
    def test_very_high_exponential_base(self, mock_sleep):
        """Test with high exponential base but capped by max_delay."""
        mock_func = Mock(side_effect=[ValueError(), ValueError(), "success"])

        @retry_with_backoff(
            max_attempts=3,
            initial_delay=1.0,
            max_delay=5.0,
            exponential_base=10.0,
            jitter=False,
        )
        def test_func():
            return mock_func()

        test_func()

        # First retry: min(1.0 * 10^0, 5.0) = 1.0
        # Second retry: min(1.0 * 10^1, 5.0) = 5.0 (capped!)
        assert mock_sleep.call_args_list == [call(1.0), call(5.0)]

    def test_different_exception_types_all_retried(self):
        """Test that all exception types trigger retries."""
        mock_func = Mock(
            side_effect=[ValueError(), KeyError(), RuntimeError(), "success"]
        )

        @retry_with_backoff(max_attempts=4, initial_delay=0.01)
        def test_func():
            return mock_func()

        result = test_func()

        assert result == "success"
        assert mock_func.call_count == 4

    @patch("time.sleep")
    def test_preserves_function_name(self, mock_sleep):
        """Test that decorator preserves function name."""

        @retry_with_backoff(max_attempts=2)
        def my_function():
            return "result"

        assert my_function.__name__ == "my_function"

    @patch("time.sleep")
    def test_handles_exception_with_no_message(self, mock_sleep):
        """Test handling of exceptions without messages."""
        mock_func = Mock(side_effect=[ValueError(), "success"])

        @retry_with_backoff(max_attempts=2)
        def test_func():
            return mock_func()

        result = test_func()

        assert result == "success"


class TestRetryWithBackoffLogging:
    """Tests for logging behavior."""

    @patch("time.sleep")
    def test_logs_warnings_on_retry(self, mock_sleep):
        """Test that retry attempts are logged."""
        mock_func = Mock(side_effect=[ValueError("transient"), "success"])

        @retry_with_backoff(max_attempts=2, initial_delay=0.5, jitter=False)
        def test_func():
            return mock_func()

        with patch("starboard_server.infra.reliability.retry.logger") as mock_logger:
            test_func()

            # Should log structured warning about retry
            assert mock_logger.warning.called
            warning_event = mock_logger.warning.call_args[0][0]
            assert warning_event == "retry_attempt_failed"
            kwargs = mock_logger.warning.call_args[1]
            assert kwargs["attempt"] == 1
            assert kwargs["max_attempts"] == 2

    @patch("time.sleep")
    def test_logs_error_on_final_failure(self, mock_sleep):
        """Test that final failure is logged as error."""
        mock_func = Mock(side_effect=ValueError("final_error"))

        @retry_with_backoff(max_attempts=2)
        def test_func():
            return mock_func()

        with patch("starboard_server.infra.reliability.retry.logger") as mock_logger:
            with pytest.raises(ValueError):
                test_func()

            # Should log structured error about final failure
            assert mock_logger.error.called
            error_event = mock_logger.error.call_args[0][0]
            assert error_event == "retry_exhausted"
            kwargs = mock_logger.error.call_args[1]
            assert kwargs["max_attempts"] == 2


class TestRetryWithBackoffIntegration:
    """Integration tests with realistic scenarios."""

    @patch("time.sleep")
    def test_realistic_api_retry_scenario(self, mock_sleep):
        """Test realistic API retry scenario with transient failures."""
        call_count = []

        @retry_with_backoff(
            max_attempts=3, initial_delay=1.0, max_delay=4.0, jitter=False
        )
        def api_call():
            call_count.append(1)
            if len(call_count) < 3:
                raise ConnectionError("Temporary network issue")
            return {"status": "success", "data": "result"}

        result = api_call()

        assert result == {"status": "success", "data": "result"}
        assert len(call_count) == 3
        # Should have slept twice with exponential backoff
        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("time.sleep")
    def test_complex_function_with_multiple_params(self, mock_sleep):
        """Test decorator works with complex function signatures."""
        attempt_count = []

        @retry_with_backoff(max_attempts=2, initial_delay=0.1)
        def complex_function(a, b, c=None, *args, **kwargs):
            attempt_count.append(1)
            if len(attempt_count) == 1:
                raise ValueError("First attempt fails")
            return {
                "a": a,
                "b": b,
                "c": c,
                "args": args,
                "kwargs": kwargs,
            }

        result = complex_function(1, 2, c=3, extra_arg=4)

        assert result["a"] == 1
        assert result["b"] == 2
        assert result["c"] == 3
        assert result["kwargs"]["extra_arg"] == 4
        assert len(attempt_count) == 2

    @patch("time.sleep")
    def test_no_retry_on_success_even_with_high_max_attempts(self, mock_sleep):
        """Test that successful calls don't retry unnecessarily."""
        mock_func = Mock(return_value="immediate_success")

        @retry_with_backoff(max_attempts=100, initial_delay=10.0)
        def test_func():
            return mock_func()

        result = test_func()

        assert result == "immediate_success"
        mock_func.assert_called_once()
        mock_sleep.assert_not_called()


class TestRetryWithBackoffDelayCalculation:
    """Tests for delay calculation specifics."""

    @patch("time.sleep")
    def test_exponential_base_one_means_constant_delay(self, mock_sleep):
        """Test that exponential_base=1.0 results in constant delay."""
        mock_func = Mock(side_effect=[ValueError(), ValueError(), "success"])

        @retry_with_backoff(
            max_attempts=3, initial_delay=2.0, exponential_base=1.0, jitter=False
        )
        def test_func():
            return mock_func()

        test_func()

        # All delays should be 2.0 (2.0 * 1^n = 2.0)
        assert mock_sleep.call_args_list == [call(2.0), call(2.0)]

    @patch("time.sleep")
    def test_delay_calculation_precision(self, mock_sleep):
        """Test that delay calculations are precise."""
        mock_func = Mock(
            side_effect=[ValueError(), ValueError(), ValueError(), "success"]
        )

        @retry_with_backoff(
            max_attempts=4,
            initial_delay=0.5,
            max_delay=10.0,
            exponential_base=3.0,
            jitter=False,
        )
        def test_func():
            return mock_func()

        test_func()

        # Expected: 0.5 * 3^0 = 0.5, 0.5 * 3^1 = 1.5, 0.5 * 3^2 = 4.5
        assert mock_sleep.call_args_list == [call(0.5), call(1.5), call(4.5)]


class TestRetryWithBackoffAsync:
    """Tests for async function support."""

    @pytest.mark.asyncio
    async def test_async_successful_first_attempt(self):
        """Test that successful async call on first attempt returns immediately."""
        mock_func = AsyncMock(return_value="success")

        @retry_with_backoff(max_attempts=3)
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
        mock_func.assert_called_once()

    @pytest.mark.asyncio
    @patch("asyncio.sleep")
    async def test_async_retries_on_exception(self, mock_sleep):
        """Test that async function is retried on exception."""
        mock_func = AsyncMock(
            side_effect=[ValueError("error1"), ValueError("error2"), "success"]
        )

        @retry_with_backoff(max_attempts=3, initial_delay=1.0, jitter=False)
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
        assert mock_func.call_count == 3
        assert mock_sleep.call_count == 2  # 2 retries

    @pytest.mark.asyncio
    @patch("asyncio.sleep")
    async def test_async_exponential_backoff_delays(self, mock_sleep):
        """Test that async delays follow exponential backoff pattern."""
        mock_func = AsyncMock(side_effect=[ValueError(), ValueError(), "success"])

        @retry_with_backoff(
            max_attempts=3, initial_delay=1.0, exponential_base=2.0, jitter=False
        )
        async def test_func():
            return await mock_func()

        await test_func()

        # First retry: 1.0 * 2^0 = 1.0
        # Second retry: 1.0 * 2^1 = 2.0
        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @pytest.mark.asyncio
    @patch("asyncio.sleep")
    async def test_async_max_delay_caps_exponential_growth(self, mock_sleep):
        """Test that max_delay caps the exponential backoff for async functions."""
        mock_func = AsyncMock(
            side_effect=[ValueError(), ValueError(), ValueError(), "success"]
        )

        @retry_with_backoff(
            max_attempts=4,
            initial_delay=1.0,
            max_delay=3.0,
            exponential_base=2.0,
            jitter=False,
        )
        async def test_func():
            return await mock_func()

        await test_func()

        # First retry: min(1.0 * 2^0, 3.0) = 1.0
        # Second retry: min(1.0 * 2^1, 3.0) = 2.0
        # Third retry: min(1.0 * 2^2, 3.0) = 3.0 (capped!)
        assert mock_sleep.call_args_list == [call(1.0), call(2.0), call(3.0)]

    @pytest.mark.asyncio
    @patch("asyncio.sleep")
    async def test_async_raises_exception_on_max_attempts(self, mock_sleep):
        """Test that exception is raised after max attempts for async functions."""
        mock_func = AsyncMock(side_effect=ValueError("persistent_error"))

        @retry_with_backoff(max_attempts=3)
        async def test_func():
            return await mock_func()

        with pytest.raises(ValueError, match="persistent_error"):
            await test_func()

        assert mock_func.call_count == 3
        assert mock_sleep.call_count == 2  # max_attempts - 1


class TestRetryWithBackoffRateLimits:
    """Tests for rate limit error handling."""

    @patch("time.sleep")
    def test_rate_limit_error_uses_longer_delay(self, mock_sleep):
        """Test that RateLimitError triggers longer delays."""
        # Create a mock response object for RateLimitError
        mock_response = Mock()
        mock_response.request = Mock()

        mock_func = Mock(
            side_effect=[
                RateLimitError(
                    "Rate limit exceeded", response=mock_response, body=None
                ),
                "success",
            ]
        )

        @retry_with_backoff(max_attempts=2, initial_delay=1.0, jitter=False)
        def test_func():
            return mock_func()

        result = test_func()

        assert result == "success"
        # Rate limit errors should double the delay: 1.0 * 2 = 2.0
        mock_sleep.assert_called_once_with(2.0)

    @patch("time.sleep")
    def test_rate_limit_error_string_detection(self, mock_sleep):
        """Test that rate limit errors are detected from error messages."""
        mock_func = Mock(
            side_effect=[ValueError("429 - rate limit exceeded"), "success"]
        )

        @retry_with_backoff(max_attempts=2, initial_delay=1.0, jitter=False)
        def test_func():
            return mock_func()

        result = test_func()

        assert result == "success"
        # Should detect rate limit from error message and double delay
        mock_sleep.assert_called_once_with(2.0)

    @pytest.mark.asyncio
    @patch("asyncio.sleep")
    async def test_async_rate_limit_error_uses_longer_delay(self, mock_sleep):
        """Test that async RateLimitError triggers longer delays."""
        # Create a mock response object for RateLimitError
        mock_response = Mock()
        mock_response.request = Mock()

        mock_func = AsyncMock(
            side_effect=[
                RateLimitError(
                    "Rate limit exceeded", response=mock_response, body=None
                ),
                "success",
            ]
        )

        @retry_with_backoff(max_attempts=2, initial_delay=1.0, jitter=False)
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
        # Rate limit errors should double the delay: 1.0 * 2 = 2.0
        mock_sleep.assert_called_once_with(2.0)

    @patch("time.sleep")
    def test_rate_limit_respects_max_delay(self, mock_sleep):
        """Test that rate limit delays still respect max_delay."""
        # Create a mock response object for RateLimitError
        mock_response = Mock()
        mock_response.request = Mock()

        mock_func = Mock(
            side_effect=[
                RateLimitError(
                    "Rate limit exceeded", response=mock_response, body=None
                ),
                "success",
            ]
        )

        @retry_with_backoff(
            max_attempts=2, initial_delay=50.0, max_delay=60.0, jitter=False
        )
        def test_func():
            return mock_func()

        result = test_func()

        assert result == "success"
        # Would be 50.0 * 2 = 100.0, but capped at max_delay
        mock_sleep.assert_called_once_with(60.0)


class TestRetryWithBackoffJitter:
    """Tests for jitter functionality."""

    @patch("time.sleep")
    @patch("random.uniform")
    def test_jitter_adds_randomness_to_delay(self, mock_uniform, mock_sleep):
        """Test that jitter adds randomness to delays."""
        mock_uniform.return_value = 1.1  # 10% above base
        mock_func = Mock(side_effect=[ValueError(), "success"])

        @retry_with_backoff(max_attempts=2, initial_delay=1.0, jitter=True)
        def test_func():
            return mock_func()

        test_func()

        # Should apply jitter factor (0.75-1.25 range)
        mock_uniform.assert_called_once_with(0.75, 1.25)
        # Delay should be 1.0 * 1.1 = 1.1
        mock_sleep.assert_called_once_with(1.1)

    @patch("time.sleep")
    def test_no_jitter_when_disabled(self, mock_sleep):
        """Test that delays are exact when jitter is disabled."""
        mock_func = Mock(side_effect=[ValueError(), "success"])

        @retry_with_backoff(max_attempts=2, initial_delay=1.0, jitter=False)
        def test_func():
            return mock_func()

        test_func()

        # Should use exact delay without jitter
        mock_sleep.assert_called_once_with(1.0)
