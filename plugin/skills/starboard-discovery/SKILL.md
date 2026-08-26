---
name: starboard-discovery
description: "Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses, and Unity Catalog assets to build a comprehensive inventory. Use when the user wants a workspace inventory, a health assessment, or to explore what exists in a workspace."
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *), Bash(starboard-helper:*), Read
---

# Starboard: Workspace Discovery

Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses, and Unity Catalog assets to build a comprehensive inventory.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full agent orchestration:
```
mcp__starboard__discover  (or similar MCP tool)
```

If MCP tools are NOT available, use `starboard-helper` via Bash to enumerate workspace resources:

```bash
starboard-helper job list --limit 100
starboard-helper cluster list
starboard-helper warehouse list
starboard-helper uc catalogs
```

## MCP Path

When `mcp__starboard__*` tools are available:
1. Call the relevant MCP tool — the full agent stack handles orchestration, analysis, and recommendations.
2. Return the agent's response directly.

## Tier 1 — bundled helper (deterministic, no LLM)

If MCP tools are unavailable but `${CLAUDE_SKILL_DIR}/scripts/run.sh` exists, run
the deterministic discovery pipeline (audit + query packs, **no LLM analysis**).
It emits the stable JSON envelope (`{ok, domain, command, data|error, meta}`) to
stdout and runs out-of-context in Python — the command is pre-approved, so no
permission prompt appears:

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh run --data-only
${CLAUDE_SKILL_DIR}/scripts/run.sh run --data-only --packs finops_billing jobs
```

Read the JSON (`data.packs`, `data.audit`) and synthesize the inventory. Requires
`pip install "starboard-core[discovery]"`. For raw per-resource enumeration
instead, use the Tier-0 `starboard-helper` commands below.

## Non-MCP Path (Tier 0 — raw fetch)

When neither MCP nor the bundled helper is available, follow these steps:

### Step 1: Enumerate all resource types
```bash
# Jobs
starboard-helper job list --limit 100

# Clusters
starboard-helper cluster list

# SQL Warehouses
starboard-helper warehouse list

# Unity Catalog
starboard-helper uc catalogs
```

### Step 2: Drill into key resources
For any resources of interest, use domain-specific commands to get details:
```bash
starboard-helper uc schemas --catalog <CATALOG>
starboard-helper cluster fetch --cluster-id <CLUSTER_ID>
starboard-helper warehouse fetch --warehouse-id <WH_ID>
```

### Step 3: Build workspace inventory

Synthesize findings into a workspace map:
- **Jobs**: Count, names, schedule patterns, cluster attachment types
- **Clusters**: Running vs. terminated, job-attached vs. interactive
- **Warehouses**: Types (classic/serverless), sizes, states
- **Data**: Catalog hierarchy, number of schemas and tables

### Step 4: Produce discovery report

Output a structured inventory:
1. **Workspace summary**: Counts of each resource type
2. **Jobs inventory**: Scheduled vs. manual, production vs. development indicators
3. **Compute inventory**: Cluster and warehouse utilization snapshot
4. **Data inventory**: Unity Catalog hierarchy overview
5. **Observations**: Notable patterns, potential issues, quick wins
6. **Recommended next steps**: Which domains to analyze in depth

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST and DATABRICKS_TOKEN env vars
- 2: resource not found
- 3: API error — check workspace connectivity
