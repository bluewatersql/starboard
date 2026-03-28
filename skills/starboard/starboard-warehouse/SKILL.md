name: starboard-warehouse
description: Analyze SQL warehouse portfolio, health, sizing, user activity, and chargeback for Databricks. Use when user mentions warehouses, SQL warehouses, serverless, sizing, or SLOs.
  Triggers on: warehouse, SQL warehouse, serverless, endpoint, sizing, SLO, warehouse portfolio.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path

Two modes are available. **Direct orchestration** gives you full control and avoids double-LLM cost. **Auto-pilot** delegates everything to the server-side agent.

### Direct Orchestration (Recommended)

1. Fetch MCP resource `starboard://prompts/warehouse` — this returns the expert system prompt with warehouse sizing knowledge, SLO configuration, and portfolio optimization workflows.
2. Follow the returned prompt's guidance to call tools directly based on the user's request.
3. Start with `get_warehouse_portfolio` for fleet overview, then use `get_warehouse_fingerprint` and `get_warehouse_health` as the prompt directs.

### Auto-Pilot

Call MCP tool `warehouse_agent` with:
```json
{ "message": "<the user's original request about SQL warehouses>" }
```

If the user did not specify a warehouse, use: `{ "message": "Analyze the SQL warehouse portfolio with health scores, sizing, and utilization" }`

## Manual Workflow (Individual Tools)

For targeted analysis or when you need specific data points:

1. **Get portfolio overview** -- Call `get_warehouse_portfolio` (no params required)
   - Returns: Summary of all SQL warehouses with size, type, state, and utilization
   - Use when: You need a fleet-wide view before drilling into individual warehouses

2. **Fingerprint a warehouse** -- Call `get_warehouse_fingerprint` with `warehouse_id: "<id>"`
   - Returns: Detailed fingerprint including configuration, usage patterns, and sizing metrics
   - Use when: You need deep analysis of a specific warehouse's behavior

3. **Check health and SLOs** -- Call `get_warehouse_health` with `warehouse_id: "<id>"`
   - Returns: Health score, SLO compliance metrics, and issue indicators
   - Use when: You need to assess whether a warehouse is meeting performance targets

4. **Configure SLO targets** -- Call `configure_warehouse_slo` with `warehouse_id: "<id>"`
   - Returns: Updated SLO configuration for the warehouse
   - Use when: You need to set or adjust performance targets

5. **Analyze fleet topology** -- Call `analyze_warehouse_topology` (no params required)
   - Returns: Fleet-wide topology analysis with consolidation and optimization opportunities
   - Use when: You want to identify redundant warehouses or rebalancing opportunities

6. **Review user activity** -- Call `get_warehouse_user_activity` (no params required)
   - Returns: User activity breakdown showing who uses which warehouses and how
   - Use when: You need to understand usage patterns for chargeback or right-sizing

7. **Generate chargeback** -- Call `generate_warehouse_chargeback` with `warehouse_id: "<id>"` and `total_cost_usd: <amount>` OR call `generate_portfolio_chargeback` (no params) for fleet-wide chargeback
   - Returns: Cost allocation by user, team, or query workload
   - Use when: You need to attribute warehouse costs to consumers

8. **Check query metrics** -- Call `get_query_runtime_metrics` with `statement_id: "<id>"`
   - Returns: Execution metrics for a specific query run on the warehouse
   - Use when: You need to investigate a specific slow or expensive query

## Available MCP Tools

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `get_warehouse_portfolio` | Portfolio view of all SQL warehouses | (none) |
| `get_warehouse_fingerprint` | Detailed fingerprint for a warehouse | `warehouse_id` |
| `get_warehouse_health` | Health score and SLO compliance | `warehouse_id` |
| `configure_warehouse_slo` | Configure SLO targets | `warehouse_id` |
| `analyze_warehouse_topology` | Analyze fleet topology for optimization | (none) |
| `get_warehouse_user_activity` | User activity breakdown | (none) |
| `generate_warehouse_chargeback` | Cost chargeback for specific warehouse | `warehouse_id`, `total_cost_usd` |
| `generate_portfolio_chargeback` | Chargeback across all warehouses | (none) |
| `get_query_runtime_metrics` | Query execution metrics (shared with query domain) | `statement_id` |
| `warehouse_agent` | Full warehouse analysis (agent) | `message` |

## Example Prompts

- "Show me all SQL warehouses and their current utilization levels"
- "Is our production warehouse right-sized? Check the concurrency patterns and peak usage"
- "Generate a chargeback report for our data engineering warehouse allocating $12,000 in monthly costs"
- "Which warehouses are underutilized and could be consolidated or downsized?"
- "Check SLO compliance for warehouse abc-123 and recommend target adjustments"

## Interpreting Results

- **Right-sizing**: Compare peak concurrent queries against warehouse cluster count. If peak utilization rarely exceeds 50% of capacity, the warehouse is oversized. If queuing occurs frequently, it is undersized. Look at the 95th percentile, not just averages.
- **Concurrency patterns**: Identify peak and off-peak windows. Warehouses with sharp usage spikes benefit from serverless or auto-scaling configurations. Flat usage profiles are better served by fixed-size classic warehouses.
- **SLO compliance**: Health scores below 80% indicate frequent SLO violations. Check whether violations cluster during specific time windows (peak hours) or are distributed evenly (systemic undersizing).
- **User activity distribution**: Uneven user distribution across warehouses may indicate organic sprawl. Look for opportunities to consolidate users onto fewer, better-sized warehouses.
- **Chargeback allocation**: Validate that cost attribution reflects actual query volume and compute consumption. Watch for users running expensive ad-hoc queries on production warehouses, which distorts chargeback for scheduled workloads.
- **Topology optimization**: Fleet-wide analysis may reveal duplicate warehouses serving the same team or workload. Consolidation reduces idle compute costs and simplifies management.
