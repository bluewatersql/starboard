name: starboard-discovery
description: Run workspace discovery, comprehensive workspace health assessment and product usage discovery for Databricks. Use when user mentions discovery, workspace discovery, workspace health, assessment, audit, or inventory. This is the primary skill for "run discovery" or "run workspace discovery".
  Triggers on: run discovery, run workspace discovery, workspace discovery, workspace health, discovery, assessment, audit, overview, inventory, what's running, health check.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path

1. Fetch MCP resource `starboard://prompts/discovery` — this returns the expert system prompt with workspace assessment workflows and cross-domain analysis patterns.
2. Follow the returned prompt's guidance to call discovery tools directly.
3. Use the 4-phase workflow below.

## 4-Phase Workflow

### Phase 1: Discover active products
Call `discover_active_products` (no params required).
- Returns: `available_domains` — the list of domains to analyze

### Phase 2: Run discovery queries
Call `run_discovery_queries` (no params required).
- Returns: `domains_with_data` and `parallel_calls` — a list of tool calls to make next.

### Phase 3: Start domain analysis (async)
Call `start_discovery_analysis` (no params required — it uses all domains from Phase 2).
- The server launches all domain analyses **in parallel** in the background.
- Returns immediately with `status: "started"` and the list of target domains.

### Phase 3b: Poll for completion
Call `get_discovery_analysis_progress` every 30-60 seconds until `status` is `"completed"`.
- Each poll returns instantly with the count of completed vs remaining domains.
- Typical workspace takes 3-7 minutes to finish all domains.
- When `status` is `"completed"`, proceed to Phase 4.

**IMPORTANT:** Do NOT use `analyze_discovery_domain` with all domains at once — it will timeout. Always use the async `start_discovery_analysis` + `get_discovery_analysis_progress` pattern instead.

### Phase 4: Synthesize report
After analysis is complete, call `synthesize_discovery_report` (no params required).
- Assembles all domain analyses into a unified report with executive summary, grades, and prioritized findings.

## Available MCP Tools

| Tool | Description | Key Params |
|------|-------------|------------|
| `discover_active_products` | Audit workspace for active Databricks products | `lookback_days` (optional) |
| `run_discovery_queries` | Execute discovery SQL query packs | `domains` (optional filter) |
| `start_discovery_analysis` | Start background domain analysis (async) | `domains` (optional filter) |
| `get_discovery_analysis_progress` | Poll background analysis progress | (none) |
| `synthesize_discovery_report` | Assemble domain analyses into final report | (none) |

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
