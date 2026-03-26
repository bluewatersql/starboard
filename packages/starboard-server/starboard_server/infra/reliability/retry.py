"""Simple retry decorator with exponential backoff.

Provides both async-native and sync retry paths. The sync path includes a
runtime guard that raises ``RuntimeError`` if called from within a running
asyncio event loop, preventing accidental ``time.sleep`` calls that would
block the loop.
"""

import asyncio
import inspect
import random
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from openai import RateLimitError

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _check_not_in_async_context(func_name: str) -> None:
    """Raise RuntimeError if called from within a running asyncio event loop.

    This guard prevents sync retry paths (which use ``time.sleep``) from
    accidentally blocking an async event loop. If no running loop is found
    the function returns silently.

    Args:
        func_name: Name of the decorated function, used in the error message.

    Raises:
        RuntimeError: If an asyncio event loop is currently running.
    """
    try:
        asyncio.get_running_loop()
        raise RuntimeError(
            f"sync retry_with_backoff called from async context in '{func_name}'. "
            "Use the async path instead."
        )
    except RuntimeError as loop_err:
        # asyncio.get_running_loop() raises RuntimeError when there is no
        # running loop. We must allow that case through while re-raising our
        # own RuntimeError and any unexpected ones.
        msg = str(loop_err).lower()
        if "no current event loop" not in msg and "no running event loop" not in msg:
            raise


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
) -> Callable[[F], F]:
    """
    Retry a function with exponential backoff on exception.

    This decorator automatically retries a function when it raises an exception,
    with increasing delays between attempts following an exponential backoff strategy.
    The delay is calculated as: min(initial_delay * exponential_base^(attempt-1), max_delay).

    Supports both sync and async functions. For rate limit errors (429), uses longer delays.
    Adds jitter to prevent thundering herd problem.

    All exceptions are retried. On the final attempt, the exception is re-raised.
    Retry attempts are logged with warnings, and final failures are logged as errors.

    The sync wrapper includes a runtime guard that raises ``RuntimeError`` if
    invoked from within an active asyncio event loop, ensuring callers cannot
    accidentally block the loop with ``time.sleep``.

    Args:
        max_attempts: Maximum number of attempts including the initial call.
            Must be at least 1.
        initial_delay: Initial delay in seconds before the first retry.
            Subsequent delays grow exponentially from this base.
        max_delay: Maximum delay in seconds between attempts.
            Caps the exponential growth to prevent excessive wait times.
        exponential_base: Base for exponential backoff calculation.
            A value of 2.0 doubles the delay each attempt.
        jitter: Add random jitter (±25%) to delays to prevent thundering herd.

    Returns:
        Decorator function that wraps the target function with retry logic.
        The wrapped function has the same signature as the original.

    Notes:
        - Useful for handling transient failures in API calls, network operations,
          or any unreliable external service.
        - Consider setting appropriate max_delay to avoid long wait times.
        - All exceptions are caught and retried; use try/except around the call
          if you need to handle specific exceptions differently.
        - For rate limit errors, delay is multiplied by 2 to give more breathing room.
    """

    def decorator(func: F) -> F:
        if inspect.isasyncgenfunction(func):
            raise TypeError(
                f"@retry_with_backoff cannot wrap async generator '{func.__name__}'. "
                "Streaming methods must handle retries internally."
            )
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                attempt = 1
                while attempt <= max_attempts:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:  # noqa: BLE001 - retry catches any exception by design
                        if attempt == max_attempts:
                            logger.error(
                                "retry_exhausted",
                                func=func.__name__,
                                max_attempts=max_attempts,
                                error=str(e),
                            )
                            raise

                        delay = _calculate_delay(
                            attempt,
                            initial_delay,
                            max_delay,
                            exponential_base,
                            jitter,
                            e,
                        )
                        logger.warning(
                            "retry_attempt_failed",
                            func=func.__name__,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            error=str(e),
                            retry_delay=round(delay, 2),
                        )
                        await asyncio.sleep(delay)
                        attempt += 1

                return None  # Should never reach here

            return async_wrapper  # type: ignore
        else:

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Guard: prevent sync retry from blocking an async event loop.
                _check_not_in_async_context(func.__name__)

                attempt = 1
                while attempt <= max_attempts:
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:  # noqa: BLE001 - retry catches any exception by design
                        if attempt == max_attempts:
                            logger.error(
                                "retry_exhausted",
                                func=func.__name__,
                                max_attempts=max_attempts,
                                error=str(e),
                            )
                            raise

                        delay = _calculate_delay(
                            attempt,
                            initial_delay,
                            max_delay,
                            exponential_base,
                            jitter,
                            e,
                        )
                        logger.warning(
                            "retry_attempt_failed",
                            func=func.__name__,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            error=str(e),
                            retry_delay=round(delay, 2),
                        )
                        time.sleep(delay)
                        attempt += 1

                return None  # Should never reach here

            return sync_wrapper  # type: ignore

    return decorator


def _calculate_delay(
    attempt: int,
    initial_delay: float,
    max_delay: float,
    exponential_base: float,
    jitter: bool,
    error: Exception,
) -> float:
    """Calculate retry delay with exponential backoff, rate-limit awareness, and jitter.

    Args:
        attempt: Current attempt number (1-based).
        initial_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        exponential_base: Base for exponential growth.
        jitter: Whether to add random jitter.
        error: The exception that triggered the retry.

    Returns:
        Delay in seconds before next retry.
    """
    base_delay = min(initial_delay * (exponential_base ** (attempt - 1)), max_delay)

    # For rate limit errors, use longer delays
    error_str = str(error).lower()
    is_rate_limit = (
        isinstance(error, RateLimitError)
        or "429" in str(error)
        or "rate limit" in error_str
        or "request_limit_exceeded" in error_str
    )
    if is_rate_limit:
        base_delay = min(base_delay * 2, max_delay)

    # Add jitter to prevent thundering herd
    if jitter:
        return base_delay * random.uniform(0.75, 1.25)
    return base_delay
