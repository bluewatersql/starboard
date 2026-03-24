# Starboard AI Agent

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Frontend](https://img.shields.io/badge/frontend-Next.js_16-black.svg)](./frontend)
[![Package Manager](https://img.shields.io/badge/pkg_manager-uv-purple.svg)](https://github.com/astral-sh/uv)

AI-powered Databricks workload analysis and optimization platform.

## Overview

Starboard AI Agent is a multi-package monorepo providing:
- **Query Optimization** — AI-driven SQL query analysis and recommendations
- **Job Optimization** — Databricks job performance analysis and tuning
- **Unity Catalog** — Metadata, lineage, governance, and storage optimization
- **Cluster Analysis** — Configuration and performance optimization
- **FinOps Analytics** — Cost analysis, billing, budget forecasting, usage trends
- **Warehouse Optimization** — SQL warehouse portfolio analysis
- **Diagnostics** — Troubleshooting, debugging, and root cause analysis
- **Real-time Streaming** — Live agent reasoning and tool execution via SSE
- **Interruptible Reasoning** — User-in-the-loop interrupts and replanning

## Architecture

### Package Structure

```
packages/
├── starboard-core/         # Domain models, prompts, shared types (no I/O deps)
├── starboard-log-parser/   # Spark event log parsing with credential providers
├── starboard-server/       # FastAPI backend with multi-agent system
├── starboard-cli/          # Command-line interface
└── starboard-sdk/          # Thin SDK for notebook/programmatic use

frontend/                   # Next.js 16 web UI (React 19, Material UI v7)
```

| Package | Description | Dependencies |
|---------|-------------|--------------|
| **starboard-core** | Pure domain logic, prompts, types | None (core) |
| **starboard-log-parser** | Spark event log parsing | starboard-core |
| **starboard-server** | FastAPI backend, agents, tools | starboard-core, starboard-log-parser |
| **starboard-cli** | CLI application | starboard-core, starboard-server |
| **starboard-sdk** | Programmatic SDK for notebooks | starboard-core, starboard-server |
| **frontend** | Next.js web interface | REST API client |

### Multi-Agent System

```
MultiAgentConversationManager
├── IntentRouter        → Classifies intent, routes to specialist
├── QueryAgent          → SQL optimization and analysis
├── JobAgent            → Job performance tuning
├── UCAgent             → Unity Catalog governance
├── ClusterAgent        → Cluster configuration
├── AnalyticsAgent      → FinOps cost analysis
├── WarehouseAgent      → Warehouse portfolio optimization
└── DiagnosticAgent     → Troubleshooting and RCA
```

### Architectural Layers

```
domain/      – pure logic, deterministic, no I/O
adapters/    – I/O boundaries (LLM SDKs, DB, HTTP, FS)
agents/      – policies, tool routing, orchestration
app/         – CLI/API/FastAPI entrypoints
infra/       – config, logging, DI/wiring, observability
tools/       – tool implementations with explicit schemas
```

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- Node.js 18+ (for frontend)

### Setup

```bash
# Bootstrap the development environment
make setup

# Configure environment
cp examples/env.example .env
# Edit .env with your Databricks and OpenAI credentials
```

### Development

```bash
# Start backend + frontend together
make dev

# Or individually:
make dev-server         # Backend at http://localhost:8000 (API docs at /docs)
make dev-frontend       # Frontend at http://localhost:3000

# Stop all dev servers
make dev-stop
```

### Testing

```bash
make test               # All tests (unit + integration)
make test-unit          # Unit tests only
make test-integration   # Integration tests
make test-golden        # Golden/snapshot tests
make test-contract      # API contract tests (backend + frontend)
make test-coverage      # With coverage report
make test-frontend      # Frontend tests (Jest)
```

### Code Quality

```bash
make format             # Auto-format code (ruff)
make lint               # Python linting (ruff)
make lint-frontend      # Frontend linting (eslint + tsc)
make type-check         # Python type checking (mypy)
make check              # All checks (lint + type + test)
make pre-commit         # Run pre-commit hooks
```

### CLI Usage

```bash
starboard query --sql "SELECT * FROM large_table WHERE date > '2024-01-01'"
starboard job --job-id 12345 --mode offline
starboard pipeline --table catalog.schema.table
```

## Project Structure

```
job-agent/
├── pyproject.toml              # Root workspace config (uv, ruff, mypy, pytest)
├── uv.lock                     # Unified lockfile
├── Makefile                    # Development workflow commands
├── CLAUDE.md                   # AI assistant project context
├── .cursorrules                # Cursor workspace behavior rules
├── .cursor/                    # Detailed engineering standards (8 files)
├── packages/                   # Python packages
│   ├── starboard-core/
│   ├── starboard-log-parser/
│   ├── starboard-server/
│   ├── starboard-cli/
│   └── starboard-sdk/
├── frontend/                   # Next.js 16 web UI
├── docs/                       # MkDocs documentation site
├── tests/                      # Cross-package tests (contract, golden, integration)
├── evals/                      # Evaluation assets
├── scripts/                    # Dev/ops scripts
├── examples/                   # Usage examples and env template
└── changes/                    # Change docs, design specs, hand-offs
```

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

```bash
./scripts/databricks_deploy.sh dev    # Deploy to development
./scripts/databricks_deploy.sh prod   # Deploy to production
```

See [Deployment Guide](docs/DEPLOYMENT.md) for all deployment options.

## Documentation

### Getting Started
- [Quick Start](docs/QUICKSTART.md) — Get up and running
- [Configuration](docs/CONFIGURATION.md) — Configuration guide

### Architecture & Design
- [System Architecture](docs/ARCHITECTURE.md) — Complete system design
- [API Reference](docs/API_REFERENCE.md) — REST & Chat APIs
- [Tool Architecture](docs/TOOL_ARCHITECTURE.md) — Tool system design
- [Frontend Architecture](docs/FRONTEND_ARCHITECTURE.md) — Frontend patterns
- [Interruptible Reasoning](docs/INTERRUPTIBLE_REASONING.md) — Agent reasoning patterns

### Operations
- [Deployment](docs/DEPLOYMENT.md) — Production deployment guide
- [Runbook](docs/RUNBOOK.md) — Operational procedures
- [Testing](docs/TESTING.md) — Testing strategies

### Package Documentation
- [starboard-core](packages/starboard-core/README.md)
- [starboard-log-parser](packages/starboard-log-parser/README.md)
- [starboard-server](packages/starboard-server/README.md)
- [starboard-cli](packages/starboard-cli/README.md)
- [starboard-sdk](packages/starboard-sdk/README.md)
- [frontend](frontend/README.md)

### Full Documentation Site

```bash
make docs-serve         # Serve docs at http://localhost:8000
```

## Engineering Standards

This project follows strict Python engineering standards documented in `.cursor/`:

- **Simple, readable code** over cleverness
- **Type hints** on all public functions (mypy)
- **Pydantic validation** at all boundaries
- **Structured logging** with trace IDs and cost tracking
- **Golden tests** for all prompts (versioned, never modified in place)
- **Domain-driven design** with clear architectural layers

See [CLAUDE.md](CLAUDE.md) for a detailed summary or `.cursor/` for the full standards.

## Contributing

1. Create a feature branch (`git checkout -b feature/description`)
2. Make changes following the engineering standards
3. Add/update tests (`make test`)
4. Format and lint (`make format && make lint`)
5. Run type checks (`make type-check`)
6. Run pre-commit hooks (`make pre-commit`)
7. Commit with a clear message
8. Open a Pull Request against `main`

## License

MIT

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) — Backend framework
- [Next.js](https://nextjs.org/) — Frontend framework
- [Material UI](https://mui.com/) — UI component library
- [OpenAI](https://openai.com/) — LLM provider
- [Databricks SDK](https://github.com/databricks/databricks-sdk-py) — Databricks integration
- [uv](https://github.com/astral-sh/uv) — Package management
