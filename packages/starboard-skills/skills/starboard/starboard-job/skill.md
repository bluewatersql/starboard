# Starboard: Job Analysis

Analyze Databricks jobs — fetch configuration, inspect run history, diagnose failures, and recommend optimizations.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full agent orchestration:
```
mcp__starboard__analyze_job  (or similar MCP tool)
```

If MCP tools are NOT available, use `starboard-helper` via Bash to fetch data, then apply analytical reasoning:
```bash
starboard-helper job fetch --job-id <JOB_ID>
starboard-helper job runs --job-id <JOB_ID> --limit 10
starboard-helper job list --limit 25 --name-filter <FILTER>
```

## MCP Path

When `mcp__starboard__*` tools are available:
1. Call the relevant MCP tool — the full agent stack handles orchestration, analysis, and recommendations.
2. Return the agent's response directly.

## Non-MCP Path

When MCP tools are NOT available, follow these steps:

### Step 1: Fetch job configuration
```bash
starboard-helper job fetch --job-id <JOB_ID>
```
Inspect: task types, cluster config, schedule, timeout settings, max retries.

### Step 2: Fetch recent runs
```bash
starboard-helper job runs --job-id <JOB_ID> --limit 10
```
Inspect: run states (SUCCESS/FAILED/CANCELED), durations, failure patterns.

### Step 3: Apply analytical reasoning

Based on the structured JSON output, analyze:
- **Failure patterns**: Are failures consistent (config issue) or intermittent (resource issue)?
- **Performance**: Are run durations increasing over time? Possible data skew or cluster undersizing.
- **Configuration**: Is the cluster correctly sized? Are retries configured appropriately?
- **Cost**: Is the cluster kept alive between runs unnecessarily?

### Step 4: Produce recommendations

Output a structured analysis:
1. Summary of job health (healthy / degraded / failing)
2. Root cause(s) of failures if any
3. Specific, actionable recommendations
4. Priority: critical / high / medium / low

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST and DATABRICKS_TOKEN env vars
- 2: job not found — verify job ID
- 3: API error — check workspace connectivity
