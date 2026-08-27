---
title: Getting Started
description: Install Starboard, authenticate, and run your first Databricks analysis.
last_verified: 2026-08-27
status: current
---

# Getting Started with Starboard AI Agent

This guide walks a **user** from a clean machine to a first successful analysis. If you
want to build or contribute to Starboard itself, see the Contributing guide instead.

> **In a hurry?** The [Quickstart](../QUICKSTART.md) is the 5-minute version. This guide
> is the slightly longer, guided walkthrough.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Install](#install)
3. [Authenticate](#authenticate)
4. [Run your first analysis](#run-your-first-analysis)
5. [Use Starboard from Claude Code / Cursor](#use-starboard-from-claude-code-cursor)
6. [Use Starboard from a notebook](#use-starboard-from-a-notebook)
7. [Next steps](#next-steps)

---

## Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.12+ | `python --version` |
| Databricks workspace | — | A profile, host + token, or OAuth service principal |
| LLM access | — | An OpenAI-compatible key, or Databricks Model Serving |

You do **not** need Redis, Postgres, SQLite, or a vector database for the default
experience. Those are opt-in extras (see [Install](#install)).

---

## Install

```bash
pip install starboard
```

This installs the flagship experience: the `starboard` CLI, the middle-tier
`python -m starboard_x.<capability>` commands, and the optional `starboard-mcp` server.
Verify:

```bash
starboard --help
```

### Install options

| Command | What you get |
|---------|--------------|
| `pip install starboard` | Full experience: CLI, agents, `starboard_x`, optional MCP server. Pulls **no** store/vector drivers. |
| `pip install starboard-core` | Pure kernel + the `starboard_x` middle-tier helpers (`python -m starboard_x.<cap>`). Lightweight. |
| `pip install starboard-skills` | Canonical skills tree + `starboard-helper` (for Claude Code / Cursor). |

Store and vector drivers are **opt-in extras**, only needed if you switch away from the
defaults, e.g. `pip install 'starboard[sqlite]'`, `'starboard[postgres]'`,
`'starboard[vectorsearch]'`, or `'starboard-core[discovery]'`. If a backend needs a
driver you have not installed, Starboard raises an actionable `pip install …` error
telling you exactly which extra to add.

---

## Authenticate

Starboard uses **"auth by subtraction"** — it delegates to the standard Databricks SDK
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
export LLM_MODEL="databricks-claude-sonnet-4-5"          # default model
export LLM_BASE_URL="https://<workspace>/serving-endpoints"  # for Model Serving
```

Starboard auto-loads a `.env` file from the current directory, so you can put these in
`.env` instead of exporting them each session.

---

## Run your first analysis

Starboard gives you three high-signal entry points plus a general natural-language mode.

### Workload Review — ranked, evidence-cited findings

Reviews your workspace's jobs, SQL, and warehouses over **public `system.*` data only**
and prints a ranked, evidence-cited set of findings:

```bash
starboard review                          # default domains: jobs,sql,warehouse
starboard review --domains warehouse,sql  # narrow the scope
starboard review --json                   # machine-readable envelope
```

Every finding cites the query pack and row that triggered it. Cost-based findings are
**list-price DBU estimates**, labelled as such.

### Ask a question in natural language (NL → SQL)

```bash
starboard genie ask "which warehouses cost the most last month?"
```

### Discover your whole workspace

```bash
starboard --discover                      # 30-day workspace health assessment
starboard --discover --lookback-days 90   # 30 | 60 | 90
starboard --discover --data-only          # skip LLM analysis, raw data only
```

### General natural-language goals

```bash
starboard --goal "Optimize query with statement_id 01ef-abc123-def456"
starboard --goal "Why did job 12345 fail in its last run?"
starboard --chat                          # interactive multi-turn chat
```

Use `--output-path ./reports/` to save JSON + Markdown reports, and `--json` for a
structured envelope suitable for scripting. Modes: `--mode online` (default) ·
`offline` (no API calls) · `diagnostic` (cross-domain troubleshooting).

---

## Use Starboard from Claude Code / Cursor

Starboard ships a set of **skills** that teach AI coding assistants how to run these
analyses for you:

```bash
pip install starboard-skills
```

See [Skills](../SKILLS.md) for the full catalog and setup.

---

## Use Starboard from a notebook

The `examples/` notebooks run Starboard directly inside Databricks. They install the
packages and drive the agent via the in-package SDK
(`from starboard.sdk import StarboardClient`). Start with
`examples/Starboard AI Agent.ipynb` for the general flow and
`examples/Starboard AI Agent - Workspace Discovery.ipynb` for discovery.

---

## Next steps

- [CLI Reference](../user-guide/cli.md) — every command, flag, and environment variable
- [Quick Reference](../QUICK_REFERENCE.md) — one-page cheat sheet
- [Common Tasks](./COMMON_TASKS.md) — step-by-step recipes
- [Understanding Reports](../user-guide/understanding-reports.md) — read the findings
- [What is Starboard?](../overview/what-is-starboard.md) — architecture overview
- [FAQ](./FAQ.md) — common questions answered

---

## Common issues

### `No Databricks auth resolved`

Provide one of: `--profile <name>`, `--host` + `--token`, `--client-id` +
`--client-secret`, or set `DATABRICKS_CONFIG_PROFILE` / `DATABRICKS_HOST` +
`DATABRICKS_TOKEN`. Or run `starboard auth login`.

### `LLM_API_KEY not set`

```bash
export LLM_API_KEY="<your-api-key>"
```

### Agent exceeds the token budget

```bash
starboard --llm-max-tokens 120000 --goal "..."
```

See [Troubleshooting](../user-guide/troubleshooting.md) for more.
