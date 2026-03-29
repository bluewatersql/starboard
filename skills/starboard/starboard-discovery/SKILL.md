name: starboard-discovery
description: Run comprehensive workspace health assessment and product usage discovery for Databricks. Use when user mentions workspace health, discovery, assessment, audit, or inventory.
  Triggers on: workspace health, discovery, assessment, audit, overview, inventory, what's running.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path

Two modes are available. **Direct orchestration** gives you full control and avoids double-LLM cost. **Auto-pilot** delegates everything to the server-side agent (may take several minutes).

### Direct Orchestration (Recommended)

1. Fetch MCP resource `starboard://prompts/discovery` — this returns the expert system prompt with workspace assessment workflows and cross-domain analysis patterns.
2. Follow the returned prompt's guidance to call discovery tools directly.
3. Use the 4-phase workflow below.

### Auto-Pilot

Call MCP tool `discovery_agent` with:
```json
{ "message": "Run a full workspace health assessment and identify optimization opportunities" }
```
Wait for the result (this may take several minutes — discovery runs multiple phases).

If the user provided a specific question, pass it as the `message` instead of the default above.

## 4-Phase Workflow

### Phase 1: Discover active products
Call `discover_active_products` (no params required).
- Returns: `available_domains` — the list of domains to analyze

### Phase 2: Run discovery queries
Call `run_discovery_queries` (no params required).
- Returns: `domains_with_data` and `parallel_calls` — a list of tool calls to make next.

### Phase 3: Analyze all domains (batch)
Call `analyze_discovery_domain` with `domains` set to the `domains_with_data` list from Phase 2.
- The server runs all domain analyses **in parallel** internally.
- This is a single call that takes 5-7 minutes for a typical workspace.
- Returns complete results for all domains: grades, scores, findings, recommendations.

Example:
```
analyze_discovery_domain(domains=["billing", "jobs", "compute", "governance", "query_perf", ...])
```

**Note:** Requires `MCP_TOOL_TIMEOUT` set to at least `600000` (10 min) in Claude Code settings to avoid timeout.

### Phase 4: Synthesize report
After `analyze_discovery_domain` returns, call `synthesize_discovery_report` (no params required).
- Assembles all domain analyses into a unified report with executive summary, grades, and prioritized findings.

## Available MCP Tools

| Tool | Description | Key Params |
|------|-------------|------------|
| `discover_active_products` | Audit workspace for active Databricks products | `lookback_days` (optional) |
| `run_discovery_queries` | Execute discovery SQL query packs | `domains` (optional filter) |
| `analyze_discovery_domain` | Analyze domains (batch or single) — server parallelizes internally | `domains` (batch) or `domain` (single) |
| `synthesize_discovery_report` | Assemble domain analyses into final report | (none) |
| `run_workspace_discovery` | Legacy monolithic pipeline (not recommended) | `lookback_days`, `domains` |
| `discovery_agent` | Full workspace discovery via server-side agent | `message` |

## Composite Tools

| Tool | Description | Chains |
|------|-------------|--------|
| `get_workspace_overview` | Clusters and warehouses in parallel | `list_clusters` + `get_warehouse_portfolio` (parallel) |

## Example Prompts

- "Run a full workspace health assessment and tell me what needs attention"
- "What Databricks products are active in our workspace and how heavily are they used?"
- "Give me an inventory of all running clusters, warehouses, and jobs with their current state"
- "Audit our workspace for unused resources and optimization opportunities"
- "What does our overall Databricks footprint look like? Show me the high-level overview"

## Interpreting Results

- **Product adoption**: The discovery report identifies which Databricks products are actively used (Jobs, SQL Warehouses, Unity Catalog, MLflow, Delta Live Tables, etc.). Low adoption of governance features like Unity Catalog may indicate compliance risk.
- **Workload distribution**: Look at how workloads are spread across compute resources. Heavy concentration on a few clusters or warehouses creates reliability risk and complicates cost attribution.
- **Unused resources**: Idle clusters, dormant jobs, and empty warehouses represent direct cost waste. Prioritize decommissioning resources with no activity in the past 30 days.
- **Governance posture**: Assess Unity Catalog adoption, access control coverage, and audit logging. Workspaces without centralized governance are harder to secure and optimize.
- **Optimization opportunities**: The synthesized report highlights specific areas for improvement ranked by estimated impact. Common findings include oversized clusters, unoptimized table storage (missing VACUUM, Z-ORDER), and redundant warehouses.
- **Baseline establishment**: Use the initial discovery as a baseline. Re-run periodically (monthly or quarterly) to track improvements and detect drift.
