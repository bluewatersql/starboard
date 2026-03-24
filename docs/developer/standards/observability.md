# Observability, Cost & Performance Standards

Standards for structured logging, distributed tracing, cost attribution, and performance optimization in the Starboard AI Agent project.

!!! info "Source of truth"
    These standards are mirrored from `.cursor/05_observability_and_cost.md`.

---

## Structured Logging

Every log entry must include these fields:

| Field | Purpose | Level |
|-------|---------|-------|
| `trace_id` | Distributed trace correlation | MUST |
| `span_id` | Span within a trace | MUST |
| `user_id` | User context | MUST |
| `session_id` | Session context | MUST |
| `model` | LLM model used | MUST |
| `prompt_version` | Prompt version identifier | MUST |
| `tokens_used` | Token consumption | MUST |
| `latency_ms` | Call latency | MUST |
| `cost_usd` | Estimated cost | MUST |

**Example:**

```python
logger.info(
    "llm_call_completed",
    extra={
        "trace_id": trace_id,
        "span_id": span_id,
        "model": model_name,
        "prompt_version": "v2",
        "tokens_used": response.usage.total_tokens,
        "latency_ms": latency,
        "cost_usd": cost,
    },
)
```

### Debug Mode

| Rule | Level |
|------|-------|
| Support `DEBUG=true` mode for detailed logging | SHOULD |
| Redact PII even in debug mode | MUST |
| Add profiling hooks (CPU, memory) | SHOULD |
| Export metrics to monitoring system | SHOULD |

---

## Distributed Tracing

| Rule | Level |
|------|-------|
| Start a span for each agent invocation | MUST |
| Use child spans for each tool call, LLM call, and retrieval | MUST |
| Include input/output sizes, latency, and errors in span attributes | MUST |

**Span hierarchy:**

```
Agent Invocation (root span)
├── LLM Call (child span)
│   ├── input_tokens, output_tokens, model, latency_ms
│   └── error (if any)
├── Tool Call: resolve_job (child span)
│   ├── input_size, output_size, latency_ms
│   └── cache_hit: true/false
├── Tool Call: analyze_job_history (child span)
│   └── ...
└── LLM Call (child span)
    └── ...
```

---

## Health Endpoints

| Endpoint | Purpose | Level |
|----------|---------|-------|
| `/health/live` | Process is alive | MUST |
| `/health/ready` | Ready to serve traffic, dependencies reachable | MUST |

The `/health/ready` endpoint should verify:
- Database connectivity
- LLM provider reachability (if not in offline mode)
- Cache availability (if configured)

---

## Cost Management & Rate Limiting

### Token Budgeting

| Rule | Level |
|------|-------|
| Measure tokens per LLM call (input, output, cached) | MUST |
| Track rolling totals per user/session/tenant | MUST |
| Enforce caps; return throttling or error responses when exceeded | MUST |

### Cost Attribution

| Rule | Level |
|------|-------|
| Tag each LLM call with `feature`, `agent`, `user_id`, `tenant_id` | MUST |
| Aggregate cost metrics by these dimensions | MUST |

### Rate Limiting

| Rule | Level |
|------|-------|
| Implement rate limiting (token bucket or leaky bucket) at user and global levels | SHOULD |

### Caching

| Rule | Level |
|------|-------|
| Use semantic cache keys (hash of prompt + model + temperature) | SHOULD |
| Tune TTLs per use case (tool results ~5min, metadata ~1hr, static data longer) | SHOULD |
| Track cache hit rates and effectiveness | SHOULD |

### Circuit Breakers

| Rule | Level |
|------|-------|
| Implement circuit breakers for expensive or unstable operations | MUST |
| Expose circuit breaker state via metrics | MUST |

---

## Performance

| Rule | Level |
|------|-------|
| Optimize only after profiling; favor readability first | SHOULD |
| Use generators/iterators for large streams; avoid unnecessary copies | SHOULD |
| Prefer vectorized Polars operations where applicable | SHOULD |
| Cache stable LLM and tool results with explicit TTL and clear keys | SHOULD |
| Batch requests and parallelize independent operations when beneficial | MAY |
