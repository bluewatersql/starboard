# Starboard: Cluster Analysis

Analyze Databricks clusters — inspect configuration, review events, diagnose failures, and recommend optimizations.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full agent orchestration:
```
mcp__starboard__analyze_cluster  (or similar MCP tool)
```

If MCP tools are NOT available, use `starboard-helper` via Bash to fetch data, then apply analytical reasoning:
```bash
starboard-helper cluster list --filter-by-state RUNNING
starboard-helper cluster fetch --cluster-id <CLUSTER_ID>
starboard-helper cluster events --cluster-id <CLUSTER_ID> --limit 50
starboard-helper cluster spark-context --cluster-id <CLUSTER_ID>
```

## MCP Path

When `mcp__starboard__*` tools are available:
1. Call the relevant MCP tool — the full agent stack handles orchestration, analysis, and recommendations.
2. Return the agent's response directly.

## Non-MCP Path

When MCP tools are NOT available, follow these steps:

### Step 1: List and identify clusters
```bash
starboard-helper cluster list
starboard-helper cluster list --filter-by-state RUNNING
```

### Step 2: Inspect specific cluster
```bash
starboard-helper cluster fetch --cluster-id <CLUSTER_ID>
starboard-helper cluster events --cluster-id <CLUSTER_ID> --limit 50
starboard-helper cluster spark-context --cluster-id <CLUSTER_ID>
```

### Step 3: Apply analytical reasoning

Based on the structured JSON output, analyze:
- **Sizing**: Is the node type and worker count appropriate for the workload?
- **Autoscaling**: Is autoscale configured and within appropriate min/max bounds?
- **Events**: Are there recurring error events (OOM, node lost, preemption)?
- **Spark config**: Are there performance-relevant configs set (shuffle partitions, memory fractions)?
- **Lifespan**: Are long-running clusters accumulating state or should they be ephemeral?
- **Source**: Are clusters created interactively (risk) vs. job-attached (preferred for production)?

### Step 4: Produce recommendations

Output a structured analysis:
1. Cluster fleet overview
2. Rightsizing recommendations
3. Event-based failure diagnosis
4. Spark configuration tuning suggestions
5. Priority: critical / high / medium / low

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST and DATABRICKS_TOKEN env vars
- 2: cluster not found — verify cluster ID
- 3: API error — check workspace connectivity
