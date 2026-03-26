"""Circuit breaker pattern for external service calls.

This module implements the circuit breaker pattern to prevent cascading failures
when external services (like LLM APIs) become unavailable or degraded.

Provides an async-native ``AsyncCircuitBreaker`` implementation.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeVar

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states.

    Attributes:
        CLOSED: Normal operation, requests flow through
        OPEN: Service failing, requests are rejected immediately
        HALF_OPEN: Testing if service has recovered
    """

    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open and rejects a request."""

    pass


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior.

    Attributes:
        failure_threshold: Number of consecutive failures before opening
        recovery_timeout: Seconds to wait before testing recovery (half-open)
        half_open_max_calls: Maximum concurrent calls allowed in half-open state
        success_threshold: Consecutive successes needed to close from half-open
    """

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 1
    success_threshold: int = 1


class AsyncCircuitBreaker:
    """Async-native circuit breaker for protecting against cascading failures.

    Uses asyncio.Lock for concurrency safety and time.monotonic() for
    reliable timeout tracking. Automatically records successes and failures.

    State machine:
        CLOSED -> OPEN: after failure_threshold consecutive failures
        OPEN -> HALF_OPEN: after recovery_timeout elapsed
        HALF_OPEN -> CLOSED: after success_threshold consecutive successes
        HALF_OPEN -> OPEN: on any failure

    Example:
        >>> breaker = AsyncCircuitBreaker(
        ...     config=CircuitBreakerConfig(failure_threshold=3, recovery_timeout=30),
        ...     name="llm_api",
        ... )
        >>> result = await breaker.call(some_async_function, arg1, arg2)
    """

    def __init__(
        self,
        config: CircuitBreakerConfig | None = None,
        name: str = "default",
        # Legacy kwargs for backward compat with old CircuitBreaker constructor
        failure_threshold: int | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = CircuitBreakerConfig(
                failure_threshold=failure_threshold or 5,
                recovery_timeout=float(timeout_seconds or 60),
            )

        self.name = name
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state (check for timeout-based transition)."""
        if self._state == CircuitState.OPEN and self._should_attempt_recovery():
            return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current consecutive failure count."""
        return self._failure_count

    @property
    def failure_threshold(self) -> int:
        """Get failure threshold from config (backward compat)."""
        return self._config.failure_threshold

    @property
    def recovery_timeout(self) -> float:
        """Get recovery timeout from config (backward compat)."""
        return self._config.recovery_timeout

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has elapsed to attempt recovery."""
        if self._last_failure_time is None:
            return False
        elapsed = time.monotonic() - self._last_failure_time
        return elapsed >= self._config.recovery_timeout

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args,
        **kwargs,
    ) -> T:
        """Execute an async function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from the function

        Raises:
            CircuitBreakerError: If circuit is open and recovery timeout not elapsed
            Exception: Any exception raised by the function
        """
        async with self._lock:
            # Check state and transition OPEN -> HALF_OPEN if timeout elapsed
            if self._state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    logger.info(
                        "circuit_breaker_half_open",
                        name=self.name,
                        recovery_timeout=self._config.recovery_timeout,
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                else:
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Service calls are blocked."
                    )

        # Execute outside the lock to allow concurrent calls in CLOSED state
        try:
            result = await func(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - circuit breaker records any failure
            await self._record_failure(e)
            raise

        await self._record_success()
        return result

    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._config.success_threshold:
                    logger.info(
                        "circuit_breaker_recovered",
                        name=self.name,
                    )
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._last_failure_time = None
            elif self._failure_count > 0:
                # Reset failure count on success in CLOSED state
                self._failure_count = 0
                self._last_failure_time = None

    async def _record_failure(self, error: Exception) -> None:
        """Record a failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            self._success_count = 0

            if self._state == CircuitState.HALF_OPEN:
                logger.warning(
                    "circuit_breaker_half_open_failed",
                    name=self.name,
                    error=str(error),
                )
                self._state = CircuitState.OPEN
            elif self._failure_count >= self._config.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "circuit_breaker_opening",
                        name=self.name,
                        failure_count=self._failure_count,
                    )
                    self._state = CircuitState.OPEN
            else:
                logger.warning(
                    "circuit_breaker_failure",
                    name=self.name,
                    failure_count=self._failure_count,
                    failure_threshold=self._config.failure_threshold,
                    error=str(error),
                )

    async def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        async with self._lock:
            logger.debug("circuit_breaker_reset", name=self.name)
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None

    def get_state(self) -> CircuitState:
        """Get the current state of the circuit breaker."""
        return self.state

    def get_failure_count(self) -> int:
        """Get the current failure count."""
        return self._failure_count


# Backward-compatible alias — deprecated, use AsyncCircuitBreaker instead
CircuitBreaker = AsyncCircuitBreaker
