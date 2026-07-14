# Starboard AI Agent -- Claude Code / Cursor Integration

Connect Starboard's Databricks analysis tools and domain agents to Claude Code, Cursor, or Claude Desktop via the Model Context Protocol (MCP).

---

## Table of Contents

- [Quick Start (5 minutes)](#quick-start-5-minutes)
- [What You Get](#what-you-get)
- [Configuration Reference](#configuration-reference)
- [Usage Examples](#usage-examples)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)

---

## Quick Start (5 minutes)

### Prerequisites

Install the Starboard package:

```bash
pip install starboard
# Or from the repo:
make setup
```

Verify the CLI is available:

```bash
starboard-mcp --help
```

### Option A: Cursor IDE

1. Copy the template configuration into your project:

   ```bash
   cp examples/cursor-mcp.json .cursor/mcp.json
   ```

2. Edit `.cursor/mcp.json` with your credentials:

   ```json
   {
     "mcpServers": {
       "starboard": {
         "command": "starboard-mcp",
         "args": ["--transport", "stdio"],
         "timeout": 900,
         "env": {
           "DATABRICKS_HOST": "https://YOUR_WORKSPACE.cloud.databricks.com",
           "DATABRICKS_TOKEN": "dapi_YOUR_TOKEN_HERE",
           "LLM_PROVIDER": "openai",
           "LLM_API_KEY": "sk-YOUR_KEY_HERE",
           "LLM_MODEL": "gpt-4o"
         }
       }
     }
   }
   ```

3. Restart Cursor. Starboard tools appear in the MCP tool list.

### Option B: Claude Desktop

1. Open your Claude Desktop configuration file:

   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

2. Add the Starboard server entry (or merge with existing `mcpServers`):

   ```json
   {
     "mcpServers": {
       "starboard": {
         "command": "starboard-mcp",
         "args": ["--transport", "stdio"],
         "timeout": 900,
         "env": {
           "DATABRICKS_HOST": "https://YOUR_WORKSPACE.cloud.databricks.com",
           "DATABRICKS_TOKEN": "dapi_YOUR_TOKEN_HERE",
           "LLM_PROVIDER": "openai",
           "LLM_API_KEY": "sk-YOUR_KEY_HERE",
           "LLM_MODEL": "gpt-4o"
         }
       }
     }
   }
   ```

3. Restart Claude Desktop. Starboard tools will be available in new conversations.

### Option C: Automated Setup

Run the interactive setup script from the repository root:

```bash
./scripts/setup-mcp.sh
```

The script will:
- Install `starboard-mcp` if not already available
- Prompt for your Databricks and LLM credentials
- Write the configuration to Cursor, Claude Desktop, or both
- Optionally install Claude Code skills
- Verify connectivity with a ping test

---

## What You Get

### Quick-Lookup Tools (Phase A -- 11 tools)

Available by default. Low-latency lookups that return structured data without LLM reasoning.

| Tool | Description |
|------|-------------|
| `resolve_query` | Get SQL text from a statement ID or validate raw SQL. First step for query optimization. |
| `resolve_job` | Get job info from a job ID or run ID. First step for job optimization. |
| `get_table_metadata` | Get table metadata: columns, row count, size, partitioning, statistics. |
| `get_warehouse_portfolio` | Get portfolio view of all SQL warehouses with health scores and performance metrics. |
| `analyze_query_plan` | Generate and analyze EXPLAIN plan for a SQL query. Detects full table scans, expensive joins, shuffle operations. |
| `get_job_config` | Get full job configuration: cluster settings, tasks, Spark configs, libraries. |
| `list_uc_assets` | List Unity Catalog assets: catalogs, schemas, tables, volumes, functions. |
| `list_clusters` | List compute clusters with recent activity (default: last 30 days). |
| `get_query_runtime_metrics` | Get detailed query execution metrics: stage times, rows processed, shuffles, spills. |
| `get_cluster_health` | Get health score (0-100) and risk analysis for a Databricks cluster. |
| `get_warehouse_health` | Get health score and SLO compliance for a SQL warehouse. |

### Deep Analysis Tools (Phase B -- 40+ tools)

Enable by setting `tool_scope` to `"phase_b"` or `"full"` in your configuration (see [Tool Scope](#tool-scope)). These tools perform deeper analysis and may take longer to execute.

**Job deep analysis:**
`analyze_job_history`, `get_run_output`, `get_task_logs`, `get_source_code`, `analyze_code_quality`

**Unity Catalog deep analysis:**
`get_table_lineage`, `get_table_history`, `analyze_table_schema`, `analyze_storage_optimization`, `get_table_fingerprint`, `analyze_table_costs`, `get_table_grants`, `analyze_access_patterns`, `analyze_schema_drift`, `analyze_query_impact`, `generate_schema_diff`, `analyze_policy_coverage`, `get_enriched_table_metadata`

**Cluster deep analysis:**
`get_cluster_config`, `get_cluster_events`, `get_cluster_metrics`, `get_spark_logs`

**Warehouse deep analysis:**
`get_warehouse_fingerprint`, `configure_warehouse_slo`, `analyze_warehouse_topology`, `get_warehouse_user_activity`, `generate_warehouse_chargeback`, `generate_portfolio_chargeback`

**Discovery:**
`discover_active_products`, `run_discovery_queries`, `analyze_discovery_domain`, `synthesize_discovery_report`

**Analytics:**
`build_analytics_context`, `build_sql_query`, `validate_sql_query`, `execute_sql_query`

**Cross-domain:**
`discover_tables`, `explore_artifact`, `analyze_explain_plan`

### Agent Tools (7 domain agents)

Agent tools invoke full LLM-powered reasoning agents. Each agent has access to its own set of specialized tools and follows a multi-step reasoning loop to answer complex questions.

| Agent Tool | Domain | What It Does |
|------------|--------|--------------|
| `query_agent` | SQL Queries | Analyze SQL query performance, execution plans, and suggest optimizations for Databricks SQL queries. |
| `job_agent` | Jobs | Analyze Databricks job configuration, run history, failures, and suggest performance improvements. |
| `uc_agent` | Unity Catalog | Explore Unity Catalog assets, lineage, governance policies, and storage optimization. |
| `cluster_agent` | Clusters | Analyze Databricks cluster configuration, health, resource utilization, and autoscaling. |
| `analytics_agent` | FinOps | Run FinOps cost analysis, billing queries, budget forecasting, and usage trend analysis. |
| `warehouse_agent` | Warehouses | Analyze SQL warehouse portfolio, health, sizing, user activity, and chargeback. |
| `diagnostic_agent` | Diagnostics | Troubleshoot Databricks issues with error pattern detection, log analysis, and root cause analysis. |

Each agent accepts a natural language `message` and optional `workspace_id`, `conversation_id` (for multi-turn continuity), and `config_overrides` (model, temperature, max_iterations).

> **Note:** Workspace discovery uses the granular 4-phase tools (`discover_active_products`, `run_discovery_queries`, `analyze_discovery_domain`, `synthesize_discovery_report`) instead of a monolithic agent tool. See [Discovery tools](#deep-analysis-tools-phase-b----40-tools) in Phase B.

### Composite Tools (4 multi-step tools)

Composite tools chain multiple quick-lookup tools into a single call. They do not use LLM reasoning, so they are fast and deterministic. Partial failures are captured gracefully rather than aborting the whole call.

| Tool | Description |
|------|-------------|
| `get_job_summary` | Comprehensive job overview: resolves the job, then fetches configuration and latest run status in one call. |
| `get_query_analysis` | Full query analysis: resolves SQL, fetches runtime metrics and execution plan analysis in parallel. |
| `get_table_profile` | Table profile: fetches metadata and recent history (last 5 operations). |
| `get_workspace_overview` | Workspace overview: lists clusters and SQL warehouses in parallel. |

### Resources (5 introspection endpoints)

MCP resources provide read-only introspection into the server's current state. Use them to discover what is available or check health.

| Resource URI | Description |
|--------------|-------------|
| `starboard://workspace/info` | Workspace configuration (no secrets exposed). |
| `starboard://agents/catalog` | Available domain agents with their capabilities and tool lists. |
| `starboard://tools/catalog` | Full tool inventory with schemas and phase classification. |
| `starboard://tools/dependencies` | Tool dependency graph showing which tools must be called before others. |
| `starboard://health` | Server health snapshot: uptime, circuit breaker states, registered tool count. |

### Prompts (8 domain prompts)

MCP prompts let you preview the system prompt used by each domain agent. This is useful for understanding agent capabilities before invoking them.

| Prompt | Description |
|--------|-------------|
| `query_agent_prompt` | Preview the SQL query optimization agent's system prompt. |
| `job_agent_prompt` | Preview the Databricks job analysis agent's system prompt. |
| `uc_agent_prompt` | Preview the Unity Catalog governance agent's system prompt. |
| `cluster_agent_prompt` | Preview the cluster configuration agent's system prompt. |
| `analytics_agent_prompt` | Preview the FinOps cost analysis agent's system prompt. |
| `warehouse_agent_prompt` | Preview the SQL warehouse portfolio agent's system prompt. |
| `diagnostic_agent_prompt` | Preview the troubleshooting and diagnostics agent's system prompt. |
| `discovery_agent_prompt` | Preview the workspace discovery agent's system prompt. |

Each prompt accepts optional `goal` and `workspace_id` arguments.

---

## Configuration Reference

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABRICKS_HOST` | Yes (unless using `STARBOARD_MCP_CONFIG`) | Databricks workspace URL (e.g., `https://my-workspace.cloud.databricks.com`). |
| `DATABRICKS_TOKEN` | Yes (unless using `STARBOARD_MCP_CONFIG`) | Databricks personal access token. |
| `LLM_PROVIDER` | Yes (for agent tools) | LLM provider: `openai` or `anthropic`. |
| `LLM_API_KEY` | Yes (for agent tools) | API key for the LLM provider. |
| `LLM_MODEL` | No | LLM model name (default: `gpt-4o`). |
| `STARBOARD_MCP_CONFIG` | No | Full MCP configuration as a JSON string. Overrides `DATABRICKS_HOST`/`DATABRICKS_TOKEN`. |
| `STARBOARD_MCP_TOOL_SCOPE` | No | Tool scope: `phase_a`, `phase_b`, or `full` (default: `phase_a`). |
| `STARBOARD_MCP_SAFE_MODE` | No | Set to `true` to expose only offline-safe tools (default: `false`). |
| `STARBOARD_MCP_API_KEY` | No | API key for HTTP transport authentication. Only needed when using `--transport http`. |

### MCPServerConfig Fields

When using `STARBOARD_MCP_CONFIG` or a config file (`--config path/to/config.json`), the following fields are available:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_workspace_id` | `string` | *(required)* | Key into `workspaces` used when callers omit `workspace_id`. |
| `workspaces` | `object` | *(required)* | Mapping of workspace ID to connection profile. At least one entry required. |
| `rate_limit_per_minute` | `integer` | `60` | Maximum MCP calls per minute per session. |
| `max_response_size_bytes` | `integer` | `32768` | Truncation threshold for tool responses (bytes). |
| `safe_mode` | `boolean` | `false` | When `true`, only offline-safe tools are exposed. |
| `tool_scope` | `string` | `"phase_a"` | Tool exposure scope: `"phase_a"`, `"phase_b"`, or `"full"`. |
| `schema_version` | `string` | `"1.0.0"` | Configuration schema version for forward compatibility. |
| `agent_timeout` | `integer` | `120` | Default timeout in seconds for agent executions. |
| `token_budget` | `integer` | `null` | Optional server-wide token budget. |

**Workspace profile fields** (each entry in `workspaces`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | `string` | *(required)* | Databricks workspace URL (must include scheme, e.g. `https://...`). |
| `token_env` | `string` | *(required)* | Name of the environment variable holding the API token. |
| `warehouse_id` | `string` | `null` | Default SQL warehouse ID for this workspace. |
| `default_catalog` | `string` | `null` | Default Unity Catalog name. |
| `default_schema` | `string` | `null` | Default schema name. |
| `token_budget` | `integer` | `null` | Per-workspace token budget (overrides server default). |

**Multi-workspace example** (`examples/starboard-mcp-config.json`):

```json
{
  "default_workspace_id": "production",
  "workspaces": {
    "production": {
      "host": "https://prod.cloud.databricks.com",
      "token_env": "DATABRICKS_TOKEN_PROD",
      "warehouse_id": "abc123",
      "default_catalog": "main",
      "default_schema": "default"
    },
    "staging": {
      "host": "https://staging.cloud.databricks.com",
      "token_env": "DATABRICKS_TOKEN_STAGING"
    }
  },
  "tool_scope": "phase_b",
  "rate_limit_per_minute": 60,
  "max_response_size_bytes": 65536,
  "agent_timeout": 120,
  "safe_mode": false
}
```

### Tool Scope

The `tool_scope` setting controls which tools are exposed to the MCP client:

| Scope | Tools Exposed | When To Use |
|-------|---------------|-------------|
| `phase_a` | 11 quick-lookup tools | Default. Fast lookups with minimal token usage. Good for most workflows. |
| `phase_b` | 40+ tools (Phase A + deep analysis, discovery, analytics) | When you need deep analysis: lineage, cost analysis, code quality, warehouse chargeback. |
| `full` | All non-internal tools | Full access to every registered tool. Use when you need everything. |

Set the scope via environment variable:

```bash
STARBOARD_MCP_TOOL_SCOPE=phase_b
```

Or in the config JSON:

```json
{
  "tool_scope": "phase_b"
}
```

---

## Usage Examples

### Analyze a Slow Query

**Scenario**: A query is taking 45 minutes and you want to understand why.

**Step 1** -- Resolve the query to get its SQL text and metadata:

```
Use tool: resolve_query
Arguments: { "target": "01ef8b2c-abcd-1234-5678-abcdef123456" }
```

Returns the SQL text, statement details, and execution status.

**Step 2** -- Check runtime metrics for bottlenecks:

```
Use tool: get_query_runtime_metrics
Arguments: { "statement_id": "01ef8b2c-abcd-1234-5678-abcdef123456" }
```

Returns per-stage breakdown: task durations, rows scanned, shuffle bytes, spill metrics.

**Step 3** -- Analyze the execution plan:

```
Use tool: analyze_query_plan
Arguments: { "sql_text": "SELECT ... FROM ..." }
```

Returns EXPLAIN plan with insights: full table scans, expensive joins, missing partition pruning.

**Or use the composite tool** to do all three steps at once:

```
Use tool: get_query_analysis
Arguments: { "target": "01ef8b2c-abcd-1234-5678-abcdef123456" }
```

**Or ask the query agent** for a full natural-language analysis with recommendations:

```
Use tool: query_agent
Arguments: {
  "message": "Why is statement 01ef8b2c-abcd-1234-5678-abcdef123456 taking 45 minutes? Give me optimization recommendations."
}
```

### Debug a Failing Job

**Scenario**: A nightly ETL job started failing two days ago.

**Step 1** -- Resolve the job:

```
Use tool: resolve_job
Arguments: { "target": "987654321" }
```

Returns job details: name, settings, and last run status.

**Step 2** -- Get the full configuration:

```
Use tool: get_job_config
Arguments: { "job_id": "987654321" }
```

Returns task definitions, cluster settings, Spark configuration, and library dependencies.

**Step 3** (requires Phase B) -- Analyze run history for failure patterns:

```
Use tool: analyze_job_history
Arguments: { "job_id": "987654321", "limit": 10 }
```

Returns run history with success/failure trends, duration patterns, and error summaries.

**Step 4** (requires Phase B) -- Get task logs from the failed run:

```
Use tool: get_task_logs
Arguments: { "run_id": "111222333" }
```

Returns task-level log output for root cause analysis.

**Or ask the job agent** to investigate end-to-end:

```
Use tool: job_agent
Arguments: {
  "message": "Job 987654321 started failing two days ago. Analyze the recent runs and tell me what changed."
}
```

### Workspace Health Assessment

**Scenario**: You want a broad overview of workspace health before a quarterly review.

**Step 1** -- Get a workspace overview:

```
Use tool: get_workspace_overview
Arguments: {}
```

Returns cluster inventory and SQL warehouse portfolio in parallel.

**Step 2** -- Check warehouse health for each warehouse:

```
Use tool: get_warehouse_health
Arguments: { "warehouse_id": "abc123" }
```

Returns health score, risk factors, SLO compliance, and recommendations.

**Step 3** -- Check cluster health for active clusters:

```
Use tool: get_cluster_health
Arguments: { "cluster_id": "0123-456789-abcde" }
```

Returns health score, resource utilization metrics, and optimization suggestions.

**Or run the 4-phase discovery workflow** for a comprehensive automated assessment:

```
Step 1: discover_active_products → identifies which products are in use
Step 2: run_discovery_queries → executes SQL query packs for each product
Step 3: analyze_discovery_domain → analyzes all domains (batch call)
Step 4: synthesize_discovery_report → assembles final report with grades and recommendations
```

---

## Troubleshooting

### EXEC_NO_REGISTRY

**Symptom**: Tool calls fail with error code `EXEC_NO_REGISTRY`.

**Cause**: The MCP server was not properly bootstrapped. The tool registry is not initialized.

**Fix**: Make sure you are starting the server through the `starboard-mcp` CLI entry point, which handles bootstrap and registry initialization. If you are embedding the MCP server programmatically, ensure the server's bootstrap sequence completes before accepting tool calls.

### AUTH_NO_PROVIDER

**Symptom**: Tool calls fail with error code `AUTH_NO_PROVIDER`.

**Cause**: The workspace was resolved successfully, but no authentication credentials were found.

**Fix**: Ensure the environment variable referenced by `token_env` in your workspace profile is set and contains a valid Databricks personal access token. For the simple setup (no config file), set `DATABRICKS_TOKEN`:

```bash
export DATABRICKS_TOKEN="dapi_your_token_here"
```

For multi-workspace configs, each workspace's `token_env` must point to a valid environment variable:

```json
{
  "workspaces": {
    "production": {
      "host": "https://prod.cloud.databricks.com",
      "token_env": "DATABRICKS_TOKEN_PROD"
    }
  }
}
```

Then set:

```bash
export DATABRICKS_TOKEN_PROD="dapi_your_prod_token"
```

### Agent Timeout

**Symptom**: Agent tool calls return with `status: "timeout"` and the message "Agent execution timed out."

**Cause**: Complex analysis exceeded the default 120-second timeout. This is common for agents that chain many tool calls or analyze large datasets.

**Fix**: Increase the `agent_timeout` in your configuration:

```json
{
  "agent_timeout": 300
}
```

Or pass a per-call override via `config_overrides`:

```
Use tool: job_agent
Arguments: {
  "message": "Analyze job 12345",
  "config_overrides": { "agent_timeout": 300 }
}
```

You can also simplify your request to reduce the number of reasoning steps the agent needs.

### No Tools Appearing

**Symptom**: After restarting your IDE or Claude Desktop, no Starboard tools appear in the tool list.

**Cause**: The MCP client could not find or parse the configuration, or the `starboard-mcp` command is not on the PATH.

**Fix**:

1. **Verify the CLI is installed and accessible**:

   ```bash
   which starboard-mcp
   starboard-mcp --help
   ```

2. **Verify your config file location**:
   - Cursor: `.cursor/mcp.json` in your project root
   - Claude Desktop (macOS): `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Claude Desktop (Windows): `%APPDATA%\Claude\claude_desktop_config.json`

3. **Verify the JSON is valid**:

   ```bash
   python -c "import json; json.load(open('.cursor/mcp.json'))"
   ```

4. **Verify credentials are set**:

   ```bash
   echo $DATABRICKS_HOST
   echo $DATABRICKS_TOKEN
   ```

5. **Test the server manually**:

   ```bash
   echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | \
     DATABRICKS_HOST="https://your-workspace.cloud.databricks.com" \
     DATABRICKS_TOKEN="dapi_your_token" \
     starboard-mcp --transport stdio 2>/dev/null | head -1
   ```

---

## Architecture

The MCP server acts as a bridge between MCP clients (Claude Code, Cursor, Claude Desktop) and the Starboard agent system, which in turn communicates with Databricks workspaces.

```
+-------------------+     stdio/http     +------------------------+
|                   | =================> |                        |
|  MCP Client       |                    |  Starboard MCP Server  |
|  (Claude Code,    |     JSON-RPC       |  (starboard-mcp)       |
|   Cursor, Claude  | <================ |                        |
|   Desktop)        |                    +-----+------------------+
|                   |                          |
+-------------------+                          |
                                               v
                              +----------------+----------------+
                              |                |                |
                         +----v----+     +-----v-----+   +-----v-----+
                         |  Tool   |     |  Agent    |   | Resource  |
                         |  Bridge |     |  Bridge   |   | Provider  |
                         +---------+     +-----------+   +-----------+
                              |                |
                              v                v
                     +--------+--------+   +---+------------+
                     |  Tool Registry  |   | Agent Factory  |
                     |  (45+ tools)    |   | (7 MCP agents) |
                     +--------+--------+   +---+------------+
                              |                |
                              v                v
                     +--------+----------------+--------+
                     |      Execution Pipeline          |
                     |  rate-limit -> validate ->       |
                     |  resolve workspace -> auth ->    |
                     |  circuit-breaker -> execute ->   |
                     |  format -> sanitize              |
                     +----------------+-----------------+
                                      |
                                      v
                            +---------+----------+
                            |   Databricks APIs  |
                            |   (Jobs, SQL,      |
                            |    Unity Catalog,  |
                            |    Clusters)       |
                            +--------------------+
```

**Key components**:

- **Tool Bridge**: Maps MCP `tools/call` requests to the internal `ToolRegistry`. Handles tool scope filtering, workspace injection, and response formatting.
- **Agent Bridge**: Wraps domain agents as MCP tools. Runs agents in non-interactive (headless) mode with timeout handling, token budget enforcement, and progress reporting.
- **Composite Tools**: Chain multiple quick-lookup tools into single calls without LLM reasoning. Handle partial failures gracefully.
- **Resource Provider**: Serves read-only introspection endpoints for catalog discovery and health checks.
- **Prompt Bridge**: Exposes domain agent system prompts so MCP clients can preview agent behavior.
- **Execution Pipeline**: Every tool call passes through rate limiting, input validation, workspace resolution, authentication, circuit breaker protection, execution, response formatting, and size-based truncation.
