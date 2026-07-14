# Starboard: Query Analysis

Analyze Databricks SQL queries — fetch query history, identify slow queries, diagnose failures, and recommend optimizations.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full agent orchestration:
```
mcp__starboard__analyze_query  (or similar MCP tool)
```

If MCP tools are NOT available, use `starboard-helper` via Bash to fetch data, then apply analytical reasoning:
```bash
starboard-helper query fetch --query-id <QUERY_ID>
starboard-helper query history --warehouse-id <WH_ID> --limit 25
starboard-helper query slow --min-duration-ms 10000 --limit 25
```

## MCP Path

When `mcp__starboard__*` tools are available:
1. Call the relevant MCP tool — the full agent stack handles orchestration, analysis, and recommendations.
2. Return the agent's response directly.

## Non-MCP Path

When MCP tools are NOT available, follow these steps:

### Step 1: Fetch query history or specific query
```bash
# For a specific query:
starboard-helper query fetch --query-id <QUERY_ID>

# For recent history on a warehouse:
starboard-helper query history --warehouse-id <WH_ID> --limit 25

# For slow queries:
starboard-helper query slow --min-duration-ms 10000
```

### Step 2: Apply analytical reasoning

Based on the structured JSON output, analyze:
- **Duration**: Is query duration above expected thresholds for query complexity?
- **Failures**: What error messages are present? Are they permission, syntax, or resource errors?
- **Patterns**: Do slow queries share common tables, joins, or filter patterns?
- **Warehouse**: Is the warehouse appropriately sized for the query workload?

### Step 3: Produce recommendations

Output a structured analysis:
1. Summary of query health / performance
2. Root cause(s) of slowness or failures
3. Specific SQL optimization recommendations (indexes, partitioning, rewrite suggestions)
4. Warehouse sizing recommendations if applicable
5. Priority: critical / high / medium / low

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST and DATABRICKS_TOKEN env vars
- 2: query not found — verify query ID
- 3: API error — check workspace connectivity
