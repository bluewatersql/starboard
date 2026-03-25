"""Base service class with async patterns for Databricks SDK.

This module provides a base class for all Databricks services with:
- Async wrapping of synchronous SDK calls via dedicated thread pool
- Retry with exponential backoff
- Consistent error handling
- Logging with trace context

All service methods should be async to avoid blocking the event loop
when used in async contexts (e.g., FastAPI endpoints, SSE streaming).

The Databricks SDK is sync-only, so all SDK calls run in a bounded
dedicated ``ThreadPoolExecutor`` to avoid starving the default asyncio
executor used by the rest of the application.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, TypeVar

import httpx

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

# HTTP status codes that indicate permanent (non-retryable) errors.
_PERMANENT_HTTP_STATUS_CODES: frozenset[int] = frozenset({400, 401, 403, 404, 405, 409, 422})

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Dedicated Databricks SDK thread pool
# ---------------------------------------------------------------------------

_databricks_executor: ThreadPoolExecutor | None = None

# Threshold (fraction) at which we emit a capacity warning.
_CAPACITY_WARN_THRESHOLD = 0.75


def _get_databricks_executor(max_workers: int = 8) -> ThreadPoolExecutor:
    """Get or create dedicated Databricks SDK thread pool.

    The Databricks SDK is sync-only, so we use a bounded dedicated pool
    to avoid starving the default asyncio executor.

    Args:
        max_workers: Maximum concurrent Databricks SDK calls.

    Returns:
        Dedicated ThreadPoolExecutor for Databricks SDK calls.
    """
    global _databricks_executor
    if _databricks_executor is None:
        _databricks_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="databricks-sdk",
        )
        logger.info(
            "databricks_thread_pool_created",
            extra={"max_workers": max_workers},
        )
    return _databricks_executor


def shutdown_databricks_executor(wait: bool = True) -> None:
    """Shutdown the dedicated Databricks SDK thread pool.

    Should be called during application shutdown to release thread resources.
    Safe to call even when the pool has never been created.

    Args:
        wait: If True, wait for all pending futures to complete before
              returning. Pass False for non-blocking shutdown.
    """
    global _databricks_executor
    if _databricks_executor is not None:
        _databricks_executor.shutdown(wait=wait)
        _databricks_executor = None
        logger.info("databricks_thread_pool_shutdown")


async def run_databricks_sync(func: Callable[..., T], *args: object) -> T:  # noqa: UP047
    """Run sync Databricks SDK call in dedicated thread pool.

    Uses a bounded ``ThreadPoolExecutor`` so that synchronous SDK calls
    cannot monopolise the default asyncio executor.

    Args:
        func: Sync function to execute.
        *args: Positional arguments forwarded to *func*.

    Returns:
        Result of the sync function.
    """
    loop = asyncio.get_running_loop()
    executor = _get_databricks_executor()

    # Capacity monitoring: warn when pool is heavily utilised.
    pending = getattr(executor, "_work_queue", None)
    if pending is not None:
        queue_size = pending.qsize()
        max_workers = executor._max_workers  # noqa: SLF001
        if queue_size > max_workers * _CAPACITY_WARN_THRESHOLD:
            logger.warning(
                "databricks_thread_pool_high_utilization",
                extra={
                    "queued_tasks": queue_size,
                    "max_workers": max_workers,
                    "utilization_pct": round(queue_size / max_workers * 100, 1),
                },
            )

    return await loop.run_in_executor(executor, func, *args)


class BaseService:
    """Base class for Databricks service implementations.

    Provides common patterns for async SDK interactions:
    - _run_sync: Execute sync SDK calls in thread pool
    - _run_with_retry: Execute with exponential backoff retry

    All public methods in subclasses should be async.

    Example:
        >>> class JobService(BaseService):
        ...     async def get_job(self, job_id: int) -> dict[str, Any]:
        ...         return await self._run_sync(
        ...             lambda: self._client.jobs.get(job_id).as_dict()
        ...         )
    """

    def __init__(self, client: WorkspaceClient) -> None:
        """Initialize base service.

        Args:
            client: Authenticated Databricks WorkspaceClient
        """
        self._client = client

    @property
    def client(self) -> WorkspaceClient:
        """Get the underlying WorkspaceClient."""
        return self._client

    async def _run_sync(self, func: Callable[[], T]) -> T:
        """Run synchronous SDK function in dedicated Databricks thread pool.

        This is the standard pattern for wrapping sync Databricks SDK
        calls to avoid blocking the async event loop.

        The function runs in a dedicated bounded thread pool executor
        (not the default asyncio executor), allowing other async tasks
        to continue while waiting for the SDK call without risk of
        starving unrelated async work.

        Args:
            func: Zero-argument callable that returns the result

        Returns:
            Result of the function execution

        Raises:
            Any exception raised by the function

        Example:
            >>> result = await self._run_sync(
            ...     lambda: self._client.jobs.get(123).as_dict()
            ... )
        """
        return await run_databricks_sync(func)

    async def _run_with_retry(
        self,
        func: Callable[[], T],
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> T:
        """Run function with exponential backoff retry.

        Useful for operations that may fail due to transient errors
        (rate limiting, network issues, temporary unavailability).

        Retry delays follow exponential backoff:
        - Attempt 1: immediate
        - Attempt 2: retry_delay seconds
        - Attempt 3: retry_delay * 2 seconds
        - etc.

        Args:
            func: Zero-argument callable to execute
            max_retries: Maximum number of attempts (default: 3)
            retry_delay: Initial delay between retries in seconds (default: 1.0)

        Returns:
            Result of successful function execution

        Raises:
            The last exception if all retries are exhausted

        Example:
            >>> result = await self._run_with_retry(
            ...     lambda: self._client.clusters.get(cluster_id).as_dict(),
            ...     max_retries=3,
            ...     retry_delay=1.0,
            ... )
        """
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                return await self._run_sync(func)
            except Exception as e:
                # Do not retry permanent HTTP errors (400, 401, 403, 404, …)
                if (
                    isinstance(e, httpx.HTTPStatusError)
                    and e.response.status_code in _PERMANENT_HTTP_STATUS_CODES
                ):
                    raise

                last_error = e
                if attempt < max_retries - 1:
                    delay = retry_delay * (2**attempt)
                    logger.warning(
                        "databricks_api_retry",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "delay": delay,
                            "error": str(e),
                            "error_type": type(e).__name__,
                        },
                    )
                    await asyncio.sleep(delay)

        # All retries exhausted, raise the last error
        if last_error is not None:
            raise last_error

        # Should never reach here, but satisfy type checker
        raise RuntimeError("Unexpected state: no result and no error")
