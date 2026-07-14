# starboard-skills

Lightweight Claude skill files and Databricks data-fetching helper scripts for Starboard.

## Overview

`starboard-skills` provides two artifacts:

1. **Claude skill files** (`skills/starboard/`) — Markdown skill definitions that instruct Claude how to analyze Databricks workloads. Skills operate in dual-mode: using full MCP agent orchestration when available, or lightweight helper scripts when not.

2. **Helper scripts** (`starboard_skills/helpers/`) — Thin Databricks SDK wrappers that fetch structured JSON data. No LLM calls, no agents — pure data fetching for Claude to reason over.

## Install

```bash
pip install starboard-skills
```

Dependencies: `databricks-sdk`, `rich`, `python-dotenv` only. No FastAPI, no LLM libraries.

## Usage

### starboard-helper CLI

```bash
# Jobs
starboard-helper job fetch --job-id 123
starboard-helper job runs --job-id 123 --limit 10
starboard-helper job list --limit 25

# SQL Queries
starboard-helper query history --warehouse-id abc123 --limit 25
starboard-helper query slow --min-duration-ms 10000
starboard-helper query fetch --query-id <QUERY_ID>

# SQL Warehouses
starboard-helper warehouse list
starboard-helper warehouse fetch --warehouse-id abc123
starboard-helper warehouse metrics --warehouse-id abc123

# Unity Catalog
starboard-helper uc catalogs
starboard-helper uc schemas --catalog main
starboard-helper uc tables --catalog main --schema default
starboard-helper uc table --full-name main.default.my_table
starboard-helper uc lineage --full-name main.default.my_table

# Clusters
starboard-helper cluster list
starboard-helper cluster fetch --cluster-id 1234-567890-abc
starboard-helper cluster events --cluster-id 1234-567890-abc --limit 50

# FinOps (requires account-level access)
starboard-helper finops usage --start-date 2024-01-01 --end-date 2024-01-31
starboard-helper finops budgets

# Diagnostics
starboard-helper diagnostic run-state --run-id 456
starboard-helper diagnostic cluster-log --cluster-id 1234-567890-abc
starboard-helper diagnostic node-types
starboard-helper diagnostic workspace
```

### Authentication

Set standard Databricks environment variables:

```bash
export DATABRICKS_HOST=https://<workspace>.azuredatabricks.net
export DATABRICKS_TOKEN=<personal-access-token>

# For FinOps (account-level):
export DATABRICKS_ACCOUNT_ID=<account-id>
```

Or use a `.env` file — `python-dotenv` is included.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Authentication error |
| 2 | Resource not found |
| 3 | API error |
| 4 | Argument error |

## Dual-Mode Skills

Each skill file in `skills/starboard/<domain>/skill.md` instructs Claude to:

1. **Check for MCP tools**: If `mcp__starboard__*` tools are available (i.e., `starboard-mcp` server is running), use them for full agent orchestration with multi-step analysis.

2. **Fall back to helpers**: If MCP tools are not available, call `starboard-helper <domain> <command>` via Bash, receive structured JSON, and apply analytical reasoning using the skill's embedded prompts.

This makes the skills useful both for users running the full Starboard server and for users who only want lightweight CLI-based analysis.

## Skills included

| Skill | Description |
|-------|-------------|
| `starboard-job` | Job configuration and run history analysis |
| `starboard-query` | SQL query performance and failure analysis |
| `starboard-warehouse` | SQL warehouse sizing and cost analysis |
| `starboard-uc` | Unity Catalog metadata and governance analysis |
| `starboard-cluster` | Cluster configuration and event analysis |
| `starboard-finops` | Cost and usage analysis |
| `starboard-diagnostic` | Workspace and run-level diagnostics |
| `starboard-analyze` | Comprehensive cross-domain analysis |
| `starboard-discovery` | Workspace resource discovery and inventory |
