---
name: starboard-cluster
description: "Analyze Databricks clusters — inspect configuration, review events, diagnose failures, and recommend optimizations. Use when the user asks about cluster performance, autoscaling, node types, cluster failures, or compute sizing."
allowed-tools: Bash(starboard-helper:*), Read
---

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

For **right-sizing + cost-impact**, prefer the dedicated tools:

- `get_cluster_rightsizing` — per-cluster sizing verdict (`sizing_direction`,
  `recommended_action`, `target_cores_per_node`, `reduction_pct`) joined to a
  **list-price DBU cost estimate** (`estimated_monthly_cost_usd`,
  `estimated_monthly_savings_usd`). Scope to one cluster with `cluster_id`.
- `get_workload_rightsizing` — unified job + pipeline verdicts (ranked by
  priority) plus per-job reliability and a fleet-level list-price DBU exposure.
- `get_cluster_metrics` / `get_cluster_health` now carry a `rightsizing` block
  (`target_cores_per_node`, `reduction_pct`, `binding_resource`,
  `autoscale_constrained`, `queue_pressure`).

All `$` figures are **list-price DBU estimates** — label them as such in your
answer; actual billed cost differs under contracted rates.

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

### Step 4: Right-sizing + cost impact

Using the fetched config (node type, worker count, autoscale bounds) plus any
utilization signals, classify each cluster's sizing direction and project the
list-price cost impact:

- **Over-provisioned** (low CPU/memory p95): recommend a smaller node SKU or
  fewer/`lower` autoscale-min workers; estimate the `reduction_pct` and the
  **list-price DBU $/month** saved.
- **Under-provisioned** (high CPU/memory p95, autoscale pinned at max):
  recommend raising the autoscale max or a larger SKU.
- **Balanced**: no action.

Project cost as a **list-price DBU estimate**:
`monthly_cost ≈ dbus_per_day × 30 × list_price_per_dbu` and
`monthly_savings ≈ monthly_cost × reduction_pct / 100`. Always label the figure
a *list-price DBU estimate* — it is not a contracted-rate cost.

### Step 5: Produce recommendations

Output a structured analysis:
1. Cluster fleet overview
2. Right-sizing recommendations with list-price DBU $/month impact
3. Event-based failure diagnosis
4. Spark configuration tuning suggestions
5. Priority: critical / high / medium / low

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST and DATABRICKS_TOKEN env vars
- 2: cluster not found — verify cluster ID
- 3: API error — check workspace connectivity
