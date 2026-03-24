# SSE Streaming Backpressure — Phase 06

## Overview

Bounded-buffer SSE event stream that prevents memory exhaustion when clients consume events slower than the server produces them. Uses a two-tier approach: droppable events are shed first, critical events are never lost.

## Architecture

```
Producer → BackpressuredEventStream → Consumer (SSE client)
              │
              ├── asyncio.Queue (bounded, max_buffer_size=100)
              ├── Overflow deque (critical events only)
              └── Watermark-based flow control
```

### Event Classification

**Droppable** (shed under pressure): `progress`, `heartbeat`, `debug`, `status`

**Critical** (never dropped): `message_delta`, `tool_result`, `error`, `complete`, `tool_call`, `reasoning`

### Flow Control

| Condition | Behavior |
|-----------|----------|
| Buffer < high_watermark (80) | Normal — all events enqueued |
| Buffer >= high_watermark | Backpressure — droppable events shed, critical events enqueued |
| Buffer full (100) | Critical events wait up to 5s, droppable events dropped immediately |
| Buffer drops below low_watermark (20) | Backpressure released |

## Configuration

```python
config = BackpressureConfig(
    max_buffer_size=100,   # Total buffer capacity
    high_watermark=80,     # Trigger backpressure
    low_watermark=20,      # Release backpressure
)
stream = BackpressuredEventStream(config)
```

## Files

| File | Purpose |
|------|---------|
| `starboard_server/infra/streaming/__init__.py` | Package init |
| `starboard_server/infra/streaming/backpressure.py` | `BackpressureConfig` + `BackpressuredEventStream` |
| `tests/unit/infra/streaming/test_backpressure.py` | 15 unit tests |

## Key Properties

- **Zero message loss for critical events** — critical events use overflow deque when buffer is full
- **Graceful degradation** — clients see fewer progress updates but never miss content
- **Observable** — `events_dropped` and `events_sent` counters for monitoring
- **Thread-safe** — uses `asyncio.Queue` and atomic operations
