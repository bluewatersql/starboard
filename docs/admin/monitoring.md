# Monitoring and Observability

This guide covers the monitoring, logging, tracing, and cost tracking capabilities built into Starboard. The system follows the observability standards defined in `.cursor/05_observability_and_cost.md` and uses structured logging throughout.

---

## Health Check Endpoints

Starboard exposes two health endpoints for use with load balancers, Kubernetes probes, and monitoring systems. Both endpoints are excluded from authentication middleware.

### GET /health/live

**Purpose:** Liveness probe -- confirms the process is running and can handle HTTP requests.

**Response (200 OK):**

```json
{
  "status": "ok"
}
```

This endpoint always returns 200 if the FastAPI process is alive. It does not check dependencies.

**Kubernetes probe example:**

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
  failureThreshold: 3
```

### GET /health/ready

**Purpose:** Readiness probe -- confirms the service has completed initialization and all dependencies are reachable.

**Response (200 OK):**

```json
{
  "status": "ready",
  "environment": "production",
  "database_backend": "postgres",
  "state_store_type": "PostgresStateStore",
  "memory_store_type": "PostgresMemoryStore"
}
```

**Response (503 Service Unavailable):**

```json
{
  "status": "not_ready",
  "error": "Container not initialized. Server may not have started properly."
}
```

The readiness endpoint verifies that the `Container` has been initialized, which means:

- Configuration has been validated
- State store connection is established
- Memory store connection is established
- Cache store is available
- Foundation components (vector store, reflexion, semantic cache) have been initialized (or gracefully degraded)

**Kubernetes probe example:**

```yaml
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 15
  failureThreshold: 3
```

!!! tip "Health endpoint paths"
    Both `/health/live` and `/health/ready` are excluded from authentication middleware and rate limiting, so they can be called freely by infrastructure tooling.

---

## Structured Logging

Starboard uses **structlog** for structured logging throughout the application. All log entries are key-value pairs that can be output as human-readable console text (development) or machine-parseable JSON (production).

### Configuration

Logging is configured at application startup via `setup_structured_logging()` in `infra/observability/logging.py`.

| Variable | Values | Default | Description |
|---|---|---|---|
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` | Minimum log level |
| `LOG_JSON` | `true`, `false` | `false` | JSON output for production log aggregation |
| `DEBUG` | `true`, `false` | `false` | Enable debug mode (more verbose output) |

### Log Output Formats

**Console format (development, `LOG_JSON=false`):**

```
2026-03-01T10:15:23.456Z [info     ] server_starting                version=0.1.0
2026-03-01T10:15:24.012Z [info     ] state_container_initialized    database_backend=sqlite environment=dev
2026-03-01T10:15:24.789Z [debug    ] creating_sqlite_state_store    db_path=./dev_data/starboard_state.db environment=dev
```

**JSON format (production, `LOG_JSON=true`):**

```json
{
  "event": "specialist_execution",
  "level": "debug",
  "logger": "starboard.agents.observability.metrics",
  "timestamp": "2026-03-01T10:15:30.123456Z",
  "domain": "query",
  "duration_seconds": 2.5,
  "tokens_used": 1500,
  "input_tokens": 800,
  "output_tokens": 700,
  "cost_usd": 0.015,
  "tools_called": 3,
  "tools_used": ["resolve_query", "analyze_query_plan", "get_query_runtime_metrics"],
  "success": true,
  "model": "databricks-claude-sonnet-4-5"
}
```

### Structlog Processor Pipeline

The logging pipeline applies these processors in order:

1. **`merge_contextvars`** -- Merges context variables (like request_id) into every log entry
2. **`add_log_level`** -- Adds the `level` field
3. **`add_logger_name`** -- Adds the `logger` field (module name)
4. **`TimeStamper(fmt="iso")`** -- Adds ISO-8601 timestamp
5. **`StackInfoRenderer()`** -- Renders stack traces when present
6. **`JSONRenderer()`** or **`ConsoleRenderer(colors=True)`** -- Final output formatting

### Suppressed Loggers

To reduce noise, the following loggers are suppressed to WARNING level even in DEBUG mode:

- `uvicorn`, `uvicorn.access`, `uvicorn.error`
- `fastapi`
- `httpx`, `httpcore`, `requests`, `urllib3`
- `sqlite3`, `aiosqlite`, `sqlite_vec`
- `databricks.sdk`

### Getting a Logger

```python
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Structured log with key-value fields
logger.info(
    "operation_completed",
    user_id="user_123",
    duration_ms=45,
    result_count=10,
)
```

---

## Distributed Tracing

Starboard implements distributed tracing using an `ObservabilityContext` dataclass that propagates through the call chain. This is defined in `infra/observability/context.py`.

### ObservabilityContext

Every operation in the system can carry an `ObservabilityContext` with the following fields:

| Field | Type | Description | Auto-generated |
|---|---|---|---|
| `trace_id` | `str` (UUID) | Correlates all operations within a single request | Yes |
| `span_id` | `str` (UUID) | Identifies a specific operation within the trace | Yes |
| `conversation_id` | `str` | Conversation/session identifier | No |
| `user_id` | `str` | User identifier for attribution | No |
| `agent_domain` | `str` | Current agent domain for cost attribution | No |

### Creating and Propagating Context

```python
from starboard.infra.observability.context import (
    ObservabilityContext,
    create_observability_context,
)

# Create a context at request entry
ctx = create_observability_context(
    conversation_id="conv-abc123",
    user_id="user@example.com",
)

# Create child span for a sub-operation
child_ctx = ctx.with_span()  # Same trace_id, new span_id

# Set domain for cost attribution
domain_ctx = ctx.with_domain("warehouse")

# Include in structured logs
logger.debug("tool_call_started", **ctx.to_log_dict())
# Outputs: trace_id=<uuid> span_id=<uuid> conversation_id=conv-abc123 user_id=user@example.com
```

### Request ID Correlation

In addition to `ObservabilityContext`, the logging module provides a request-scoped correlation ID via `ContextVar`:

```python
from starboard.infra.observability.logging import (
    get_request_id,
    set_request_id,
    clear_request_id,
)

# Set at middleware/request entry
set_request_id("req-12345")

# Retrieve anywhere in the call chain
rid = get_request_id()  # Returns "req-12345"

# Clear at request end
clear_request_id()
```

### Span Hierarchy Pattern

The standard pattern for creating spans in the codebase:

```
Request arrives
  |-- ObservabilityContext(trace_id=T1, span_id=S1)
  |
  +-- IntentRouter
  |     |-- ctx.with_span()  --> trace_id=T1, span_id=S2
  |
  +-- DomainAgent (e.g., QueryAgent)
  |     |-- ctx.with_span()  --> trace_id=T1, span_id=S3
  |     |-- ctx.with_domain("query")
  |     |
  |     +-- Tool: resolve_query
  |     |     |-- ctx.with_span()  --> trace_id=T1, span_id=S4
  |     |
  |     +-- Tool: analyze_query_plan
  |           |-- ctx.with_span()  --> trace_id=T1, span_id=S5
  |
  +-- Response streamed back
```

All log entries across this chain share the same `trace_id`, enabling end-to-end request tracing in log aggregation systems.

---

## Token and Cost Tracking

Cost tracking is implemented through the `MultiAgentMetrics` and `AgentMetrics` classes in `agents/observability/metrics.py`.

### Metric Data Classes

**SpecialistMetrics** -- recorded per agent execution:

| Field | Type | Description |
|---|---|---|
| `domain` | `str` | Agent domain (query, job, warehouse, etc.) |
| `duration_seconds` | `float` | Total execution time |
| `tokens_used` | `int` | Total tokens consumed |
| `input_tokens` | `int` | Input/prompt tokens |
| `output_tokens` | `int` | Output/completion tokens |
| `cost_usd` | `float` | Estimated cost in USD |
| `tools_called` | `int` | Number of tool invocations |
| `tools_used` | `list[str]` | Names of tools called |
| `model` | `str` | LLM model used |
| `success` | `bool` | Whether execution succeeded |

**AgentMetrics** -- per-session agent tracking:

| Field | Type | Description |
|---|---|---|
| `session_id` | `str` | Unique session identifier |
| `agent_type` | `str` | Agent type (reasoning, router) |
| `model` | `str` | LLM model |
| `budget_tokens` | `int` | Token budget (default: 100,000) |
| `total_tokens` | `int` | Running total of tokens used |
| `estimated_cost_usd` | `float` | Running cost estimate |
| `tool_calls` | `list[ToolMetrics]` | Per-tool execution metrics |
| `steps` | `list[StepMetrics]` | Per-reasoning-step metrics |

### Recording Metrics

```python
from starboard.agents.observability.metrics import get_metrics

metrics = get_metrics()

# Record routing decision
metrics.record_routing_decision(
    domain="query",
    confidence=0.95,
    clarification_needed=False,
    reasoning="Statement ID detected in input",
    routing_method="pattern",
)

# Record agent execution
metrics.record_specialist_execution(
    domain="query",
    duration_seconds=2.5,
    tokens_used=1500,
    input_tokens=800,
    output_tokens=700,
    cost_usd=0.015,
    tools_called=3,
    tools_used=["resolve_query", "analyze_query_plan"],
    model="databricks-claude-sonnet-4-5",
    success=True,
)

# Record agent transition
metrics.record_agent_transition(
    from_agent="router",
    to_agent="query",
    reason="Statement ID found",
    context_size=1024,
)
```

### Cost Summary Reports

```python
metrics = get_metrics()

# Cost breakdown by domain
cost_summary = metrics.get_cost_summary()
# Returns:
# {
#     "total_cost_usd": 0.45,
#     "total_tokens": 45000,
#     "by_domain": {
#         "query": {"executions": 10, "total_cost_usd": 0.15, "avg_cost_usd": 0.015, ...},
#         "warehouse": {"executions": 5, "total_cost_usd": 0.20, "avg_cost_usd": 0.04, ...},
#     }
# }

# Routing accuracy
routing = metrics.get_routing_accuracy()
# Returns:
# {
#     "total_decisions": 100,
#     "avg_confidence": 0.92,
#     "clarification_rate": 0.05,
#     "by_domain": { ... }
# }

# Transition statistics
transitions = metrics.get_transition_stats()
# Returns:
# {
#     "total_transitions": 50,
#     "unique_paths": 8,
#     "most_common_transitions": [("router->query", 20), ("router->warehouse", 15), ...]
# }
```

### Per-Step Metrics (AgentMetrics)

Individual agent sessions track granular step-by-step metrics:

```python
from starboard.agents.observability.metrics import AgentMetrics

agent_metrics = AgentMetrics(
    session_id="sess-123",
    agent_type="reasoning",
    model="databricks-claude-sonnet-4-5",
    budget_tokens=100_000,
)

# Record each reasoning step
agent_metrics.record_step(
    step_number=1,
    duration=1.2,
    tokens_used=500,
    input_tokens=300,
    output_tokens=200,
)

# Record tool executions
agent_metrics.record_tool(
    tool_name="resolve_query",
    success=True,
    duration=0.8,
)

# Finalize and export
agent_metrics.finalize()
agent_metrics.export_json(Path("./metrics/session-123.json"))
```

---

## Event System

The `EventEmitter` in `infra/observability/events.py` provides a publish-subscribe system for status events that bubble up through the execution stack.

### Event Types

| Type | Description | Example |
|---|---|---|
| `EventType.INFO` | General information messages | "Starting query analysis" |
| `EventType.TRACE` | Detailed execution trace | "Tool resolve_query returned 5 results" |

### StatusEvent Fields

| Field | Type | Description |
|---|---|---|
| `type` | `EventType` | INFO or TRACE |
| `source` | `str` | Source component (e.g., "task:discover_tables") |
| `message` | `str` | Human-readable message |
| `data` | `dict` | Optional structured data |
| `phase` | `str` | Optional workflow phase (e.g., "planner", "execution") |

### Event Bubbling

Events emitted by child components bubble up to parent emitters:

```python
from starboard.infra.observability.events import EventEmitter

# Parent emitter (e.g., orchestrator)
parent = EventEmitter()
parent.on(lambda event: logger.info(str(event)))

# Child emitter (e.g., tool executor) -- events bubble to parent
child = EventEmitter(parent=parent)
child.emit_info("tool:resolve_query", "Found 5 matching queries")
# Both child handlers AND parent handlers fire
```

---

## Circuit Breaker Monitoring

Circuit breakers protect against cascading failures from external services (LLM APIs, Databricks APIs). They are implemented in `infra/reliability/circuit_breaker.py`.

### Circuit States

| State | Description | Behavior |
|---|---|---|
| **CLOSED** | Normal operation | Requests flow through |
| **OPEN** | Service failing | Requests rejected with `CircuitBreakerError` |
| **HALF_OPEN** | Testing recovery | One request allowed through to test |

### Configuration

```python
from starboard.infra.reliability.circuit_breaker import CircuitBreaker

breaker = CircuitBreaker(
    failure_threshold=5,    # Open after 5 consecutive failures
    timeout_seconds=60,     # Wait 60s before testing recovery
    name="llm_api",         # Name for log entries
)
```

### Log Events to Monitor

| Log Event | Level | Meaning |
|---|---|---|
| `circuit_breaker_failure` | WARNING | A failure occurred (includes current count and threshold) |
| `circuit_breaker_opening` | WARNING | Threshold reached, circuit is now OPEN |
| `circuit_breaker_half_open` | INFO | Timeout elapsed, testing recovery |
| `circuit_breaker_recovered` | INFO | Test request succeeded, circuit CLOSED |
| `circuit_breaker_half_open_failed` | WARNING | Recovery test failed, back to OPEN |

---

## Semantic Cache Metrics

The `SemanticCache` in `infra/cache/semantic_cache.py` tracks its own hit/miss metrics:

```python
cache_metrics = semantic_cache.get_metrics()
# Returns:
# {
#     "hits": 150,
#     "misses": 50,
#     "total_requests": 200,
#     "hit_rate": 0.75,
#     "similarity_threshold": 0.95,
#     "default_ttl": 300
# }
```

!!! tip "Monitor cache hit rate"
    A healthy semantic cache should have a hit rate above 30% for repeated query patterns. If the hit rate is consistently below 10%, consider lowering `SEMANTIC_CACHE_THRESHOLD` from the default of 0.95 to 0.90.

---

## SSE (Real-Time Streaming) Monitoring

The `SSEBroadcaster` in `agents/observability/sse_broadcaster.py` manages real-time event streaming to frontend clients.

### Key Metrics

```python
from starboard.agents.observability.sse_broadcaster import SSEBroadcaster

broadcaster = SSEBroadcaster()

# Total active subscribers across all conversations
total = broadcaster.get_total_subscriber_count()

# Subscribers for a specific conversation
count = broadcaster.get_subscriber_count("conv-123")

# All conversations with active subscribers
active = broadcaster.get_all_conversation_ids()
```

### Log Events to Monitor

| Log Event | Level | Meaning |
|---|---|---|
| `subscriber_added` | DEBUG | New SSE client connected |
| `subscriber_removed` | DEBUG | SSE client disconnected |
| `broadcast_queue_full` | WARNING | A subscriber's queue is full (slow client) |
| `broadcast_error` | ERROR | Failed to deliver event to a subscriber |
| `event_stream_cancelled` | DEBUG | Client disconnected (normal) |

---

## Rate Limiting

Rate limiting is implemented using `slowapi` with configurable storage backends.

### Configuration

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | Enable/disable rate limiting |
| `RATE_LIMIT_STORAGE` | `memory://` | Storage backend (`memory://` or `redis://...`) |
| `RATE_LIMIT_DEFAULT` | `100/minute` | Default limit for all routes |

### Key Identification

Rate limits are applied per-user when authenticated, falling back to per-IP:

1. If `request.state.user_id` is set (by auth middleware): key is `user:<user_id>`
2. Otherwise: key is the client IP address

### Monitoring Rate Limits

When a client exceeds the limit, the server returns:

```
HTTP 429 Too Many Requests
{"detail": "Rate limit exceeded"}
```

---

## Key Metrics to Monitor

### Infrastructure Metrics

| Metric | Source | Alert Threshold |
|---|---|---|
| `/health/ready` status | Health endpoint | Any 503 response |
| Container initialization time | `state_container_initialized` log | > 30 seconds |
| Database connection pool usage | asyncpg pool stats | > 80% of max pool |
| Redis connection status | `RedisCacheStore.connect()` | Connection failures |
| Circuit breaker state | `circuit_breaker_opening` log | Any OPEN state |

### Agent Performance Metrics

| Metric | Source | Alert Threshold |
|---|---|---|
| Agent execution duration | `SpecialistMetrics.duration_seconds` | p95 > 30 seconds |
| Token usage per request | `SpecialistMetrics.tokens_used` | > 50,000 per request |
| Cost per request | `SpecialistMetrics.cost_usd` | > $0.50 per request |
| Routing confidence | `RoutingMetrics.confidence` | Average < 0.7 |
| Clarification rate | `RoutingMetrics.clarification_needed` | > 20% of requests |
| Tool call failures | `ToolMetrics.success` | Failure rate > 10% |

### Cache Metrics

| Metric | Source | Alert Threshold |
|---|---|---|
| Semantic cache hit rate | `SemanticCache.get_metrics()` | < 10% (over 1 hour) |
| Cache TTL effectiveness | Cache miss patterns | Frequent re-computation |
| Redis memory usage | Redis INFO command | > 80% of maxmemory |

### SSE/Streaming Metrics

| Metric | Source | Alert Threshold |
|---|---|---|
| Active subscribers | `SSEBroadcaster.get_total_subscriber_count()` | > 1000 concurrent |
| Queue full events | `broadcast_queue_full` log | > 10 per minute |
| Broadcast errors | `broadcast_error` log | Any occurrence |

---

## Log Levels and When to Use Them

| Level | Usage in Starboard | Examples |
|---|---|---|
| **ERROR** | Unrecoverable failures requiring operator attention | Database connection lost, event handler crash |
| **WARNING** | Degraded operation, recoverable issues | Circuit breaker failure, full broadcast queue, extension not available |
| **INFO** | Significant lifecycle events | Server start/stop, container initialized, circuit breaker state changes |
| **DEBUG** | Detailed operational data | Store operations, routing decisions, tool executions, metrics recording |

!!! note "Production log level"
    For production, use `LOG_LEVEL=INFO` with `LOG_JSON=true`. Switch to `LOG_LEVEL=DEBUG` temporarily for troubleshooting, but be aware this significantly increases log volume due to per-operation structured entries for every tool call, routing decision, and database operation.

---

## Alerting Recommendations

### Critical Alerts (Page On-Call)

- `/health/ready` returns 503 for more than 2 minutes
- Any `circuit_breaker_opening` log entry for the LLM API circuit
- `state_container_initialization_failed` at startup
- Database connection pool exhaustion (all connections in use)

### Warning Alerts (Notify Team)

- Average routing confidence drops below 0.7 over a 15-minute window
- Agent execution p95 latency exceeds 30 seconds
- Per-user token budget exceeds 80% of cap
- Semantic cache hit rate below 10% over 1 hour
- Rate limit (429) responses exceed 5% of total traffic
- `broadcast_queue_full` events exceed 10 per minute

### Informational (Dashboard Only)

- Cost per domain trends (daily/weekly)
- Agent transition patterns (which domains are most active)
- Tool usage frequency (which tools are called most)
- Cache hit rates over time
- Active SSE subscriber count

---

## Source Files

| File | Description |
|---|---|
| `main.py` | Health endpoints, app lifecycle, middleware setup |
| `infra/observability/logging.py` | Structlog setup, request ID correlation |
| `infra/observability/context.py` | `ObservabilityContext` for distributed tracing |
| `infra/observability/events.py` | `EventEmitter` and `StatusEvent` system |
| `agents/observability/metrics.py` | `MultiAgentMetrics`, `AgentMetrics`, cost tracking |
| `agents/observability/sse_broadcaster.py` | `SSEBroadcaster` for real-time streaming |
| `infra/reliability/circuit_breaker.py` | `CircuitBreaker` pattern implementation |
| `infra/cache/semantic_cache.py` | `SemanticCache` with hit/miss metrics |
| `infra/middleware/rate_limit.py` | Rate limiting utilities |
| `.cursor/05_observability_and_cost.md` | Engineering standards for observability |

All paths are relative to `packages/starboard-server/starboard/`.
