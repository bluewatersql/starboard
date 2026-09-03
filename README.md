# Starboard AI Agent

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
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
- **Interruptible Reasoning** — User-in-the-loop interrupts and replanning

## Architecture

### Package Structure

```
packages/
├── starboard-core/          # Pure kernel: DTOs, ports, analyzers + starboard_x progressive helpers
├── starboard/               # FastAPI server + CLI + adapters + tools (the full experience wheel)
├── starboard-skills/        # Canonical skill files + Databricks helper scripts
├── starboard-internal/      # Internal-only gated port adapters — never in a public wheel
└── starboard-plugin-sample/ # Sample MCP-tools plugin (entry-point discovery demo)
```

| Package | Description | Dependencies |
|---------|-------------|--------------|
| **starboard-core** | Pure kernel (DTOs, ports, analyzers) + `starboard_x` helpers | None heavy (kernel-pure) |
| **starboard** | FastAPI server, CLI, agents, tools | starboard-core |
| **starboard-skills** | Claude skill files + thin helper scripts | starboard-core |
| **starboard-internal** | Internal-only gated adapters (not published publicly) | starboard-core, starboard |
| **starboard-plugin-sample** | Reference MCP-tools plugin | starboard-core |

Kernel purity (`starboard-core`/`starboard_x` carry no `databricks-sdk`/`openai`/`fastapi`/`mcp`) and the
public↔internal boundary are enforced by import-linter (4 contracts). See [`CLAUDE.md`](CLAUDE.md).

### Install Tiers

```bash
pip install starboard          # Full experience: CLI + MCP server + agents + tools
pip install starboard-core     # Kernel + starboard_x helpers (python -m starboard_x.<cap>)
pip install starboard-skills   # Lightweight: Claude skill files + helper scripts only
```

The default `pip install starboard` pulls **no** store/vector drivers. Durable state and ANN retrieval are
opt-in extras that lazy-import and raise an actionable error if missing:

```bash
pip install "starboard[sqlite]"        # local SQLite state + sqlite-vec ANN
pip install "starboard[postgres]"      # Postgres/Lakebase state driver
pip install "starboard[vectorsearch]"  # managed Databricks Vector Search
pip install "starboard-core[discovery]"  # a single starboard_x capability's deps
```

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
app/         – CLI/MCP entrypoints
infra/       – config, logging, DI/wiring, observability
tools/       – tool implementations with explicit schemas
```

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
# Bootstrap the development environment
make setup

# Configure environment
cp examples/env.example .env
# Edit .env with your Databricks and LLM credentials
```

### Development

```bash
# Start the MCP server / backend
make dev-server

# Stop all dev servers
make dev-stop
```

### Use with Claude Code / Cursor

Starboard can be used as an MCP server inside Claude Code, Cursor, or Claude Desktop:

```bash
# Quick setup
pip install starboard
# Copy the example MCP config to your IDE's MCP config location and edit credentials
cp examples/cursor-mcp.json <ide-mcp-config-path>

# Or use the interactive setup wizard (handles config placement automatically):
./scripts/setup-mcp.sh
```

See [Skills Guide](docs/guide/skills.md) for full details, tool reference, and usage examples.

### Testing

```bash
make test               # All tests (unit + integration)
make test-unit          # Unit tests only
make test-integration   # Integration tests
make test-golden        # Golden/snapshot tests
make test-coverage      # With coverage report
```

### Code Quality

```bash
make format             # Auto-format code (ruff)
make lint               # Python linting (ruff)
make type-check         # Python type checking (mypy)
make check              # All checks (lint + type + test)
make pre-commit         # Run pre-commit hooks
```

### CLI Usage

The primary interface is a single natural-language goal. The intent router
automatically selects the right specialist agent.

```bash
# Query optimization
starboard --goal "Optimize the query with statement_id abc123"

# Job performance analysis
starboard --goal "Analyze job 456 for performance issues and suggest tuning"

# Unity Catalog governance
starboard --goal "Show lineage and access patterns for catalog.schema.my_table"

# Warehouse cost analysis
starboard --goal "Review warehouse portfolio for cost savings opportunities"

# Interactive multi-turn session
starboard --chat

# Workspace discovery + health assessment
starboard --discover --lookback-days 30

# See all available flags
starboard --help
```

#### Focused subcommands

```bash
# Workload Review — ranked, evidence-cited findings over public system.* data
starboard review --domains jobs,sql,warehouse --lookback-days 30

# Databricks auth (delegates to the SDK credential chain)
starboard auth status
starboard auth login --profile my-workspace
```

Progressive helpers (kernel tier, dep-light) are also runnable standalone:

```bash
python -m starboard_x.review --help       # also: discovery, warehouse, uc, sparklog, diagnostic
```

### MCP Server

```bash
# Start the MCP server (stdio transport for Claude Code / Cursor)
starboard-mcp --transport stdio
```

## Project Structure

```
job-agent/
├── pyproject.toml              # Root workspace config (uv, ruff, mypy, pytest)
├── uv.lock                     # Unified lockfile
├── Makefile                    # Development workflow commands
├── CONTRIBUTING.md             # Contribution guide
├── packages/                   # Python packages
│   ├── starboard-core/         # Pure kernel + starboard_x helpers
│   ├── starboard/              # FastAPI server + CLI + adapters + tools
│   ├── starboard-skills/       # Claude skills + helper scripts
│   ├── starboard-internal/     # Internal-only gated adapters (not published)
│   └── starboard-plugin-sample/# Sample MCP-tools plugin
├── plugin/                     # Claude Code plugin bundle (skills + rules) + marketplace.json
├── docs/                       # MkDocs documentation site
├── tests/                      # Cross-package tests (architecture, golden, integration, contract)
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
LLM_API_KEY="..."
LLM_MODEL="databricks-claude-sonnet-4-5"
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

## Documentation

### Getting Started
- [Quick Start](docs/guide/quickstart.md) — Get up and running
- [CLI Reference](docs/guide/cli.md) — Configuration and command reference

### Architecture & Design
- [Architecture](docs/architecture.md) — System design and package structure

### Contributing
- [Contributing](docs/contributing.md) — Contribution workflow and standards

### Package Documentation
- [starboard-core](packages/starboard-core/README.md)
- [starboard](packages/starboard/README.md)
- [starboard-skills](packages/starboard-skills/README.md)

### Full Documentation Site

```bash
make docs-serve         # Serve docs at http://localhost:8000
```

## Engineering Standards

This project follows strict Python engineering standards:

- **Simple, readable code** over cleverness
- **Type hints** on all public functions (mypy)
- **Pydantic validation** at all boundaries
- **Structured logging** with trace IDs and cost tracking
- **Golden tests** for all prompts (versioned, never modified in place)
- **Domain-driven design** with clear architectural layers

Full standards are documented in [`docs/contributing.md`](docs/contributing.md).
Contribution workflow is described in [`CONTRIBUTING.md`](CONTRIBUTING.md).

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

Licensed under the [Databricks Open Model License](LICENSE).

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) — MCP server framework
- [OpenAI](https://openai.com/) — LLM provider
- [Databricks SDK](https://github.com/databricks/databricks-sdk-py) — Databricks integration
- [uv](https://github.com/astral-sh/uv) — Package management
