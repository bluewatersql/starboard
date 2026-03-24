# 04 – Testing & Evaluations

---

## Testing

MUST: Use pytest with fixtures; write tests alongside code changes.  
MUST: Coverage target: at least 80% overall; 100% for agent policies, schema validators, and tool routers.  
MUST: Test edge cases: timeouts, rate limits, retries, invalid JSON, empty retrievals, PII in prompts.  
MUST: Maintain golden tests for prompts (snapshots and structured assertions).  
MUST: Mock external dependencies; provide offline test mode (no network).
MUST: Use `respx` for mocking httpx requests in integration tests (provides `respx_mock` fixture automatically).

SHOULD: Add adversarial tests: prompt injection, malformed inputs, resource exhaustion.  
SHOULD: Add regression tests to assert agent behavior remains stable across refactors.

---

## Evaluation & Monitoring

MUST: Maintain an evals/ directory with:
- Task suites (accuracy, robustness, safety, latency)  
- Golden datasets (input/expected output pairs)  
- Evaluation runners (batch, CI, nightly)

MUST: Run evals on PRs that touch prompts, schemas, or agents; block merge on significant regressions.  

SHOULD: Track metrics such as:
- Latency (p50, p95, p99 per agent/tool)  
- Success rate (% of successful completions)  
- Cost per query (tokens and API calls)  
- User satisfaction (explicit ratings or signals)  
- Retrieval quality (precision@k, recall@k, MRR)

SHOULD: Use shadow-mode evaluation to compare new prompt versions with current production behavior.  
SHOULD: Use A/B testing for high-impact changes and measure effectiveness and cost.  

MUST: Detect regressions and provide a clear rollback path for prompts and agent behavior.  
SHOULD: Include red-teaming / adversarial evaluation scenarios in your evals.
