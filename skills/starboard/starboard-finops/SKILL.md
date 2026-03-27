name: starboard-finops
description: Run FinOps cost analysis, billing queries, budget forecasting, and usage trend analysis for Databricks. Use when user mentions costs, billing, budget, spend, or chargeback.
  Triggers on: cost, billing, budget, spend, FinOps, usage, chargeback, consumption, DBU.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- Environment variables set: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `LLM_API_KEY`

## Quick Path (Agent Tool)

For comprehensive analysis, call the `analytics_agent` MCP tool with a natural language message.
The agent runs a full reasoning loop with automatic SQL generation and multi-step analysis.

Example:
```
Call MCP tool: analytics_agent
Arguments: { "message": "Show me cost trends by workspace for the last 90 days" }
```

## Manual Workflow (Individual Tools)

For targeted analysis or when you need specific data points:

1. **Build context** -- Call `build_analytics_context` with `user_query: "<your cost question>"`
   - Returns: A context handle containing RAG-retrieved schema and metric definitions
   - Use when: You need to generate SQL against the billing/usage tables

2. **Generate SQL** -- Call `build_sql_query` with `user_query: "<your cost question>"` and `context_handle: "<handle from step 1>"`
   - Returns: A SQL query tailored to the user's cost/billing question
   - Use when: You want to inspect or modify the generated SQL before execution

3. **Validate SQL** -- Call `validate_sql_query` with `sql: "<generated SQL>"`
   - Returns: Validation result with pass/fail status and any detected issues (two-gate validation)
   - Use when: You want to ensure correctness and safety before executing

4. **Execute SQL** -- Call `execute_sql_query` with `sql: "<validated SQL>"`
   - Returns: Query results with cost, usage, or billing data
   - Use when: The SQL has passed validation and you are ready to retrieve data

## Available MCP Tools

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `build_analytics_context` | Build analytics RAG context for SQL generation | `user_query` |
| `build_sql_query` | Generate SQL from user request using retrieved context | `user_query`, `context_handle` |
| `validate_sql_query` | Validate SQL query using two-gate validation | `sql` |
| `execute_sql_query` | Execute validated SQL on Databricks | `sql` |
| `analytics_agent` | Full FinOps analysis with automatic SQL generation (agent) | `message` |

## Example Prompts

- "What is our total Databricks spend by workspace over the last quarter?"
- "Show me DBU consumption trends broken down by cluster type for the past 30 days"
- "Generate a chargeback report allocating costs across business units by usage"
- "Are we on track to stay within budget this month? Show burn rate projections"

## Interpreting Results

- **Cost allocation**: Look at spend distribution across workspaces, clusters, and warehouses to identify the largest cost drivers. Uneven distribution often signals optimization opportunities.
- **Budget burn rate**: Compare current cumulative spend against the linear budget trajectory. A burn rate above 1.0x indicates overspend risk before period end.
- **Usage trends**: Rising DBU consumption without corresponding workload growth may indicate inefficient cluster sizing or runaway queries. Look for step changes that correlate with configuration changes.
- **Chargeback models**: Verify that cost attribution aligns with actual resource consumption. Common distortions include shared clusters attributed to a single team and idle compute costs spread evenly rather than by utilization.
- **Optimization ROI**: When recommending changes (right-sizing, spot instances, auto-termination), quantify the expected monthly savings against current spend to prioritize highest-impact actions.
