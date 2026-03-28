name: starboard-cluster
description: Analyze Databricks cluster configuration, health, resource utilization, and autoscaling. Use when user mentions clusters, compute, autoscaling, Spark config, or instance types.
  Triggers on: cluster, compute, autoscaling, Spark, driver, worker, node, instance type.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path

Two modes are available. **Direct orchestration** gives you full control and avoids double-LLM cost. **Auto-pilot** delegates everything to the server-side agent.

### Direct Orchestration (Recommended)

1. Fetch MCP resource `starboard://prompts/cluster` — this returns the expert system prompt with tool ordering, autoscaling knowledge, and cluster optimization workflows.
2. Follow the returned prompt's guidance to call tools directly based on the user's request.
3. Start with `list_clusters` to discover clusters, then use `get_cluster_config`, `get_cluster_health`, and `get_cluster_metrics` as the prompt directs.

### Auto-Pilot

Call MCP tool `cluster_agent` with:
```json
{ "message": "<the user's original request about clusters>" }
```

If the user did not specify a cluster, use: `{ "message": "List all clusters, analyze health and utilization, and suggest right-sizing changes" }`

## Manual Workflow (Individual Tools)

For targeted analysis or when you need specific data points:

1. **List active clusters** — Call `list_clusters` with no required params
   - Returns: All compute clusters with recent activity, state, and basic config
   - Use when: You need to discover clusters or get an overview of compute resources

2. **Get cluster configuration** — Call `get_cluster_config` with `cluster_id: 0315-182023-abcde`
   - Returns: Instance types, autoscaling range, Spark config, libraries, policies
   - Use when: Reviewing cluster setup or comparing against best practices

3. **Check cluster health** — Call `get_cluster_health` with `cluster_id: 0315-182023-abcde`
   - Returns: Health score, risk indicators, and actionable recommendations
   - Use when: You need a quick assessment of whether a cluster is well-configured

4. **Get resource metrics** — Call `get_cluster_metrics` with `cluster_id: 0315-182023-abcde`
   - Returns: CPU, memory, disk, and network utilization over time
   - Use when: Diagnosing performance bottlenecks or validating right-sizing

5. **Review lifecycle events** — Call `get_cluster_events` with `cluster_id: 0315-182023-abcde`
   - Returns: Start, stop, resize, and failure events with timestamps
   - Use when: Investigating startup failures, unexpected terminations, or autoscaling behavior

6. **Get Spark logs** — Call `get_spark_logs` with `cluster_id: 0315-182023-abcde`
   - Returns: Spark UI log data for debugging executor and stage issues
   - Use when: Debugging Spark-level problems like shuffle failures, OOM errors, or data skew

## Available MCP Tools

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `list_clusters` | List compute clusters with recent activity | (none) |
| `get_cluster_config` | Get cluster configuration and settings | `cluster_id` |
| `get_cluster_health` | Get health score and risk analysis | `cluster_id` |
| `get_cluster_metrics` | Get CPU, memory, disk, network metrics | `cluster_id` |
| `get_cluster_events` | Get lifecycle events (start, stop, resize) | `cluster_id` |
| `get_spark_logs` | Get Spark UI logs for debugging | `cluster_id` |
| `cluster_agent` | Full cluster analysis with automatic tool selection | `message` |

## Composite Tools

| Tool | Description | Chains |
|------|-------------|--------|
| `get_workspace_overview` | Workspace-wide overview including cluster inventory | `list_clusters` + other domain tools |

## Example Prompts

- "List all running clusters and identify which ones are over-provisioned based on CPU and memory utilization"
- "Why does cluster 0315-182023-abcde keep restarting? Check events and Spark logs for root cause"
- "Compare the autoscaling configuration of our ETL clusters and recommend optimal min/max worker counts"
- "Get the health score for all production clusters and flag any with high-risk Spark configurations"
- "Analyze memory and disk metrics for cluster 0422-091500-xyz to determine if we need a larger instance type"

## Interpreting Results

**Autoscaling Efficiency**: Look for clusters that consistently run at max workers (undersized) or min workers (oversized). Frequent scale-up/scale-down cycles (thrashing) indicate the autoscaling range is too narrow or the workload is highly variable -- consider spot instances or separate clusters for batch vs. interactive workloads.

**Instance Type Selection**: Compare CPU utilization vs. memory utilization. CPU-bound workloads (high CPU, low memory) benefit from compute-optimized instances. Memory-bound workloads (low CPU, high memory) need memory-optimized instances. Mixed workloads with both high CPU and memory may need general-purpose instances with more workers.

**Idle Cluster Costs**: Clusters in RUNNING state with near-zero CPU/memory utilization are wasting compute spend. Check `get_cluster_events` for the last job execution time. Clusters idle for more than 1 hour should have auto-termination enabled (recommended: 30-60 minutes for interactive, 10-15 minutes for job clusters).

**Spark Configuration Tuning**: Key settings to review include `spark.sql.shuffle.partitions` (default 200 is often too high or too low), `spark.executor.memory` and `spark.executor.cores` (should match instance type), `spark.sql.adaptive.enabled` (should be true for most workloads), and `spark.databricks.delta.optimizeWrite.enabled` (reduces small files).

**Event Log Patterns**: Repeated DRIVER_NOT_RESPONDING events indicate driver OOM or GC pressure -- increase driver memory or reduce broadcast join thresholds. SPOT_INSTANCE_TERMINATION events indicate cost savings but potential reliability issues for long-running jobs. INIT_SCRIPT_FAILURE events need immediate attention as they prevent cluster startup.
