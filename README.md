# Starboard AI Agent

[![Coverage](https://img.shields.io/badge/coverage-49%25-yellow.svg)](./htmlcov/index.html)
[![Tests](https://img.shields.io/badge/tests-3%2C269%20passed-brightgreen.svg)](./tests)
[![Agents](https://img.shields.io/badge/agents-100%25_native-brightgreen.svg)](./changes/test_coverage/)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Frontend](https://img.shields.io/badge/frontend-518%20tests-blue.svg)](./frontend)

AI-powered Databricks workload analysis and optimization platform.

## Overview

Starboard AI Agent is a multi-package monorepo providing:
- **Query Optimization**: AI-driven SQL query analysis and recommendations
- **Job Optimization**: Databricks job performance analysis
- **Pipeline Optimization**: Data pipeline lineage and optimization
- **Real-time Streaming**: Live agent reasoning and tool execution
- **Interruptible Reasoning**: User-in-the-loop interrupts and replanning
- **Conversation Patterns**: Multi-turn conversations with intelligent routing and feedback

## Architecture

This is a **multi-package monorepo** with the following packages:

```
packages/
├── starboard-core/      # Core domain models, prompts, shared types
├── starboard-server/    # FastAPI backend server
└── starboard-cli/       # Command-line interface
frontend/                # Next.js web UI
```

### Package Details

| Package | Description | Dependencies |
|---------|-------------|--------------|
| **starboard-core** | Pure domain logic, prompts, types | None (core) |
| **starboard-server** | FastAPI backend, agents, tools | starboard-core |
| **starboard-cli** | CLI application | starboard-core |
| **frontend** | Next.js web interface | REST API client |

## Quick Start

### First-Time Setup

```bash
# Bootstrap the development environment
make setup

# This will:
# - Create virtual environment (.venv)
# - Install all packages with test dependencies
# - Verify installation is working
```

### Environment Configuration

```bash
# Copy example environment file
cp examples/env.example .env

# Edit .env and configure:
# - DATABRICKS_HOST: Your Databricks workspace URL
# - DATABRICKS_TOKEN: Databricks access token
# - OPENAI_API_KEY: OpenAI API key
```

### Development

```bash
# Start the backend server
make dev-server
# Server runs on http://localhost:8000
# API docs at http://localhost:8000/docs

# Start the frontend (in another terminal)
make dev-frontend
# Frontend runs on http://localhost:3000

# Or start both together
make dev
```

### Testing

```bash
# Run all tests
make test

# Run only unit tests
make test-unit

# Run with coverage report
make test-coverage

# Run tests in parallel (faster)
make test-parallel
```

### Code Quality

```bash
# Format code
make format

# Run linter
make lint

# Run type checking
make type-check

# Run all checks (format + lint + type + test)
make check
```

### Using the CLI

```bash
# Optimize a query
starboard query --sql "SELECT * FROM large_table WHERE date > '2024-01-01'"

# Optimize a job
starboard job --job-id 12345 --mode offline

# Analyze a pipeline
starboard pipeline --table catalog.schema.table
```

### Common Commands

```bash
make help            # Show all available commands
make info            # Show environment information
make verify-install  # Verify installation is working
make clean           # Remove cache files
```

### Using the Web UI

```bash
# Start the Next.js web interface
cd frontend
npm install
npm run dev

# Open browser to http://localhost:3000
# See frontend/docs/QUICKSTART.md for detailed setup
```

## Development

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
# Clone repository
git clone <repo-url>
cd job-agent

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e "packages/starboard-core[test]"
pip install -e "packages/starboard-server[dev,test]"
pip install -e "packages/starboard-cli[test]"
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Test specific package
uv run pytest packages/starboard-server/tests/

# Run with coverage
uv run pytest --cov=starboard_core --cov=starboard_server
```

### Code Quality

```bash
# Format code
uv run ruff format packages/

# Lint
uv run ruff check packages/

# Type check
uv run mypy packages/
```

### Package-Specific Commands

```bash
# Server development
cd packages/starboard-server
uvicorn starboard_server.main:app --reload

# Web UI development
cd frontend
npm run dev

# Run CLI locally
cd packages/starboard-cli
python -m starboard_cli.cli.main query --sql "SELECT 1"
```

## Project Structure

```
job-agent/
├── pyproject.toml              # Root workspace config
├── uv.lock                     # Unified lockfile
├── README.md                   # This file
├── docs/                       # Documentation
│   ├── QUICKSTART.md
│   ├── ARCHITECTURE.md
│   ├── API_REFERENCE.md
│   ├── CONFIGURATION.md
│   ├── DEPLOYMENT.md
│   └── RUNBOOK.md
├── packages/                   # Package source code
│   ├── starboard-core/
│   │   ├── pyproject.toml
│   │   ├── starboard_core/
│   │   ├── tests/
│   │   └── README.md
│   ├── starboard-server/
│   │   ├── pyproject.toml
│   │   ├── starboard_server/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── README.md
│   └── starboard-cli/
├── frontend/                   # Next.js web UI
├── scripts/                    # Dev/ops scripts
└── examples/                   # Usage examples
```

## Documentation

### Getting Started
- **[Quick Start](docs/QUICKSTART.md)** - Get up and running in 5 minutes
- **[Configuration](docs/CONFIGURATION.md)** - Configuration guide
- **[Frontend Quick Start](frontend/docs/QUICKSTART.md)** - Web UI setup guide

### Architecture & Design
- **[System Architecture](docs/ARCHITECTURE.md)** - Complete system design
- **[API Reference](docs/API_REFERENCE.md)** - REST & Chat APIs
- **[Tool Architecture](docs/TOOL_ARCHITECTURE.md)** - Tool system design
- **[Frontend Architecture](docs/FRONTEND_ARCHITECTURE.md)** - Frontend patterns and best practices
- **[Interruptible Reasoning](docs/INTERRUPTIBLE_REASONING.md)** - Agent reasoning and interrupts
- **[Conversation Patterns](docs/conversation-patterns/README.md)** - Multi-turn conversation system (Phases 1-4)
- **[Future Patterns](docs/futures/README.md)** - Proposed enhancements (Phases 5-8)

### Operations
- **[Deployment](docs/DEPLOYMENT.md)** - Production deployment guide
- **[Runbook](docs/RUNBOOK.md)** - Operational procedures
- **[Testing](docs/TESTING.md)** - Testing strategies
- **[Test Coverage Strategy](docs/TEST_COVERAGE_STRATEGY.md)** - Coverage improvement roadmap

### Project History
- **[Changelog](CHANGELOG.md)** - Release notes and version history
- **[Refactoring History](docs/REFACTORING_HISTORY.md)** - Major refactoring initiative (Sprints 1-11)

### Package Documentation
- [starboard-core](packages/starboard-core/README.md) - Core domain models
- [starboard-server](packages/starboard-server/README.md) - Backend server
- [starboard-cli](packages/starboard-cli/README.md) - CLI usage
- [frontend](frontend/README.md) - Next.js web UI

## Configuration

### Environment Variables

```bash
# Databricks connection
DATABRICKS_HOST="https://workspace.databricks.com"
DATABRICKS_TOKEN="dapi..."
DATABRICKS_WAREHOUSE_ID="warehouse-id"

# LLM configuration
OPENAI_API_KEY="sk-..."
LLM_MODEL="gpt-4"
LLM_TEMPERATURE="0.4"

# Server configuration
HOST="0.0.0.0"
PORT="8000"
LOG_LEVEL="INFO"
DEBUG="false"
```

See [examples/env.example](examples/env.example) for full configuration options.

## Deployment

### Databricks Asset Bundles (Recommended)

Deploy to Databricks with auto-scaling, integrated auth, and monitoring:

```bash
# Quick deploy to development
./scripts/databricks_deploy.sh dev

# Deploy to production
./scripts/databricks_deploy.sh prod
```

**📚 Guides:**
- **[Deployment Guide](docs/DEPLOYMENT.md)** - All deployment options including Databricks

### Docker Compose (Self-hosted)

```bash
# Build and run with Docker Compose
docker-compose up -d

# Or build for Databricks
docker build -f Dockerfile.databricks -t starboard-agent .
```

### Deployment Options

| Option | Best For | Complexity | Auto-scaling |
|--------|----------|------------|--------------|
| **Databricks Apps** | Production | Low | ✅ Yes |
| **Docker Compose** | Development/Self-hosted | Low | ❌ Manual |
| **Kubernetes** | Enterprise | High | ✅ Yes |

## Testing & Quality

The project has comprehensive test coverage ensuring production readiness:

### Coverage Metrics

| Package | Tests | Coverage |
|---------|-------|----------|
| **starboard-server** | 1,489 | 49% |
| **starboard-core** | 115 | 97% |
| **starboard-cli** | 53 | 75% |
| **frontend** | 518 | 51% |
| **root tests** | 1,762 | - |

- **Total Tests**: 3,269+ passing (100% pass rate)
- **Core Domain**: 97% coverage
- **Multi-Agent Framework**: 85%+ coverage
- **Critical Paths**: 100% coverage (safety, events, checkpoints)

### Test Suite Breakdown
- **Tier 1 (Critical)**: ~500 tests, 95%+ coverage
  - Safety & PII redaction
  - Event streaming
  - Checkpoint system
  - Error recovery
  - Intent routing
  - Agent factory & configuration

- **Tier 2 (High-Impact)**: ~700 tests, 85%+ coverage
  - Configuration management
  - State management
  - Routing decisions
  - Tool registry & factory
  - Domain prompts
  - Multi-agent coordination

- **Tier 3 (Comprehensive)**: ~600 tests, 75%+ coverage
  - Shared context
  - Replan logic
  - Metrics & monitoring
  - LLM response handling
  - Service integrations

### Running Tests

#### Quick Start - Install Test Dependencies

```bash
# One-time setup: Install test dependencies
make install-test

# Or use the setup script directly
bash scripts/setup_testing.sh
```

#### Run Tests

```bash
# Using Makefile (recommended)
make test                # Run all tests
make test-unit           # Run unit tests only
make test-integration    # Run integration tests only
make test-coverage       # Run with coverage report
make test-parallel       # Run tests in parallel (faster)

# Or run pytest directly
cd packages/starboard-server
pytest tests/unit/ -v                    # Unit tests
pytest tests/integration/ -v             # Integration tests
pytest tests/ --cov=starboard_server     # With coverage
pytest tests/ -n auto                    # Parallel execution

# View coverage report
open htmlcov/index.html
```

#### Code Quality

```bash
# Run all quality checks
make check               # Lint + type-check + tests

# Individual checks
make lint                # Run ruff linter
make type-check          # Run mypy type checking
make format              # Auto-format code
```

For detailed testing documentation, see [TESTING.md](docs/TESTING.md).

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`uv run pytest`)
5. Ensure coverage doesn't decrease
6. Format code (`uv run ruff format packages/`)
7. Commit changes (`git commit -m 'Add amazing feature'`)
8. Push to branch (`git push origin feature/amazing-feature`)
9. Open a Pull Request

## Engineering Standards

This project follows strict Python engineering standards documented in the repository rules. Key principles:

- **Simple, readable code** over cleverness
- **Type hints** on all public functions
- **Pydantic validation** at all boundaries
- **Structured logging** with trace IDs
- **Golden tests** for prompts
- **Domain-driven design** with clear layers

See engineering standards document for full details.

## License

MIT

## Support

- **Issues**: [GitHub Issues](https://github.com/starboard-ai/job-agent/issues)
- **Documentation**: [docs/](docs/)
- **Examples**: [examples/](examples/)

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Backend framework
- [Dash](https://dash.plotly.com/) - Web UI framework
- [OpenAI](https://github.com/openai/openai-python) - LLM client and tool calling
- [Databricks SDK](https://github.com/databricks/databricks-sdk-py) - Databricks integration
- [OpenAI](https://openai.com/) - LLM provider
