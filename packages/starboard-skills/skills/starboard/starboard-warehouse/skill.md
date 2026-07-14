# Starboard: Warehouse Analysis

Analyze Databricks SQL warehouses — inspect configuration, monitor state, identify sizing and cost issues.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full agent orchestration:
```
mcp__starboard__analyze_warehouse  (or similar MCP tool)
```

If MCP tools are NOT available, use `starboard-helper` via Bash to fetch data, then apply analytical reasoning:
```bash
starboard-helper warehouse list
starboard-helper warehouse fetch --warehouse-id <WH_ID>
starboard-helper warehouse metrics --warehouse-id <WH_ID>
```

## MCP Path

When `mcp__starboard__*` tools are available:
1. Call the relevant MCP tool — the full agent stack handles orchestration, analysis, and recommendations.
2. Return the agent's response directly.

## Non-MCP Path

When MCP tools are NOT available, follow these steps:

### Step 1: List all warehouses
```bash
starboard-helper warehouse list
```
Review: warehouse names, states, sizes, types (classic vs. serverless).

### Step 2: Inspect specific warehouse
```bash
starboard-helper warehouse fetch --warehouse-id <WH_ID>
starboard-helper warehouse metrics --warehouse-id <WH_ID>
```
Review: cluster count, active sessions, auto-stop configuration, health status.

### Step 3: Apply analytical reasoning

Based on the structured JSON output, analyze:
- **Sizing**: Is `cluster_size` appropriate for the active session count?
- **Scaling**: Is `max_num_clusters` unnecessarily high, driving cost?
- **Auto-stop**: Is `auto_stop_mins` configured too high (idle cost)?
- **Type**: Should classic warehouses be migrated to serverless for variable workloads?
- **Health**: Are there any health warnings or errors?

### Step 4: Produce recommendations

Output a structured analysis:
1. Summary of warehouse fleet health
2. Rightsizing recommendations per warehouse
3. Cost optimization opportunities (auto-stop, serverless migration)
4. Priority: critical / high / medium / low

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST and DATABRICKS_TOKEN env vars
- 2: warehouse not found — verify warehouse ID
- 3: API error — check workspace connectivity
