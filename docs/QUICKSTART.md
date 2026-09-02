---
title: Quickstart
description: Install Starboard and run your first workspace analysis in minutes.
last_verified: 2026-08-27
status: current
---

# Quickstart

Install Starboard AI Agent and run your first Databricks analysis. Starboard runs
entirely from the command line (and from AI coding assistants via skills) — there is
no server to stand up and no database to provision. The default install is
**store-free**: state is in-memory and analytics context comes from curated
reference files, not an embedding/vector database.

---

## Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.12+ | `python --version` |
| Databricks workspace | — | A profile, host+token, or OAuth service principal |
| LLM access | — | An OpenAI-compatible key, or Databricks Model Serving |

You do **not** need Redis, Postgres, SQLite, or a vector database for the default
experience. Those are opt-in extras (see [Install options](#install-options)).

---

## Step 1: Install

```bash
pip install starboard
```

This installs the flagship experience: the `starboard` CLI, the middle-tier
`python -m starboard_x.<capability>` commands, and the optional `starboard-mcp`
server. Verify the CLI:

```bash
starboard --help
```

### Install options

| Command | What you get |
|---------|--------------|
| `pip install starboard` | Full experience: CLI, agents, `starboard_x`, optional MCP server. Pulls **no** store/vector drivers. |
| `pip install starboard-core` | Pure kernel + the `starboard_x` middle-tier helpers (`python -m starboard_x.<cap>`). Lightweight, SDK-free scoring. |
| `pip install starboard-skills` | Canonical skills tree + the `starboard-helper` script (for Claude Code / Cursor). |

The Redis cache backend is an **opt-in extra**: `pip install 'starboard[redis]'`.
If a backend needs a driver you have not installed, Starboard raises an actionable
`pip install …` error telling you exactly which extra to add.

---

## Step 2: Authenticate

Starboard uses "auth by subtraction" — it delegates to the standard Databricks SDK
credential chain. Provide credentials any one of these ways:

```bash
# Option A — a ~/.databrickscfg profile (recommended)
starboard auth login --host https://your-workspace.cloud.databricks.com --profile my-ws
starboard auth status          # verify the resolved identity (no secrets printed)

# Option B — environment variables
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."

# Option C — an OAuth service principal
export DATABRICKS_CLIENT_ID="..."
export DATABRICKS_CLIENT_SECRET="..."
```

Then set an LLM key (any OpenAI-compatible provider, or point at Databricks Model
Serving):

```bash
export LLM_API_KEY="<your-api-key>"
# optional overrides:
export LLM_MODEL="databricks-claude-sonnet-4-5"   # default model
export LLM_BASE_URL="https://<workspace>/serving-endpoints"  # for Model Serving
```

Starboard auto-loads a `.env` file from the current directory, so you can put these
in `.env` instead of exporting them each session. See the
[CLI reference](user-guide/cli.md) for every flag and environment variable.

---

## Step 3: Run your first analysis

Starboard gives you three high-signal entry points plus a general natural-language
mode.

### Workload Review — ranked, evidence-cited findings

Reviews your workspace's jobs, SQL, and warehouses over **public `system.*` data
only** and prints a ranked, evidence-cited set of findings:

```bash
starboard review                          # default domains: jobs,sql,warehouse
starboard review --domains warehouse,sql  # narrow the scope
starboard review --json                   # machine-readable envelope
```

Every finding cites the query pack and row that triggered it. Cost-based findings
are **list-price DBU estimates**, labelled as such.

### Discover your whole workspace

```bash
starboard --discover                       # 30-day workspace health assessment
starboard --discover --lookback-days 90    # 30 | 60 | 90
starboard --discover --data-only           # skip LLM analysis, raw data only
```

### General natural-language goals

```bash
# Optimize a query by statement ID
starboard --goal "Optimize query with statement_id 01ef-abc123-def456"

# Investigate a job
starboard --goal "Why did job 12345 fail in its last run?"

# Interactive multi-turn chat
starboard --chat
```

Use `--output-path ./reports/` to save JSON + Markdown reports, and `--json` for a
structured envelope suitable for scripting.

---

## Using Starboard from Claude Code / Cursor (skills)

Starboard ships a set of **skills** that teach AI coding assistants how to run these
analyses for you. Install the skills package and point your assistant at the skills
tree:

```bash
pip install starboard-skills
```

See [Skills](SKILLS.md) for the full catalog and setup, and
[Claude Code Integration](CLAUDE_CODE_INTEGRATION.md) for the optional MCP server.

---

## Using Starboard from a notebook

The `examples/` notebooks run Starboard directly inside Databricks. They install the
packages from source and drive the agent via the in-package SDK
(`from starboard.sdk import StarboardClient`). Start with
`examples/Starboard AI Agent.ipynb` for the general flow and
`examples/Starboard AI Agent - Workspace Discovery.ipynb` for discovery.

---

## What happens behind the scenes

```
Your request
    │
    ▼
Intent Router  ──▶ classifies the domain (query, job, uc, cluster,
    │                 analytics, warehouse, discovery, diagnostic)
    ▼
Domain agent   ──▶ reasons step-by-step, selects tools dynamically
    │
    ▼
Tools          ──▶ call Databricks APIs / public system tables
    │
    ▼
Report         ──▶ findings, evidence, and recommendations
```

`starboard review` and `--discover` are deterministic, public-data paths that do
not require the full agent loop. `--goal` and `--chat` run the
multi-agent conversation. There are **8 domain agents** plus the Intent Router.

| Agent | Domain |
|-------|--------|
| Router | Intent classification and routing |
| Query | SQL optimization and execution plans |
| Job | Job performance and Spark tuning |
| UC | Unity Catalog governance and metadata |
| Cluster | Cluster sizing and health |
| Analytics | Cost analysis (list-price DBU estimates) |
| Warehouse | SQL warehouse portfolio optimization |
| Discovery | Workspace health assessment |
| Diagnostic | Cross-domain troubleshooting |

---

## Next steps

- [CLI Reference](user-guide/cli.md) — every command, flag, and environment variable
- [Skills](SKILLS.md) — run Starboard from Claude Code / Cursor
- [Workflow: Workspace Discovery](user-guide/workflows/workspace-discovery.md)
- [What is Starboard?](overview/what-is-starboard.md) — architecture overview
- [FAQ](guides/FAQ.md) — common questions answered
