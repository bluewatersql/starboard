# ⚠️  DEPRECATED: Use root Makefile instead
# 
# This Makefile is deprecated. Please use the root Makefile from the project root:
#   cd ../.. && make help
#
# Common commands:
#   make dev-server      - Start development server
#   make test            - Run all tests
#   make lint            - Run linting
#   make format          - Format code
#   make clean           - Clean cache files

.PHONY: help validate dev test lint format clean

help:
	@echo "⚠️  This Makefile is deprecated."
	@echo ""
	@echo "Please use the root Makefile instead:"
	@echo "  cd ../.. && make help"
	@echo ""
	@echo "Quick reference (run from project root):"
	@echo "  make dev-server   - Start backend server"
	@echo "  make test         - Run all tests"
	@echo "  make lint         - Run linting"
	@echo "  make format       - Format code"
	@echo "  make clean        - Clean cache"

validate:
	@echo "⚠️  Running from deprecated Makefile. Use: cd ../.. && make verify-install"
	@python validate.py

dev:
	@echo "⚠️  Running from deprecated Makefile. Use: cd ../.. && make dev-server"
	@./dev.sh

lint:
	@echo "⚠️  Running from deprecated Makefile. Use: cd ../.. && make lint"
	@ruff check starboard_server/

format:
	@echo "⚠️  Running from deprecated Makefile. Use: cd ../.. && make format"
	@ruff format starboard_server/

test:
	@echo "⚠️  Running from deprecated Makefile. Use: cd ../.. && make test"
	@pytest

clean:
	@echo "⚠️  Running from deprecated Makefile. Use: cd ../.. && make clean"
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true

