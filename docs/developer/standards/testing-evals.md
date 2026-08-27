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
| Unit tests | `packages/*/tests/unit/` | Pure logic, fast, no I/O |
| Integration tests | `packages/starboard/tests/integration/` | Service interactions, mocked external APIs |
| Golden tests | `tests/golden/` | Prompt snapshot + structured assertions |
| Contract tests | `tests/contract/` | Output/schema compatibility |
| Architecture (import-linter) | `pyproject.toml` contracts | Kernel purity + package boundaries |
| Architecture (guidelines) | `tests/architecture/` | GUIDELINE-* fitness suite |

> The legacy top-level `tests/unit/` tree was removed in the close-out cleanup. Package
> unit tests live under `packages/*/tests/unit/`.

### Running Tests

```bash
make test                          # unit + integration
make test-unit                     # package unit suites
make test-integration              # integration
make test-golden                   # golden/snapshot tests
make test-contract                 # output-contract tests
make test-architecture             # import-linter contracts
make test-architecture-guidelines  # pytest tests/architecture/
make test-coverage                 # with coverage report

# Single test file (package-scoped)
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
