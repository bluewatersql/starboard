# CLI Reference

The Starboard CLI provides direct command-line access to the multi-agent conversation
system. Each invocation maps to a single conversation turn, making it ideal for
scripting, CI/CD pipelines, and terminal-first workflows.

---

## Installation

The CLI is installed as part of the monorepo setup:

```bash
# Full setup (recommended)
make setup

# Or install manually with uv
uv sync --all-packages

# Verify installation
starboard --help
```

The `starboard` command becomes available in your virtual environment after
installation.

---

## Prerequisites

Before using the CLI, configure your environment:

```bash
# Copy the example environment file
cp examples/env.example .env

# Required: Databricks credentials
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."

# Required: LLM provider
export LLM_API_KEY="<your-api-key>"

# Optional: Override defaults
export LLM_MODEL="databricks-claude-sonnet-4-5"   # Default model
export AGENT_MAX_TOKENS="120000"                   # Token budget
export AGENT_TEMPERATURE="0.3"                     # Response determinism
export AGENT_MAX_STEPS="20"                        # Max reasoning steps
```

!!! tip "Use a .env file"
    The CLI loads `.env` automatically from the project root, so you do not need
    to export variables manually every session.

---

## Basic Usage

The primary interface is the `--goal` flag, which accepts a natural-language request:

```bash
starboard --goal "Analyze job performance for job 12345"
```

The agent system automatically routes your request to the appropriate domain
specialist, runs its analysis, and prints the results.

---

## Command Reference

### Core Arguments

| Flag | Type | Description |
|------|------|-------------|
| `--goal` | string | Natural-language description of what you want the agent to do. |
| `--config` | path | Path to a YAML configuration file for broader settings. |
| `--mode` | choice | Optimization mode: `online` (comprehensive, default), `offline` (no API calls), `diagnostic` (focused troubleshooting). |

### Databricks Parameters

| Flag | Type | Description |
|------|------|-------------|
| `--databricks-host` | string | Databricks workspace URL (overrides `DATABRICKS_HOST`). |
| `--databricks-token` | string | Databricks personal access token (overrides `DATABRICKS_TOKEN`). |

### LLM Parameters

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--llm-model` | string | env default | Model name (e.g., `gpt-4o`, `claude-3-5-sonnet`). |
| `--llm-api-key` | string | env default | LLM API key (overrides `LLM_API_KEY`). |
| `--llm-base-url` | string | -- | Custom LLM API endpoint URL. |
| `--llm-temperature` | float | 0.4 | Temperature (0.0--1.0). Lower values are more deterministic. |
| `--llm-max-tokens` | int | 120000 | Maximum token budget for the session. |

### Input / Output

| Flag | Type | Description |
|------|------|-------------|
| `--input-file` | path | File to load and pass to the agent (SQL, Python, logs, etc.). |
| `--output-path` | path | Directory to save JSON and Markdown reports. |

### Display Options

| Flag | Description |
|------|-------------|
| `--plain` | Use plain text output instead of Rich formatting. |
| `--quiet`, `-q` | Suppress progress output; only show final results. |

### Logging Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--log-level` | choice | `ERROR` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `--log-file` | path | -- | Write logs to a file instead of the console. |
| `--debug` | flag | -- | Enable debug logging to stderr. |

### Discovery Mode

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--discover` | flag | -- | Run workspace discovery and health assessment. |
| `--lookback-days` | choice | 30 | Discovery lookback period: `30`, `60`, or `90` days. |
| `--discovery-domains` | list | all active | Specific domains to analyze (space-separated). |
| `--data-only` | flag | -- | Skip LLM analysis; output raw data only. |

---

## Configuration Priority

Settings are resolved in the following order (highest priority first):

1. **CLI arguments** (`--llm-model`, `--databricks-host`, etc.)
2. **YAML config file** (passed via `--config`)
3. **Environment variables** (`LLM_MODEL`, `DATABRICKS_HOST`, etc.)
4. **Built-in defaults**

### YAML Configuration File

You can define persistent settings in a YAML file:

```yaml
# starboard-config.yaml
databricks:
  host: "https://my-workspace.cloud.databricks.com"
  token: "dapi..."
  warehouse_id: "abc123def456"
  default_catalog: "main"
  default_schema: "default"

llm:
  model: "gpt-4o"
  temperature: 0.3
  max_tokens: 120000
```

Then reference it:

```bash
starboard --config starboard-config.yaml --goal "Analyze job 12345"
```

---

## Examples

### Query Optimization

```bash
# Analyze a SQL query by statement ID
starboard --goal "Optimize query with statement ID 01ef-abc123"

# Analyze raw SQL
starboard --goal "Optimize this query: SELECT * FROM users WHERE created_at > '2024-01-01'"

# Analyze SQL from a file
starboard --input-file queries/slow_query.sql \
          --goal "Optimize this SQL query and suggest index improvements"

# Offline analysis (no Databricks API calls)
starboard --mode offline \
          --input-file queries/complex_join.sql \
          --goal "Review this query for anti-patterns"
```

### Job Analysis

```bash
# Analyze a specific job
starboard --goal "Analyze performance for job 12345 and suggest optimizations"

# Investigate a job failure
starboard --goal "Why did job 67890 fail in its last run?"

# Analyze a specific run
starboard --goal "Analyze run 99999 of job 12345 and identify the bottleneck"

# Review job source code
starboard --goal "Review the source code for job 12345 and identify anti-patterns"
```

### Unity Catalog / Table Analysis

```bash
# Inspect table metadata
starboard --goal "Show schema and statistics for table sales.customer_orders"

# Trace table lineage
starboard --goal "What is the lineage for table analytics.daily_metrics?"

# Check governance policies
starboard --goal "Audit access policies for catalog main, schema finance"

# Analyze storage optimization
starboard --goal "Recommend storage optimizations for table events.raw_clicks"
```

### Cluster Analysis

```bash
# Review cluster configuration
starboard --goal "Analyze cluster config for cluster-id abc-123"

# Check cluster health
starboard --goal "What is the health status of cluster abc-123?"

# Review cluster fleet
starboard --goal "List all active clusters and identify underutilized ones"
```

### Cost Analysis (FinOps)

```bash
# Analyze cost trends
starboard --goal "Analyze Databricks cost trends for the last 30 days"

# Identify top cost drivers
starboard --goal "Which warehouses consumed the most credits last month?"

# Generate chargeback report
starboard --goal "Generate a chargeback report for warehouse wh-prod-analytics"
```

### SQL Warehouse Analysis

```bash
# Portfolio overview
starboard --goal "Show me the SQL warehouse portfolio with health scores"

# Deep-dive into a warehouse
starboard --goal "Analyze warehouse wh-prod-main and check SLO compliance"

# Cross-warehouse topology
starboard --goal "Analyze topology across all warehouses for consolidation opportunities"
```

### Workspace Discovery

```bash
# Full workspace health assessment
starboard --discover

# Scoped discovery (last 90 days, specific domains)
starboard --discover \
          --lookback-days 90 \
          --discovery-domains jobs warehouses

# Data-only discovery (skip LLM analysis)
starboard --discover --data-only
```

### Troubleshooting / Diagnostics

```bash
# Debug a failing job
starboard --mode diagnostic \
          --goal "Job 12345 has been failing intermittently for the past week"

# Investigate performance regression
starboard --mode diagnostic \
          --goal "Query q_abc123 was fast last week but now takes 10 minutes"
```

---

## Saving Results

Use `--output-path` to save the agent's report to disk:

```bash
starboard --goal "Analyze job 12345" --output-path ./reports/

# This creates:
# ./reports/starboard-report-2026-03-01.json   (structured data)
# ./reports/starboard-report-2026-03-01.md     (human-readable report)
```

!!! tip "Combine with --quiet for scripting"
    Use `--quiet` to suppress progress output and only get the final report, which
    is useful in CI/CD pipelines:
    ```bash
    starboard --goal "Analyze job 12345" \
              --output-path ./reports/ \
              --quiet
    ```

---

## Understanding CLI Output

During execution, the CLI displays real-time progress using Rich formatting:

1. **Thinking events** -- The agent's reasoning steps as it plans its approach.
2. **Tool calls** -- Each tool invocation (e.g., "Resolving job...",
   "Analyzing history...") with start and completion indicators.
3. **Step summaries** -- Brief summaries after each reasoning step.
4. **Final report** -- The complete analysis with findings, recommendations, and
   suggested next steps.

Use `--plain` if your terminal does not support Rich formatting, or `--quiet` to
skip everything except the final report.

---

## Modes

### Online Mode (default)

```bash
starboard --mode online --goal "..."
```

The agent has full access to the Databricks API. It can fetch live job configurations,
run EXPLAIN plans, query system tables, and retrieve cluster metrics. This is the most
comprehensive mode.

### Offline Mode

```bash
starboard --mode offline --goal "..."
```

All tools that require Databricks API calls are disabled. The agent can still:

- Analyze code provided via `--input-file`.
- Perform static code quality analysis.
- Provide general best-practice recommendations.

This mode is useful when you do not have network access to Databricks or want to
avoid making API calls.

### Diagnostic Mode

```bash
starboard --mode diagnostic --goal "..."
```

Routes directly to the Diagnostic agent, which has unrestricted access to all tools
across every domain. Use this mode when you need cross-cutting investigation that
spans multiple domains (e.g., a job failure that involves cluster issues and query
performance).

---

## Debugging the CLI

```bash
# Enable debug logging to stderr
starboard --debug --goal "Analyze job 12345"

# Write detailed logs to a file
starboard --log-level DEBUG \
          --log-file starboard-debug.log \
          --goal "Analyze job 12345"

# Then inspect the log
tail -f starboard-debug.log
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success -- analysis completed. |
| `1` | Error -- check stderr or log file for details. |

---

## Common Issues

### "No config file found"

This warning is informational. The CLI works without a config file by using
environment variables. To silence it, set the required environment variables or
create a config file.

### "Databricks connection failed"

```bash
# Verify your credentials
databricks workspace list

# Check that DATABRICKS_HOST and DATABRICKS_TOKEN are set
echo $DATABRICKS_HOST
echo $DATABRICKS_TOKEN

# Use offline mode as a fallback
starboard --mode offline --goal "..."
```

### "LLM API key not set"

Ensure one of the following is configured:

```bash
export LLM_API_KEY="<your-api-key>"
# or
export OPENAI_API_KEY="<your-api-key>"
```

### Agent times out or exceeds token budget

Reduce the scope of your request or increase the budget:

```bash
starboard --llm-max-tokens 200000 --goal "..."
```

For very large workloads, consider breaking the analysis into smaller, focused
questions.
