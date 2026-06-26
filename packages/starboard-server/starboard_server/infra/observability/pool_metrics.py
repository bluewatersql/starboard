# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Connection pool metrics via OpenTelemetry.

Exports pool size, active connections, and acquisition wait time
for each instrumented connection pool (database, HTTP, Redis).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

meter = metrics.get_meter("starboard.pools")


class PoolMetricsCollector:
    """Collects and exports connection pool metrics via OpenTelemetry.

    Creates observable gauges for pool size and active connections,
    and a histogram for acquisition wait times.
    """

    def __init__(self, pool: Any, pool_name: str) -> None:
        self._pool = pool
        self._pool_name = pool_name

        self._size_gauge = meter.create_observable_gauge(
            f"pool.{pool_name}.size",
            callbacks=[self._observe_size],
            description=f"Total pool size for {pool_name}",
        )
        self._active_gauge = meter.create_observable_gauge(
            f"pool.{pool_name}.active",
            callbacks=[self._observe_active],
            description=f"Active connections for {pool_name}",
        )
        self._wait_histogram = meter.create_histogram(
            f"pool.{pool_name}.wait_ms",
            description=f"Wait time to acquire connection from {pool_name}",
            unit="ms",
        )

    @property
    def pool_name(self) -> str:
        return self._pool_name

    def get_pool_size(self) -> int:
        """Get current pool size from pool object."""
        if hasattr(self._pool, "size"):
            return self._pool.size  # type: ignore[no-any-return]
        if hasattr(self._pool, "maxsize"):
            return self._pool.maxsize  # type: ignore[no-any-return]
        return 0

    def get_active_count(self) -> int:
        """Get active (in-use) connection count."""
        if hasattr(self._pool, "size") and hasattr(self._pool, "freesize"):
            return self._pool.size - self._pool.freesize  # type: ignore[no-any-return]
        if hasattr(self._pool, "active_count"):
            return self._pool.active_count  # type: ignore[no-any-return]
        return 0

    def _observe_size(self, options: CallbackOptions) -> Iterable[Observation]:  # noqa: ARG002
        return [Observation(self.get_pool_size())]

    def _observe_active(self, options: CallbackOptions) -> Iterable[Observation]:  # noqa: ARG002
        return [Observation(self.get_active_count())]

    def record_acquisition(self, wait_ms: float) -> None:
        """Record connection acquisition wait time in milliseconds."""
        self._wait_histogram.record(wait_ms)
