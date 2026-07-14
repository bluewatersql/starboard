# Starboard: Diagnostic Analysis

Run diagnostics on Databricks workspace components — inspect run states, cluster logs, node types, and workspace configuration.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full agent orchestration:
```
mcp__starboard__run_diagnostic  (or similar MCP tool)
```

If MCP tools are NOT available, use `starboard-helper` via Bash to fetch data, then apply analytical reasoning:
```bash
starboard-helper diagnostic workspace
starboard-helper diagnostic node-types
starboard-helper diagnostic spark-versions
starboard-helper diagnostic run-state --run-id <RUN_ID>
starboard-helper diagnostic cluster-log --cluster-id <CLUSTER_ID> --limit 100
```

## MCP Path

When `mcp__starboard__*` tools are available:
1. Call the relevant MCP tool — the full agent stack handles orchestration, analysis, and recommendations.
2. Return the agent's response directly.

## Non-MCP Path

When MCP tools are NOT available, follow these steps:

### Step 1: Fetch relevant diagnostic data
```bash
# For a failed job run:
starboard-helper diagnostic run-state --run-id <RUN_ID>

# For cluster issues:
starboard-helper diagnostic cluster-log --cluster-id <CLUSTER_ID> --limit 100

# For workspace-level config:
starboard-helper diagnostic workspace
```

### Step 2: Apply analytical reasoning

Based on the structured JSON output, analyze:
- **Run failures**: Which tasks failed? What are their error messages? Are retries exhausted?
- **Cluster errors**: Are there OOM events, node-lost events, or preemption events?
- **Timing**: Is execution duration abnormally long? Are tasks queued waiting for resources?
- **Configuration**: Is the workspace configured securely (IP access lists, token policies)?
- **Version currency**: Are outdated Spark versions in use that should be upgraded?

### Step 3: Produce diagnostic report

Output a structured report:
1. Overall health assessment
2. Specific error events with timestamps
3. Root cause hypothesis for each failure mode
4. Recommended remediation steps
5. Priority: critical / high / medium / low

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST and DATABRICKS_TOKEN env vars
- 2: resource not found — verify run ID or cluster ID
- 3: API error — check workspace connectivity
