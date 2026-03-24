# Health Checks — Phase 06

## Overview

Enhanced `/health/ready` endpoint with protocol-based dependency probing. Each probe checks a specific external dependency and returns a structured `ProbeResult`.

## Architecture

```
HealthCheckRunner
├── DatabaseProbe    → pool.acquire() / pool.release()
├── RedisProbe       → client.ping()
├── DatabricksProbe  → client.list_clusters(max_results=1)
├── LLMProviderProbe → client.models.list()
└── BackpressureProbe → checks stream.is_healthy
```

### Key Design Decisions

1. **Generic probe names** (`database`, `cache`, `compute`, `ai`) — avoids leaking internal technology choices (PostgreSQL, Redis, Databricks, OpenAI) in health responses.

2. **Protocol-based** — `HealthProbe` is a `typing.Protocol` with a single `async check()` method. Any object implementing `check() -> ProbeResult` can be used as a probe.

3. **Configurable timeout** — `PROBE_TIMEOUT_SECONDS = 5.0`. Each probe is wrapped with `asyncio.wait_for()` via `check_with_timeout()`.

4. **Concurrent execution** — `HealthCheckRunner.run()` uses `asyncio.gather()` to check all probes in parallel.

## Files

| File | Purpose |
|------|---------|
| `starboard_server/infra/health/__init__.py` | Package init |
| `starboard_server/infra/health/probes.py` | All probe implementations + runner |
| `tests/unit/infra/health/test_probes.py` | 21 unit tests |
| `starboard_server/main.py` | Wiring into `/health/ready` |

## Response Format

```json
{
  "status": "ready",
  "checks": {
    "database": {"name": "database", "healthy": true, "latency_ms": 2.1, "detail": null},
    "cache": {"name": "cache", "healthy": true, "latency_ms": 0.8, "detail": null}
  }
}
```

When any probe fails:

```json
{
  "status": "not_ready",
  "checks": {
    "database": {"name": "database", "healthy": false, "latency_ms": 5000.0, "detail": "Timeout after 5.0s"}
  }
}
```

## Adding a New Probe

1. Create a class implementing the `HealthProbe` protocol (must have `async def check() -> ProbeResult`)
2. Add it to `_build_health_probes()` in `main.py`
3. Add unit tests in `test_probes.py`
