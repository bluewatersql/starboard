# Starboard Server

> Last verified: 2026-03-24

FastAPI backend server for the Starboard AI Agent platform.

## Overview

`starboard-server` is the core backend package providing:

- **REST API**: Conversation management, message handling, and health endpoints
- **SSE Streaming**: Real-time Server-Sent Events for agent reasoning progress
- **Multi-Agent System**: 8 domain agents + Intent Router with dynamic tool selection
- **Tool Implementations**: 45+ tools across 9 categories for Databricks API integrations
- **LLM Adapters**: Multi-provider support (OpenAI, Azure OpenAI, Databricks Model Serving)

## Installation

```bash
# Using uv (recommended)
uv pip install -e ".[dev,test]"

# Using pip
pip install -e ".[dev,test]"
```

## Quick Start

```bash
# Set environment variables
export DATABRICKS_HOST="https://your-workspace.databricks.com"
export DATABRICKS_TOKEN="dapi..."
export LLM_API_KEY="<your-llm-api-key>"

# Start with make (recommended)
make dev-server

# Or with uvicorn directly (note the --factory flag)
uvicorn starboard_server.main:create_app --factory --host 0.0.0.0 --port 8000
```

Server starts on `http://localhost:8000`.

**Entry point**: `starboard_server.main:app` via `starboard_server.main:create_app` factory.

## API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

!!! note
    API docs are disabled in production (`ENVIRONMENT=production`) to prevent schema leakage.

## API Endpoints

### Health Probes

```
GET  /health/live              # Liveness probe (process alive?)
GET  /health/ready             # Readiness probe (dependencies connected?)
```

### Chat API (`/api/chat`)

```
POST /api/chat/conversations                           # Create conversation
GET  /api/chat/conversations                           # List conversations
GET  /api/chat/conversations/{id}                      # Get conversation
HEAD /api/chat/conversations/{id}                      # Check exists
GET  /api/chat/conversations/{id}/history              # Get history
GET  /api/chat/conversations/{id}/export               # Export (md/json)
DELETE /api/chat/conversations/{id}                     # Delete one
DELETE /api/chat/conversations                          # Delete all (batch)
POST /api/chat/conversations/{id}/messages             # Send message
POST /api/chat/conversations/{id}/inject-input         # Inject during reasoning
POST /api/chat/conversations/{id}/respond-to-solicitation  # Answer agent question
GET  /api/chat/conversations/{id}/checkpoints          # Get checkpoints
GET  /api/chat/conversations/{id}/stream               # SSE event stream
GET  /api/chat/config                                  # Server configuration
GET  /api/chat/health                                  # Chat API health
GET  /api/chat/me                                      # Current user info
```

### Other APIs

```
POST /api/conversations/{id}/feedback                  # Submit feedback
GET  /api/feedback/agents/{name}/performance           # Agent metrics
POST /api/conversations/{id}/clarifications/{cid}/respond  # Clarification
GET  /api/data/{data_reference}                        # Cached query data
POST /api/visualization/render                         # Render chart
```

See [API Reference](../../docs/api/API_REFERENCE.md) for complete documentation.

## Domain Agents

The server hosts 8 domain-specialized agents plus an Intent Router:

| Agent | Domain | Purpose |
|-------|--------|---------|
| **Router** | Intent Classification | Routes requests to specialist agents |
| **Query** | SQL Optimization | Execution plans, query rewrites, partitioning |
| **Job** | Job Performance | Task analysis, Spark tuning, code quality |
| **UC** | Unity Catalog | Metadata, lineage, governance, schema drift |
| **Cluster** | Compute | Cluster sizing, health, utilization |
| **Analytics** | FinOps & Cost | Cost analysis, chargeback, budget forecasting |
| **Warehouse** | SQL Warehouses | Portfolio optimization, SLO, topology |
| **Discovery** | Workspace Health | Resource inventory, health scoring (4-phase) |
| **Diagnostic** | Troubleshooting | Root cause analysis, cross-domain debugging |

## Configuration

Environment variables (set in `.env` or environment):

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABRICKS_HOST` | Databricks workspace URL | Yes | -- |
| `DATABRICKS_TOKEN` | Databricks access token | Yes | -- |
| `LLM_API_KEY` | LLM provider API key | Yes | -- |
| `LLM_MODEL` | Model name | No | `databricks-claude-sonnet-4-5` |
| `LLM_BASE_URL` | Custom OpenAI-compatible endpoint | No | -- |
| `LOG_LEVEL` | Logging level | No | `INFO` |
| `DATABASE_URL` | State backend URL | No | SQLite |

See [Configuration Guide](../../docs/CONFIGURATION.md) for the complete reference.

## Architecture

```
starboard_server/
    main.py              # FastAPI app factory (create_app)
    api/                 # FastAPI routes and streaming
        chat/            # Conversation and message routes
    agents/              # Multi-agent system
        conversation/    # Conversation manager
        domain/          # Base domain agent
        routing/         # Intent router
        tools/           # Tool registry
    tools/               # Tool implementations
        domain/          # Pure business logic
        services/        # Orchestration layer
        adapters/        # I/O adapters (Databricks, etc.)
    prompts/             # Domain-specific system prompts
    infra/               # Config, logging, DI, observability
    services/            # Business services
    adapters/            # External service adapters (LLM, Databricks)
```

## Development

```bash
# Install with dev dependencies
uv pip install -e ".[dev,test]"

# Run tests
pytest

# Run with hot reload
uvicorn starboard_server.main:create_app --factory --reload --port 8000

# Lint and type check
make lint && make type-check
```

## Documentation

- [System Architecture](../../docs/architecture/SYSTEM_ARCHITECTURE.md) -- Full system design
- [API Reference](../../docs/api/API_REFERENCE.md) -- REST API specification
- [Tool Catalog](../../docs/tools/TOOL_CATALOG.md) -- All 45+ tools
- [Configuration Guide](../../docs/CONFIGURATION.md) -- Environment variables
- [Testing Guide](../../docs/TESTING.md) -- Testing strategies
