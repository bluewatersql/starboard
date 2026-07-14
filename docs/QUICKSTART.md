---
title: Quickstart
description: Get Starboard AI Agent running in under 5 minutes.
last_verified: 2026-07-12
status: current
---

# Quickstart

> Last verified: 2026-07-12

Get Starboard AI Agent running locally and execute your first analysis in under 5 minutes.

---

## Prerequisites

| Requirement | Version | Check Command |
|-------------|---------|---------------|
| Python | 3.12+ | `python --version` |
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
LLM_API_KEY=<your-api-key>

# Optional: Model selection (defaults to databricks-claude-sonnet-4-5)
LLM_MODEL=databricks-claude-sonnet-4-5
```

!!! note
    For the complete list of environment variables, see the [Configuration Guide](CONFIGURATION.md).

---

## Step 3: Run Your First Analysis

### Using the CLI

```bash
# Optimize a SQL query
starboard --goal "Optimize query with statement_id 01948a0b-1ebb-17a4-959c-70dde9c5e3fc"

# Analyze a Databricks job
starboard --goal "Analyze job 12345 for performance issues"

# Run a workspace health assessment
starboard --goal "Run a discovery assessment of my workspace"

# Interactive multi-turn session
starboard --chat
```

### Using the MCP Server (Claude Code / Cursor)

```bash
# Install the package
pip install starboard

# Run the interactive setup wizard
./scripts/setup-mcp.sh
```

Then restart your IDE to pick up the new MCP configuration. See [Claude Code Integration Guide](CLAUDE_CODE_INTEGRATION.md) for full details.

---

## What Happens Behind the Scenes

When you send a goal, Starboard follows this flow:

```
Your Goal
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
Report --> Structured recommendations output
```

The system has 9 domain agents (including the router), each specialized in a different area of Databricks optimization.

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
- [CLI Reference](user-guide/cli.md) -- Command-line usage and options
- [Claude Code Integration](CLAUDE_CODE_INTEGRATION.md) -- MCP server setup
- [What is Starboard?](overview/what-is-starboard.md) -- Architecture overview
- [FAQ](guides/FAQ.md) -- Common questions answered

---

**Last Updated**: 2026-07-12
**Version**: 4.0
