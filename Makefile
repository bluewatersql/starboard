# Starboard Development Makefile
# ================================
# Development workflow for Starboard AI Agent monorepo

.PHONY: help setup install install-dev verify \
        dev dev-debug dev-server dev-server-debug dev-stop dev-debug-context \
        test test-unit test-sdk test-integration test-golden test-contract test-coverage test-architecture \
        lint type-check format check pre-commit audit-deps \
        clean clean-debug clean-deep build info

# Package manager detection (prefer uv)
PACKAGE_MANAGER := $(shell command -v uv >/dev/null 2>&1 && echo "uv" || echo "pip")

# Python package paths
PY_PACKAGES := packages/starboard-core/starboard_core \
               packages/starboard-log-parser/starboard_log_parser \
               packages/starboard/starboard
PY_TESTS := packages/*/tests tests

# Colors
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m

# ================================
# Help
# ================================

help:
	@echo "$(BLUE)Starboard Development Commands$(NC)"
	@echo ""
	@echo "$(GREEN)Setup:$(NC)"
	@echo "  setup             First-time environment setup"
	@echo "  install           Install packages (production)"
	@echo "  install-dev       Install with dev dependencies"
	@echo ""
	@echo "$(GREEN)Development:$(NC)"
	@echo "  dev               Start backend server"
	@echo "  dev-debug         Start with debug logging"
	@echo "  dev-server        Backend only (localhost:8000)"
	@echo "  dev-stop          Stop all dev servers"
	@echo ""
	@echo "$(GREEN)Testing:$(NC)"
	@echo "  test              All tests (unit + integration)"
	@echo "  test-unit         Unit tests only (all packages incl. SDK)"
	@echo "  test-sdk          SDK-specific tests"
	@echo "  test-integration  Integration tests"
	@echo "  test-golden       Golden/snapshot tests"
	@echo "  test-contract     API contract tests"
	@echo "  test-coverage     With coverage report"
	@echo "  test-architecture Architecture fitness tests (GUIDELINE-001–010)"
	@echo ""
	@echo "$(GREEN)Code Quality:$(NC)"
	@echo "  lint              Python linting (ruff)"
	@echo "  type-check        Python type checking (mypy)"
	@echo "  format            Auto-format all code"
	@echo "  check             All checks (lint + type + test)"
	@echo "  pre-commit        Run pre-commit hooks"
	@echo ""
	@echo "$(GREEN)Other:$(NC)"
	@echo "  build             Build all packages"
	@echo "  clean             Remove cache/build artifacts"
	@echo "  clean-deep        Deep clean (removes .venv)"
	@echo "  info              Show environment info"
	@echo ""
	@echo "$(YELLOW)Package manager: $(PACKAGE_MANAGER)$(NC)"

info:
	@echo "Package Manager: $(PACKAGE_MANAGER)"
	@python --version 2>/dev/null || echo "Python: not found"

# ================================
# Setup & Installation
# ================================

setup: clean
	@echo "$(BLUE)Setting up development environment...$(NC)"
	@if [ ! -d ".venv" ]; then \
		if [ "$(PACKAGE_MANAGER)" = "uv" ]; then uv venv; else python -m venv .venv; fi; \
	fi
	@$(MAKE) install-dev
	@$(MAKE) verify
	@echo ""
	@echo "$(GREEN)✓ Setup complete!$(NC)"
	@echo "Next: copy examples/env.example to .env and configure"

install:
	@echo "$(BLUE)Installing packages...$(NC)"
	@if [ "$(PACKAGE_MANAGER)" = "uv" ]; then \
		uv sync && \
		uv pip install -e packages/starboard-core -e packages/starboard-log-parser \
		              -e packages/starboard; \
	else \
		pip install -e packages/starboard-core -e packages/starboard-log-parser \
		            -e packages/starboard; \
	fi
	@echo "$(GREEN)✓ Done$(NC)"

install-dev:
	@echo "$(BLUE)Installing with dev dependencies...$(NC)"
	@if [ "$(PACKAGE_MANAGER)" = "uv" ]; then \
		uv sync && \
		uv pip install -e "packages/starboard-core[test]" \
		              -e "packages/starboard-log-parser[test,databricks,http]" \
		              -e "packages/starboard[test,dev]"; \
	else \
		pip install -e "packages/starboard-core[test]" \
		            -e "packages/starboard-log-parser[test,databricks,http]" \
		            -e "packages/starboard[test,dev]"; \
	fi
	@echo "$(GREEN)✓ Done$(NC)"

verify:
	@echo "$(BLUE)Verifying installation...$(NC)"
	# Requires Python 3.12 — aligned with pyproject.toml (python_version=3.12) and .python-version (3.12.10)
	@python -c "import sys; assert sys.version_info >= (3, 12)" && echo "$(GREEN)✓ Python 3.12+$(NC)"
	@python -c "import starboard_core" && echo "$(GREEN)✓ starboard-core$(NC)"
	@python -c "import starboard_log_parser" && echo "$(GREEN)✓ starboard-log-parser$(NC)"
	@python -c "import starboard" && echo "$(GREEN)✓ starboard$(NC)"

# ================================
# Development Servers
# ================================

# Debug output directory
DEBUG_DIR := .debug

dev:
	@echo "$(BLUE)Starting Starboard backend...$(NC)"
	@$(MAKE) dev-server

dev-debug:
	@mkdir -p $(DEBUG_DIR)
	@echo "$(BLUE)Starting server with debug logging...$(NC)"
	@echo "$(YELLOW)Logs: $(DEBUG_DIR)/server.log$(NC)"
	@$(MAKE) dev-server-debug

dev-server:
	@echo "$(BLUE)Starting backend server...$(NC)"
	@cd packages/starboard && STARBOARD_LOG_LEVEL=DEBUG uvicorn "starboard.main:create_app" --factory --reload --host 0.0.0.0 --port 8000

dev-server-debug:
	@mkdir -p $(DEBUG_DIR)
	@echo "$(BLUE)Starting backend (debug)...$(NC)"
	@cd packages/starboard && \
		STARBOARD_LOG_LEVEL=DEBUG STARBOARD_DEBUG=true \
		uvicorn "starboard.main:create_app" --factory --reload --host 0.0.0.0 --port 8000 \
		--log-level debug 2>&1 | tee ../../$(DEBUG_DIR)/server.log

dev-stop:
	@echo "$(BLUE)Stopping dev servers...$(NC)"
	@-pkill -f "uvicorn starboard" 2>/dev/null || true
	@echo "$(GREEN)✓ Servers stopped$(NC)"

dev-debug-context:
	@echo "$(BLUE)Running debug lints/type-checks/tests...$(NC)"
	@rm -rf .debug/test
	@mkdir -p .debug/test/lint .debug/test/type-check .debug/test/tests
	@echo "$(BLUE)  Running format...$(NC)"
	@ruff format >/dev/null 2>&1 || true
	@ruff check --fix >/dev/null 2>&1 || true
	@echo "$(BLUE)  Running lint...$(NC)"
	@ruff check > .debug/test/lint/ruff.txt || true
	@echo "$(BLUE)  Running type-check...$(NC)"
	@mypy . > .debug/test/type-check/mypy.txt || true
	@echo "$(BLUE)  Running test-unit...$(NC)"
	@pytest packages/starboard-core/tests/unit/ packages/starboard-log-parser/tests/unit/ packages/starboard/tests/unit/ --tb=line 2>&1 | grep -E "^(FAILED|ERROR|packages/.*FAILED)" > .debug/test/tests/unit.txt || true
	@echo "$(BLUE)  Running test-integration...$(NC)"
	@pytest packages/starboard/tests/integration/ --tb=line 2>&1 | grep -E "^(FAILED|ERROR|packages/.*FAILED)" > .debug/test/tests/integration.txt || true
	@echo "$(BLUE)  Running test-golden...$(NC)"
	@pytest -m golden --tb=line 2>&1 | grep -E "^(FAILED|ERROR|packages/.*FAILED)" > .debug/test/tests/golden.txt || true
	@echo "$(BLUE)  Running test-contract...$(NC)"
	@pytest tests/contract/ --tb=line 2>&1 | grep -E "^(FAILED|ERROR|tests/.*FAILED)" > .debug/test/tests/contract.txt || true
	@find .debug/test -type f -empty -delete
	@echo "$(GREEN)✓ Debug context saved to .debug/test/ (empty files removed)$(NC)"
# ================================
# Testing
# ================================

test: test-unit test-integration

test-unit:
	@echo "$(BLUE)Running unit tests...$(NC)"
	@pytest packages/starboard-core/tests/unit/ -v --tb=short
	@pytest packages/starboard-log-parser/tests/unit/ -v --tb=short
	@pytest packages/starboard/tests/unit/ -v --tb=short
	@echo "$(GREEN)✓ Unit tests passed$(NC)"

test-sdk:
	@echo "$(BLUE)Running SDK tests...$(NC)"
	@pytest packages/starboard/tests/unit/test_sdk.py -v --tb=short
	@echo "$(GREEN)✓ SDK tests passed$(NC)"

test-integration:
	@echo "$(BLUE)Running integration tests...$(NC)"
	@pytest packages/starboard/tests/integration/ -v --tb=short
	@pytest tests/integration/ -v --tb=short 2>/dev/null || true
	@echo "$(GREEN)✓ Integration tests passed$(NC)"

test-golden:
	@echo "$(BLUE)Running golden tests...$(NC)"
	@pytest tests/golden/ -v --tb=short
	@echo "$(GREEN)✓ Golden tests passed$(NC)"

test-contract:
	@echo "$(BLUE)Running contract tests...$(NC)"
	@pytest tests/contract/ -v --tb=short
	@echo "$(GREEN)✓ Contract tests passed$(NC)"

test-coverage:
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	@pytest packages/starboard-core/tests/unit/ \
		packages/starboard-log-parser/tests/unit/ \
		packages/starboard/tests/unit/ \
		--cov=starboard_core \
		--cov=starboard_log_parser \
		--cov=starboard \
		--cov-report=term-missing --cov-report=html:htmlcov
	@echo "$(GREEN)✓ Coverage report: htmlcov/index.html$(NC)"

test-architecture:
	@echo "$(BLUE)Running architecture fitness tests...$(NC)"
	@pytest tests/architecture/ -v --tb=short
	@echo "$(GREEN)Architecture tests complete.$(NC)"

# ================================
# Code Quality
# ================================

lint:
	@echo "$(BLUE)Running Python linter...$(NC)"
	@ruff check $(PY_PACKAGES) $(PY_TESTS)
	@echo "$(GREEN)✓ Lint passed$(NC)"

type-check:
	@echo "$(BLUE)Running type checker...$(NC)"
	@mypy packages/starboard/starboard/ --config-file pyproject.toml
	@echo "$(GREEN)✓ Type check passed$(NC)"

format:
	@echo "$(BLUE)Formatting code...$(NC)"
	@ruff format $(PY_PACKAGES) $(PY_TESTS)
	@ruff check --fix $(PY_PACKAGES) $(PY_TESTS)
	@echo "$(GREEN)✓ Code formatted$(NC)"

check: lint type-check test-unit test-architecture
	@echo "$(GREEN)✓ All checks passed$(NC)"

pre-commit:
	@echo "$(BLUE)Running pre-commit hooks...$(NC)"
	@pre-commit run --all-files
	@echo "$(GREEN)✓ Pre-commit complete$(NC)"

audit-deps:
	@echo "$(BLUE)Auditing dependencies...$(NC)"
	pip-audit --strict
	@echo "$(GREEN)✓ Audit complete$(NC)"

# ================================
# Build
# ================================

build:
	@echo "$(BLUE)Building packages...$(NC)"
	@if [ "$(PACKAGE_MANAGER)" = "uv" ]; then \
		uv build packages/starboard-core && \
		uv build packages/starboard-log-parser && \
		uv build packages/starboard; \
	else \
		cd packages/starboard-core && python -m build && \
		cd ../starboard-log-parser && python -m build && \
		cd ../starboard && python -m build; \
	fi
	@echo "$(GREEN)✓ Build complete$(NC)"

# ================================
# Cleanup
# ================================

clean:
	@echo "$(BLUE)Cleaning...$(NC)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "dist" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "build" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name ".coverage*" -delete 2>/dev/null || true
	@echo "$(GREEN)✓ Clean$(NC)"

clean-debug:
	@echo "$(BLUE)Cleaning debug logs...$(NC)"
	@rm -rf $(DEBUG_DIR)
	@echo "$(GREEN)✓ Debug logs cleaned$(NC)"

clean-deep: clean clean-debug
	@echo "$(YELLOW)Deep cleaning (removing all temp files)...$(NC)"
	@# Python virtual environment
	@rm -rf .venv
	@# Python compiled and temp files
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name "*.so" -delete 2>/dev/null || true
	@find . -type f -name "*.pyd" -delete 2>/dev/null || true
	@find . -type f -name "*.db" -delete 2>/dev/null || true
	@find . -type f -name "*.db-journal" -delete 2>/dev/null || true
	@find . -type d -name ".hypothesis" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".tox" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".benchmarks" -exec rm -rf {} + 2>/dev/null || true
	@# Documentation build output
	@rm -rf site
	@# OS and editor temp files
	@find . -type f -name ".DS_Store" -delete 2>/dev/null || true
	@find . -type f -name "Thumbs.db" -delete 2>/dev/null || true
	@find . -type f -name "*~" -delete 2>/dev/null || true
	@find . -type f -name "*.swp" -delete 2>/dev/null || true
	@find . -type f -name "*.swo" -delete 2>/dev/null || true
	@echo "$(GREEN)✓ Deep clean complete$(NC)"

# ================================
# Documentation (optional)
# ================================

.PHONY: docs docs-serve

docs:
	@echo "$(BLUE)Building docs...$(NC)"
	@python scripts/generate_diagrams.py --verbose 2>/dev/null --quality medium || true
	@python -m mkdocs build --strict
	@echo "$(GREEN)✓ Docs built: site/$(NC)"

docs-serve:
	@echo "$(BLUE)Serving docs at http://localhost:8000$(NC)"
	@python -m mkdocs serve
