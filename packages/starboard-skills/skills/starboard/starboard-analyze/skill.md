# Starboard: Comprehensive Analysis

Run a comprehensive analysis of a Databricks workload — combining job, cluster, query, and cost data into a unified optimization report.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full agent orchestration:
```
mcp__starboard__analyze  (or similar MCP tool)
```

If MCP tools are NOT available, use `starboard-helper` via Bash across multiple domains, then synthesize findings:

```bash
# Gather data from all relevant domains
starboard-helper job fetch --job-id <JOB_ID>
starboard-helper job runs --job-id <JOB_ID> --limit 10
starboard-helper diagnostic run-state --run-id <LATEST_RUN_ID>
starboard-helper cluster fetch --cluster-id <CLUSTER_ID>
starboard-helper cluster events --cluster-id <CLUSTER_ID> --limit 50
```

## MCP Path

When `mcp__starboard__*` tools are available:
1. Call the relevant MCP tool — the full agent stack handles orchestration, analysis, and recommendations.
2. Return the agent's response directly.

## Non-MCP Path

When MCP tools are NOT available, follow this multi-step investigation:

### Step 1: Identify the workload
Determine what to analyze from user input: job ID, cluster ID, warehouse ID, or a named workload.

### Step 2: Fetch data across all relevant domains
Run multiple `starboard-helper` commands to gather comprehensive data:
- Job configuration and recent runs
- Cluster configuration and events
- Query history (if SQL workload)
- Run state details for failed runs

### Step 3: Cross-domain synthesis

Connect findings across domains:
- **Job → Cluster**: Does job configuration match cluster sizing for the workload?
- **Run history → Events**: Do cluster error events correlate with job failures?
- **Duration trends → Cost**: Is increasing run duration driving cost growth?
- **Retry patterns → Failure modes**: Are failures transient (retry works) or systematic?

### Step 4: Produce comprehensive report

Output a unified analysis:
1. **Executive summary**: Overall health in 2-3 sentences
2. **Critical issues**: Immediate action required
3. **Performance analysis**: Bottlenecks and optimization opportunities
4. **Cost analysis**: Waste and rightsizing opportunities
5. **Recommended actions**: Ordered by impact, with specific implementation steps
6. **Estimated impact**: Time/cost savings from top recommendations

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST and DATABRICKS_TOKEN env vars
- 2: resource not found
- 3: API error — check workspace connectivity
