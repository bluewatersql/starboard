# Connection Pool Metrics — Phase 06

## Overview

OpenTelemetry-based metrics collection for connection pools (database, HTTP, Redis). Uses observable gauges for pool state and histograms for acquisition latency.

## Metrics Emitted

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `pool.connections.size` | ObservableGauge | connections | Total pool capacity |
| `pool.connections.active` | ObservableGauge | connections | Currently in-use connections |
| `pool.connections.wait_time` | Histogram | seconds | Time spent acquiring a connection |

All metrics include a `pool.name` attribute for filtering (e.g., `"database"`, `"http"`, `"redis"`).

## Architecture

```python
collector = PoolMetricsCollector()
collector.register_pool("database", asyncpg_pool)
collector.register_pool("http", httpx_pool)

# Record acquisition latency
collector.record_acquire_time("database", 0.003)
```

### Duck-Typed Pool Attributes

The collector uses duck-typing to read pool sizes from different pool implementations:

| Pool Library | Size Attribute | Free Attribute |
|-------------|---------------|----------------|
| asyncpg | `.size` | `.freesize` |
| httpx | `.maxsize` | (computed) |
| aioredis | `.size` | `.freesize` |
| Fallback | 0 | 0 |

## Files

| File | Purpose |
|------|---------|
| `starboard_server/infra/observability/pool_metrics.py` | `PoolMetricsCollector` implementation |
| `tests/unit/infra/observability/test_pool_metrics.py` | 9 unit tests |

## Integration

Wire into application startup:

```python
from starboard_server.infra.observability.pool_metrics import PoolMetricsCollector

collector = PoolMetricsCollector()
collector.register_pool("database", container.state_store.pool)
```

OTEL exporter configuration is handled by the existing `infra/observability/` setup.
