---
title: CLI Reference
description: Complete command-line reference for the Starboard AI Agent.
last_verified: 2026-08-27
status: current
---

# CLI Reference

The `starboard` command is the primary way to run analyses. It has a **flag-based**
top-level interface (natural-language goals, discovery, chat) plus three
subcommands: `review`, `genie ask`, and `auth`.

---

## Installation

```bash
pip install starboard

# Verify
starboard --help
```

The default install is store-free (in-memory state, reference-file analytics
context). Opt in to a durable backend only if you need one, e.g.
`pip install 'starboard[sqlite]'` or `'starboard[postgres]'`.

---

## Authentication

Starboard delegates to the Databricks SDK credential chain ("auth by subtraction").
Use `starboard auth` for a guided login, or provide credentials via flags or
environment.

```bash
# Guided login (prefers the Databricks CLI; falls back to an in-process browser flow)
starboard auth login --host https://your-workspace.cloud.databricks.com --profile my-ws

# Show the resolved identity (host / auth_type / profile / user) — never prints a token
starboard auth status
starboard auth status --json
```

`starboard auth login` flags: `--host`, `--profile`.
`starboard auth status` flags: `--json`.

You can also authenticate inline or via environment variables (see below).

---

## Top-level flags

The top-level `starboard` command runs the multi-agent system against a
natural-language `--goal`, an interactive `--chat` session, or a `--discover`
assessment.

### Input

| Flag | Description |
|------|-------------|
| `--goal TEXT` | Natural-language description of what you want the agent to do. |
| `--input-file PATH` | File to load and pass to the agent (SQL, source code, logs). |

### Databricks configuration

| Flag | Description |
|------|-------------|
| `--databricks-host`, `--host` | Workspace URL (or set `DATABRICKS_HOST`). |
| `--databricks-token`, `--token` | Personal access token (or set `DATABRICKS_TOKEN`). |
| `--profile` | `~/.databrickscfg` profile name (or `DATABRICKS_CONFIG_PROFILE` / `STARBOARD_WORKSPACE`). |
| `--client-id` | OAuth client ID / service principal (or `DATABRICKS_CLIENT_ID`). |
| `--client-secret` | OAuth client secret (or `DATABRICKS_CLIENT_SECRET`). |
| `--auth-type` | Force an SDK auth strategy, e.g. `pat`, `databricks-cli`, `oauth-m2m`. |

### LLM configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--llm-model` | `databricks-claude-sonnet-4-5` | Model name (e.g. `gpt-4o`, a Model Serving endpoint). |
| `--llm-api-key` | env `LLM_API_KEY` | LLM API key. |
| `--llm-base-url` | — | Custom / Model Serving endpoint base URL. |
| `--llm-temperature` | `0.4` | Temperature (0.0–1.0). |
| `--llm-max-tokens` | `75000` | Token budget for the session. |

### Output & display

| Flag | Description |
|------|-------------|
| `--output-path PATH` | Directory to save JSON + Markdown reports. |
| `--plain` | Plain text output instead of Rich formatting. |
| `--quiet`, `-q` | Suppress progress output; only show final results. |
| `--json` | Emit a structured JSON envelope to stdout (implies `--quiet`). |
| `--no-color` | Disable color (also respects `NO_COLOR`). |

### Session management

| Flag | Description |
|------|-------------|
| `--session NAME` | Named session for multi-turn conversations; reuse the name to continue. |
| `--session-db PATH` | Session database path (default: `~/.starboard/sessions.db`). |
| `--chat` | Start an interactive multi-turn chat session. |

### Workspace discovery

| Flag | Default | Description |
|------|---------|-------------|
| `--discover` | — | Run a workspace health assessment via the discovery pipeline. |
| `--lookback-days {30,60,90}` | `30` | Discovery lookback window. |
| `--discovery-domains …` | all active | Space-separated domains to analyze. |
| `--data-only` | — | Skip LLM analysis; output raw data only. |
| `--no-cache` | — | Disable the discovery scan cache. |

### Agent options & logging

| Flag | Default | Description |
|------|---------|-------------|
| `--mode {online,offline,diagnostic}` | `online` | Analysis mode (see [Modes](#modes)). |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | `WARNING` | Logging level. |
| `--log-file PATH` | — | Write logs to a file instead of the console. |
| `--debug` | — | Enable debug logging to stderr. |
| `--config PATH` | — | Path to a YAML config file (see below). |

---

## Subcommands

### `starboard review` — Workload Review

Runs a ranked, evidence-cited review of your workspace's jobs, SQL, and warehouses
over **public `system.*` data only**.

```bash
starboard review [--domains jobs,sql,warehouse] [--workspace NAME | --profile NAME]
                 [--lookback-days N] [--validate] [--min-severity …] [--min-score …]
                 [--since snapshot.json] [--snapshot-out snapshot.json] [--json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--domains` | `jobs,sql,warehouse` | Comma-separated review domains. |
| `--workspace` / `--profile` | — | Workspace profile to review (aliases). |
| `--host` / `--token` | — | Inline Databricks credentials. |
| `--lookback-days` | `30` | Evidence lookback window. |
| `--max-parallelism` | `4` | Concurrent evidence queries. |
| `--no-cache` | — | Disable the discovery scan cache. |
| `--validate` | — | Gate findings through the bounded validator council (models from config). |
| `--min-severity {low,medium,high,critical}` | — | Suppress findings below this severity. |
| `--min-score FLOAT` | — | Suppress findings below this priority score. |
| `--since PATH` | — | Prior snapshot JSON; report the resolved-rate delta (read-only). |
| `--snapshot-out PATH` | — | Write a snapshot for a later `--since` (local file, never the workspace). |
| `--json` | — | Emit the JSON envelope instead of a table. |

#### Validator council configuration

`--validate` gates findings through a bounded multi-pass model council before surfacing them.
Configure which models the council uses via environment variables — model IDs resolve
dynamically via the Databricks model-serving catalog or AI gateway and are **never
hard-coded**:

| Env var | Default | Purpose |
|---------|---------|---------|
| `STARBOARD_REVIEW_COUNCIL_MODELS` | `databricks-claude-sonnet-4-5` | Comma-separated list of model IDs to vote across (ensemble). Any AI-gateway or model-serving catalog ID works. |
| `STARBOARD_REVIEW_COUNCIL_MAX_PASSES` | `2` | Maximum self-critique passes per finding (1–5). Bounds model spend. |
| `STARBOARD_REVIEW_COUNCIL_SEED` | `0` | Integer seed for reproducible results across runs. |

```bash
# Two-model ensemble using workspace-provisioned models (IDs from your AI gateway):
export STARBOARD_REVIEW_COUNCIL_MODELS="databricks-claude-opus-4-8m,databricks-claude-sonnet-4-6"
export STARBOARD_REVIEW_COUNCIL_MAX_PASSES=3
starboard review --validate --min-severity high
```

Spend is **bounded**: worst-case model calls = `max_passes × models × findings`.
When a model call fails, the affected finding is kept (fail-safe — an infra hiccup
never silently suppresses a real finding).

Cost-based findings are **list-price DBU estimates**, labelled as such. The review
is read-only: it never writes back to your workspace.

### `starboard genie ask` — natural language → SQL

```bash
starboard genie ask "which warehouses cost the most last month?" \
    [--workspace NAME | --profile NAME] [--warehouse-id ID] [--json]
```

| Flag | Description |
|------|-------------|
| `question` | The natural-language question (positional, required). |
| `--workspace` / `--profile` | Target workspace profile (aliases). |
| `--host` / `--token` | Inline Databricks credentials. |
| `--warehouse-id` | SQL warehouse id for query context. |
| `--json` | Emit the JSON envelope instead of formatted text. |

### `starboard auth` — login / status

See [Authentication](#authentication) above.

---

## Configuration priority

Settings resolve in this order (highest first):

1. CLI arguments (`--llm-model`, `--host`, …)
2. YAML config file (`--config`)
3. Environment variables (`LLM_MODEL`, `DATABRICKS_HOST`, …)
4. Built-in defaults

### YAML config file

```yaml
# starboard-config.yaml
databricks:
  host: "https://my-workspace.cloud.databricks.com"
  token: "dapi..."
  warehouse_id: "abc123def456"
  default_catalog: "main"
  default_schema: "default"

llm:
  model: "databricks-claude-sonnet-4-5"
  temperature: 0.4
  max_tokens: 75000
```

```bash
starboard --config starboard-config.yaml --goal "Analyze job 12345"
```

---

## Examples

### Query optimization

```bash
starboard --goal "Optimize query with statement_id 01ef-abc123"
starboard --input-file queries/slow_query.sql --goal "Optimize this SQL"
starboard --mode offline --input-file queries/complex_join.sql \
          --goal "Review this query for anti-patterns"
```

### Job analysis

```bash
starboard --goal "Analyze performance for job 12345"
starboard --goal "Why did job 67890 fail in its last run?"
starboard --mode diagnostic --goal "Job 12345 fails intermittently — find the root cause"
```

### Workload review & discovery

```bash
starboard review --domains jobs,sql,warehouse --lookback-days 60
starboard review --validate --min-severity high --json
starboard --discover --lookback-days 90 --discovery-domains jobs warehouse
starboard --discover --data-only
```

### Ask a question

```bash
starboard genie ask "what drove the cost increase last month?"
```

### Multi-turn sessions

```bash
starboard --goal "Analyze query 01ef-abc123" --session my-project
starboard --goal "Would liquid clustering help?" --session my-project
starboard --chat
```

---

## Saving results

```bash
starboard --goal "Analyze job 12345" --output-path ./reports/
# Writes ./reports/<timestamp>_<goal>.json  and  ./reports/<timestamp>_<goal>.md
```

For scripting, combine `--json` (structured envelope to stdout) with a saved report:

```bash
starboard --goal "Analyze job 12345" --json > result.json
```

---

## Modes

| Mode | Behavior |
|------|----------|
| `online` (default) | Full Databricks API access: live configs, EXPLAIN plans, system tables, metrics. |
| `offline` | Disables API-dependent tools. Still analyzes `--input-file` content and gives best-practice guidance. |
| `diagnostic` | Routes to the Diagnostic agent for cross-domain investigation. |

---

## Debugging

```bash
starboard --debug --goal "Analyze job 12345"                 # debug logs to stderr
starboard --log-level DEBUG --log-file starboard.log --goal "…"
```

---

## Exit codes

The top-level agent path returns `0` on success and a nonzero code on error. The
subcommands (`review`, `genie ask`) and the `python -m starboard_x.<cap>` middle
tier use the shared contract:

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Authentication error |
| `2` | Resource not found |
| `3` | API error |
| `4` | Argument error |

---

## Common issues

### "No Databricks auth resolved"

Provide one of: `--profile <name>`, `--host` + `--token`, `--client-id` +
`--client-secret`, or set `DATABRICKS_CONFIG_PROFILE` / `DATABRICKS_HOST` +
`DATABRICKS_TOKEN`. Or run `starboard auth login`.

### "LLM_API_KEY not set"

```bash
export LLM_API_KEY="<your-api-key>"
```

### Agent exceeds the token budget

Increase the budget or narrow the request:

```bash
starboard --llm-max-tokens 120000 --goal "..."
```

---

## See also

- [Quickstart](../QUICKSTART.md)
- [Quick Reference](../QUICK_REFERENCE.md)
- [Understanding Reports](understanding-reports.md)
- [Workflow: Workspace Discovery](workflows/workspace-discovery.md)
