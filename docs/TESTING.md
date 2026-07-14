# Testing Guide

Testing structure and practices for the Starboard AI Agent monorepo.

---

## Test Organization

Tests are co-located with code in each package:

```
packages/
├── starboard-core/
│   └── tests/
│       ├── conftest.py
│       └── unit/
│
└── starboard/
    └── tests/
        ├── conftest.py
        ├── unit/
        ├── golden/        # Snapshot tests for prompts
        └── integration/   # Integration tests

tests/                      # Root-level cross-package tests
└── integration/            # Cross-package integration
```

### Test Types

| Type | Location | Purpose | Speed |
|------|----------|---------|-------|
| **Unit** | `packages/*/tests/unit/` | Test individual functions/classes | Fast |
| **Golden** | `packages/starboard/tests/golden/` | Snapshot tests for prompts | Fast |
| **Package Integration** | `packages/*/tests/integration/` | Test package components together | Medium |
| **Cross-Package** | `tests/integration/` | Test package interactions | Medium |

---

## Running Tests

### Single Package

```bash
# From package directory
cd packages/starboard
pytest

# Or from root
pytest packages/starboard/tests/

# Specific test types
pytest -m unit                # Only unit tests
pytest -m golden              # Only golden tests
pytest -m integration         # Only integration tests
```

### All Packages

```bash
# Run all package tests
pytest packages/

# Run in parallel (faster)
pytest packages/ -n auto
```

### Integration Tests

```bash
# Package integration
pytest packages/starboard/tests/integration/

# Cross-package integration
pytest tests/integration/
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

**Last Updated**: November 19, 2025  
**Version**: 2.0.0
