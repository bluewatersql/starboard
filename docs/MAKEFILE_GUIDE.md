# Makefile Guide

Complete guide to the Starboard development Makefile.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Setup & Installation](#setup--installation)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Code Quality](#code-quality)
- [Build & Package](#build--package)
- [Cleanup](#cleanup)
- [Troubleshooting](#troubleshooting)

---

## Overview

The root Makefile provides a unified interface for all development tasks across the Starboard monorepo. It automatically detects and uses `uv` (preferred) or falls back to `pip`.

**Key Features:**
- Single source of truth for all build/test/dev commands
- Supports both `uv` and `pip` package managers
- Colored output for better readability
- Installation verification
- Parallel test execution
- Comprehensive code quality checks

---

## Prerequisites

### Required
- **Python 3.12+**: The project requires Python 3.12 or higher
- **Package Manager**: Either `uv` (recommended) or `pip`

### Recommended
- **uv**: For best performance and dependency management

```bash
# Install uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Check Prerequisites

```bash
make info
```

This shows:
- Package manager being used (uv or pip)
- Python version
- Installed tools (pytest, ruff, mypy)

---

## Setup & Installation

### First-Time Setup (Recommended)

```bash
make setup
```

**What it does:**
1. Creates virtual environment (`.venv`)
2. Installs all packages in editable mode
3. Installs development and test dependencies
4. Verifies installation is working
5. Shows next steps

**When to use:**
- First time cloning the repository
- After `make clean-deep`
- When dependencies have been updated

### Install Targets

#### `make install`
Install all packages without test dependencies.

```bash
make install
```

**Use case:** Production-like installation or minimal setup.

#### `make install-dev`
Install all packages with development dependencies.

```bash
make install-dev
```

**Installs:**
- All three packages (core, server, cli) in editable mode
- Test frameworks (pytest, pytest-cov, pytest-asyncio, etc.)
- Linting/formatting tools (ruff, mypy)
- Development tools (uvicorn with auto-reload)

**Use case:** Full development environment (recommended).

---

## Development Workflow

### Start Development Server

#### Backend Only

```bash
make dev-server
```

- Starts FastAPI server with hot-reload
- Runs on `http://localhost:8000`
- API docs at `http://localhost:8000/docs`
- Auto-reloads on code changes

#### MCP Server (stdio transport)

```bash
starboard-mcp --transport stdio
```

The MCP server communicates over stdio for use with Claude Code, Cursor, and Claude Desktop.

---

## Testing

### Run Tests

#### All Tests

```bash
make test
```

Runs unit tests and integration tests for all packages.

#### Unit Tests Only

```bash
make test-unit
```

**What it tests:**
- `packages/starboard/tests/unit/`
- `packages/starboard-core/tests/unit/`
- `packages/starboard-skills/tests/unit/`

**Characteristics:**
- Fast (<1 second per test)
- No external dependencies
- Pure logic testing

#### Integration Tests

```bash
make test-integration
```

**What it tests:**
- `packages/starboard/tests/integration/`

**Characteristics:**
- May call external services (mocked in most cases)
- Tests component interactions
- Slower than unit tests

#### Golden/Snapshot Tests

```bash
make test-golden
```

Tests for:
- Prompt outputs
- LLM response schemas
- Data transformation snapshots

**Use case:** Ensure prompt changes don't break existing behavior.

#### Coverage Report

```bash
make test-coverage
```

**Output:**
- Terminal: Summary with line-by-line coverage
- HTML: `packages/starboard/htmlcov/index.html`
- JSON: `.coverage.json`

**Opens HTML report:**
```bash
open packages/starboard/htmlcov/index.html
```

---

## Code Quality

### Linting

```bash
make lint
```

**What it checks:**
- PEP 8 compliance
- Import sorting
- Unused imports
- Code complexity
- Best practices violations

**Tool:** Ruff (fast Python linter)

**Fix automatically:**
```bash
make format
```

### Type Checking

```bash
make type-check
```

**What it checks:**
- Type hint correctness
- Type consistency
- Missing type annotations
- Type inference issues

**Tool:** mypy with strict mode

**Configuration:** `pyproject.toml`

### Formatting

```bash
make format
```

**What it does:**
1. Formats code with Ruff
2. Auto-fixes linting issues
3. Organizes imports

**Applies to:**
- All Python files in `packages/*/`
- Test files
- Root-level tests

**Safe:** Non-destructive, only formats code style.

### Pre-Commit Checks

```bash
make pre-commit
```

**Runs:**
1. `make format` - Auto-format code
2. `make lint` - Check for issues
3. `make type-check` - Verify types

**Use case:** Run before committing to ensure clean code.

### Complete Check

```bash
make check
```

**Runs:**
1. Linting
2. Type checking
3. Unit tests

**Use case:** CI/CD pipeline, final verification before merge.

**Exit codes:**
- `0`: All checks passed
- `>0`: At least one check failed

---

## Build & Package

### Build All Packages

```bash
make build
```

**What it builds:**
- `packages/starboard-core/dist/`
- `packages/starboard/dist/`
- `packages/starboard-skills/dist/`

**Output formats:**
- Wheel (`.whl`) - binary distribution
- Source distribution (`.tar.gz`)

**Use case:** Preparing for PyPI release or Docker image.

---

## Cleanup

### Standard Clean

```bash
make clean
```

**Removes:**
- `__pycache__/` directories
- `.pytest_cache/`
- `.mypy_cache/`
- `.ruff_cache/`
- `htmlcov/` coverage reports
- `*.pyc` compiled Python files
- `.coverage*` coverage data
- `dist/` and `build/` directories
- `*.egg-info/` package metadata

**Safe:** Does not remove virtual environment or dependencies.

### Deep Clean

```bash
make clean-deep
```

**Removes everything from `make clean` plus:**
- `.venv/` virtual environment

**Warning:** After deep clean, you must run `make setup` again.

**Use case:**
- Starting fresh
- Troubleshooting dependency issues
- Freeing disk space

---

## Troubleshooting

### Common Issues

#### "Package Manager Not Found"

```bash
make info
```

If neither `uv` nor `pip` is found:

```bash
# Install uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or ensure pip is available
python -m ensurepip
```

#### "Python 3.12+ Required"

```bash
python --version
```

If version is < 3.12:

```bash
# Install Python 3.12+ using pyenv
pyenv install 3.12
pyenv local 3.12

# Or use system package manager
# macOS
brew install python@3.12

# Ubuntu
sudo apt install python3.12
```

#### "pytest: command not found"

If pytest is missing:

```bash
make install-dev
```

#### Tests Failing with Import Errors

Ensure packages are installed in editable mode:

```bash
make install-dev
```

#### "No such file or directory" when running `make dev-server`

Activate virtual environment first:

```bash
source .venv/bin/activate
make dev-server
```

Or use:

```bash
# Run within virtual environment automatically
.venv/bin/python -m uvicorn starboard.main:app --reload
```

#### Makefile Shows Deprecation Warning

If you see:

```
⚠️  This Makefile is deprecated.
```

You're in a package subdirectory. Change to project root:

```bash
cd ../..
make help
```

### Performance Tips

#### Slow Package Installation

Install `uv` for 10-100x faster dependency resolution:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
make info  # Should now show "uv" as package manager
```

#### Slow Linting

Ruff is already fast, but ensure you're not linting generated files:

```bash
# Check .gitignore includes:
__pycache__/
*.pyc
htmlcov/
.venv/
```

---

## Advanced Usage

### Running Specific Package Tests

```bash
# Test only starboard
cd packages/starboard && pytest tests/unit/ -v

# Test only starboard-core
cd packages/starboard-core && pytest tests/unit/ -v
```

### Watch Mode (Auto-run tests on change)

```bash
# Install pytest-watch
pip install pytest-watch

# Watch and re-run tests
cd packages/starboard
ptw tests/unit/
```

### Debug Mode

```bash
# Run tests with verbose output
cd packages/starboard
pytest tests/unit/ -vv -s

# Run single test
pytest tests/unit/agents/test_domain_agent.py::test_specific_function -vv -s
```

### Coverage Thresholds

Set minimum coverage in `pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 80
```

Then:

```bash
make test-coverage
# Will exit with error if coverage < 80%
```

---

## Environment Variables

The Makefile respects these environment variables:

- `PACKAGE_MANAGER`: Override auto-detection (`uv` or `pip`)
- Standard color codes can be disabled (set `NO_COLOR=1`)

Example:

```bash
# Force pip even if uv is available
PACKAGE_MANAGER=pip make install

# Disable colored output
NO_COLOR=1 make test
```

---

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      
      - name: Install dependencies
        run: make install-dev
      
      - name: Run checks
        run: make check
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: .coverage.json
```

---

## Best Practices

### Development Workflow

1. **Start of day:**
   ```bash
   git pull
   make install-dev  # Update dependencies if needed
   ```

2. **During development:**
   ```bash
   make dev-server  # In one terminal
   make test-unit   # Run frequently
   ```

3. **Before committing:**
   ```bash
   make pre-commit
   # or
   make check
   ```

4. **Before pushing:**
   ```bash
   make test
   make check
   ```

### Package Updates

When dependencies change:

```bash
make clean
make install-dev
make test
```

### Debugging Setup Issues

```bash
make info        # Check environment
make clean       # Clear caches
make install-dev # Reinstall
```

---

## Migration from Old Setup

If you were using the old `scripts/setup_testing.sh`:

### Old Way

```bash
bash scripts/setup_testing.sh
make test
```

### New Way

```bash
make setup
make test
```

**Benefits:**
- Single entry point
- Automatic package manager detection
- Verification built-in
- Cleaner, more maintainable

---

## Help & Support

### Show All Commands

```bash
make help
```

### Show Environment Info

```bash
make info
```

### Report Issues

If you encounter issues with the Makefile:

1. Run diagnostics:
   ```bash
   make info
   ```

2. Clean and retry:
   ```bash
   make clean
   make install-dev
   ```

3. Check documentation:
   - This guide
   - [QUICKSTART.md](./QUICKSTART.md)

4. Open an issue with:
   - Output of `make info`
   - Error message
   - Steps to reproduce

---

## Summary

### Essential Commands

| Command | Purpose |
|---------|---------|
| `make setup` | First-time setup |
| `make dev-server` | Start backend server |
| `make test` | Run all tests |
| `make test-unit` | Run unit tests |
| `make lint` | Check code quality |
| `make format` | Auto-format code |
| `make check` | Run all checks |
| `make clean` | Clean caches |
| `make help` | Show all commands |

### Daily Development

```bash
# Morning
make dev-server

# During development
make test-unit

# Before commit
make pre-commit

# Before push
make check
```

That's it! Happy developing! 🚀

