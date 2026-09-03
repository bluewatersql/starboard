# Troubleshooting & FAQ

Common problems, fixes, and quick answers for Starboard users.

---

## Install & auth

### `starboard: command not found`

The package is not installed in the active environment, or `bin/` is not on `PATH`.

```bash
pip install starboard
starboard --help
```

If you use a virtualenv, activate it first.

---

### No Databricks credentials resolved

Starboard delegates to the Databricks SDK credential chain. If nothing is found:

```bash
# Option A — guided login
starboard auth login --host https://your-workspace.cloud.databricks.com --profile my-ws

# Option B — environment variables
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=dapi_your_token

# Option C — config profile (~/.databrickscfg)
starboard --profile my-profile ...

# Check what is currently resolved (never prints the token)
starboard auth status
```

OAuth service principal also works: `DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET`.

---

### Authentication failure (401 / 403)

Credentials are expired or lack permissions.

1. `starboard auth status` — confirm the resolved identity.
2. If expired, generate a new token: **Databricks workspace → User Settings → Developer → Access tokens**, then re-run `starboard auth login`.
3. The identity needs access to the resources being analyzed (jobs, clusters, warehouses, Unity Catalog) **and** to the public `system.*` tables used by `starboard review` and `--discover`.

---

### `system.*` tables return no data or permission denied

`starboard review` and `starboard --discover` read public `system.*` tables (e.g. `system.lakeflow.jobs`, `system.billing.usage`). If these return nothing or fail:

1. Confirm the workspace has system table access enabled (workspace setting).
2. Grant `USE CATALOG` on `system` and `SELECT` on the relevant schemas to your identity.
3. System table data can lag up to 24 hours. For very recent activity, extend the lookback: `--lookback-days 30`.

---

## LLM / model

### `LLM_API_KEY not set`

```bash
export LLM_API_KEY=sk-your-key-here
# or in a .env file in the project root:
LLM_API_KEY=sk-your-key-here
```

### Which LLM providers are supported?

Any OpenAI-compatible endpoint:

| Provider | Config |
|----------|--------|
| OpenAI (GPT-4o, GPT-4o-mini) | `LLM_PROVIDER=openai`, `LLM_API_KEY=sk-...` |
| Azure OpenAI | `LLM_BASE_URL=https://...`, `LLM_API_KEY=...` |
| Databricks Model Serving | `LLM_PROVIDER=openai`, `LLM_BASE_URL=<serving endpoint>` |

Override model: `LLM_MODEL=gpt-4o-mini` (or `--llm-model gpt-4o-mini` on the CLI).

---

## Install extras

### Missing optional driver (e.g. Redis)

The default install is memory-only and pulls no store or vector drivers. If you opt in to the Redis cache backend, Starboard raises an error naming the extra:

```bash
pip install 'starboard[redis]'
```

No other extras are required for normal CLI or MCP use.

---

## Agent issues

### Wrong agent selected

The Intent Router sometimes misclassifies ambiguous requests. Be specific — include domain keywords and resource IDs:

| Domain | Keywords to add |
|--------|----------------|
| SQL queries | "query", "statement ID", "execution plan" |
| Jobs | "job", "job ID", "run", "task" |
| Costs | "cost", "spend", "billing", "chargeback", "DBU" |
| Clusters | "cluster", "node", "worker", "autoscaling" |
| Warehouses | "warehouse", "SQL warehouse", "SLO" |
| Unity Catalog | "table", "catalog", "schema", "lineage", "governance" |
| Workspace health | "workspace health", "health check", "discovery" |

If the wrong agent answered, follow up: *"I was asking about the SQL query, not the job. Please analyze statement 01ef-abc123."*

---

### Agent timeout / token budget exhausted

Complex analyses can hit the configured budget. Options:

1. Simplify the request: instead of "analyze everything about job 12345", ask "why did job 12345 fail in the last run?"
2. Raise the budget: `starboard --goal "..." --llm-max-tokens 150000`
3. Break into multiple turns.
4. For MCP server agents, increase `agent_timeout` in config (default 120s; discovery and analytics agents use 900s):

```json
{ "agent_timeout": 600 }
```

---

### Discovery tools not appearing in MCP

The `discover_active_products` / `run_discovery_queries` tools require `phase_b` scope (the default). Check for an explicit override:

```bash
echo $STARBOARD_MCP_TOOL_SCOPE   # should be "phase_b" or unset
```

---

## MCP server issues

### No tools appearing after restart

1. Verify the CLI is on PATH: `which starboard-mcp && starboard-mcp --help`
2. Confirm the config file is valid JSON:
   ```bash
   python -c "import json; json.load(open('.cursor/mcp.json'))"   # Cursor
   ```
3. Restart the IDE fully after any config change.
4. Test the server manually:
   ```bash
   echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | \
     DATABRICKS_HOST="https://your-ws.cloud.databricks.com" \
     DATABRICKS_TOKEN="dapi_..." \
     starboard-mcp --transport stdio 2>/dev/null | head -1
   ```

### `EXEC_NO_REGISTRY`

The MCP server was not started through the `starboard-mcp` entry point. Always start it via `starboard-mcp --transport stdio`; do not invoke the module directly.

### `AUTH_NO_PROVIDER`

The workspace config references a `token_env` variable that is not set.

```bash
export DATABRICKS_TOKEN="dapi_your_token"          # simple single-workspace
export DATABRICKS_TOKEN_PROD="dapi_prod_token"     # multi-workspace
```

---

## Output issues

### Numbers look wrong or cost figures seem off

All `$` figures from Starboard are **list-price DBU estimates**, not finance-grade billing numbers. For authoritative cost data, cross-reference with the Databricks billing console. System table data can lag up to 24 hours.

### Garbled terminal output

Some terminals and pipelines don't handle Rich / ANSI formatting:

```bash
starboard --plain --goal "..."      # plain text
starboard --no-color --goal "..."   # no ANSI color (also respects NO_COLOR env var)
starboard --json --goal "..."       # structured JSON envelope
```

---

## Quick-reference error table

| Error / symptom | Likely cause | Fix |
|-----------------|--------------|-----|
| `starboard: command not found` | Not installed / wrong env | `pip install starboard` |
| "No Databricks auth resolved" | Missing credentials | `starboard auth login` or set `DATABRICKS_HOST`/`DATABRICKS_TOKEN` |
| `LLM_API_KEY not set` | Missing LLM key | `export LLM_API_KEY="..."` |
| 401 / 403 from Databricks | Expired or low-permission token | `starboard auth status`, re-login |
| `system.*` tables empty | No system-table access or data lag | Grant `system` access; wait up to 24 h |
| "Statement not found" | Invalid / expired statement ID | Verify ID format and workspace |
| "Token budget exhausted" | Analysis too complex | Simplify or raise `--llm-max-tokens` |
| `pip install 'starboard[...]'` fails | Extra not in install | Install the named extra (e.g. `starboard[redis]`) |
| `EXEC_NO_REGISTRY` (MCP) | Server not started via entry point | Use `starboard-mcp --transport stdio` |
| `AUTH_NO_PROVIDER` (MCP) | `token_env` variable not set | Export the referenced env var |
| No MCP tools in IDE | Config missing / bad JSON | Verify config path, validate JSON, restart IDE |

---

## FAQ

**What are the minimum environment variables?**

```bash
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi_your_token
LLM_API_KEY=sk-your-api-key
```

**Does Starboard store data?**
State is memory-only — conversation memory is ephemeral and in-process. Durable CLI session state is written to a local JSON file by the `SessionManager`. No cloud database is required.

**Can I run Starboard without a live Databricks connection?**
Yes. Use `--mode offline` for static analysis of a file passed via `--input-file`. No Databricks API calls are made. Live agent analysis requires a connected workspace.

**Can I use Starboard programmatically from Python?**
Yes: `from starboard.sdk import StarboardClient`. See `examples/` in the repo.

**How do I enable debug logging?**

```bash
starboard --debug --goal "..."
starboard --log-level DEBUG --log-file starboard.log --goal "..."
```

---

## Related

- [Quickstart](./quickstart.md) — five-minute setup
- [CLI reference](./cli.md) — all flags and subcommands
- [Skills & MCP](./skills.md) — coding-assistant integration
- [Agent catalog](../overview/agents.md) — what each domain agent does
