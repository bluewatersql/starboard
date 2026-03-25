# tests/ — Top-Level Test Suite

This directory contains cross-package and integration-level tests. Package-level unit tests live under `packages/*/tests/`.

## Test Organization

```
tests/
├── unit/         # Cross-package unit tests (shared utilities, workspace-level)
├── integration/  # End-to-end integration tests against a running server
├── contract/     # API contract tests (backend schema vs. frontend Zod schemas)
├── golden/       # Golden/snapshot tests for prompt outputs
├── benchmarks/   # Performance benchmarks (pytest-benchmark)
└── conftest.py   # Shared fixtures (test client, mock services, etc.)
```

## Test Types

| Type | Marker | Command | Description |
|------|--------|---------|-------------|
| Unit | `unit` | `make test-unit` | No external deps; fast |
| Integration | `integration` | `make test-integration` | May call external services |
| Golden | `golden` | `make test-golden` | Prompt snapshot regression |
| Contract | — | `make test-contract` | API schema alignment |
| Frontend | — | `make test-frontend` | Jest/RTL in `frontend/` |

## Coverage Requirements

- Overall: ≥ 80%
- Agent policies and schema validators: 100%
- Tool routers: 100%

## Running Tests

```bash
make test              # unit + integration
make test-unit         # unit only (all packages)
make test-golden       # golden/snapshot tests
make test-contract     # contract tests (backend + frontend)
make test-coverage     # with HTML coverage report
```

## Writing Tests

- Mock all external services; tests must pass offline
- Use `respx` for mocking `httpx` requests
- Golden test updates: run `pytest tests/golden/ --snapshot-update`
- Mark slow tests with `@pytest.mark.slow`
