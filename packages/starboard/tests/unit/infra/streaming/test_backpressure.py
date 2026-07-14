# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for SSE streaming backpressure."""

import asyncio

import pytest
from starboard.infra.streaming.backpressure import (
    BackpressureConfig,
    BackpressuredEventStream,
)


class TestBackpressureConfig:
    """Tests for BackpressureConfig defaults."""

    def test_default_config(self):
        config = BackpressureConfig()
        assert config.max_buffer_size == 100
        assert config.high_watermark == 80
        assert config.low_watermark == 20

    def test_custom_config(self):
        config = BackpressureConfig(
            max_buffer_size=50, high_watermark=40, low_watermark=10
        )
        assert config.max_buffer_size == 50

    def test_default_droppable_types(self):
        config = BackpressureConfig()
        assert "progress" in config.droppable_types
        assert "heartbeat" in config.droppable_types

    def test_critical_types_never_droppable(self):
        config = BackpressureConfig()
        for critical in [
            "message_delta",
            "tool_result",
            "error",
            "complete",
            "tool_call",
            "reasoning",
        ]:
            assert critical not in config.droppable_types


class TestBackpressuredEventStream:
    """Tests for BackpressuredEventStream."""

    @pytest.mark.asyncio
    async def test_normal_flow(self):
        """Events flow through normally under no pressure."""
        stream = BackpressuredEventStream()

        event = {"type": "message_delta", "data": "hello"}
        accepted = await stream.put(event)

        assert accepted is True
        assert stream.is_backpressured is False

        result = await stream.get()
        assert result == event

    @pytest.mark.asyncio
    async def test_drops_non_critical_under_pressure(self):
        """Non-critical events dropped when buffer exceeds high watermark."""
        config = BackpressureConfig(
            max_buffer_size=10, high_watermark=5, low_watermark=2
        )
        stream = BackpressuredEventStream(config)

        # Fill buffer to high watermark with critical events
        for i in range(6):
            await stream.put({"type": "message_delta", "data": f"msg_{i}"})

        # Now try to add a droppable event
        accepted = await stream.put({"type": "progress", "data": "50%"})
        assert accepted is False
        assert stream.dropped_count == 1

    @pytest.mark.asyncio
    async def test_critical_events_never_dropped(self):
        """Critical events are never dropped even under pressure."""
        config = BackpressureConfig(
            max_buffer_size=10, high_watermark=5, low_watermark=2
        )
        stream = BackpressuredEventStream(config)

        # Fill buffer to high watermark
        for i in range(6):
            await stream.put({"type": "message_delta", "data": f"msg_{i}"})

        # Critical events should still be accepted
        for event_type in [
            "message_delta",
            "tool_result",
            "error",
            "complete",
            "tool_call",
        ]:
            accepted = await stream.put({"type": event_type, "data": "critical"})
            assert accepted is True, f"Critical event '{event_type}' was dropped"

    @pytest.mark.asyncio
    async def test_backpressure_flag_activates(self):
        """Backpressure flag activates when high watermark exceeded."""
        config = BackpressureConfig(
            max_buffer_size=10, high_watermark=5, low_watermark=2
        )
        stream = BackpressuredEventStream(config)

        assert stream.is_backpressured is False

        # Fill past high watermark
        for i in range(6):
            await stream.put({"type": "message_delta", "data": f"msg_{i}"})

        assert stream.is_backpressured is True

    @pytest.mark.asyncio
    async def test_backpressure_flag_deactivates(self):
        """Backpressure flag deactivates when buffer drops below low watermark."""
        config = BackpressureConfig(
            max_buffer_size=10, high_watermark=5, low_watermark=2
        )
        stream = BackpressuredEventStream(config)

        # Fill past high watermark
        for i in range(6):
            await stream.put({"type": "message_delta", "data": f"msg_{i}"})

        assert stream.is_backpressured is True

        # Drain below low watermark
        for _ in range(5):
            await stream.get()

        assert stream.is_backpressured is False

    @pytest.mark.asyncio
    async def test_buffer_full_drops_droppable(self):
        """When buffer is completely full, droppable events are dropped."""
        config = BackpressureConfig(
            max_buffer_size=5, high_watermark=4, low_watermark=1
        )
        stream = BackpressuredEventStream(config)

        # Fill buffer completely with critical events
        for i in range(5):
            await stream.put({"type": "message_delta", "data": f"msg_{i}"})

        # Buffer is full — droppable event should be dropped
        accepted = await stream.put({"type": "heartbeat", "data": ""})
        assert accepted is False

    @pytest.mark.asyncio
    async def test_buffer_full_critical_blocks_briefly(self):
        """When buffer is completely full, critical events wait briefly."""
        config = BackpressureConfig(
            max_buffer_size=3, high_watermark=2, low_watermark=1
        )
        stream = BackpressuredEventStream(config)

        # Fill buffer completely
        for i in range(3):
            await stream.put({"type": "message_delta", "data": f"msg_{i}"})

        # Start a consumer that drains after a short delay
        async def delayed_drain():
            await asyncio.sleep(0.05)
            await stream.get()

        drain_task = asyncio.create_task(delayed_drain())

        # Critical event should eventually succeed (after drain)
        accepted = await stream.put({"type": "tool_result", "data": "result"})
        assert accepted is True

        await drain_task

    @pytest.mark.asyncio
    async def test_dropped_count_tracking(self):
        """Dropped count is tracked accurately."""
        config = BackpressureConfig(
            max_buffer_size=10, high_watermark=3, low_watermark=1
        )
        stream = BackpressuredEventStream(config)

        # Fill past watermark
        for i in range(4):
            await stream.put({"type": "message_delta", "data": f"msg_{i}"})

        # Drop multiple non-critical events
        await stream.put({"type": "progress", "data": "1"})
        await stream.put({"type": "heartbeat", "data": "2"})
        await stream.put({"type": "progress", "data": "3"})

        assert stream.dropped_count == 3

    @pytest.mark.asyncio
    async def test_buffer_size_property(self):
        """buffer_size returns current queue size."""
        stream = BackpressuredEventStream()
        assert stream.buffer_size == 0

        await stream.put({"type": "message_delta", "data": "test"})
        assert stream.buffer_size == 1

    @pytest.mark.asyncio
    async def test_heartbeat_droppable(self):
        """Heartbeat events are droppable."""
        config = BackpressureConfig(
            max_buffer_size=10, high_watermark=3, low_watermark=1
        )
        stream = BackpressuredEventStream(config)

        for i in range(4):
            await stream.put({"type": "message_delta", "data": f"msg_{i}"})

        accepted = await stream.put({"type": "heartbeat", "data": ""})
        assert accepted is False

    @pytest.mark.asyncio
    async def test_debug_event_droppable(self):
        """Debug events are droppable."""
        config = BackpressureConfig(
            max_buffer_size=10, high_watermark=3, low_watermark=1
        )
        stream = BackpressuredEventStream(config)

        for i in range(4):
            await stream.put({"type": "message_delta", "data": f"msg_{i}"})

        accepted = await stream.put({"type": "debug", "data": "info"})
        assert accepted is False
