# Starboard Skills for Claude Code & Cursor

Starboard ships a set of **Claude Code / Cursor skills** that give AI assistants deep knowledge of how to use Starboard's MCP tools for Databricks workspace analysis. Skills act as domain-specific playbooks — they teach the assistant which tools to call, in what order, and how to interpret the results.

---

## Table of Contents

- [Overview](#overview)
- [Setup & Installation](#setup--installation)
  - [1. Install Starboard MCP Server](#1-install-starboard-mcp-server)
  - [2. Configure MCP for Cursor](#2-configure-mcp-for-cursor)
  - [3. Configure MCP for Claude Code](#3-configure-mcp-for-claude-code)
  - [4. Configure MCP for Claude Desktop](#4-configure-mcp-for-claude-desktop)
  - [5. Install Skills](#5-install-skills)
  - [6. Verify Installation](#6-verify-installation)
- [Skill Catalog](#skill-catalog)
  - [starboard-analyze (Meta-Router)](#starboard-analyze-meta-router)
  - [starboard-query](#starboard-query)
  - [starboard-job](#starboard-job)
  - [starboard-uc](#starboard-uc)
  - [starboard-cluster](#starboard-cluster)
  - [starboard-finops](#starboard-finops)
  - [starboard-warehouse](#starboard-warehouse)
  - [starboard-diagnostic](#starboard-diagnostic)
  - [starboard-discovery](#starboard-discovery)
  - [starboard-workspace](#starboard-workspace)
- [Usage Scenarios](#usage-scenarios)
  - [Scenario 1: Investigate a Slow Query](#scenario-1-investigate-a-slow-query)
  - [Scenario 2: Debug a Failing Nightly Job](#scenario-2-debug-a-failing-nightly-job)
  - [Scenario 3: Quarterly Workspace Health Review](#scenario-3-quarterly-workspace-health-review)
  - [Scenario 4: FinOps Cost Drill-Down](#scenario-4-finops-cost-drill-down)
  - [Scenario 5: Cross-Domain Root Cause Analysis](#scenario-5-cross-domain-root-cause-analysis)
  - [Scenario 6: Unity Catalog Governance Audit](#scenario-6-unity-catalog-governance-audit)
  - [Scenario 7: SQL Warehouse Fleet Optimization](#scenario-7-sql-warehouse-fleet-optimization)
  - [Scenario 8: Workspace Switching](#scenario-8-workspace-switching)
  - [Scenario 9: Multi-Workspace Comparison](#scenario-9-multi-workspace-comparison)
- [Configuration Reference](#configuration-reference)
  - [Environment Variables](#environment-variables)
  - [Multi-Workspace Configuration](#multi-workspace-configuration)
  - [Domain Prompt Resources](#domain-prompt-resources)
  - [Tool Scope](#tool-scope)
- [Troubleshooting](#troubleshooting)

---

## Overview

Starboard skills are Markdown files in the `skills/starboard/` directory. Each skill maps to a Databricks analysis domain and provides:

- **Trigger keywords** that tell the assistant when the skill applies
- **Quick path** with two orchestration modes (direct orchestration or auto-pilot agent)
- **Manual workflow** with step-by-step individual tool calls for targeted analysis
- **Tool reference tables** listing every MCP tool available in the domain
- **Interpretation guidance** explaining what to look for in the results

### Orchestration Modes

Each domain skill supports two modes:

| Mode | How it works | Best for |
|------|-------------|----------|
| **Direct Orchestration** | Fetch `starboard://prompts/{domain}` MCP resource, then follow the expert guidance to call tools directly | Full control, lower cost (no double-LLM), interactive analysis |
| **Auto-Pilot** | Call the `{domain}_agent` MCP tool — the server-side agent handles all reasoning and tool orchestration | Quick results, complex multi-step workflows, batch analysis |

Direct orchestration fetches the same expert prompts that power the server-side agents (tool ordering, Databricks domain knowledge, analysis workflows) and lets Claude orchestrate the tools directly. This avoids double-LLM cost while maintaining the same quality of analysis.

### Skill Architecture

```
skills/starboard/
├── starboard-analyze/SKILL.md     # Meta-router — dispatches to domain skills
├── starboard-query/SKILL.md       # SQL query performance
├── starboard-job/SKILL.md         # Job/workflow analysis
├── starboard-uc/SKILL.md          # Unity Catalog governance
├── starboard-cluster/SKILL.md     # Cluster & compute
├── starboard-finops/SKILL.md      # Cost analysis & billing
├── starboard-warehouse/SKILL.md   # SQL warehouse portfolio
├── starboard-diagnostic/SKILL.md  # Troubleshooting & RCA
├── starboard-discovery/SKILL.md   # Workspace health assessment
└── starboard-workspace/SKILL.md   # Workspace switching & management
```

The **starboard-analyze** skill is a meta-router. When a user mentions "analyze", "optimize", or "Databricks", it reads the request, matches against a routing table, and invokes the appropriate domain skill. For requests that span multiple domains, it triggers multiple agent tools in parallel.

The **starboard-workspace** skill handles switching between Databricks workspaces. Credentials are managed via the `starboard-mcp workspace` CLI — never exposed to AI assistants.

---

## Setup & Installation

### 1. Install Starboard MCP Server

From the repository root:

```bash
make setup
```

Or install directly with pip:

```bash
pip install starboard-server[mcp]
```

Verify the CLI is available:

```bash
starboard-mcp --help
```

### 2. Configure MCP for Cursor

**Option A — Copy the template:**

```bash
cp examples/cursor-mcp.json .cursor/mcp.json
```

Then edit `.cursor/mcp.json` with your credentials:

```json
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"],
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

> **Tip:** If these environment variables are already exported in your shell or defined in a `.env` file, you can omit the `env` block entirely. The MCP server falls back to reading from the process environment automatically (see [Environment Variable Fallback](#environment-variable-fallback) below).

**Option B — Automated setup:**

```bash
./scripts/setup-mcp.sh
```

The interactive wizard will prompt for credentials and write the config automatically.

**Restart Cursor** after saving the configuration. Starboard tools appear in the MCP tool list.

### 3. Configure MCP for Claude Code

Claude Code uses a project-level `.mcp.json` file (in the repo root) or the global `~/.claude/settings.json` for MCP server configuration.

> **Environment variable fallback:** The `env` block is optional. If `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`, etc. are already set in your shell environment (or in a `.env` file), the MCP server picks them up automatically — you only need to specify the `command` and `args`. The `env` block in the MCP config is a convenience for setting variables that are specific to this server process.
>
> Resolution order: (1) `env` block values in MCP config, (2) `STARBOARD_MCP_CONFIG` env var, (3) shell environment variables / `.env` file.

**Option A — Minimal config (variables already in your environment):**

If you've already exported `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and `LLM_API_KEY` in your shell (or have a `.env` file in the project root), the config is just:

```json
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

Place this in `.mcp.json` (project-level) or `~/.claude/settings.json` (global).

**Option B — Explicit credentials in config:**

If your environment variables aren't set, include them in the `env` block:

```json
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"],
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

**Option C — Automated setup:**

```bash
./scripts/setup-mcp.sh
```

The setup wizard (step 5) will offer to install skills to `~/.claude/skills/` automatically.

### 4. Configure MCP for Claude Desktop

Open your configuration file:

| Platform | Path |
|----------|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

Add the `starboard` server entry:

```json
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"],
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

Restart Claude Desktop. Starboard tools will be available in new conversations.

### 5. Install Skills

Skills are SKILL.md files that teach the AI assistant which MCP tools to call and how to interpret results. They need to live in a location the AI agent can discover.

#### Cursor (local project)

Skills in `skills/starboard/` are picked up automatically when the workspace is open. No additional installation needed — Cursor reads SKILL.md files from the project tree.

#### Claude Code (local clone)

Copy skills into the Claude Code skills directory:

```bash
# Automated (via setup script)
./scripts/setup-mcp.sh
# Choose "y" when prompted to install Claude Code skills

# Manual
cp -r skills/starboard ~/.claude/skills/starboard
```

This copies all 9 skills into `~/.claude/skills/starboard/`, making them available in every Claude Code session.

#### Install from Git without cloning the full repo

You do **not** need to clone the entire Starboard repository to use the skills. Use one of these approaches to pull just the `skills/` directory:

**Option A — Git sparse checkout (recommended, stays updatable):**

```bash
mkdir -p ~/starboard-skills && cd ~/starboard-skills
git init
git remote add origin https://github.com/YOUR_ORG/job-agent.git
git sparse-checkout init --cone
git sparse-checkout set skills/starboard
git pull origin main

# Symlink or copy into your skills directory
cp -r skills/starboard ~/.claude/skills/starboard     # Claude Code
cp -r skills/starboard ~/.cursor/skills/starboard     # Cursor (global)
```

To update later:

```bash
cd ~/starboard-skills && git pull origin main
cp -r skills/starboard ~/.claude/skills/starboard
```

**Option B — Download via GitHub API (no git required):**

```bash
# Download and extract just the skills directory
curl -L https://github.com/YOUR_ORG/job-agent/archive/refs/heads/main.tar.gz | \
  tar xz --strip-components=1 -C /tmp/starboard-skills "job-agent-main/skills/starboard"

cp -r /tmp/starboard-skills/skills/starboard ~/.claude/skills/starboard
```

**Option C — degit (simple, no history):**

```bash
npx degit YOUR_ORG/job-agent/skills/starboard ~/.claude/skills/starboard
```

#### Verify skills are installed

```bash
# Check the skill files are in place
ls ~/.claude/skills/starboard/*/SKILL.md

# Expected output (9 skills):
# ~/.claude/skills/starboard/starboard-analyze/SKILL.md
# ~/.claude/skills/starboard/starboard-cluster/SKILL.md
# ~/.claude/skills/starboard/starboard-diagnostic/SKILL.md
# ~/.claude/skills/starboard/starboard-discovery/SKILL.md
# ~/.claude/skills/starboard/starboard-finops/SKILL.md
# ~/.claude/skills/starboard/starboard-job/SKILL.md
# ~/.claude/skills/starboard/starboard-query/SKILL.md
# ~/.claude/skills/starboard/starboard-uc/SKILL.md
# ~/.claude/skills/starboard/starboard-warehouse/SKILL.md
```

### 6. Auto-Approve MCP Tool Permissions (Claude Code)

Claude Code prompts for approval on every MCP tool call by default. Starboard has 64 tools — this gets tedious fast. The setup script can auto-approve all of them:

```bash
./scripts/setup-mcp.sh   # Choose option 3 (Claude Code) — will offer auto-approve
```

**Manual method** — if you've already run setup, add permissions directly:

```bash
cd /path/to/job-agent
source .venv/bin/activate
python3 -c "
import json, os

settings_path = os.path.expanduser('~/.claude/settings.json')
with open(settings_path) as f:
    settings = json.load(f)

from starboard_server.mcp.tool_bridge import PHASE_B_TOOLS
from starboard_server.mcp.composite_tools import COMPOSITE_TOOL_METADATA
from starboard_server.mcp.agent_bridge import AGENT_TOOL_METADATA

tools = {'starboard_ping'}
tools.update(PHASE_B_TOOLS)
tools.update(t['name'] for t in COMPOSITE_TOOL_METADATA)
tools.update(t['name'] for t in AGENT_TOOL_METADATA)
new_tools = sorted(f'mcp__starboard__{t}' for t in tools)

for key in ('permissions', ):
    allow = settings.setdefault(key, {}).setdefault('allow', [])
    for t in new_tools:
        if t not in allow:
            allow.append(t)

top_allow = settings.setdefault('allow', [])
for t in new_tools:
    if t not in top_allow:
        top_allow.append(t)

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')

print(f'{len(new_tools)} tools auto-approved')
"
```

> **Note:** Claude Code does not support wildcard permissions for MCP tools (`mcp__starboard__*` does not work). Each tool must be listed explicitly in `~/.claude/settings.json`. The setup script handles this automatically.

### 7. Verify Installation

**Verify the MCP server is reachable:**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | \
  DATABRICKS_HOST="https://your-workspace.cloud.databricks.com" \
  DATABRICKS_TOKEN="dapi_your_token" \
  starboard-mcp --transport stdio 2>/dev/null | head -1
```

**Verify tools are visible:**

1. Open a new chat in Cursor or Claude Code
2. Type: "What Starboard tools are available?"
3. The assistant should list the MCP tools from the Starboard server

**Verify skills are loaded:**

1. Ask the assistant: "Analyze my Databricks workspace"
2. The `starboard-analyze` skill should activate and route to the appropriate domain

---

## Skill Catalog

### starboard-analyze (Meta-Router)

**Triggers:** analyze, optimize, Databricks, Starboard, workspace, help me with

The meta-router reads the user's request and dispatches to the correct domain skill based on keyword and identifier matching. It does not call MCP tools directly.

**Routing table:**

| User mentions | Routes to |
|---|---|
| SQL, query, statement, execution plan | `starboard-query` |
| Job, run, task, DAG, workflow, schedule | `starboard-job` |
| Table, catalog, schema, lineage, grants, UC | `starboard-uc` |
| Cluster, compute, autoscaling, Spark, node | `starboard-cluster` |
| Cost, billing, budget, FinOps, spend | `starboard-finops` |
| Warehouse, SQL warehouse, endpoint, SLO | `starboard-warehouse` |
| Error, debug, troubleshoot, failing, broken | `starboard-diagnostic` |
| Discovery, assessment, audit, overview | `starboard-discovery` |

**Identifier shortcuts:**

| Pattern | Routes to |
|---|---|
| Numeric job ID (e.g., `123456789`) | `starboard-job` |
| UUID statement ID (e.g., `01ef-...`) | `starboard-query` |
| Three-part name (e.g., `catalog.schema.table`) | `starboard-uc` |

---

### starboard-query

**Triggers:** SQL, query, slow query, execution plan, statement_id, optimize query, DBSQL

Analyzes SQL query performance, execution plans, and optimization opportunities.

**Agent tool:** `query_agent` — full reasoning with automatic tool selection

**Individual tools:**

| Tool | Purpose |
|------|---------|
| `resolve_query` | Get SQL text from a statement ID |
| `discover_tables` | Extract table references from SQL |
| `analyze_query_plan` | Generate and analyze EXPLAIN plan |
| `analyze_explain_plan` | Extract structured metrics from EXPLAIN output |
| `get_query_runtime_metrics` | Get execution duration, bytes, spill metrics |
| `get_table_metadata` | Check table stats and partitioning |

**Key signals to watch:** join order, partition pruning, filter pushdown, statistics freshness, spill to disk, data skew, shuffle size.

---

### starboard-job

**Triggers:** job, run, failure, task, workflow, DAG, schedule, job_id

Analyzes Databricks job configuration, run history, failures, and performance trends.

**Agent tool:** `job_agent` — full reasoning with automatic tool selection

**Individual tools:**

| Tool | Purpose |
|------|---------|
| `resolve_job` | Get job info from job_id or run_id |
| `get_job_config` | Get full job definition (tasks, clusters, libraries) |
| `analyze_job_history` | Analyze run duration trends and failure patterns |
| `get_run_output` | Get output and error messages for a specific run |
| `get_task_logs` | Get detailed logs for a specific task |
| `get_source_code` | Get notebook/script source code |
| `analyze_code_quality` | Detect Spark/PySpark anti-patterns |

**Key signals to watch:** failure patterns, retry configuration, cluster sizing, task dependency bottlenecks, code quality anti-patterns, schedule alignment, duration trends.

---

### starboard-uc

**Triggers:** table, catalog, schema, lineage, governance, Unity Catalog, UC, grants, drift, storage

Explores Unity Catalog assets, lineage, governance, and storage optimization.

**Agent tool:** `uc_agent` — full reasoning with automatic tool selection

**Individual tools:**

| Tool | Purpose |
|------|---------|
| `list_uc_assets` | List catalogs, schemas, tables, volumes |
| `get_table_metadata` | Get column definitions, row count, size |
| `get_table_history` | Get recent Delta operations |
| `get_table_lineage` | Get upstream/downstream dependencies |
| `get_table_grants` | Get access permissions |
| `analyze_table_schema` | Analyze schema for patterns/anomalies |
| `analyze_schema_drift` | Analyze schema changes over time |
| `analyze_storage_optimization` | Get Z-ordering, vacuum, compaction recommendations |
| `get_table_fingerprint` | Comprehensive table profile in one call |
| `analyze_table_costs` | Storage and compute cost attribution |
| `analyze_access_patterns` | Analyze table access patterns |
| `analyze_policy_coverage` | Analyze security policy coverage |

**Key signals to watch:** schema evolution frequency, lineage completeness, overly broad grants, small file accumulation, missing OPTIMIZE/VACUUM operations, cost-to-usage ratio.

---

### starboard-cluster

**Triggers:** cluster, compute, autoscaling, Spark, driver, worker, node, instance type

Analyzes Databricks cluster configuration, health, resource utilization, and autoscaling.

**Agent tool:** `cluster_agent` — full reasoning with automatic tool selection

**Individual tools:**

| Tool | Purpose |
|------|---------|
| `list_clusters` | List all clusters with recent activity |
| `get_cluster_config` | Get instance types, autoscaling, Spark config |
| `get_cluster_health` | Get health score and risk analysis |
| `get_cluster_metrics` | Get CPU, memory, disk, network utilization |
| `get_cluster_events` | Get lifecycle events (start, stop, resize) |
| `get_spark_logs` | Get Spark UI logs for debugging |

**Key signals to watch:** autoscaling efficiency, instance type vs. workload fit, idle cluster costs, Spark configuration tuning, event log patterns (OOM, spot termination).

---

### starboard-finops

**Triggers:** cost, billing, budget, spend, FinOps, usage, chargeback, consumption, DBU

Runs FinOps cost analysis, billing queries, budget forecasting, and usage trend analysis.

**Agent tool:** `analytics_agent` — full reasoning with automatic SQL generation

**Individual tools:**

| Tool | Purpose |
|------|---------|
| `build_analytics_context` | Build RAG context for SQL generation |
| `build_sql_query` | Generate SQL from a cost/billing question |
| `validate_sql_query` | Validate generated SQL (two-gate validation) |
| `execute_sql_query` | Execute validated SQL on Databricks |

**Key signals to watch:** cost allocation distribution, budget burn rate, DBU consumption trends, chargeback accuracy, optimization ROI.

---

### starboard-warehouse

**Triggers:** warehouse, SQL warehouse, serverless, endpoint, sizing, SLO, warehouse portfolio

Analyzes SQL warehouse portfolio, health, sizing, user activity, and chargeback.

**Agent tool:** `warehouse_agent` — full reasoning with automatic tool selection

**Individual tools:**

| Tool | Purpose |
|------|---------|
| `get_warehouse_portfolio` | Portfolio view of all SQL warehouses |
| `get_warehouse_fingerprint` | Detailed fingerprint for a specific warehouse |
| `get_warehouse_health` | Health score and SLO compliance |
| `configure_warehouse_slo` | Configure performance targets |
| `analyze_warehouse_topology` | Fleet-wide topology and consolidation analysis |
| `get_warehouse_user_activity` | User activity breakdown by warehouse |
| `generate_warehouse_chargeback` | Cost allocation for a specific warehouse |
| `generate_portfolio_chargeback` | Cost allocation across all warehouses |

**Key signals to watch:** right-sizing (peak vs. capacity), concurrency patterns, SLO compliance, user distribution, chargeback accuracy, topology consolidation opportunities.

---

### starboard-diagnostic

**Triggers:** error, debug, troubleshoot, failing, broken, root cause, logs, stack trace, exception

Troubleshoots Databricks issues with cross-domain error detection, log analysis, and root cause analysis. The diagnostic agent has access to **all** Starboard tools across every domain.

**Agent tool:** `diagnostic_agent` — full cross-domain troubleshooting

**Manual workflow:**

1. **Identify the failure** — resolve the failing job or query
2. **Get execution details** — retrieve logs, output, and error messages
3. **Check cluster state** — correlate with infrastructure events at failure time
4. **Examine configuration** — check for misconfiguration in job/cluster setup
5. **Check upstream data** — verify table health if failure may be data-related
6. **Analyze patterns** — look for recurring issues in run history

**Key signals to watch:** error type correlation (OOM, ClassNotFound, AnalysisException, Timeout), cross-domain correlation (job + cluster + table signals), root cause vs. symptom chains, remediation priority (quick wins vs. high-effort fixes).

---

### starboard-discovery

**Triggers:** workspace health, discovery, assessment, audit, overview, inventory, what's running

Runs comprehensive workspace health assessment and product usage discovery.

**Agent tool:** `discovery_agent` — full workspace assessment

**Individual tools:**

| Tool | Purpose |
|------|---------|
| `discover_active_products` | Audit workspace for active Databricks products |
| `run_discovery_queries` | Execute discovery SQL query packs |
| `analyze_discovery_domain` | Domain-level analysis with heuristics and LLM |
| `synthesize_discovery_report` | Assemble domains into a final report |
| `run_workspace_discovery` | End-to-end workspace assessment in one call |

**Key signals to watch:** product adoption gaps, workload distribution across compute, unused/idle resources, governance posture, optimization opportunities ranked by impact.

---

### starboard-workspace

**Triggers:** switch workspace, change workspace, which workspace, production, staging, environments

Manages workspace switching and discovery. Credentials are managed outside Claude via the `starboard-mcp workspace` CLI.

**MCP tools:**

| Tool | Purpose |
|------|---------|
| `list_workspaces` | List configured workspaces with IDs and hosts (no secrets) |
| `switch_workspace` | Validate workspace ID and get instructions for switching |

**CLI commands** (for credential management — run from terminal, not Claude):

| Command | Purpose |
|---------|---------|
| `starboard-mcp workspace add` | Add a workspace (interactive — prompts for token) |
| `starboard-mcp workspace list` | List configured workspaces |
| `starboard-mcp workspace remove <id>` | Remove a workspace profile |
| `starboard-mcp workspace set-default <id>` | Change the default workspace |

**Key concept:** Tokens are stored in `~/.starboard/.env` (mode 0600) and referenced by environment variable name in `~/.starboard/config.json`. Claude only sees workspace IDs and hosts — never credentials.

---

## Usage Scenarios

### Scenario 1: Investigate a Slow Query

> "Statement 01ef-abcd-1234-5678 used to run in 2 minutes but now takes 20. Why?"

#### Auto-Pilot Mode

The simplest approach — delegate everything to the server-side agent:

```
You: Analyze statement 01ef-abcd-1234-5678 — it's running 10x slower than last week.

Claude calls → query_agent { "message": "Analyze statement 01ef-abcd-1234-5678..." }
              ↓
Server-side agent resolves query → pulls metrics → analyzes plan → checks tables
              ↓
Returns: Root cause (stale statistics → full scan) + optimization recommendations
```

#### Direct Orchestration Mode

More control, lower cost — Claude fetches the expert prompt and calls tools directly:

```
You: Analyze statement 01ef-abcd-1234-5678 — it's running 10x slower than last week.

Claude fetches → starboard://prompts/query
              ↓ (receives expert guidance: tool ordering, analysis patterns)
Claude calls  → resolve_query { "target": "01ef-abcd-1234-5678" }
              → get_query_runtime_metrics { "statement_id": "01ef-abcd-1234-5678" }
              → analyze_query_plan { "sql_text": "<resolved SQL>" }
              → get_table_metadata { "table_name": "<referenced table>" }
              ↓
Claude synthesizes findings using the prompt's interpretation guidance
```

**Try it yourself:**

```
Analyze statement 01ef-abcd-1234-5678 — it's running 10x slower than last week.
Show me the execution plan and runtime metrics, then suggest optimizations.
```

---

### Scenario 2: Debug a Failing Nightly Job

> "Job 98765 has been failing every night at 2am for the past week. What's wrong?"

#### Auto-Pilot Mode

```
You: Job 98765 started failing two days ago. What changed?

Claude calls → job_agent { "message": "Job 98765 started failing..." }
              ↓
Server-side agent resolves job → analyzes history → retrieves logs → reviews code
              ↓
Returns: Failure pattern (OOM on same task due to growing data) + recommended fixes
```

#### Direct Orchestration Mode

```
You: Job 98765 started failing two days ago. What changed?

Claude fetches → starboard://prompts/job
              ↓
Claude calls  → resolve_job { "target": "98765" }
              → analyze_job_history { "job_id": "98765" }
              → get_run_output { "run_id": "<latest failed run>" }
              → get_task_logs { "run_id": "<failed run>", "task_key": "<failing task>" }
              → get_source_code { "job_id": "98765", "task_key": "<failing task>" }
              ↓
Claude correlates failure patterns, log errors, and code anti-patterns
```

**Try it yourself:**

```
Job 98765 started failing two days ago. Analyze the recent runs,
check the task logs, and tell me what changed.
```

---

### Scenario 3: Quarterly Workspace Health Review

> "Give me a full health assessment of our Databricks workspace before the quarterly review."

#### Auto-Pilot Mode

```
You: Run a full workspace health assessment.

Claude calls → discovery_agent { "message": "Run a full workspace health assessment..." }
              ↓ (may take several minutes — discovery runs multiple phases)
Server-side agent discovers products → runs queries → analyzes domains → synthesizes report
              ↓
Returns: Product adoption, utilization, idle resources, governance gaps, ranked optimizations
```

#### Direct Orchestration Mode

```
You: Run a full workspace health assessment.

Claude fetches → starboard://prompts/discovery
              ↓
Claude calls  → discover_active_products { }
              → run_discovery_queries { }
              → analyze_discovery_domain { }
              → synthesize_discovery_report { }
              ↓
Claude presents findings domain by domain with the prompt's grading framework
```

**Try it yourself:**

```
Run a full workspace health assessment. Identify underutilized resources,
cost optimization opportunities, and governance gaps.
Give me the findings ranked by impact.
```

---

### Scenario 4: FinOps Cost Drill-Down

> "How much are we spending on Databricks this month? Break it down by workspace and cluster type."

#### Auto-Pilot Mode

```
You: What is our total spend by workspace over the last quarter?

Claude calls → analytics_agent { "message": "What is our total spend by workspace..." }
              ↓
Server-side agent builds RAG context → generates SQL → validates → executes
              ↓
Returns: Cost breakdown with trends and burn rate projections
```

#### Direct Orchestration Mode

```
You: What is our total spend by workspace over the last quarter?

Claude fetches → starboard://prompts/analytics
              ↓
Claude calls  → build_analytics_context { "user_query": "total spend by workspace last quarter" }
              → build_sql_query { "user_query": "...", "context_handle": "<handle>" }
              → validate_sql_query { "sql": "<generated SQL>" }
              → execute_sql_query { "sql": "<validated SQL>" }
              ↓
Claude formats results with cost trends, burn rate, and optimization ROI
```

**Try it yourself:**

```
What is our total Databricks spend by workspace over the last quarter?
Are we on track to stay within budget this month?
Show burn rate projections.
```

---

### Scenario 5: Cross-Domain Root Cause Analysis

> "Our nightly ETL pipeline timed out. Check the job runs, cluster events, and upstream tables."

#### Auto-Pilot Mode (Recommended for Cross-Domain)

Cross-domain diagnosis benefits from the agent's ability to dynamically decide which tools to call based on intermediate results:

```
You: Job 12345 timed out last night and the queries inside are failing with OOM errors.

Claude calls → diagnostic_agent { "message": "Job 12345 timed out last night..." }
              ↓
Server-side agent: resolve_job → get_run_output → get_cluster_events (correlate timing)
                 → get_cluster_metrics (check memory at failure time)
                 → get_table_metadata (check upstream data growth)
                 → analyze_schema_drift (check for changes)
              ↓
Returns: Root cause chain (data volume 3x increase → OOM on shuffle → cluster restart)
         + remediation steps ordered by impact
```

#### Direct Orchestration Mode

```
You: Job 12345 timed out. Check jobs, clusters, and tables.

Claude fetches → starboard://prompts/diagnostic
              ↓ (prompt contains cross-domain correlation patterns)
Claude calls  → resolve_job { "target": "12345" }
              → get_run_output { "run_id": "<latest run>" }
              → get_cluster_events { "cluster_id": "<job's cluster>" }
              → get_cluster_metrics { "cluster_id": "<job's cluster>" }
              → get_table_metadata { "table_name": "<upstream table>" }
              ↓
Claude follows the prompt's "root cause vs. symptom" framework to diagnose
```

**Try it yourself:**

```
Job 12345 timed out last night and the queries inside are failing with OOM errors.
The cluster was also restarted. Find the root cause across all domains
and give me a fix.
```

---

### Scenario 6: Unity Catalog Governance Audit

> "Run a governance audit on the finance catalog — grants, policy coverage, and access patterns."

#### Direct Orchestration Mode

```
You: Run a governance audit on finance catalog tables.

Claude fetches → starboard://prompts/uc
              ↓
Claude calls  → list_uc_assets { }  (discover tables in finance catalog)
              → get_table_grants { "table_name": "finance.core.transactions" }
              → analyze_policy_coverage { }
              → analyze_access_patterns { "table_name": "finance.core.transactions" }
              → analyze_schema_drift { "table_name": "finance.core.transactions" }
              ↓
Claude highlights: overly broad grants, missing policies, unused tables, drift risks
```

#### Auto-Pilot Mode

```
You: Run a governance audit on finance catalog tables.

Claude calls → uc_agent { "message": "Run a governance audit on the finance catalog..." }
```

**Try it yourself:**

```
Show me the lineage for production.analytics.customer_orders,
check who has access, and flag any governance concerns.
Also check for schema drift over the last 30 days.
```

---

### Scenario 7: SQL Warehouse Fleet Optimization

> "Which warehouses are underutilized and could be consolidated?"

#### Direct Orchestration Mode

```
You: Analyze our SQL warehouse fleet for consolidation opportunities.

Claude fetches → starboard://prompts/warehouse
              ↓
Claude calls  → get_warehouse_portfolio { }  (fleet overview)
              → get_warehouse_fingerprint { "warehouse_id": "wh-001" }
              → get_warehouse_fingerprint { "warehouse_id": "wh-002" }
              → analyze_warehouse_topology { }  (consolidation analysis)
              → get_warehouse_user_activity { }  (who uses what)
              → generate_portfolio_chargeback { }  (cost allocation)
              ↓
Claude identifies redundant warehouses, recommends right-sizing, estimates savings
```

#### Auto-Pilot Mode

```
You: Analyze our SQL warehouse fleet for consolidation opportunities.

Claude calls → warehouse_agent { "message": "Analyze our SQL warehouse fleet..." }
```

**Try it yourself:**

```
Analyze our SQL warehouse fleet. Show me utilization levels, SLO compliance,
and recommend which warehouses to consolidate or downsize.
Generate a chargeback report allocating $15,000 in monthly costs.
```

---

### Scenario 8: Workspace Switching

> "Switch to the staging workspace and check cluster health there."

#### Setup (one-time, from terminal)

```bash
$ starboard-mcp workspace add
Workspace ID (e.g. production, staging): production
Databricks host URL: https://prod.cloud.databricks.com
Databricks API token: ********
Default SQL warehouse ID (optional): abc-123
Default catalog (optional): main
Workspace 'production' added to ~/.starboard/config.json
Token stored in ~/.starboard/.env (mode 0600)

$ starboard-mcp workspace add --id staging --host https://staging.cloud.databricks.com --set-default
Databricks API token: ********
Workspace 'staging' added to ~/.starboard/config.json
Token stored in ~/.starboard/.env (mode 0600)

$ starboard-mcp workspace list
  production
    host: https://prod.cloud.databricks.com
    credentials: token set
    warehouse: abc-123
    catalog: main
  staging (default)
    host: https://staging.cloud.databricks.com
    credentials: token set
```

#### From Claude/Cursor

```
You: Which workspace am I connected to?

Claude calls → list_workspaces { }
              ↓
Returns:
  default_workspace_id: "staging"
  workspaces:
    - workspace_id: production, host: https://prod.cloud.databricks.com
    - workspace_id: staging, host: https://staging.cloud.databricks.com (default)
```

```
You: Switch to production and check cluster health.

Claude calls → switch_workspace { "workspace_id": "production" }
              ↓ (confirms workspace_id to use)
Claude calls → list_clusters { "workspace_id": "production" }
              → get_cluster_health { "cluster_id": "0315-abc", "workspace_id": "production" }
              ↓
Claude presents cluster health from the production workspace
```

**Try it yourself:**

```
List my configured workspaces, switch to production,
and run a cluster health check there.
```

---

### Scenario 9: Multi-Workspace Comparison

> "Compare cluster costs between production and staging workspaces."

```
You: Compare cluster costs between production and staging.

Claude calls → list_workspaces { }  (discover available workspaces)
Claude calls → list_clusters { "workspace_id": "production" }
              → list_clusters { "workspace_id": "staging" }
              (parallel calls to both workspaces)
Claude calls → analytics_agent { "message": "Show cluster costs", "workspace_id": "production" }
              → analytics_agent { "message": "Show cluster costs", "workspace_id": "staging" }
              (parallel cost analysis)
              ↓
Claude compares results side-by-side and highlights differences
```

**Try it yourself:**

```
Compare our production and staging workspaces — show me the
cluster inventory and cost differences between them.
```

---

## Configuration Reference

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABRICKS_HOST` | Yes | Databricks workspace URL (e.g., `https://my-workspace.cloud.databricks.com`) |
| `DATABRICKS_TOKEN` | Yes | Databricks personal access token |
| `LLM_PROVIDER` | Yes (for agents) | `openai` or `anthropic` |
| `LLM_API_KEY` | Yes (for agents) | API key for the LLM provider |
| `LLM_MODEL` | No | Model name (default: `gpt-4o`) |
| `STARBOARD_MCP_TOOL_SCOPE` | No | `phase_a`, `phase_b`, or `full` (default: `phase_b`) |
| `STARBOARD_MCP_SAFE_MODE` | No | `true` to restrict to offline-safe tools (default: `false`) |
| `STARBOARD_MCP_CONFIG` | No | Full MCP config as JSON (overrides host/token) |

### Environment Variable Fallback

The MCP server resolves configuration through a four-level priority chain:

1. **`--config` CLI flag** — explicit path to a JSON config file (highest priority)
2. **`STARBOARD_MCP_CONFIG` env var** — a JSON string containing the full server config
3. **`~/.starboard/config.json`** — user config file written by `starboard-mcp workspace add` (auto-discovered)
4. **`DATABRICKS_HOST` + `DATABRICKS_TOKEN`** — environment variables create a single "default" workspace

For `env` blocks in MCP configs (`mcp.json`, `claude_desktop_config.json`, `.mcp.json`), values are injected into the server process environment before the priority chain runs.

This means you do **not** need to duplicate credentials in the MCP config if they are already set in your environment. A minimal config with just `command` and `args` is sufficient:

```json
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

The server will pick up `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and `LLM_API_KEY` from your shell exports or `.env` file automatically.

### Multi-Workspace Configuration

#### Quick Setup with CLI (Recommended)

The `starboard-mcp workspace` CLI manages workspace profiles interactively. Credentials are stored in `~/.starboard/.env` (mode 0600) — never exposed to AI assistants.

```bash
# Add a workspace (interactive — prompts for host and token)
starboard-mcp workspace add

# Add with flags (token still prompted securely)
starboard-mcp workspace add --id production --host https://prod.cloud.databricks.com --set-default

# List configured workspaces
starboard-mcp workspace list

# Change the default
starboard-mcp workspace set-default staging

# Remove a workspace
starboard-mcp workspace remove old-dev
```

The CLI writes two files:
- `~/.starboard/config.json` — workspace profiles with `token_env` references (safe for AI to read)
- `~/.starboard/.env` — actual token values (never read by AI assistants)

The MCP server automatically discovers `~/.starboard/config.json` as a config source (priority 3, after explicit `--config` and `STARBOARD_MCP_CONFIG`).

#### Switching Workspaces from Claude/Cursor

Once workspaces are configured, use the `list_workspaces` and `switch_workspace` MCP tools:

```
Step 1 — Discover workspaces:
  Call MCP tool: list_workspaces
  Returns: { "default_workspace_id": "production", "workspaces": [
    { "workspace_id": "production", "host": "https://prod...", "is_default": true },
    { "workspace_id": "staging", "host": "https://staging...", "is_default": false }
  ]}

Step 2 — Switch context:
  Call MCP tool: switch_workspace { "workspace_id": "staging" }
  Returns: { "status": "ok", "workspace_id": "staging",
             "instruction": "Pass workspace_id='staging' to subsequent tool calls." }

Step 3 — Use the workspace:
  Call MCP tool: list_clusters { "workspace_id": "staging" }
  Call MCP tool: get_cluster_health { "cluster_id": "...", "workspace_id": "staging" }
```

Or use the `starboard-workspace` skill — it handles this flow automatically when you say "switch to staging" or "which workspace am I on?".

#### Manual JSON Configuration

For advanced setups, create a JSON config file directly:

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
  "agent_timeout": 900
}
```

Set the corresponding environment variables for each workspace token:

```bash
export DATABRICKS_TOKEN_PROD="dapi_your_prod_token"
export DATABRICKS_TOKEN_STAGING="dapi_your_staging_token"
```

Reference the config via environment variable or CLI flag:

```bash
# Via environment variable
export STARBOARD_MCP_CONFIG='{"default_workspace_id":"production","workspaces":{...}}'

# Via CLI flag
starboard-mcp --config path/to/starboard-mcp-config.json
```

### Domain Prompt Resources

Each domain agent's expert system prompt is available as an MCP resource. These resources contain the same guidance that powers the server-side agents: tool ordering, Databricks domain knowledge, analysis workflows, and output formatting.

| Resource URI | Domain | Description |
|-------------|--------|-------------|
| `starboard://prompts/query` | Query | SQL optimization expertise |
| `starboard://prompts/job` | Job | Spark job performance analysis |
| `starboard://prompts/uc` | UC | Unity Catalog governance |
| `starboard://prompts/cluster` | Cluster | Compute configuration and sizing |
| `starboard://prompts/analytics` | FinOps | Cost analysis and billing |
| `starboard://prompts/warehouse` | Warehouse | SQL warehouse portfolio |
| `starboard://prompts/diagnostic` | Diagnostic | Troubleshooting and RCA |
| `starboard://prompts/discovery` | Discovery | Workspace health assessment |

#### What a Prompt Resource Returns

```json
{
  "domain": "query",
  "prompt_version": "1.0.0",
  "system_prompt": "You are a Databricks SQL query optimization expert...\n\n## Available Tools\n- resolve_query: ...\n- analyze_query_plan: ...\n\n## Workflow\n1. Resolve the query...\n2. Analyze the execution plan...\n...",
  "available_tools": ["analyze_explain_plan", "analyze_query_plan", "discover_tables", "get_query_runtime_metrics", "get_table_metadata", "resolve_query"],
  "usage": "Use this prompt as expert guidance when orchestrating Starboard query tools directly. Replace {goal} with the user's actual goal. Call the listed tools in the order recommended by the prompt."
}
```

The `system_prompt` contains the full expert guidance: tool ordering, Databricks domain knowledge, analysis workflows, error handling, and output formatting. The `available_tools` list tells you exactly which MCP tools to call.

#### Example: Direct Orchestration with a Prompt Resource

```
Step 1 — Fetch the expert prompt:
  Fetch MCP resource: starboard://prompts/query
  → Read the system_prompt to understand tool ordering and analysis workflow

Step 2 — Follow the prompt's workflow:
  Call MCP tool: resolve_query { "target": "01ef-abcd-1234" }
  Call MCP tool: get_query_runtime_metrics { "statement_id": "01ef-abcd-1234" }
  Call MCP tool: analyze_query_plan { "sql_text": "<SQL from step 1>" }

Step 3 — Use the prompt's interpretation guidance:
  The prompt explains what to look for: join order, partition pruning,
  filter pushdown, statistics freshness, spill to disk, data skew.
  Synthesize findings and recommend optimizations.
```

This is the same logic the server-side `query_agent` uses internally — exposed directly for Claude to orchestrate.

### Tool Scope

The `tool_scope` setting controls which tools the MCP server exposes:

| Scope | Tools | When to Use |
|-------|-------|-------------|
| `phase_a` | 11 quick-lookup tools | Minimal footprint. Fast lookups only — no discovery or deep analysis. |
| `phase_b` | 40+ tools (Phase A + deep analysis, discovery, analytics) | **Default.** Full analysis: lineage, code quality, cost attribution, warehouse chargeback, workspace discovery. |
| `full` | All registered tools | Full access to everything including internal tools. |

The default is `phase_b`. To restrict to quick-lookup tools only, set in your MCP config:

```json
{
  "env": {
    "STARBOARD_MCP_TOOL_SCOPE": "phase_a"
  }
}
```

---

## Troubleshooting

### No tools appearing in Cursor

1. Verify the CLI is installed: `which starboard-mcp && starboard-mcp --help`
2. Verify `.cursor/mcp.json` exists in your project root and is valid JSON
3. Verify credentials are set (check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`)
4. Restart Cursor after any configuration change

### Skills not activating

1. Confirm the `skills/starboard/` directory exists in the workspace root
2. Check that each skill directory contains a `SKILL.md` file
3. Try mentioning a trigger keyword explicitly (e.g., "use Starboard to analyze my cluster")

### Agent timeout errors

The default timeout is 15 minutes (900s). Discovery, analytics, and diagnostic agents have
domain-specific overrides (discovery: 900s, analytics: 900s, diagnostic: 600s). Other agents
default to the server-level `agent_timeout`.

If you still hit timeouts, increase the server-level default:

```json
{
  "env": {
    "STARBOARD_MCP_CONFIG": "{\"agent_timeout\": 1200, ...}"
  }
}
```

Or pass a per-call override:

```
Call MCP tool: discovery_agent
Arguments: {
  "message": "Run full workspace discovery",
  "config_overrides": { "agent_timeout": 1200 }
}
```

### Discovery tools not appearing

If discovery tools like `run_workspace_discovery` or `discover_active_products` are not
visible, your `tool_scope` may be set to `phase_a`. Discovery tools require `phase_b`
(the default) or `full`. Check your MCP config for an explicit `tool_scope` override:

```json
{
  "env": {
    "STARBOARD_MCP_TOOL_SCOPE": "phase_b"
  }
}
```

### Authentication failures (AUTH_NO_PROVIDER)

Ensure the environment variable holding your Databricks token is set. For simple setups, set `DATABRICKS_TOKEN`. For multi-workspace configs, each workspace's `token_env` field must reference a valid environment variable.

```bash
export DATABRICKS_TOKEN="dapi_your_token_here"
```

### Tool registry errors (EXEC_NO_REGISTRY)

The MCP server was not bootstrapped correctly. Make sure you start it via the `starboard-mcp` CLI entry point, which handles registry initialization.
