# Testing Guide

Testing structure and practices for the Starboard AI Agent monorepo.

---

## Test Organization

Unit tests are co-located with each package; cross-cutting suites (golden, contract,
architecture, integration, benchmarks) live under the **root `tests/`** tree.

```
packages/
├── starboard-core/tests/unit/          # kernel + starboard_x unit tests
├── starboard/tests/{unit,integration,golden}/
├── starboard-internal/tests/           # gated-adapter parity tests
└── starboard-plugin-sample/tests/      # plugin-contract tests

tests/                      # root cross-cutting suites
├── unit/  ...              # (the legacy root tests/unit tree was REMOVED — see below)
├── integration/
├── golden/                 # prompt/schema snapshot tests
├── contract/               # output-contract tests
├── architecture/           # GUIDELINE-* pytest fitness suite
└── benchmarks/
```

> **Note:** the old top-level `tests/unit/` convention was removed in the close-out
> cleanup (it ran in no CI target). Package unit tests live under
> `packages/*/tests/unit/`. Golden/contract/architecture suites live under `tests/`.

### Test Types

| Type | Location | Make target | Purpose |
|------|----------|-------------|---------|
| **Unit** | `packages/*/tests/unit/` | `make test-unit` | Fast, isolated logic |
| **Package Integration** | `packages/starboard/tests/integration/` | `make test-integration` | Components together |
| **Golden** | `tests/golden/` | `make test-golden` | Prompt/schema snapshots |
| **Contract** | `tests/contract/` | `make test-contract` | Output contracts |
| **Architecture (import-linter)** | `pyproject.toml` contracts | `make test-architecture` | Kernel purity + boundaries (4 kept contracts) |
| **Architecture (guidelines)** | `tests/architecture/` | `make test-architecture-guidelines` | GUIDELINE-* fitness suite |

---

## Running Tests

### Via Make (recommended)

```bash
make test-unit                 # package unit suites
make test-integration          # package + cross-package integration
make test-golden               # tests/golden/
make test-contract             # tests/contract/
make test-architecture         # import-linter contracts (lint-imports)
make test-architecture-guidelines  # pytest tests/architecture/
make check                     # lint + type-check + test-unit + test-architecture
```

### Architecture contracts (import-linter)

`make test-architecture` runs `lint-imports` against the 4 **kept** contracts in
`pyproject.toml`:

1. Kernel is free of `databricks-sdk` / `openai` / `fastapi` / `mcp`.
2. `starboard_x` diagnostics-core trio is stdlib-only.
3. `starboard_x` pure analyzers (warehouse / uc / review) are SDK-free.
4. Public packages import no `starboard_internal`.

### Direct pytest

```bash
# Single package
cd packages/starboard && pytest tests/unit/

# Specific markers
pytest -m unit
pytest -m integration

# Cross-cutting suites (from repo root)
pytest tests/golden/ tests/contract/ tests/architecture/
```

### With Coverage

```bash
# Single package
cd packages/starboard
pytest --cov=starboard --cov-report=html

# All packages
pytest packages/ \
  --cov=starboard_core \
  --cov=starboard
```

---

## Test Markers

Use markers to categorize and selectively run tests:

| Marker | Purpose | Usage |
|--------|---------|-------|
| `@pytest.mark.unit` | Fast, isolated unit tests | `pytest -m unit` |
| `@pytest.mark.integration` | Cross-package tests | `pytest -m integration` |
| `@pytest.mark.golden` | Snapshot tests | `pytest -m golden` |
| `@pytest.mark.slow` | Tests >1s | `pytest -m "not slow"` |

---

## Coverage

### Per-Package Coverage

```bash
cd packages/starboard
pytest --cov=starboard --cov-report=html --cov-report=term-missing
```

**Coverage Requirements**:
- Overall: ≥80%
- Agent policies: 100%
- Schema validators: 100%
- Tool routers: 100%

### Coverage Badge

The repository includes an auto-updating coverage badge:

[![Coverage](https://img.shields.io/badge/coverage-94%25-brightgreen.svg)]()

**Update badge**:
```bash
# Run tests with coverage
pytest packages/starboard --cov=starboard --cov-report=json

# Update badge
python scripts/update_coverage_badge.py
```

---

## Best Practices

### Test Organization
- ✅ Keep tests co-located with code
- ✅ Use descriptive test names
- ✅ One concept per test
- ✅ Arrange-Act-Assert pattern

### Test Isolation
- ✅ Use fixtures for test data
- ✅ Mock external dependencies
- ✅ Clean up after tests
- ❌ Don't rely on test execution order

### Test Coverage
- ✅ Aim for ≥80% overall coverage
- ✅ 100% for critical paths
- ✅ Test edge cases
- ✅ Test error handling

### Test Performance
- ✅ Unit tests <0.1s each
- ✅ Mark slow tests
- ✅ Use parallel execution
- ✅ Mock expensive operations

### Golden Tests
- ✅ Update when prompts intentionally change
- ✅ Review diffs carefully
- ✅ Document why changed
- ❌ Don't ignore failures

---

## Quick Reference

```bash
# Run all tests
pytest packages/ tests/

# Only fast tests
pytest packages/ -m "unit and not slow"

# With coverage
pytest packages/starboard --cov=starboard --cov-report=html

# Parallel execution
pytest packages/ -n auto

# Specific test file (agents)
pytest packages/starboard/tests/unit/agents/test_domain_agent.py

# Matching pattern
pytest packages/ -k "test_tool"

# Stop on first failure
pytest packages/ -x

# Show print statements
pytest packages/ -s

# Run last failed
pytest packages/ --lf

# Detailed output
pytest packages/ -vv
```

---

## Troubleshooting

### Tests Not Found
```bash
# Ensure package is installed
uv sync

# Check test discovery
pytest --collect-only packages/starboard/tests/
```

### Import Errors
```bash
# Install all workspace packages
uv sync

# Check PYTHONPATH
export PYTHONPATH=/path/to/job-agent:$PYTHONPATH
```

### Coverage Not Working
```bash
# Install pytest-cov
uv pip install pytest-cov

# Run with explicit coverage
pytest --cov=starboard packages/starboard/tests/
```

---

**Last Updated**: 2026-08-27
**Version**: 3.0 — architecture/contract suites, root `tests/unit` removed
