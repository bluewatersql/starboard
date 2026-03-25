# 05 – Observability, Cost & Performance

---

## Observability & Debugging

**GUIDELINE-004: MUST: Use `structlog` exclusively for all logging in `starboard-server`.** stdlib `logging` module must not be imported directly. All log calls must use keyword arguments (not f-strings). Enforced by `tests/architecture/test_logging_compliance.py`.

MUST: Use structured logging with fields like:
- trace_id, span_id
- user_id, session_id
- model, prompt_version
- tokens_used, latency_ms, cost_usd  

MUST: Use distributed tracing for agent workflows:
- Start a span for agent invocation  
- Use child spans for each tool call, LLM call, and retrieval  
- Include input/output sizes, latency, and errors in span attributes  

SHOULD: Support a DEBUG=true mode that logs more detail (with PII redaction).  
SHOULD: Add profiling hooks (CPU, memory) and export metrics to your monitoring system.  

MUST: Provide health endpoints for services:
- /health/live – process is alive  
- /health/ready – ready to serve traffic and dependencies reachable  

---

## Cost Management & Rate Limiting

MUST: Implement token budgeting:
- Measure tokens per LLM call (input, output, cached)  
- Track rolling totals per user/session/tenant  
- Enforce caps; return throttling or error responses when exceeded  

MUST: Implement cost attribution:
- Tag each LLM call with feature, agent, user_id, tenant_id  
- Aggregate cost metrics by these dimensions  

SHOULD: Use rate limiting strategies (token bucket, leaky bucket) at user and global levels.  

SHOULD: Implement caching strategies:
- Semantic cache keys (hash of prompt + model + temperature)  
- TTLs tuned per use case (tool results, retrievals, static data)  
- Track cache hit rates and effectiveness  

MUST: Implement circuit breakers for expensive or unstable operations and expose their state via metrics.

---

## Performance

SHOULD: Optimize only after profiling; favor readability first.  
SHOULD: Use generators/iterators for large streams and avoid unnecessary copies.  
SHOULD: Prefer vectorized Polars operations where applicable.  
SHOULD: Cache stable LLM and tool results with explicit TTL and clear keys.  
MAY: Batch requests and parallelize independent operations when it materially improves performance.
