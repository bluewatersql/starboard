# Testing & Evaluations Standards

Standards for testing practices, coverage requirements, and evaluation pipelines in the Starboard AI Agent project.

---

## Testing Requirements

### Coverage Targets

| Scope | Target | Level |
|-------|--------|-------|
| Overall codebase | ≥ 80% | MUST |
| Agent policies | 100% | MUST |
| Schema validators | 100% | MUST |
| Tool routers | 100% | MUST |

### Test Types

| Test Type | Location | Purpose |
|-----------|----------|---------|
| Unit tests | `tests/unit/` | Pure logic, fast, no I/O |
| Integration tests | `tests/integration/` | Service interactions, mocked external APIs |
| Golden tests | `tests/golden/` | Prompt snapshot + structured assertions |
| Contract tests | `tests/contract/` | API schema compatibility (backend + frontend) |

### Running Tests

```bash
make test               # All tests (unit + integration)
make test-unit          # Unit tests only
make test-integration   # Integration tests only
make test-golden        # Golden/snapshot tests
make test-contract      # API contract tests
make test-coverage      # With coverage report
make test-parallel      # Parallel execution (faster)

# Single test file
cd packages/starboard && pytest tests/unit/path/to/test_file.py -v

# By marker
pytest -m unit
pytest -m integration
pytest -m golden
```

### Test Standards

| Rule | Level |
|------|-------|
| Use pytest with fixtures; write tests alongside code changes | MUST |
| Mock external dependencies; provide offline test mode | MUST |
| Maintain golden tests for prompts | MUST |
| Use `respx` for mocking httpx requests | MUST |
| Test edge cases: timeouts, rate limits, retries, invalid JSON | MUST |
| Adversarial tests: prompt injection, malformed inputs | SHOULD |
| Regression tests for agent behavior stability | SHOULD |

### Edge Cases to Test

Every tool and agent should be tested against:

- Timeouts and connection failures
- Rate limit responses (HTTP 429)
- Retry exhaustion
- Invalid JSON from LLM
- Empty retrievals / no results
- PII in prompts
- Resource exhaustion

---

## Evaluation & Monitoring

### Evaluation Infrastructure

| Component | Location | Purpose |
|-----------|----------|---------|
| Task suites | `evals/` | Accuracy, robustness, safety, latency |
| Golden datasets | `evals/` | Input/expected output pairs |
| Evaluation runners | `evals/` | Batch, CI, nightly execution |

### Evaluation Metrics

| Metric | Description | Level |
|--------|------------|-------|
| Latency (p50/p95/p99) | Per agent and per tool | SHOULD |
| Success rate | % of successful completions | SHOULD |
| Cost per query | Tokens and API calls | SHOULD |
| Retrieval quality | Precision@k, recall@k, MRR | SHOULD |

### Evaluation Rules

| Rule | Level |
|------|-------|
| Run evals on PRs touching prompts, schemas, or agents | MUST |
| Block merge on significant regressions | MUST |
| Detect regressions with clear rollback path | MUST |
| Shadow-mode evaluation for new prompt versions | SHOULD |
| A/B testing for high-impact changes | SHOULD |
| Red-teaming / adversarial evaluation scenarios | SHOULD |
