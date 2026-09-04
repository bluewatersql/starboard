---
title: CLI Reference
description: Complete command, flag, and configuration reference for the Starboard CLI.
---

# CLI Reference

The `starboard` command has a **flag-based** top-level interface for natural-language goals,
workspace discovery, and interactive chat, plus two subcommands: `review` and `auth`.

```bash
pip install starboard
starboard --help
```

The default install is store-free: `database_backend="memory"` (the only option) and analytics
context comes from curated reference files. The Redis cache backend is opt-in:
`pip install 'starboard[redis]'`.

---

## `starboard auth`

```bash
# Guided login — writes a profile to ~/.databrickscfg
starboard auth login --host https://your-workspace.cloud.databricks.com --profile my-ws

# Show the resolved identity (host / auth_type / profile / user) — never prints a token
starboard auth status
starboard auth status --json
```

| Flag | Description |
|------|-------------|
| `--host TEXT` | Workspace URL. |
| `--profile TEXT` | Profile name to write/use in `~/.databrickscfg`. |

`auth status` accepts `--json`.

---

## Top-level flags

### Input

| Flag | Description |
|------|-------------|
| `--goal TEXT` | Natural-language description of what you want the agent to do. |
| `--chat` | Start an interactive multi-turn chat session. |
| `--input-file PATH` | File to load and pass to the agent (SQL, source code, logs). |

### Workspace discovery

| Flag | Default | Description |
|------|---------|-------------|
| `--discover` | — | Run a workspace health assessment via the discovery pipeline. |
| `--lookback-days {30,60,90}` | `30` | Discovery lookback window. |
| `--discovery-domains …` | all active | Space-separated domains to analyze. |
| `--data-only` | — | Skip LLM analysis; output raw data only. |
| `--no-cache` | — | Disable the discovery scan cache. |

### Databricks credentials

| Flag | Env var | Description |
|------|---------|-------------|
| `--host`, `--databricks-host` | `DATABRICKS_HOST` | Workspace URL. |
| `--token`, `--databricks-token` | `DATABRICKS_TOKEN` | Personal access token. |
| `--profile` | `DATABRICKS_CONFIG_PROFILE` / `STARBOARD_WORKSPACE` | `~/.databrickscfg` profile name. |
| `--client-id` | `DATABRICKS_CLIENT_ID` | OAuth service-principal client ID. |
| `--client-secret` | `DATABRICKS_CLIENT_SECRET` | OAuth service-principal client secret. |
| `--auth-type` | — | Force an SDK auth strategy, e.g. `pat`, `databricks-cli`, `oauth-m2m`. |

### LLM configuration

| Flag | Default | Env var | Description |
|------|---------|---------|-------------|
| `--llm-model` | `databricks-claude-sonnet-4-5` | `LLM_MODEL` | Model name (or a Model Serving endpoint). |
| `--llm-api-key` | — | `LLM_API_KEY` | LLM API key. |
| `--llm-base-url` | — | `LLM_BASE_URL` | Custom / Model Serving endpoint base URL. |
| `--llm-temperature` | `0.4` | `LLM_TEMPERATURE` | Temperature (0.0–1.0). |
| `--llm-max-tokens` | `75000` | `LLM_MAX_TOKENS` | Token budget for the session. |

### Output and display

| Flag | Description |
|------|-------------|
| `--output-path PATH` | Directory to write JSON + Markdown reports. |
| `--json` | Emit a structured JSON envelope to stdout (implies `--quiet`). |
| `--plain` | Plain text output instead of Rich formatting. |
| `--quiet`, `-q` | Suppress progress output; only show final results. |
| `--no-color` | Disable color (also respects `NO_COLOR`). |

### Session management

| Flag | Default | Description |
|------|---------|-------------|
| `--session NAME` | — | Named session for multi-turn conversations; reuse the name to continue. |
| `--session-db PATH` | `~/.starboard/sessions.db` | Session file path (JSON-file `SessionManager`). |

### Agent options and logging

| Flag | Default | Description |
|------|---------|-------------|
| `--mode {online,offline,diagnostic}` | `online` | Analysis mode (see [Modes](#modes)). |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | `WARNING` | Logging level. |
| `--log-file PATH` | — | Write logs to a file. |
| `--debug` | — | Enable debug logging to stderr. |
| `--config PATH` | — | Path to a YAML config file (see [Config file](#yaml-config-file)). |

---

## `starboard review`

Ranked, evidence-cited review of your workspace's jobs, SQL, and warehouses over
**public `system.*` data only**. Read-only — never writes back to your workspace.
Cost findings are **list-price DBU estimates**, labelled as such.

```bash
starboard review [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--domains TEXT` | `jobs,sql,warehouse` | Comma-separated review domains. |
| `--workspace` / `--profile` | — | Workspace profile to review (aliases). |
| `--host` / `--token` | — | Inline Databricks credentials. |
| `--lookback-days INT` | `30` | Evidence lookback window. |
| `--max-parallelism INT` | `4` | Concurrent evidence queries. |
| `--no-cache` | — | Disable the discovery scan cache. |
| `--min-severity {low,medium,high,critical}` | — | Suppress findings below this severity. |
| `--min-score FLOAT` | — | Suppress findings below this priority score. |
| `--since PATH` | — | Prior snapshot JSON; report the resolved-rate delta (read-only). |
| `--snapshot-out PATH` | — | Write a snapshot for a later `--since`. |
| `--output-path PATH` | — | Directory to write JSON + Markdown reports. |
| `--json` | — | Emit the JSON envelope instead of a findings table. |

---

## Modes

| Mode | Behavior |
|------|----------|
| `online` (default) | Full Databricks API access: live configs, EXPLAIN plans, system tables, metrics. |
| `offline` | Disables API-dependent tools. Useful with `--input-file` for static analysis. |
| `diagnostic` | Routes to the Diagnostic agent for cross-domain investigation. |

---

## Examples

### Workload review

```bash
starboard review                                          # default: jobs,sql,warehouse
starboard review --domains warehouse,sql --lookback-days 60
starboard review --min-severity high --json
```

### Workspace discovery

```bash
starboard --discover
starboard --discover --lookback-days 90 --discovery-domains jobs warehouse
starboard --discover --data-only
```

### Goal-based analysis

```bash
starboard --goal "Optimize query with statement_id 01ef-abc123"
starboard --goal "Why did job 12345 fail in its last run?"
starboard --input-file queries/slow.sql --goal "Review this query for anti-patterns"
starboard --mode diagnostic --goal "Job 12345 fails intermittently — find the root cause"
```

### Sessions and output

```bash
starboard --goal "Analyze query 01ef-abc123" --session my-project
starboard --goal "Would liquid clustering help?" --session my-project   # continues the session
starboard --goal "Analyze job 12345" --output-path ./reports/
starboard --goal "Analyze job 12345" --json > result.json
starboard --chat
```

### Middle-tier (`python -m starboard_x.<cap>`)

Lightweight per-capability commands available after `pip install starboard-core`:

```bash
python -m starboard_x.review score --rows rows.json --domains jobs,sql,warehouse
python -m starboard_x.discovery --help
```

All emit the shared JSON envelope (`{ok, domain, command, data|error, meta}`).

---

## Saving results

`--output-path DIR` writes two files per run:
```
DIR/<timestamp>_<goal>.json
DIR/<timestamp>_<goal>.md
```

For scripting, `--json` emits the structured envelope to stdout:

```bash
starboard --goal "Analyze job 12345" --json > result.json
```

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Authentication error |
| `2` | Resource not found |
| `3` | API error |
| `4` | Argument error |

---

## Environment variables

Starboard auto-loads `.env` from the current directory. All settings resolve in this
priority order (highest first): CLI flags → YAML config file → environment variables →
built-in defaults.

### Databricks authentication

Provide **any one** of these paths — the SDK credential chain resolves the rest:

```bash
# Inline PAT
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi...

# Profile (recommended)
DATABRICKS_CONFIG_PROFILE=my-ws   # or STARBOARD_WORKSPACE=my-ws

# OAuth service principal
DATABRICKS_CLIENT_ID=...
DATABRICKS_CLIENT_SECRET=...
```

Optional warehouse config:

```bash
DATABRICKS_WAREHOUSE_ID=abc123def456   # if unset and AUTOCREATE_DBX_DW=true (default),
                                       # Starboard auto-creates a serverless warehouse
DEFAULT_CATALOG=main
DEFAULT_SCHEMA=default
```

### LLM

```bash
LLM_API_KEY=<your-api-key>               # required (falls back to OPENAI_API_KEY)
LLM_MODEL=databricks-claude-sonnet-4-5   # default model
LLM_BASE_URL=                            # custom / Model Serving endpoint base URL
LLM_TEMPERATURE=0.4                      # sampling temperature
LLM_MAX_TOKENS=75000                     # token budget
LLM_SEED=                                # optional: seed for deterministic output
LLM_PROVIDER=openai                      # openai | azure | databricks
```

### Cache

```bash
CACHE_TTL=300                 # default TTL in seconds
REDIS_URL=redis://localhost:6379   # selects Redis when set; requires starboard[redis]
```

### Multi-agent overrides

```bash
# Per-domain model and temperature overrides (JSON)
DOMAIN_MODEL_OVERRIDES='{"router":"databricks-gpt-5-mini","query":"gpt-4o"}'
DOMAIN_TEMPERATURE_OVERRIDES='{"router":0.2,"query":0.3}'

DISABLED_AGENT_DOMAINS=diagnostic,warehouse   # comma-separated domains to disable
TOOL_PARALLELISM=4                            # max parallel tool executions
MAX_ANALYSIS_RESULT_ROWS=50                   # max rows returned from analytics queries
```

### Feature and testing flags

```bash
OFFLINE_MODE=false      # skip Databricks/LLM validation (useful in tests)
MOCK_LLM=false          # use mock LLM responses
SAFE_MODE=false         # disable external API calls
ENABLE_CACHING=true
ENABLE_PII_REDACTION=true

# Internal-data gate — leave empty for the public path (closed by default)
INTERNAL_CONTEXT_HOST_ALLOWLIST=
```

---

## YAML config file

Pass `--config starboard-config.yaml` to set databricks and LLM defaults without
exporting environment variables. Environment variables and CLI flags still take precedence.

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

## See also

- [Quickstart](./quickstart.md) — prerequisites and first run
- [Skills](./skills.md) — run Starboard from Claude Code / Cursor
- [Workflows](./workflows.md) — step-by-step task recipes
- [Reports](./reports.md) — reading findings output
- [Troubleshooting](./troubleshooting.md) — common errors
- [Agents](../overview/agents.md) — the 8 domain agents catalog
