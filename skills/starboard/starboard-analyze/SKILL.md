name: starboard-analyze
description: Route Databricks analysis requests to the right Starboard domain. Use when user mentions "analyze", "optimize", "Databricks", "Starboard", "workspace", or "help me with".
  Triggers on: analyze, optimize, Databricks, Starboard, workspace, help me with.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path (Agent Tool)

This is a **meta-routing skill** — it does NOT call tools directly. Instead, determine the user's intent and route to the correct domain skill.

Read the user's message and match against the routing table below, then invoke the corresponding domain skill.

If the request spans multiple domains, call the corresponding `*_agent` MCP tools in parallel for each relevant domain.

## Manual Workflow (Intent Routing)

1. **Identify domain signals** — Scan the user's message for keywords, identifiers, and context clues
   - Look for: domain keywords, resource IDs, three-part table names, error messages
   - Use when: The user's request is ambiguous or mentions "analyze" without a clear domain

2. **Match to domain skill** — Use the routing table below to select the target skill
   - If a single domain matches, invoke that domain's skill
   - If multiple domains match, invoke multiple `*_agent` tools in parallel

3. **Handle ambiguity** — If no clear match, ask the user to clarify or start with `starboard-discovery` for a workspace overview

### Routing Table

| User mentions | Route to |
|---|---|
| SQL, query, statement, execution plan | `starboard-query` |
| Job, run, task, DAG, workflow, schedule | `starboard-job` |
| Table, catalog, schema, lineage, grants, Unity Catalog, UC | `starboard-uc` |
| Cluster, compute, autoscaling, Spark, node, driver | `starboard-cluster` |
| Cost, billing, budget, FinOps, spend, chargeback | `starboard-finops` |
| Warehouse, SQL warehouse, endpoint, sizing, SLO | `starboard-warehouse` |
| Error, debug, troubleshoot, failing, broken, root cause | `starboard-diagnostic` |
| Discovery, assessment, audit, overview, workspace health | `starboard-discovery` |

### Identifier-Based Routing

| Identifier pattern | Route to |
|---|---|
| Job ID (numeric, e.g. `123456789`) | `starboard-job` |
| Statement ID (UUID, e.g. `01ef-...`) | `starboard-query` |
| Three-part name (e.g. `catalog.schema.table`) | `starboard-uc` |

### Priority Order for Ambiguous Triggers

1. **Identifier-based** — Job ID, Statement ID, or table name takes precedence
2. **Domain keyword** — "cluster", "warehouse", "table" route to their specific domain
3. **Action keyword** — "troubleshoot" routes to diagnostic, "cost" routes to finops
4. **Fallback** — Use `starboard-discovery` for broad workspace-level requests

## Available MCP Tools

This meta-routing skill does not call tools directly. It routes to domain skills which use the following agent tools:

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `query_agent` | Full SQL query analysis | `message` |
| `job_agent` | Full job/workflow analysis | `message` |
| `uc_agent` | Full Unity Catalog analysis | `message` |
| `cluster_agent` | Full cluster/compute analysis | `message` |
| `analytics_agent` | Full FinOps/cost analysis | `message` |
| `warehouse_agent` | Full SQL warehouse analysis | `message` |
| `diagnostic_agent` | Full troubleshooting analysis | `message` |
| `discovery_agent` | Full workspace discovery | `message` |

## Composite Tools

| Tool | Description | Chains |
|------|-------------|--------|
| `get_workspace_overview` | Broad workspace health assessment | `discover_active_products` -> `run_discovery_queries` -> `synthesize_discovery_report` |

## Example Prompts

- "Analyze my Databricks workspace and find optimization opportunities"
  - Routes to: `starboard-discovery` (workspace-level overview)

- "Help me optimize job 12345 — it's been running slowly and the queries inside are timing out"
  - Routes to: `starboard-job` AND `starboard-query` in parallel (job ID + query keywords)

- "What's happening with catalog.schema.my_table? I'm seeing schema drift and the costs are increasing"
  - Routes to: `starboard-uc` (three-part table name + schema/cost keywords)

- "My Spark cluster keeps running out of memory during peak hours"
  - Routes to: `starboard-cluster` (cluster + Spark + memory keywords)

- "How much are we spending on Databricks this month compared to last month?"
  - Routes to: `starboard-finops` (spending + cost comparison keywords)

## Interpreting Results

This skill produces routing decisions, not analysis results. After routing:

- **Single domain match**: The domain skill handles the full analysis. Review its output for actionable findings.
- **Multi-domain match**: Results arrive from multiple agent tools in parallel. Synthesize findings across domains — look for correlations (e.g., a failing job may be caused by a misconfigured cluster or a slow query).
- **No clear match**: Start with `starboard-discovery` to get a workspace overview, then drill into specific domains based on what the discovery reveals.
- **Cross-cutting concerns**: Cost issues often span multiple domains. A "why is this expensive?" question may need warehouse + cluster + job analysis to fully answer.
