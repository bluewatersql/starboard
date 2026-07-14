# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for AsyncCircuitBreaker.

Tests cover:
- State transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Failure counting and threshold enforcement
- Timeout behavior and recovery attempts (mocked time.monotonic)
- Manual reset functionality
- Error propagation and circuit breaker errors
- Concurrent call safety
- Backward-compatible CircuitBreaker alias
"""

import asyncio
from unittest.mock import patch

import pytest
from starboard.infra.reliability.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
)

# --- Helpers ---


async def succeed() -> str:
    return "success"


async def fail_value_error() -> str:
    raise ValueError("Test error")


async def fail_runtime_error() -> str:
    raise RuntimeError("Runtime error")


# --- Happy Path ---


class TestAsyncCircuitBreakerHappyPath:
    """Tests for successful execution paths."""

    @pytest.mark.asyncio
    async def test_closed_state_allows_calls(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=5),
            name="test",
        )
        result = await breaker.call(succeed)
        assert result == "success"
        assert breaker.get_state() == CircuitState.CLOSED
        assert breaker.get_failure_count() == 0

    @pytest.mark.asyncio
    async def test_multiple_successful_calls(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=3),
        )
        for _ in range(10):
            result = await breaker.call(succeed)
            assert result == "success"

        assert breaker.get_state() == CircuitState.CLOSED
        assert breaker.get_failure_count() == 0

    @pytest.mark.asyncio
    async def test_successful_call_resets_failure_count(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=3),
        )
        # Cause 2 failures (below threshold)
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(fail_value_error)

        assert breaker.get_failure_count() == 2

        # Success resets counter
        await breaker.call(succeed)
        assert breaker.get_failure_count() == 0
        assert breaker.get_state() == CircuitState.CLOSED


# --- Failure Threshold ---


class TestAsyncCircuitBreakerFailureThreshold:
    """Tests for failure counting and circuit opening."""

    @pytest.mark.asyncio
    async def test_failures_below_threshold_stay_closed(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=5),
        )
        for _ in range(4):
            with pytest.raises(ValueError):
                await breaker.call(fail_value_error)

        assert breaker.get_state() == CircuitState.CLOSED
        assert breaker.get_failure_count() == 4

    @pytest.mark.asyncio
    async def test_failure_at_threshold_opens_circuit(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=3),
        )
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail_value_error)

        assert breaker.get_state() == CircuitState.OPEN
        assert breaker.get_failure_count() == 3

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=2),
        )
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(fail_value_error)

        with pytest.raises(CircuitBreakerError, match="OPEN"):
            await breaker.call(succeed)

    @pytest.mark.asyncio
    async def test_open_circuit_does_not_call_function(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=1),
        )
        call_count = 0

        async def counting_fn() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        # Open circuit
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)

        # Function should not execute
        with pytest.raises(CircuitBreakerError):
            await breaker.call(counting_fn)

        assert call_count == 0


# --- Half-Open State ---


class TestAsyncCircuitBreakerHalfOpenState:
    """Tests for half-open state and recovery using mocked time.monotonic."""

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=10.0),
        )
        # Open circuit
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)
        assert breaker._state == CircuitState.OPEN

        # Advance monotonic time past recovery_timeout
        original_time = breaker._last_failure_time
        with patch(
            "starboard.infra.reliability.circuit_breaker.time"
        ) as mock_time:
            mock_time.monotonic.return_value = original_time + 11.0
            result = await breaker.call(succeed)

        assert result == "success"
        assert breaker.get_state() == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=10.0,
                success_threshold=1,
            ),
        )
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)

        # Advance time
        original_time = breaker._last_failure_time
        with patch(
            "starboard.infra.reliability.circuit_breaker.time"
        ) as mock_time:
            mock_time.monotonic.return_value = original_time + 11.0
            await breaker.call(succeed)

        assert breaker.get_state() == CircuitState.CLOSED
        assert breaker.get_failure_count() == 0

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=10.0),
        )
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)

        # Advance time to trigger half-open, then fail
        original_time = breaker._last_failure_time
        with patch(
            "starboard.infra.reliability.circuit_breaker.time"
        ) as mock_time:
            mock_time.monotonic.return_value = original_time + 11.0
            with pytest.raises(ValueError):
                await breaker.call(fail_value_error)

        assert breaker._state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_half_open_requires_success_threshold(self):
        """Test that success_threshold > 1 requires multiple successes."""
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=10.0,
                success_threshold=3,
            ),
        )
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)

        original_time = breaker._last_failure_time
        with patch(
            "starboard.infra.reliability.circuit_breaker.time"
        ) as mock_time:
            mock_time.monotonic.return_value = original_time + 11.0

            # First success: still half-open
            await breaker.call(succeed)
            assert breaker._state == CircuitState.HALF_OPEN

            # Second success: still half-open
            await breaker.call(succeed)
            assert breaker._state == CircuitState.HALF_OPEN

            # Third success: closed
            await breaker.call(succeed)
            assert breaker._state == CircuitState.CLOSED


# --- Manual Reset ---


class TestAsyncCircuitBreakerManualReset:
    """Tests for manual reset functionality."""

    @pytest.mark.asyncio
    async def test_manual_reset_closes_circuit(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=1),
        )
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)
        assert breaker.get_state() == CircuitState.OPEN

        await breaker.reset()
        assert breaker.get_state() == CircuitState.CLOSED
        assert breaker.get_failure_count() == 0

    @pytest.mark.asyncio
    async def test_reset_allows_immediate_calls(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=1),
        )
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)

        await breaker.reset()
        result = await breaker.call(succeed)
        assert result == "success"


# --- Concurrent Safety ---


class TestAsyncCircuitBreakerConcurrency:
    """Tests for concurrent call handling."""

    @pytest.mark.asyncio
    async def test_concurrent_calls_handled_safely(self):
        """Multiple concurrent calls don't corrupt state."""
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=10),
        )

        async def slow_success() -> str:
            await asyncio.sleep(0.01)
            return "ok"

        results = await asyncio.gather(*[breaker.call(slow_success) for _ in range(20)])
        assert all(r == "ok" for r in results)
        assert breaker.get_state() == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_concurrent_failures_open_circuit_once(self):
        """Concurrent failures don't cause double-open or corruption."""
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=3),
        )

        async def slow_fail() -> str:
            await asyncio.sleep(0.01)
            raise ValueError("fail")

        # Fire 10 concurrent failures
        results = await asyncio.gather(
            *[breaker.call(slow_fail) for _ in range(10)],
            return_exceptions=True,
        )

        # All should be either ValueError or CircuitBreakerError
        for r in results:
            assert isinstance(r, (ValueError, CircuitBreakerError))

        assert breaker._state == CircuitState.OPEN


# --- Edge Cases ---


class TestAsyncCircuitBreakerEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_threshold_one_opens_immediately(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=1),
        )
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)
        assert breaker.get_state() == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_custom_circuit_name_in_error(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=1),
            name="test_circuit",
        )
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)

        with pytest.raises(CircuitBreakerError, match="test_circuit"):
            await breaker.call(succeed)

    @pytest.mark.asyncio
    async def test_exception_propagates_with_details(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=5),
        )

        async def custom_error():
            raise ValueError("Custom error message")

        with pytest.raises(ValueError, match="Custom error message"):
            await breaker.call(custom_error)

    @pytest.mark.asyncio
    async def test_different_exception_types(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=5),
        )
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)
        with pytest.raises(RuntimeError):
            await breaker.call(fail_runtime_error)

        assert breaker.get_failure_count() == 2

    @pytest.mark.asyncio
    async def test_call_with_args_and_kwargs(self):
        """Test that args and kwargs are forwarded correctly."""
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=5),
        )

        async def add(a: int, b: int, extra: int = 0) -> int:
            return a + b + extra

        result = await breaker.call(add, 1, 2, extra=10)
        assert result == 13

    @pytest.mark.asyncio
    async def test_open_before_timeout_rejects(self):
        breaker = AsyncCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=1000.0),
        )
        with pytest.raises(ValueError):
            await breaker.call(fail_value_error)

        with pytest.raises(CircuitBreakerError):
            await breaker.call(succeed)


# --- Config ---


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig dataclass."""

    def test_default_values(self):
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60.0
        assert config.half_open_max_calls == 1
        assert config.success_threshold == 1

    def test_custom_values(self):
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=30.0,
            half_open_max_calls=2,
            success_threshold=2,
        )
        assert config.failure_threshold == 3
        assert config.recovery_timeout == 30.0


# --- Backward Compatibility ---


class TestCircuitBreakerBackwardCompat:
    """Tests for backward-compatible CircuitBreaker alias."""

    def test_alias_is_async_circuit_breaker(self):
        assert CircuitBreaker is AsyncCircuitBreaker

    @pytest.mark.asyncio
    async def test_legacy_constructor_kwargs(self):
        """Old CircuitBreaker(failure_threshold=5, timeout_seconds=60) still works."""
        breaker = CircuitBreaker(
            failure_threshold=3,
            timeout_seconds=30,
            name="legacy",
        )
        assert breaker._config.failure_threshold == 3
        assert breaker._config.recovery_timeout == 30.0
        assert breaker.name == "legacy"

        result = await breaker.call(succeed)
        assert result == "success"
