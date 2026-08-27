# Starboard

> Last verified: 2026-08-27

The full-experience package for the Starboard AI Agent platform: the **CLI**, the
**MCP server** (stdio + optional Streamable HTTP transport), the **multi-agent
system**, and the **tool catalog**. It hard-depends on the `starboard-core` kernel.

## Overview

`starboard` provides:

- **CLI (`starboard`)** — direct, in-process agent execution with live terminal
  progress, plus the deterministic surfaces `starboard review`, `starboard genie ask`,
  `starboard --discover`, and `starboard auth`.
- **MCP server** — `starboard-mcp` (stdio transport, no FastAPI) and an optional
  Streamable HTTP transport mounted at `/mcp` by the `starboard-server` app.
- **Multi-Agent System** — 8 domain agents + Intent Router with dynamic tool selection.
- **Tool Implementations** — 45+ tools across categories for Databricks API integrations.
- **LLM Adapters** — OpenAI-compatible providers (OpenAI, Databricks Model Serving).

The primary consumption paths are the **CLI** and the **stdio MCP server**. The
FastAPI app (`starboard-server`) is a thin process that exposes health probes and
the optional `/mcp` HTTP transport — it is not a REST/streaming chat backend.

## Installation

```bash
# Using uv (recommended)
uv pip install -e ".[dev,test]"

# Using pip
pip install -e ".[dev,test]"
```

## Quick Start

```bash
# Authenticate (auth-by-subtraction: reuses your Databricks CLI/SDK config)
export DATABRICKS_HOST="https://your-workspace.databricks.com"
export DATABRICKS_TOKEN="dapi..."
export LLM_API_KEY="<your-llm-api-key>"   # or configure Databricks Model Serving

# Run an analysis from the CLI (in-process, no server required)
starboard "Why is my nightly ETL job slow?"

# Deterministic surfaces
starboard review --rows 200
starboard genie ask "top 10 most expensive queries last week"
starboard --discover
```

To run the stdio MCP server (for Claude Code / Cursor):

```bash
starboard-mcp
```

To run the optional HTTP app (health probes + `/mcp` transport):

```bash
# via the entry point
starboard-server

# or with uvicorn directly (note the --factory flag)
uvicorn starboard.main:create_app --factory --host 0.0.0.0 --port 8000
```

Server starts on `http://localhost:8000`. **Entry point**: `starboard.main:create_app`.

## HTTP Endpoints

The `starboard-server` app is intentionally minimal:

```
GET  /                 # Service info (name, version, status, links)
GET  /health/live      # Liveness probe
GET  /health/ready     # Readiness probe
ANY  /mcp              # Streamable HTTP MCP transport (only when MCP config is present)
```

Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are served outside
production (`ENVIRONMENT=production` disables them).

## Domain Agents

The package hosts 8 domain-specialized agents plus an Intent Router:

| Agent | Domain | Purpose |
|-------|--------|---------|
| **Router** | Intent Classification | Routes requests to specialist agents |
| **Query** | SQL Optimization | Execution plans, query rewrites, partitioning |
| **Job** | Job Performance | Task analysis, Spark tuning, code quality |
| **UC** | Unity Catalog | Metadata, lineage, governance, schema drift |
| **Cluster** | Compute | Cluster sizing, health, utilization |
| **Analytics** | FinOps & Cost | Cost analysis, chargeback, budget forecasting (list-price DBU estimates) |
| **Warehouse** | SQL Warehouses | Portfolio optimization, SLO, topology |
| **Discovery** | Workspace Health | Resource inventory, health scoring (4-phase) |
| **Diagnostic** | Troubleshooting | Root cause analysis, cross-domain debugging |

## Configuration

Environment variables (set in `.env` or the environment):

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABRICKS_HOST` | Databricks workspace URL | Yes* | -- |
| `DATABRICKS_TOKEN` | Databricks access token | Yes* | -- |
| `LLM_API_KEY` | LLM provider API key | Yes* | -- |
| `LLM_MODEL` | Model name | No | `databricks-claude-sonnet-4-5` |
| `LLM_BASE_URL` | Custom OpenAI-compatible endpoint | No | -- |
| `LOG_LEVEL` | Logging level | No | `INFO` |
| `DATABASE_URL` | State backend URL | No | in-memory (store-free) |

\* Auth is resolved by subtraction: Starboard reuses your Databricks CLI/SDK
configuration where available. State is **in-memory by default** — no database to
provision; `uc`/`sqlite`/`postgres`/`lakebase` backends are opt-in. See the
[Configuration Guide](../../docs/CONFIGURATION.md) for the complete reference.

## Architecture

```
starboard/
    main.py              # Thin FastAPI app factory (health + optional /mcp)
    cli/                 # CLI entry points and commands (review, genie ask, auth, --discover)
    mcp/                 # MCP server (stdio + HTTP transport), config, workspace tools
    agents/              # Multi-agent system (routing, domain agents, tool registry)
    tools/               # Tool implementations
        domain/          # Pure business logic
        services/        # Orchestration layer
        adapters/        # I/O adapters (Databricks, etc.)
    prompts/             # Domain-specific system prompts
    domain/              # Package-local domain models
    ports/               # Kernel port wiring + capability discovery
    repositories/        # State/persistence repositories
    services/            # Business services
    adapters/            # External service adapters (LLM, Databricks)
    sdk/                 # In-process client (from starboard.sdk import StarboardClient)
    infra/               # Config, logging, DI, observability, auth
```

## Development

```bash
# Install with dev dependencies
uv pip install -e ".[dev,test]"

# Run tests
pytest

# Lint and type check
make lint && make type-check
```

## Documentation

- [System Architecture](../../docs/architecture/SYSTEM_ARCHITECTURE.md) -- Full system design
- [API Reference](../../docs/api/API_REFERENCE.md) -- Programmatic surfaces (CLI, MCP, SDK)
- [Tool Catalog](../../docs/tools/TOOL_CATALOG.md) -- Tool reference
- [Configuration Guide](../../docs/CONFIGURATION.md) -- Environment variables
- [Testing Guide](../../docs/TESTING.md) -- Testing strategies
