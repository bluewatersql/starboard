# Starboard: FinOps Analysis

Analyze Databricks cost and usage — fetch billable usage, review budgets, and identify cost optimization opportunities.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full agent orchestration:
```
mcp__starboard__analyze_finops  (or similar MCP tool)
```

If MCP tools are NOT available, use `starboard-helper` via Bash to fetch data, then apply analytical reasoning:
```bash
starboard-helper finops usage --start-date YYYY-MM-DD --end-date YYYY-MM-DD
starboard-helper finops budgets
starboard-helper finops log-delivery
```

## MCP Path

When `mcp__starboard__*` tools are available:
1. Call the relevant MCP tool — the full agent stack handles orchestration, analysis, and recommendations.
2. Return the agent's response directly.

## Non-MCP Path

When MCP tools are NOT available, follow these steps:

### Step 1: Fetch usage data
```bash
starboard-helper finops usage --start-date 2024-01-01 --end-date 2024-01-31
```

### Step 2: Review budgets and alerts
```bash
starboard-helper finops budgets
```

### Step 3: Apply analytical reasoning

Based on the structured JSON output, analyze:
- **Cost drivers**: Which SKUs (Jobs Compute, SQL Compute, All-Purpose) dominate spend?
- **Trends**: Is spend increasing month-over-month? Which workloads are growing?
- **Waste**: Are there All-Purpose clusters with low utilization (idle cost)?
- **Budget alerts**: Are any budgets close to or exceeding thresholds?
- **Optimization levers**: Spot instances, serverless SQL, job cluster ephemeral patterns.

### Step 4: Produce recommendations

Output a structured analysis:
1. Cost summary by SKU and time period
2. Top cost drivers
3. Waste identification (idle resources, oversized clusters)
4. Specific optimization actions with estimated savings
5. Priority: critical / high / medium / low

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST, DATABRICKS_ACCOUNT_ID, and DATABRICKS_TOKEN env vars
- 2: resource not found
- 3: API error — note: billable usage requires account-level access
