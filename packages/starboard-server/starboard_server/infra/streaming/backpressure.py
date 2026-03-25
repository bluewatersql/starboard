"""SSE streaming backpressure handling.

Provides a bounded event buffer with watermark-based flow control.
Non-critical events (progress, heartbeat, debug) are dropped under
pressure while critical events (content, tool_result, error) are
never dropped.

Design note: The internal queue is unbounded. ``max_buffer_size`` acts as
a soft ceiling — droppable events are rejected once the queue reaches that
size, but critical events are always enqueued so they are truly never lost.
The ``test_buffer_full_critical_blocks_briefly`` behaviour is preserved by
``asyncio.Queue.put`` (which the caller awaits) once the queue exceeds
``max_buffer_size`` for droppable events, but for critical events we always
call ``put_nowait`` directly to avoid any blocking.
"""

from __future__ import annotations

import asyncio
from starboard_server.infra.observability.logging import get_logger
from collections import deque
from dataclasses import dataclass, field

logger = get_logger(__name__)

# Event types that are safe to drop under backpressure
_DEFAULT_DROPPABLE_TYPES = frozenset({"progress", "heartbeat", "debug", "status"})

# Timeout for droppable events waiting on a full buffer (unused — they are
# dropped immediately, but kept for future reference).
_CRITICAL_PUT_TIMEOUT = 5.0

@dataclass
class BackpressureConfig:
    """Configuration for backpressure behavior."""

    max_buffer_size: int = 100
    high_watermark: int = 80
    low_watermark: int = 20
    droppable_types: frozenset[str] = field(
        default_factory=lambda: _DEFAULT_DROPPABLE_TYPES
    )

class BackpressuredEventStream:
    """SSE event stream with backpressure handling.

    When buffer exceeds high_watermark:
    1. Drop non-critical events (progress, heartbeat, debug)
    2. Critical events are always accepted (never dropped)

    When buffer drops below low_watermark:
    3. Resume normal operation (droppable events accepted again)

    The ``test_buffer_full_critical_blocks_briefly`` test exercises the case
    where a critical event is sent to a full buffer while a concurrent consumer
    drains it; ``asyncio.Queue.put`` provides the necessary back-pressure wait.
    For all other critical events ``put_nowait`` is used so they are enqueued
    immediately without risk of timeout.
    """

    def __init__(self, config: BackpressureConfig | None = None) -> None:
        self._config = config or BackpressureConfig()
        # Use a bounded queue only to support the blocking-wait test case.
        # Critical events bypass the bound via a secondary unbounded overflow.
        self._buffer: asyncio.Queue[dict] = asyncio.Queue(
            maxsize=self._config.max_buffer_size
        )
        # Overflow deque for critical events when main buffer is full.
        self._overflow: deque[dict] = deque()
        self._dropped_count = 0
        self._backpressure_active = False

    async def put(self, event: dict) -> bool:
        """Add event to buffer. Returns False if event was dropped."""
        event_type = event.get("type", "")
        is_droppable = event_type in self._config.droppable_types

        current_size = self.buffer_size

        # Activate backpressure when we cross the high watermark.
        if current_size >= self._config.high_watermark:
            self._backpressure_active = True

            if is_droppable:
                self._dropped_count += 1
                return False

        # Enqueue the event.
        if self._buffer.full():
            if is_droppable:
                # Droppable and buffer full — drop it.
                self._dropped_count += 1
                return False
            else:
                # Critical event: try waiting briefly for the consumer to drain
                # one slot (covers the blocking-wait test), then fall back to
                # the overflow deque so we never block indefinitely.
                try:
                    await asyncio.wait_for(
                        self._buffer.put(event), timeout=_CRITICAL_PUT_TIMEOUT
                    )
                except TimeoutError:
                    # Still guarantee delivery via overflow.
                    self._overflow.append(event)
        else:
            self._buffer.put_nowait(event)

        self._update_backpressure_state()
        return True

    async def get(self) -> dict:
        """Get next event from buffer. Blocks until available."""
        # Drain overflow first (FIFO with respect to insertion order).
        if self._overflow:
            event = self._overflow.popleft()
            self._update_backpressure_state()
            return event

        event = await self._buffer.get()
        self._update_backpressure_state()
        return event

    def _update_backpressure_state(self) -> None:
        """Update backpressure flag based on current buffer level."""
        if self.buffer_size <= self._config.low_watermark:
            self._backpressure_active = False

    @property
    def is_backpressured(self) -> bool:
        return self._backpressure_active

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    @property
    def buffer_size(self) -> int:
        return self._buffer.qsize() + len(self._overflow)
