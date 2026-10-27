# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
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
from datetime import UTC
from functools import wraps
from typing import Any, TypeVar

from openai import RateLimitError

from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# HTTP statuses that will never succeed on retry: bad request, auth, not-found,
# method-not-allowed, unprocessable-entity. Retrying these just burns time and
# backoff (e.g. a mistyped model-serving endpoint returns 404 forever). Rate
# limits (429), request timeouts (408), conflicts (409) and 5xx are transient
# and remain retryable.
_PERMANENT_STATUS_CODES = frozenset({400, 401, 403, 404, 405, 422})


def _status_code_of(error: BaseException) -> int | None:
    """Best-effort extraction of an HTTP status code from an exception.

    Reads ``error.status_code`` (openai ``APIStatusError``) and falls back to a
    nested ``error.response.status_code`` (httpx-style). Returns ``None`` when no
    HTTP status is present (non-HTTP errors stay retryable by default).
    """
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        status = getattr(getattr(error, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def _retry_after_seconds(error: BaseException) -> float | None:
    """Best-effort extraction of a server-directed ``Retry-After`` wait.

    Reads the ``Retry-After`` header off ``error.response.headers`` (openai/httpx
    style). The header may be an integer/float number of seconds or an HTTP-date;
    both forms are parsed. Returns the number of seconds to wait (never negative),
    or ``None`` when no usable value is present. Honoring this keeps us from
    retrying before the server is ready — the surest way to clear a 429.
    """
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = None
    try:
        raw = headers.get("retry-after")
    except (AttributeError, TypeError):
        return None
    if raw is None:
        return None
    # Numeric form: seconds to wait.
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    # HTTP-date form: absolute time to resume.
    try:
        from datetime import datetime
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(raw)
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return None


def is_permanent_error(error: BaseException) -> bool:
    """Return ``True`` for errors that cannot succeed on retry.

    A permanent error is an HTTP client error in :data:`_PERMANENT_STATUS_CODES`
    (a nonexistent endpoint, denied auth, malformed request). Rate limits, request
    timeouts, conflicts, 5xx, and any exception without an HTTP status are treated
    as transient so existing retry behavior is preserved for them.
    """
    status = _status_code_of(error)
    if status is None:
        return False
    return status in _PERMANENT_STATUS_CODES


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
    rate_limit_max_delay: float = 90.0,
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
        rate_limit_max_delay: Delay cap (seconds) applied specifically to rate
            limit (429) errors, allowing them to back off longer than ``max_delay``.
            A saturated per-minute token window needs the total backoff to span
            ~60s; the default 90s lets a few attempts cover it. A server-provided
            ``Retry-After`` is honored (as a floor) up to this cap.

    Returns:
        Decorator function that wraps the target function with retry logic.
        The wrapped function has the same signature as the original.

    Notes:
        - Useful for handling transient failures in API calls, network operations,
          or any unreliable external service.
        - Consider setting appropriate max_delay to avoid long wait times.
        - All exceptions are caught and retried; use try/except around the call
          if you need to handle specific exceptions differently.
        - For rate limit errors, the delay is doubled and capped at
          ``rate_limit_max_delay``; a ``Retry-After`` header, when present, wins.
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
                        if is_permanent_error(e):
                            logger.error(
                                "retry_aborted_permanent",
                                func=func.__name__,
                                attempt=attempt,
                                status_code=_status_code_of(e),
                                error=str(e),
                            )
                            raise
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
                            rate_limit_max_delay,
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
                        if is_permanent_error(e):
                            logger.error(
                                "retry_aborted_permanent",
                                func=func.__name__,
                                attempt=attempt,
                                status_code=_status_code_of(e),
                                error=str(e),
                            )
                            raise
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
                            rate_limit_max_delay,
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
    rate_limit_max_delay: float | None = None,
) -> float:
    """Calculate retry delay with exponential backoff, rate-limit awareness, and jitter.

    Args:
        attempt: Current attempt number (1-based).
        initial_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        exponential_base: Base for exponential growth.
        jitter: Whether to add random jitter.
        error: The exception that triggered the retry.
        rate_limit_max_delay: Delay cap applied to rate-limit (429) errors instead
            of ``max_delay``. Defaults to ``max_delay`` when ``None`` (preserves the
            original behavior for callers that do not pass it).

    Returns:
        Delay in seconds before next retry.
    """
    base_delay = min(initial_delay * (exponential_base ** (attempt - 1)), max_delay)

    # For rate limit errors, back off harder and up to a longer cap so the total
    # wait can span a saturated per-minute token window.
    error_str = str(error).lower()
    is_rate_limit = (
        isinstance(error, RateLimitError)
        or "429" in str(error)
        or "rate limit" in error_str
        or "request_limit_exceeded" in error_str
    )
    # When True, the delay is a server-directed Retry-After that must be treated as
    # a floor — jitter may only push it up, never below what the server asked for.
    server_directed = False
    if is_rate_limit:
        cap = max_delay if rate_limit_max_delay is None else rate_limit_max_delay
        retry_after = _retry_after_seconds(error)
        if retry_after is not None:
            base_delay = min(retry_after, cap)
            server_directed = True
        else:
            base_delay = min(base_delay * 2, cap)

    # Add jitter to prevent thundering herd. A server-directed wait only jitters
    # upward so we never retry before the server is ready.
    if jitter:
        low = 1.0 if server_directed else 0.75
        return base_delay * random.uniform(low, 1.25)
    return base_delay
