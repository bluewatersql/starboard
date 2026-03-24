"""Health check dependency probes.

Each probe checks a specific dependency and returns a generic name
(database, cache, compute, ai) to avoid exposing internal architecture.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ProbeResult:
    """Result of a health check probe."""

    name: str
    healthy: bool
    latency_ms: float
    error: str | None = None


@runtime_checkable
class HealthProbe(Protocol):
    """Protocol for health check probes."""

    @property
    def name(self) -> str: ...

    async def check(self) -> ProbeResult: ...


class DatabaseProbe:
    """Probes database connectivity via connection pool."""

    def __init__(self, db_pool: Any) -> None:
        self._pool = db_pool

    @property
    def name(self) -> str:
        return "database"

    async def check(self) -> ProbeResult:
        start = time.monotonic()
        try:
            conn = await self._pool.acquire()
            try:
                await conn.execute("SELECT 1")
            finally:
                await self._pool.release(conn)
            return ProbeResult(
                name="database",
                healthy=True,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return ProbeResult(
                name="database",
                healthy=False,
                latency_ms=(time.monotonic() - start) * 1000,
                error=str(e),
            )


class RedisProbe:
    """Probes Redis/cache connectivity."""

    def __init__(self, redis_client: Any) -> None:
        self._client = redis_client

    @property
    def name(self) -> str:
        return "cache"

    async def check(self) -> ProbeResult:
        start = time.monotonic()
        try:
            await self._client.ping()
            return ProbeResult(
                name="cache",
                healthy=True,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return ProbeResult(
                name="cache",
                healthy=False,
                latency_ms=(time.monotonic() - start) * 1000,
                error=str(e),
            )


class DatabricksProbe:
    """Probes Databricks compute connectivity."""

    def __init__(self, databricks_client: Any) -> None:
        self._client = databricks_client

    @property
    def name(self) -> str:
        return "compute"

    async def check(self) -> ProbeResult:
        start = time.monotonic()
        try:
            await self._client.get_current_user()
            return ProbeResult(
                name="compute",
                healthy=True,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return ProbeResult(
                name="compute",
                healthy=False,
                latency_ms=(time.monotonic() - start) * 1000,
                error=str(e),
            )


class LLMProviderProbe:
    """Probes LLM provider connectivity."""

    def __init__(self, llm_client: Any) -> None:
        self._client = llm_client

    @property
    def name(self) -> str:
        return "ai"

    async def check(self) -> ProbeResult:
        start = time.monotonic()
        try:
            await self._client.models.list()
            return ProbeResult(
                name="ai",
                healthy=True,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return ProbeResult(
                name="ai",
                healthy=False,
                latency_ms=(time.monotonic() - start) * 1000,
                error=str(e),
            )


class BackpressureProbe:
    """Probes internal queue / backpressure health.

    Checks whether the service is overloaded by inspecting an async queue
    or semaphore. Healthy when utilisation is below the configured threshold.
    """

    def __init__(
        self, queue: asyncio.Queue, max_size: int, threshold: float = 0.9
    ) -> None:
        self._queue = queue
        self._max_size = max_size
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "backpressure"

    async def check(self) -> ProbeResult:
        start = time.monotonic()
        try:
            utilisation = (
                self._queue.qsize() / self._max_size if self._max_size > 0 else 0.0
            )
            healthy = utilisation < self._threshold
            return ProbeResult(
                name="backpressure",
                healthy=healthy,
                latency_ms=(time.monotonic() - start) * 1000,
                error=None
                if healthy
                else f"queue utilisation {utilisation:.0%} exceeds threshold",
            )
        except Exception as e:
            return ProbeResult(
                name="backpressure",
                healthy=False,
                latency_ms=(time.monotonic() - start) * 1000,
                error=str(e),
            )


async def check_with_timeout(
    probe: HealthProbe, timeout_seconds: float = PROBE_TIMEOUT_SECONDS
) -> ProbeResult:
    """Run a probe with timeout protection."""
    try:
        return await asyncio.wait_for(probe.check(), timeout=timeout_seconds)
    except TimeoutError:
        return ProbeResult(
            name=probe.name,
            healthy=False,
            latency_ms=timeout_seconds * 1000,
            error="timeout",
        )


class HealthCheckRunner:
    """Runs all health probes concurrently and aggregates results."""

    def __init__(
        self, probes: list[HealthProbe], timeout_seconds: float = PROBE_TIMEOUT_SECONDS
    ) -> None:
        self._probes = probes
        self._timeout = timeout_seconds

    async def run(self) -> dict:
        """Run all probes and return aggregated health status."""
        if not self._probes:
            return {"status": "ready", "checks": {}}

        results = await asyncio.gather(
            *(check_with_timeout(p, self._timeout) for p in self._probes),
            return_exceptions=True,
        )

        checks: dict[str, dict] = {}
        all_healthy = True

        for r in results:
            if isinstance(r, ProbeResult):
                checks[r.name] = {
                    "healthy": r.healthy,
                    "latency_ms": round(r.latency_ms, 1),
                }
                if not r.healthy:
                    all_healthy = False
            elif isinstance(r, BaseException):
                all_healthy = False

        status = "ready" if all_healthy else "degraded"
        return {"status": status, "checks": checks}
