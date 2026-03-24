---
title: Quickstart
description: Get Starboard AI Agent running in under 5 minutes.
last_verified: 2026-03-24
status: current
---

# Quickstart

> Last verified: 2026-03-24

Get Starboard AI Agent running locally and execute your first analysis in under 5 minutes.

---

## Prerequisites

| Requirement | Version | Check Command |
|-------------|---------|---------------|
| Python | 3.12+ | `python --version` |
| Node.js | 18+ | `node --version` |
| uv (recommended) | Latest | `uv --version` |
| Databricks workspace | -- | Access token required |
| LLM API key | -- | OpenAI, Azure, or Databricks Model Serving |

---

## Step 1: Install

```bash
# Clone the repository
git clone https://github.com/starboard-ai/job-agent.git
cd job-agent

# Bootstrap the environment (creates .venv, installs all packages)
make setup
```

!!! tip
    `make setup` uses `uv` if available, falling back to `pip`. The full install takes 2-3 minutes.

**Verify installation:**

```bash
starboard --help
```

You should see the CLI help output with available commands and options.

---

## Step 2: Configure

```bash
# Copy the example environment file
cp examples/env.example .env
```

Edit `.env` with your credentials:

```bash
# Required: Databricks connection
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi_your_token_here
DATABRICKS_WAREHOUSE_ID=your_warehouse_id

# Required: LLM provider
LLM_API_KEY=sk-...

# Optional: Model selection (defaults to databricks-claude-sonnet-4-5)
LLM_MODEL=databricks-claude-sonnet-4-5
```

!!! note
    For the complete list of environment variables, see the [Configuration Guide](CONFIGURATION.md).

---

## Step 3: Start Development Servers

```bash
# Start both backend (port 8000) and frontend (port 3000)
make dev
```

Or start them individually:

```bash
# Backend only
make dev-server

# Frontend only (in a separate terminal)
make dev-frontend
```

**Verify the backend is running:**

```bash
curl http://localhost:8000/health/live
```

Expected response:

```json
{"status": "ok"}
```

To check full readiness (database, cache, dependencies):

```bash
curl http://localhost:8000/health/ready
```

Expected response:

```json
{"status": "ok", "checks": []}
```

!!! warning
    If `/health/ready` returns `503`, the server is running but one or more dependencies (database, cache) are not yet initialized. Check the server logs for details.

---

## Step 4: Run Your First Analysis

### Using the Web UI

1. Open **http://localhost:3000** in your browser
2. Click **New Conversation** in the sidebar
3. Type a question and press Enter:

```
Why is my nightly ETL job taking 3 hours? Job ID: 12345
```

4. Watch the agent reason in real-time -- you will see thinking steps, tool calls, and the final report stream in as they happen

### Using the CLI

```bash
# Optimize a SQL query
starboard "Optimize query with statement_id 01948a0b-1ebb-17a4-959c-70dde9c5e3fc"

# Analyze a Databricks job
starboard "Analyze job 12345 for performance issues"

# Run a workspace health assessment
starboard "Run a discovery assessment of my workspace"
```

### Using the REST API

```bash
# Create a conversation
CONV_ID=$(curl -s -X POST http://localhost:8000/api/chat/conversations \
  -H "Content-Type: application/json" \
  -d '{"user_id": "quickstart_user"}' | python -c "import sys,json; print(json.load(sys.stdin)['conversation_id'])")

# Send a message
curl -X POST "http://localhost:8000/api/chat/conversations/${CONV_ID}/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "Analyze job 12345"}'

# Stream events (SSE)
curl -N "http://localhost:8000/api/chat/conversations/${CONV_ID}/stream"
```

---

## Step 5: Verify Health Endpoints

Starboard exposes two health endpoints for monitoring:

| Endpoint | Purpose | Healthy Response |
|----------|---------|------------------|
| `GET /health/live` | Liveness probe -- is the process alive? | `{"status": "ok"}` |
| `GET /health/ready` | Readiness probe -- are dependencies connected? | `{"status": "ok", "checks": [...]}` |

```bash
# Liveness (always responds if server is up)
curl http://localhost:8000/health/live

# Readiness (checks database, cache connectivity)
curl http://localhost:8000/health/ready
```

---

## What Happens Behind the Scenes

When you send a message, Starboard follows this flow:

```
Your Message
    |
    v
Intent Router --> Classifies domain (query, job, uc, cluster, analytics, warehouse, discovery, diagnostic)
    |
    v
Domain Agent --> Reasons step-by-step, selects tools dynamically
    |
    v
Tools (45+) --> Calls Databricks APIs, gathers real data
    |
    v
Analysis --> Interprets results using domain expertise
    |
    v
Report --> Streams structured recommendations via SSE
```

The system has 9 domain agents (including the router), each specialized in a different area of Databricks optimization. The agent autonomously decides which tools to call and in what order based on the data it discovers.

| Agent | Domain |
|-------|--------|
| **Router** | Intent classification and routing |
| **Query** | SQL optimization and execution plans |
| **Job** | Job performance and Spark tuning |
| **UC** | Unity Catalog governance and metadata |
| **Cluster** | Cluster sizing and health |
| **Analytics** | FinOps cost analysis and budgeting |
| **Warehouse** | SQL warehouse portfolio optimization |
| **Discovery** | Workspace health assessment (4-phase) |
| **Diagnostic** | Cross-domain troubleshooting |

---

## Next Steps

- [Configuration Guide](CONFIGURATION.md) -- Complete environment variable reference
- [Web UI Guide](user-guide/web-ui.md) -- Learn the web interface
- [CLI Reference](user-guide/cli.md) -- Command-line usage and options
- [What is Starboard?](overview/what-is-starboard.md) -- Architecture overview
- [FAQ](guides/FAQ.md) -- Common questions answered

---

**Last Updated**: 2026-03-24
**Version**: 3.0
